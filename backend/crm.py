"""CRM: contacts + leads (+ activities) and the CEO KPI snapshot. All writes are CSRF-protected, role-checked server-side, audited."""
import csv, io, logging, os, re
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Response
import permissions
from pydantic import BaseModel, Field, field_validator
log = logging.getLogger("crm")
# Selectable pipeline (decided by the CEO): New Lead -> Contacted -> Proposal Sent -> Negotiation -> Won / Lost.
# DB values stay short ("proposal" is shown as "Proposal Sent") so no data rewrite is needed.
STAGES = ["new", "contacted", "proposal", "negotiation", "won", "lost"]
STAGE_LABELS = {"new": "New Lead", "contacted": "Contacted", "proposal": "Proposal Sent", "negotiation": "Negotiation", "won": "Won", "lost": "Lost"}
# "qualified" is LEGACY: db/003 still allows it until db/004 is applied. Existing rows are read/ordered correctly but it can no longer be set.
CONTACT_TYPES = ["customer", "partner", "vendor", "internal", "other"]
CONTACT_SORTS = {"full_name": "lower(t.full_name)", "email": "lower(t.email)", "phone": "t.phone", "organization": "lower(t.organization)", "contact_type": "t.contact_type", "created_at": "t.created_at"}
# Pipeline order shown on Leads & Pipeline: New -> Contacted -> In Discussion -> Proposal -> Converted / Lost.
# "qualified" and "negotiation" are both In Discussion (same rank), so In Discussion -> Proposal is forward and Proposal -> In Discussion is blocked.
# (Previously negotiation ranked after proposal; the old Proposal -> Negotiation move is therefore no longer allowed.)
RANK = {"new": 0, "contacted": 1, "qualified": 2, "negotiation": 2, "proposal": 3, "won": 4, "lost": 5}
# Display stages for Leads & Pipeline. DB values are NOT rewritten: this is a read-time mapping only. "db_value" is what the UI writes.
UI_STAGES = [{"key": "new", "label": "New", "db_value": "new", "db_values": ["new"]},
             {"key": "contacted", "label": "Contacted", "db_value": "contacted", "db_values": ["contacted"]},
             {"key": "in_discussion", "label": "In Discussion", "db_value": "negotiation", "db_values": ["qualified", "negotiation"]},
             {"key": "proposal", "label": "Proposal", "db_value": "proposal", "db_values": ["proposal"]},
             {"key": "converted", "label": "Converted", "db_value": "won", "db_values": ["won"]},
             {"key": "lost", "label": "Lost / Closed", "db_value": "lost", "db_values": ["lost"]}]
DB_TO_UI = {v: u["key"] for u in UI_STAGES for v in u["db_values"]}
UI_LABEL = {u["key"]: u["label"] for u in UI_STAGES}
UI_DB_VALUES = {u["key"]: u["db_values"] for u in UI_STAGES}
LEAD_SOURCES = ["Website", "Referral", "LinkedIn", "Direct", "Campaign", "Other"]
LEAD_SORTS = {"title": "lower(t.title)", "contact": "lower(c.full_name)", "organization": "lower(c.organization)", "source": "lower(t.source)", "value": "t.value",
              "stage": "case t.stage " + " ".join(f"when '{k}' then {v}" for k, v in RANK.items()) + " end",   # constants only, no user input
              "expected_closure": "t.expected_closure", "next_follow_up": "t.next_follow_up", "created_at": "t.created_at"}
LABEL = {k: STAGE_LABELS[k] for k in ("new", "contacted", "proposal", "negotiation", "won")}   # funnel panel on the CEO dashboard
roles = lambda n, d: {r.strip() for r in os.getenv(n, d).split(",") if r.strip()}
W = lambda: roles("CRM_WRITE_ROLES", "ceo"); R = lambda: roles("CRM_READ_ROLES", "ceo,coo") | W()
A = lambda: roles("CRM_ARCHIVE_ROLES", "ceo") & R()   # who may delete (= archive). Separate from write; a role must also be able to read CRM.
class ContactBody(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=120); email: Optional[str] = Field(None, max_length=254)
    contact_type: Optional[Literal["customer", "partner", "vendor", "internal", "other"]] = None
    phone: Optional[str] = None; organization: Optional[str] = Field(None, max_length=160); notes: Optional[str] = Field(None, max_length=2000)
    @field_validator("email", "phone", "organization", "notes", mode="before")
    def blank(cls, v): return (v.strip() or None) if isinstance(v, str) else v
    @field_validator("email")
    def em(cls, v):
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v): raise ValueError("Enter a valid email address")
        return v
    @field_validator("phone")
    def ph(cls, v):
        if v and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", v): raise ValueError("Enter a valid phone number")
        return v
class LeadBody(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=160); contact_id: Optional[str] = None; source: Optional[str] = Field(None, max_length=80)
    stage: Optional[Literal["new", "contacted", "proposal", "negotiation", "won", "lost"]] = None
    value: Optional[float] = Field(None, ge=0, le=1e12); next_follow_up: Optional[date] = None; lost_reason: Optional[str] = Field(None, max_length=500)
    expected_closure: Optional[date] = None; notes: Optional[str] = Field(None, max_length=2000)   # added by db/014
    @field_validator("title", mode="before")
    def title_strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v: raise ValueError("Title cannot be empty")
        return v
    @field_validator("notes", "source", "lost_reason", mode="before")
    def lead_blank(cls, v): return (v.strip() or None) if isinstance(v, str) else v
class InlineContact(BaseModel):
    """Contact details typed into a lead form. Matched to an existing contact first; a new contact is created only when nothing matches."""
    contact_name: Optional[str] = Field(None, max_length=120); email: Optional[str] = Field(None, max_length=254); phone: Optional[str] = None; organization: Optional[str] = Field(None, max_length=160)
    @field_validator("contact_name", "email", "phone", "organization", mode="before")
    def inline_blank(cls, v): return (v.strip() or None) if isinstance(v, str) else v
    @field_validator("email")
    def inline_em(cls, v):   # same rules as ContactBody
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v): raise ValueError("Enter a valid email address")
        return v
    @field_validator("phone")
    def inline_ph(cls, v):
        if v and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", v): raise ValueError("Enter a valid phone number")
        return v
class LeadCreate(LeadBody, InlineContact):
    """POST /leads only. Either contact_id (existing CRM contact) or the inline contact fields."""
class ConvertBody(BaseModel):
    """POST /leads/{id}/convert. contact_id links an existing contact; new_contact reuses/creates one (no duplicates); mark_customer sets that contact's type to customer."""
    contact_id: Optional[str] = None; mark_customer: bool = False; new_contact: Optional[InlineContact] = None
def norm_source(v, current=None):
    """Canonical lead source. Legacy free-text values already stored on a lead stay editable unchanged."""
    if v is None: return None
    for s in LEAD_SOURCES:
        if s.lower() == v.lower(): return s
    if current is not None and v == current: return v
    raise HTTPException(422, "Choose a valid lead source: " + ", ".join(LEAD_SOURCES) + ".")
class Note(BaseModel): note: str = Field(min_length=1, max_length=2000)

def snapshot(dsn, date_from=None, date_to=None):
    """CEO CRM KPIs from real rows. Date filters apply to both KPI and stage chart."""
    try:
        with psycopg.connect(dsn, connect_timeout=5, prepare_threshold=None) as c:
            clauses = ["not is_archived"]
            args = []
            if date_from is not None:
                clauses.append("created_at::date >= %s"); args.append(date_from)
            elif date_to is None:
                clauses.append("created_at >= now() - interval '30 days'")
            if date_to is not None:
                clauses.append("created_at::date <= %s"); args.append(date_to)
            where = " and ".join(clauses)
            n = c.execute(f"select count(*) from office_dashboard.leads where {where}", args).fetchone()[0]
            by = dict(c.execute(f"select stage, count(*) from office_dashboard.leads where {where} group by 1", args).fetchall())
    except Exception as e:
        log.warning("CRM snapshot unavailable: %s", type(e).__name__)   # class only: never log the DSN or message (may contain host/credentials)
        return None
    return {"kpis": {"New Leads": {"value": str(n), "trend": "last 30 days"}}, "panels": {"pipeline": [{"name": LABEL[s], "value": by.get(s, 0)} for s in STAGES if s in LABEL]}}

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix="/api/crm")
    def read(s=Depends(session)):
        if s["role"] not in R(): raise HTTPException(403, "You do not have access to CRM.")
        return s
    def write(s=Depends(csrf)):
        if s["role"] not in W(): raise HTTPException(403, "You do not have permission to change CRM records.")
        return s
    def arch(s=Depends(csrf)):
        if s["role"] not in A():
            audit.write("crm_archive_denied", s["id"], None, role=s["role"]); raise HTTPException(403, "You do not have permission to delete CRM records.")
        return s
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)   # no server-side prepared statements: safe behind Supabase pgbouncer (transaction mode)
    def page(table, where, args, p, size, extra="", order="t.created_at desc"):
        with db() as c:
            total = c.execute(f"select count(*) as n from office_dashboard.{table} t where not t.is_archived {where}", args).fetchone()["n"]
            rows = c.execute(f"select t.* {extra} from office_dashboard.{table} t where not t.is_archived {where} order by {order}, t.id limit %s offset %s", args + [size, (p - 1) * size]).fetchall()
        return rows, total
    def like(q): return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    def one(c, table, i):
        try: row = c.execute(f"select * from office_dashboard.{table} where id=%s and not is_archived", (i,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, "Record not found.")
        return row
    def dup(e): raise HTTPException(409, "A contact with this email already exists.")

    def exp(s=Depends(session)):
        if s["role"] not in R() or not permissions.can(s["role"], "crm.export"):
            audit.write("crm_export_denied", s["id"], None, role=s["role"]); raise HTTPException(403, "You do not have permission to export CRM records.")
        return s
    def cfilter(q="", contact_type="", organization="", date_from=None, date_to=None):
        w, a = "", []
        if q.strip(): w += " and (t.full_name ilike %s or t.email ilike %s or t.phone ilike %s or t.organization ilike %s)"; a += [like(q.strip())] * 4
        if contact_type:
            if contact_type not in CONTACT_TYPES: raise HTTPException(422, "Unknown contact type.")
            w += " and t.contact_type=%s"; a.append(contact_type)
        if organization.strip(): w += " and t.organization=%s"; a.append(organization.strip())
        if date_from: w += " and t.created_at::date >= %s"; a.append(date_from)
        if date_to: w += " and t.created_at::date <= %s"; a.append(date_to)
        if date_from and date_to and date_from > date_to: raise HTTPException(422, "Start date must be on or before end date.")
        return w, a
    def csv_safe(v, phone=False):   # neutralise spreadsheet formula injection
        v = "" if v is None else str(v)
        if phone and re.fullmatch(r"\+?[0-9 ()-]{7,20}", v): return v   # validated phone numbers (e.g. +91 98765 43210) are digits/symbols only; do not corrupt them
        return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v

    @r.get("/contacts")
    def contacts(q: str = "", contact_type: str = "", organization: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None,
                 sort: str = "created_at", dir: Literal["asc", "desc"] = "desc",
                 page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), s=Depends(read)):
        if sort not in CONTACT_SORTS: raise HTTPException(422, "Unknown sort column.")
        w, a = cfilter(q, contact_type, organization, date_from, date_to)
        rows, total = page("contacts", w, a, page_no, page_size, order=f"{CONTACT_SORTS[sort]} {dir} nulls last")
        return {"items": rows, "total": total, "page": page_no, "page_size": page_size, "can_write": s["role"] in W(), "can_archive": s["role"] in A(),
                "can_export": permissions.can(s["role"], "crm.export"), "contact_types": CONTACT_TYPES}
    @r.get("/contacts/stats")
    def contact_stats(date_from: Optional[date] = None, date_to: Optional[date] = None, s=Depends(read)):
        w, a = cfilter("", "", "", date_from, date_to)
        base = f"from office_dashboard.contacts t where not t.is_archived {w}"
        with db() as c:
            by = {k["contact_type"]: k["n"] for k in c.execute(f"select t.contact_type, count(*)::int as n {base} group by 1", a).fetchall()}
            months = c.execute(f"select to_char(date_trunc('month', t.created_at), 'YYYY-MM') as month, count(*)::int as new {base} group by 1 order by 1", a).fetchall()
            orgs = c.execute(f"select t.organization as name, count(*)::int as value {base} and t.organization is not null group by 1 order by 2 desc, 1 limit 5", a).fetchall()
            tm = {k["contact_type"]: k["n"] for k in c.execute("select contact_type, count(*)::int as n from office_dashboard.contacts where not is_archived and created_at >= date_trunc('month', now()) group by 1").fetchall()}
        run, growth = 0, []
        for m in months: run += m["new"]; growth.append({"month": m["month"], "new": m["new"], "total": run})
        return {"total": sum(by.values()), "by_type": {t: by.get(t, 0) for t in CONTACT_TYPES}, "growth": growth[-24:], "top_organizations": orgs,
                "this_month": {"total": sum(tm.values()), **{t: tm.get(t, 0) for t in CONTACT_TYPES}}}   # real rows created this calendar month; independent of the date filter
    @r.get("/contacts/organizations")
    def contact_orgs(s=Depends(read)):
        with db() as c:
            rows = c.execute("select distinct organization from office_dashboard.contacts where not is_archived and organization is not null order by 1 limit 500").fetchall()
        return {"items": [x["organization"] for x in rows]}
    @r.get("/contacts/export")
    def export_contacts(q: str = "", contact_type: str = "", organization: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None,
                        sort: str = "created_at", dir: Literal["asc", "desc"] = "desc", s=Depends(exp)):
        if sort not in CONTACT_SORTS: raise HTTPException(422, "Unknown sort column.")
        w, a = cfilter(q, contact_type, organization, date_from, date_to)
        with db() as c:
            rows = c.execute(f"select t.* from office_dashboard.contacts t where not t.is_archived {w} order by {CONTACT_SORTS[sort]} {dir} nulls last, t.id limit 10000", a).fetchall()
        buf = io.StringIO(); wr = csv.writer(buf)
        wr.writerow(["Name", "Email", "Phone", "Organization", "Contact Type", "Notes", "Date Added"])
        for x in rows: wr.writerow([csv_safe(x["full_name"]), csv_safe(x["email"]), csv_safe(x["phone"], phone=True), csv_safe(x["organization"]), x["contact_type"], csv_safe(x["notes"]), x["created_at"].date().isoformat()])
        audit.write("contacts_exported", s["id"], None, count=len(rows))
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="contacts.csv"', "X-Export-Truncated": str(len(rows) >= 10000).lower()})
    @r.post("/contacts", status_code=201)
    def add_contact(b: ContactBody, s=Depends(write)):
        if not b.full_name: raise HTTPException(422, "Name is required.")
        try:
            with db() as c: row = c.execute("insert into office_dashboard.contacts(full_name,email,phone,organization,notes,contact_type,created_by,updated_by) values(%s,%s,%s,%s,%s,%s,%s,%s) returning *", (b.full_name, b.email, b.phone, b.organization, b.notes, b.contact_type or "other", s["id"], s["id"])).fetchone()
        except psycopg.errors.UniqueViolation as e: dup(e)
        audit.write("contact_created", s["id"], None, record=str(row["id"])); return row
    @r.get("/contacts/{cid}")
    def get_contact(cid: str, s=Depends(read)):
        with db() as c: return one(c, "contacts", cid)
    @r.patch("/contacts/{cid}")
    def edit_contact(cid: str, b: ContactBody, s=Depends(write)):
        d = b.model_dump(exclude_unset=True)
        if "full_name" in d and not d["full_name"]: raise HTTPException(422, "Name cannot be empty.")
        if "contact_type" in d and not d["contact_type"]: raise HTTPException(422, "Contact type cannot be empty.")
        if not d: raise HTTPException(422, "Nothing to update.")
        try:
            with db() as c:
                one(c, "contacts", cid)
                row = c.execute("update office_dashboard.contacts set " + ",".join(f"{k}=%s" for k in d) + ",updated_by=%s,updated_at=now() where id=%s returning *", [*d.values(), s["id"], cid]).fetchone()
        except psycopg.errors.UniqueViolation as e: dup(e)
        audit.write("contact_updated", s["id"], None, record=cid); return row
    @r.delete("/contacts/{cid}")
    def archive_contact(cid: str, s=Depends(arch)):
        with db() as c:
            one(c, "contacts", cid)
            if c.execute("select 1 from office_dashboard.leads where contact_id=%s and not is_archived and stage not in ('won','lost')", (cid,)).fetchone(): raise HTTPException(409, "This contact has open leads. Close or archive them first.")
            c.execute("update office_dashboard.contacts set is_archived=true,updated_by=%s,updated_at=now() where id=%s", (s["id"], cid))
        audit.write("contact_archived", s["id"], None, record_type="contact", record=cid); return {"ok": True}

    # ---- Leads & Pipeline ------------------------------------------------------------------------------------------------
    LEAD_COLS = ("select t.*, c.full_name as contact_name, c.email as contact_email, c.phone as contact_phone, c.organization as organization, c.contact_type as contact_type ")
    LEAD_FROM = "from office_dashboard.leads t left join office_dashboard.contacts c on c.id=t.contact_id where not t.is_archived"
    def ui_stage(row):   # read-time mapping only; the stored stage value is never rewritten
        row["stage_ui"] = DB_TO_UI.get(row["stage"], "new"); row["stage_label"] = UI_LABEL[row["stage_ui"]]; return row
    def dates(date_from, date_to):
        if date_from and date_to and date_from > date_to: raise HTTPException(422, "Start date must be on or before end date.")
        w, a = "", []
        if date_from: w += " and t.created_at::date >= %s"; a.append(date_from)
        if date_to: w += " and t.created_at::date <= %s"; a.append(date_to)
        return w, a
    def lfilter(q="", stage="", source="", date_from=None, date_to=None, follow_ups=False):
        w, a = dates(date_from, date_to)
        if follow_ups: w += " and t.next_follow_up is not null and t.stage not in ('won','lost')"   # open leads with a follow-up date (Upcoming Follow-ups card)
        if q.strip(): w += " and (t.title ilike %s or t.source ilike %s or c.full_name ilike %s or c.email ilike %s or c.phone ilike %s or c.organization ilike %s)"; a += [like(q.strip())] * 6
        if stage:
            if stage in UI_DB_VALUES: w += " and t.stage = any(%s)"; a.append(list(UI_DB_VALUES[stage]))
            elif stage in RANK: w += " and t.stage=%s"; a.append(stage)
            else: raise HTTPException(422, "Unknown stage.")
        if source.strip(): w += " and lower(t.source)=lower(%s)"; a.append(source.strip())
        return w, a
    def find_or_create_contact(c, name, email, phone, org, uid):
        """Reuse a matching active contact (same email, else same name + organization) instead of creating a duplicate. Returns (row, created)."""
        if email:
            row = c.execute("select * from office_dashboard.contacts where lower(email)=lower(%s) and not is_archived", (email,)).fetchone()
            if row: return row, False
        elif name:
            rows = c.execute("select * from office_dashboard.contacts where not is_archived and lower(full_name)=lower(%s) and coalesce(lower(organization),'')=coalesce(lower(%s),'') limit 2", (name, org)).fetchall()
            if len(rows) == 1: return rows[0], False
        if not name: raise HTTPException(422, "Contact name is required to create a new contact.")
        try:
            with c.transaction():   # savepoint: a lost race on the unique email index must not abort the whole request
                return c.execute("insert into office_dashboard.contacts(full_name,email,phone,organization,contact_type,created_by,updated_by) values(%s,%s,%s,%s,'other',%s,%s) returning *", (name, email, phone, org, uid, uid)).fetchone(), True
        except psycopg.errors.UniqueViolation:
            return c.execute("select * from office_dashboard.contacts where lower(email)=lower(%s) and not is_archived", (email,)).fetchone(), False
    def stage_note(old, new, reason=None):
        n = f"Stage changed: {UI_LABEL[DB_TO_UI.get(old, 'new')]} → {UI_LABEL[DB_TO_UI.get(new, 'new')]}"
        return n + (f" ({reason.strip()})" if reason and reason.strip() else "")

    @r.get("/leads")
    def leads(q: str = "", stage: str = "", source: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None, follow_ups: bool = False,
              sort: str = "created_at", dir: Literal["asc", "desc"] = "desc",
              page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), s=Depends(read)):
        if sort not in LEAD_SORTS: raise HTTPException(422, "Unknown sort column.")
        w, a = lfilter(q, stage, source, date_from, date_to, follow_ups)
        with db() as c:
            total = c.execute("select count(*) as n " + LEAD_FROM + w, a).fetchone()["n"]
            rows = c.execute(LEAD_COLS + LEAD_FROM + w + f" order by {LEAD_SORTS[sort]} {dir} nulls last, t.id limit %s offset %s", a + [page_size, (page_no - 1) * page_size]).fetchall()
            legacy = [x["source"] for x in c.execute("select distinct source from office_dashboard.leads where not is_archived and source is not null order by 1 limit 50").fetchall()]
        srcs = LEAD_SOURCES + [x for x in legacy if x.lower() not in {y.lower() for y in LEAD_SOURCES}]
        return {"items": [ui_stage(x) for x in rows], "total": total, "page": page_no, "page_size": page_size, "can_write": s["role"] in W(), "can_archive": s["role"] in A(),
                "can_export": permissions.can(s["role"], "crm.export"), "stages": STAGES, "stage_labels": STAGE_LABELS, "ui_stages": UI_STAGES, "sources": srcs}
    @r.get("/leads/stats")
    def lead_stats(date_from: Optional[date] = None, date_to: Optional[date] = None, s=Depends(read)):
        """KPI / chart numbers from real rows. Stage counts and trend follow the date range (by created date); growth is calendar-month vs previous month and independent of the range."""
        w, a = dates(date_from, date_to)
        base = "from office_dashboard.leads t where not t.is_archived" + w
        gran = "day" if date_from and date_to and (date_to - date_from).days <= 92 else "month"
        fmt = "YYYY-MM-DD" if gran == "day" else "YYYY-MM"
        with db() as c:
            by_db = c.execute(f"select t.stage, count(*)::int as n, coalesce(sum(t.value),0)::float8 as v {base} group by 1", a).fetchall()
            tr = c.execute(f"select to_char(date_trunc('{gran}', t.created_at), '{fmt}') as period, count(*)::int as n {base} group by 1 order by 1", a).fetchall()
            gr = c.execute("select stage, count(*) filter (where created_at >= date_trunc('month', now()))::int as cur, "
                           "count(*) filter (where created_at >= date_trunc('month', now()) - interval '1 month' and created_at < date_trunc('month', now()))::int as prev "
                           "from office_dashboard.leads where not is_archived group by 1").fetchall()
        by = {u["key"]: {"count": 0, "value": 0.0} for u in UI_STAGES}
        for x in by_db: k = DB_TO_UI.get(x["stage"], "new"); by[k]["count"] += x["n"]; by[k]["value"] += x["v"]
        cnt = {x["period"]: x["n"] for x in tr}; pts = []
        if cnt:   # fill empty periods with real zeros so the line is not misleading
            first, last = min(cnt), max(cnt)
            if gran == "month":
                y, m, ly, lm = int(first[:4]), int(first[5:7]), int(last[:4]), int(last[5:7])
                while (y, m) <= (ly, lm):
                    k = f"{y:04d}-{m:02d}"; pts.append({"period": k, "count": cnt.get(k, 0)}); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
                pts = pts[-24:]
            else:
                d0, d1 = date.fromisoformat(first), date.fromisoformat(last)
                while d0 <= d1: k = d0.isoformat(); pts.append({"period": k, "count": cnt.get(k, 0)}); d0 += timedelta(days=1)
        g = {u["key"]: {"this_month": 0, "last_month": 0} for u in UI_STAGES}
        for x in gr: k = DB_TO_UI.get(x["stage"], "new"); g[k]["this_month"] += x["cur"]; g[k]["last_month"] += x["prev"]
        g["total"] = {"this_month": sum(v["this_month"] for v in g.values()), "last_month": sum(v["last_month"] for v in g.values())}
        for v in g.values(): v["pct"] = round((v["this_month"] - v["last_month"]) * 100 / v["last_month"], 1) if v["last_month"] else None   # null = no previous-month data: show nothing
        return {"total": {"count": sum(v["count"] for v in by.values()), "value": sum(v["value"] for v in by.values())}, "by_stage": by,
                "trend": {"granularity": gran, "points": pts}, "growth": g, "ui_stages": UI_STAGES}
    @r.get("/leads/export")
    def export_leads(q: str = "", stage: str = "", source: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None,
                     sort: str = "created_at", dir: Literal["asc", "desc"] = "desc", s=Depends(exp)):
        if sort not in LEAD_SORTS: raise HTTPException(422, "Unknown sort column.")
        w, a = lfilter(q, stage, source, date_from, date_to)   # identical filters to the table
        with db() as c:
            rows = c.execute(LEAD_COLS + LEAD_FROM + w + f" order by {LEAD_SORTS[sort]} {dir} nulls last, t.id limit 10000", a).fetchall()
        buf = io.StringIO(); wr = csv.writer(buf)
        wr.writerow(["Lead Title", "Contact", "Organization", "Email", "Phone", "Source", "Estimated Value (INR)", "Stage", "Expected Closure", "Next Follow-up", "Created Date", "Notes"])
        for x in rows:
            wr.writerow([csv_safe(x["title"]), csv_safe(x["contact_name"]), csv_safe(x["organization"]), csv_safe(x["contact_email"]), csv_safe(x["contact_phone"], phone=True), csv_safe(x["source"]),
                         "" if x["value"] is None else x["value"], UI_LABEL[DB_TO_UI.get(x["stage"], "new")], x["expected_closure"].isoformat() if x["expected_closure"] else "",
                         x["next_follow_up"].isoformat() if x["next_follow_up"] else "", x["created_at"].date().isoformat(), csv_safe(x["notes"])])
        audit.write("leads_exported", s["id"], None, count=len(rows))
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="leads.csv"', "X-Export-Truncated": str(len(rows) >= 10000).lower()})
    @r.get("/leads/followups")
    def lead_followups(limit: int = Query(5, ge=1, le=20), s=Depends(read)):
        """Open leads with a follow-up date, soonest first (overdue ones come first). Real rows only."""
        with db() as c:
            rows = c.execute(LEAD_COLS + LEAD_FROM + " and t.next_follow_up is not null and t.stage not in ('won','lost') order by t.next_follow_up asc, t.id limit %s", (limit,)).fetchall()
        return {"items": [ui_stage(x) for x in rows]}
    @r.get("/leads/{lid}")
    def get_lead(lid: str, s=Depends(read)):
        with db() as c:
            one(c, "leads", lid)
            row = c.execute(LEAD_COLS + LEAD_FROM + " and t.id=%s", (lid,)).fetchone()
            acts = c.execute("select * from office_dashboard.lead_activities where lead_id=%s order by created_at desc, id desc limit 200", (lid,)).fetchall()
        row = ui_stage(row); row["activities"] = acts; return row
    @r.post("/leads", status_code=201)
    def add_lead(b: LeadCreate, s=Depends(write)):
        if not b.title: raise HTTPException(422, "Title is required.")
        stage = b.stage or "new"
        if stage == "lost" and not b.lost_reason: raise HTTPException(422, "A reason is required for a lost lead.")
        src = norm_source(b.source); made = reused = False
        with db() as c:
            cid = b.contact_id or None
            if cid: one(c, "contacts", cid)
            elif b.contact_name or b.email:
                ct, made = find_or_create_contact(c, b.contact_name, b.email, b.phone, b.organization, s["id"]); cid = str(ct["id"]); reused = not made
            elif b.phone or b.organization: raise HTTPException(422, "Add a contact name or email, or pick an existing contact.")
            row = c.execute("insert into office_dashboard.leads(title,contact_id,source,stage,value,next_follow_up,expected_closure,notes,lost_reason,converted_at,created_by,updated_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                            (b.title, cid, src, stage, b.value, b.next_follow_up, b.expected_closure, b.notes, b.lost_reason, datetime.now(timezone.utc) if stage == "won" else None, s["id"], s["id"])).fetchone()
        if made: audit.write("contact_created", s["id"], None, record=str(ct["id"]), via="lead")
        audit.write("lead_created", s["id"], None, record=str(row["id"])); row = ui_stage(row); row["contact_created"] = made; row["contact_reused"] = reused; return row
    @r.patch("/leads/{lid}")
    def edit_lead(lid: str, b: LeadBody, s=Depends(write)):
        d = b.model_dump(exclude_unset=True)
        if not d: raise HTTPException(422, "Nothing to update.")
        for k in ("title", "stage"):
            if k in d and d[k] is None: raise HTTPException(422, f"{k.capitalize()} cannot be empty.")
        with db() as c:
            cur = one(c, "leads", lid)
            if "source" in d: d["source"] = norm_source(d["source"], cur["source"])
            moved = "stage" in d and d["stage"] != cur["stage"]
            if moved:
                if cur["stage"] in ("won", "lost"): raise HTTPException(409, f"A {cur['stage']} lead cannot change stage.")
                if d["stage"] != "lost" and RANK[d["stage"]] < RANK.get(cur["stage"], 0): raise HTTPException(409, "A lead cannot move back to an earlier stage.")
                if d["stage"] == "lost" and not (d.get("lost_reason") or "").strip(): raise HTTPException(422, "A reason is required for a lost lead.")
                if d["stage"] == "won": d["converted_at"] = datetime.now(timezone.utc)
            if d.get("contact_id"): one(c, "contacts", d["contact_id"])
            row = c.execute("update office_dashboard.leads set " + ",".join(f"{k}=%s" for k in d) + ",updated_by=%s,updated_at=now() where id=%s returning *", [*d.values(), s["id"], lid]).fetchone()
            if moved: c.execute("insert into office_dashboard.lead_activities(lead_id,note,created_by) values(%s,%s,%s)", (lid, stage_note(cur["stage"], row["stage"], d.get("lost_reason")), s["id"]))   # stage history = existing lead_activities
        audit.write("lead_updated", s["id"], None, record=lid, stage=row["stage"])
        if moved: audit.write("lead_stage_changed", s["id"], None, record=lid, from_stage=cur["stage"], to_stage=row["stage"])
        return ui_stage(row)
    @r.post("/leads/{lid}/convert")
    def convert_lead(lid: str, b: ConvertBody, s=Depends(write)):
        """Mark an open lead Converted (db value 'won'), optionally linking an existing contact, reusing/creating one without duplicates, and marking it a customer."""
        made = typed = False
        with db() as c:
            cur = one(c, "leads", lid)
            if cur["stage"] in ("won", "lost"): raise HTTPException(409, "Only an open lead can be converted.")
            cid = str(cur["contact_id"]) if cur["contact_id"] else None
            if b.contact_id: one(c, "contacts", b.contact_id); cid = b.contact_id
            elif not cid and b.new_contact and (b.new_contact.contact_name or b.new_contact.email):
                n = b.new_contact; ct, made = find_or_create_contact(c, n.contact_name, n.email, n.phone, n.organization, s["id"]); cid = str(ct["id"])
            if b.mark_customer:
                if not cid: raise HTTPException(422, "Link or create a contact before marking it as a customer.")
                ct = one(c, "contacts", cid)
                if ct["contact_type"] not in ("other", "customer"): raise HTTPException(409, f"This contact is a {ct['contact_type']}. Change its type in CRM & Contacts first.")   # never overwrite a deliberate classification
                if ct["contact_type"] != "customer": c.execute("update office_dashboard.contacts set contact_type='customer',updated_by=%s,updated_at=now() where id=%s", (s["id"], cid)); typed = True
            row = c.execute("update office_dashboard.leads set stage='won',contact_id=%s,converted_at=now(),updated_by=%s,updated_at=now() where id=%s returning *", (cid, s["id"], lid)).fetchone()
            c.execute("insert into office_dashboard.lead_activities(lead_id,note,created_by) values(%s,%s,%s)", (lid, stage_note(cur["stage"], "won") + ("; contact marked as customer" if typed else ""), s["id"]))
        if made: audit.write("contact_created", s["id"], None, record=cid, via="lead_conversion")
        if typed: audit.write("contact_updated", s["id"], None, record=cid, contact_type="customer", via="lead_conversion")
        audit.write("lead_converted", s["id"], None, record=lid, contact=cid); row = ui_stage(row); row["contact_created"] = made; row["contact_marked_customer"] = typed; return row
    @r.delete("/leads/{lid}")
    def archive_lead(lid: str, s=Depends(arch)):
        with db() as c: one(c, "leads", lid); c.execute("update office_dashboard.leads set is_archived=true,updated_by=%s,updated_at=now() where id=%s", (s["id"], lid))
        audit.write("lead_archived", s["id"], None, record_type="lead", record=lid); return {"ok": True}
    @r.post("/leads/{lid}/activities", status_code=201)
    def add_note(lid: str, b: Note, s=Depends(write)):
        with db() as c: one(c, "leads", lid); row = c.execute("insert into office_dashboard.lead_activities(lead_id,note,created_by) values(%s,%s,%s) returning *", (lid, b.note.strip(), s["id"])).fetchone()
        audit.write("lead_note_added", s["id"], None, record=lid); return row
    @r.get("/leads/{lid}/activities")
    def notes(lid: str, s=Depends(read)):
        with db() as c: one(c, "leads", lid); return c.execute("select * from office_dashboard.lead_activities where lead_id=%s order by created_at desc", (lid,)).fetchall()
    return r
