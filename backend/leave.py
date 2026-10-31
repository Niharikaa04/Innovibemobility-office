"""HR & Leave API. Rules live in leavelogic.py; permissions in permissions.py (module "leave"), enforced here on the server.
Employees/technicians are own-only. Approval needs leave.approve and never your own request. Leave types and holidays need leave.admin (CEO in the proposed matrix).
Working days come from attendance_config (db/007); requests are refused until that exists. Every write is audited in the same transaction. Needs db/007 + db/008.
NOT built yet: notifying people (no notification system exists), carry-forward, leave on behalf of someone else, manager-based approval."""
from datetime import date, datetime, timezone
from typing import Literal, Optional
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
import attendance, attendancelogic as AL, auditdb, leavelogic as L, permissions

TYPE_COLS = ("code", "name", "is_paid", "annual_entitlement_days", "allow_half_day", "min_notice_days", "allow_backdated_days", "max_consecutive_days", "is_active")
class TypeIn(BaseModel):
    code: Optional[str] = Field(None, pattern=r"^[a-z0-9_]{2,30}$"); name: Optional[str] = Field(None, min_length=1, max_length=80); is_paid: Optional[bool] = None
    annual_entitlement_days: Optional[float] = Field(None, ge=0, le=999); allow_half_day: Optional[bool] = None; min_notice_days: Optional[int] = Field(None, ge=0, le=365)
    allow_backdated_days: Optional[int] = Field(None, ge=0, le=365); max_consecutive_days: Optional[int] = Field(None, ge=1, le=366); is_active: Optional[bool] = None
NOT_NULL = ("code", "name", "is_paid", "allow_half_day", "min_notice_days", "allow_backdated_days", "is_active")
def type_fields(b: TypeIn) -> dict:
    d = {k: v for k, v in b.model_dump(exclude_unset=True).items() if k in TYPE_COLS}
    if any(k in NOT_NULL and v is None for k, v in d.items()): raise HTTPException(422, "Those fields cannot be empty.")
    return d
class RequestIn(BaseModel):
    leave_type_id: str; start_date: date; end_date: date; half_day: Optional[Literal["first_half", "second_half"]] = None; reason: str = Field(min_length=1, max_length=500)
class Decision(BaseModel):
    decision: Literal["approve", "reject"]; note: Optional[str] = Field(None, max_length=1000)
class Cancel(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)
class HolidayIn(BaseModel):
    holiday_date: date; name: str = Field(min_length=1, max_length=120)

def build_router(dsn, need, cfg, ip):
    r = APIRouter(prefix="/api/leave")
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def users_table(): return sql.SQL(".").join(map(sql.Identifier, cfg["table"].split(".")))
    def names(c, ids):
        ids = sorted({i for i in ids if i})
        if not ids: return {}
        q = sql.SQL("select {i}::text as id, {n} as name from {t} where {i}::text = any(%s)").format(i=sql.Identifier(cfg["id"]), n=sql.Identifier(cfg["name"]), t=users_table())
        return {x["id"]: x["name"] for x in c.execute(q, (ids,)).fetchall()}
    def rule(e: L.LeaveError): raise HTTPException(e.status, e.message)
    def conf(c):
        row = c.execute("select timezone, working_days from office_dashboard.attendance_config").fetchone()
        if not row: raise HTTPException(409, "Leave needs the working days and timezone from Attendance settings. A CEO must set those up first.")
        return row["timezone"], list(row["working_days"])
    def today_local(c):
        row = c.execute("select timezone from office_dashboard.attendance_config").fetchone()
        return AL.work_date(attendance.clock(), row["timezone"] if row else "UTC")
    def holidays_between(c, a, b): return {x["holiday_date"] for x in c.execute("select holiday_date from office_dashboard.holidays where holiday_date between %s and %s", (a, b)).fetchall()}
    def get_type(c, tid):
        try: t = c.execute("select * from office_dashboard.leave_types where id=%s", (tid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: t = None
        if not t: raise HTTPException(422, "Unknown leave type.")
        return t
    def used(c, uid, tid, year, exclude=None):
        rows = c.execute("select status, coalesce(sum(days),0) as d from office_dashboard.leave_requests where user_id=%s and leave_type_id=%s and extract(year from start_date)=%s and status in ('approved','pending')"
                         + (" and id<>%s" if exclude else "") + " group by status", (uid, tid, year) + ((exclude,) if exclude else ())).fetchall()
        m = {x["status"]: x["d"] for x in rows}; return m.get("approved", 0), m.get("pending", 0)
    def bal(c, uid, t, year, exclude=None):
        a, p = used(c, uid, t["id"], year, exclude); return L.balance(t["annual_entitlement_days"], a, p)
    def lock(c, uid): c.execute("select pg_advisory_xact_lock(hashtext(%s))", (uid,))

    @r.get("/meta")
    def meta(s=Depends(need("leave.read"))):
        with db() as c:
            types = c.execute("select * from office_dashboard.leave_types" + ("" if permissions.can(s["role"], "leave.admin") else " where is_active") + " order by name").fetchall()
        return {"types": types, "can_write": permissions.can(s["role"], "leave.write"), "can_approve": permissions.can(s["role"], "leave.approve"), "can_admin": permissions.can(s["role"], "leave.admin"), "own_only": s["own_only"], "me": s["id"]}

    # ---- leave types (admin) ----
    @r.post("/types", status_code=201)
    def add_type(b: TypeIn, request: Request, s=Depends(need("leave.admin", True))):
        if not (b.code and b.name): raise HTTPException(422, "Code and name are required.")
        d = type_fields(b)
        with db() as c:
            try: row = c.execute(sql.SQL("insert into office_dashboard.leave_types({}) values({}) returning *").format(sql.SQL(",").join(map(sql.Identifier, d)), sql.SQL(",").join(sql.Placeholder() for _ in d)), list(d.values())).fetchone()
            except psycopg.errors.UniqueViolation: raise HTTPException(409, "A leave type with this code already exists.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.type_created", entity_type="leave_type", entity_id=row["id"], after=d, ip=ip(request)); return row

    @r.patch("/types/{tid}")
    def edit_type(tid: str, b: TypeIn, request: Request, s=Depends(need("leave.admin", True))):
        d = type_fields(b)
        if not d: raise HTTPException(422, "Nothing to update.")
        with db() as c:
            old = get_type(c, tid)
            try: row = c.execute(sql.SQL("update office_dashboard.leave_types set {}, updated_at=now() where id=%s returning *").format(sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in d)), list(d.values()) + [tid]).fetchone()
            except psycopg.errors.UniqueViolation: raise HTTPException(409, "A leave type with this code already exists.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.type_updated", entity_type="leave_type", entity_id=tid, before={k: old[k] for k in d}, after=d, ip=ip(request)); return row

    # ---- holidays (admin writes, anyone with leave.read reads) ----
    @r.get("/holidays")
    def list_holidays(year: int = Query(..., ge=2000, le=2100), s=Depends(need("leave.read"))):
        with db() as c: return {"items": c.execute("select * from office_dashboard.holidays where extract(year from holiday_date)=%s order by holiday_date", (year,)).fetchall(), "can_admin": permissions.can(s["role"], "leave.admin")}
    @r.post("/holidays", status_code=201)
    def add_holiday(b: HolidayIn, request: Request, s=Depends(need("leave.admin", True))):
        with db() as c:
            try: row = c.execute("insert into office_dashboard.holidays(holiday_date,name,created_by) values(%s,%s,%s) returning *", (b.holiday_date, b.name.strip(), s["id"])).fetchone()
            except psycopg.errors.UniqueViolation: raise HTTPException(409, "That date is already a holiday.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.holiday_added", entity_type="holiday", entity_id=row["id"], after={"date": b.holiday_date, "name": b.name.strip()}, ip=ip(request)); return row
    @r.delete("/holidays/{hid}")
    def del_holiday(hid: str, request: Request, s=Depends(need("leave.admin", True))):
        with db() as c:
            try: row = c.execute("delete from office_dashboard.holidays where id=%s returning *", (hid,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: row = None
            if not row: raise HTTPException(404, "Holiday not found.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.holiday_removed", entity_type="holiday", entity_id=hid, before={"date": row["holiday_date"], "name": row["name"]}, ip=ip(request)); return {"ok": True}

    # ---- balances ----
    @r.get("/balances")
    def balances(year: Optional[int] = Query(None, ge=2000, le=2100), user_id: Optional[str] = None, s=Depends(need("leave.read"))):
        who = user_id or s["id"]
        if who != s["id"] and s["own_only"]: raise HTTPException(403, "You can only view your own leave balance.")
        with db() as c:
            y = year or today_local(c).year
            out = []
            for t in c.execute("select * from office_dashboard.leave_types where is_active order by name").fetchall():
                b = bal(c, who, t, y); out.append({"leave_type_id": t["id"], "code": t["code"], "name": t["name"], **b})
            return {"year": y, "user_id": who, "name": names(c, [who]).get(who), "items": out}

    # ---- requests ----
    def decorate(rows, c, s):
        nm = names(c, [x for q in rows for x in (q["user_id"], q["decided_by"], q["cancelled_by"])]); tn = {t["id"]: t["name"] for t in c.execute("select id, name from office_dashboard.leave_types").fetchall()}
        td = today_local(c); appr = permissions.can(s["role"], "leave.approve")
        for q in rows:
            q["name"] = nm.get(q["user_id"]); q["type_name"] = tn.get(q["leave_type_id"]); q["decided_by_name"] = nm.get(q["decided_by"])
            q["can_decide"] = appr and q["status"] == "pending" and q["user_id"] != s["id"]
            try: L.can_cancel(q["status"], q["start_date"], td, q["user_id"] == s["id"], appr); q["can_cancel"] = True
            except L.LeaveError: q["can_cancel"] = False
        return rows

    @r.post("/requests", status_code=201)
    def request_leave(b: RequestIn, request: Request, s=Depends(need("leave.write", True))):
        with db() as c:
            tz, wd = conf(c); today = AL.work_date(attendance.clock(), tz); t = get_type(c, b.leave_type_id)
            try:
                L.validate_request(b.start_date, b.end_date, today, b.reason, t, b.half_day)
                days = L.count_days(b.start_date, b.end_date, wd, holidays_between(c, b.start_date, b.end_date), b.half_day); L.check_length(days, t)
            except L.LeaveError as e: rule(e)
            lock(c, s["id"])
            if c.execute("select 1 from office_dashboard.leave_requests where user_id=%s and status in ('pending','approved') and start_date<=%s and end_date>=%s limit 1", (s["id"], b.end_date, b.start_date)).fetchone():
                raise HTTPException(409, "You already have a pending or approved leave request overlapping these dates.")
            try: L.check_balance(days, bal(c, s["id"], t, b.start_date.year))
            except L.LeaveError as e: rule(e)
            row = c.execute("insert into office_dashboard.leave_requests(user_id,leave_type_id,start_date,end_date,half_day,days,reason) values(%s,%s,%s,%s,%s,%s,%s) returning *",
                            (s["id"], t["id"], b.start_date, b.end_date, b.half_day, days, b.reason.strip())).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.requested", entity_type="leave_request", entity_id=row["id"],
                           after={"type": t["code"], "start_date": b.start_date, "end_date": b.end_date, "days": days, "half_day": b.half_day}, ip=ip(request))
            return decorate([row], c, s)[0]

    @r.get("/requests")
    def list_requests(status: str = "", mine: bool = False, s=Depends(need("leave.read"))):
        if status and status not in L.STATUSES: raise HTTPException(422, "Unknown status.")
        w, a = "true", []
        if s["own_only"] or mine: w += " and user_id=%s"; a.append(s["id"])
        if status: w += " and status=%s"; a.append(status)
        with db() as c:
            rows = c.execute(f"select * from office_dashboard.leave_requests where {w} order by (status<>'pending'), start_date desc limit 300", a).fetchall()
            return {"items": decorate(rows, c, s)}

    def load(c, rid, for_update=True):
        try: q = c.execute("select * from office_dashboard.leave_requests where id=%s" + (" for update" if for_update else ""), (rid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: q = None
        if not q: raise HTTPException(404, "Leave request not found.")
        return q

    @r.post("/requests/{rid}/decision")
    def decide(rid: str, b: Decision, request: Request, s=Depends(need("leave.approve", True))):
        if b.decision == "reject" and not (b.note or "").strip(): raise HTTPException(422, "Please give a reason for rejecting.")
        with db() as c:
            q = load(c, rid); lock(c, q["user_id"]); q = load(c, rid)
            try: L.can_decide(s["id"], q["user_id"], q["status"])
            except L.LeaveError as e: rule(e)
            if b.decision == "approve":
                t = get_type(c, q["leave_type_id"]); a, _ = used(c, q["user_id"], t["id"], q["start_date"].year, exclude=q["id"])
                try: L.check_balance(q["days"], L.balance(t["annual_entitlement_days"], a, 0))
                except L.LeaveError as e: rule(e)
            new = c.execute("update office_dashboard.leave_requests set status=%s, decided_by=%s, decided_at=now(), decision_note=%s where id=%s returning *",
                            ("approved" if b.decision == "approve" else "rejected", s["id"], (b.note or "").strip() or None, rid)).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action=f"leave.{new['status']}", entity_type="leave_request", entity_id=rid, before={"status": "pending"},
                           after={"status": new["status"], "note": new["decision_note"], "days": new["days"], "user_id": new["user_id"]}, ip=ip(request))
            return decorate([new], c, s)[0]

    @r.post("/requests/{rid}/cancel")
    def cancel(rid: str, b: Cancel, request: Request, s=Depends(need("leave.write", True))):
        with db() as c:
            q = load(c, rid); owner = q["user_id"] == s["id"]; appr = permissions.can(s["role"], "leave.approve")
            if not owner and not appr: raise HTTPException(404, "Leave request not found.")
            try: L.can_cancel(q["status"], q["start_date"], today_local(c), owner, appr)
            except L.LeaveError as e: rule(e)
            if not owner and not (b.note or "").strip(): raise HTTPException(422, "Please give a reason for cancelling someone else's leave.")
            new = c.execute("update office_dashboard.leave_requests set status='cancelled', cancelled_by=%s, cancelled_at=now(), decision_note=coalesce(%s, decision_note) where id=%s returning *", ((s["id"]), (b.note or "").strip() or None, rid)).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="leave.cancelled", entity_type="leave_request", entity_id=rid, before={"status": q["status"]},
                           after={"status": "cancelled", "by_owner": owner, "note": (b.note or "").strip() or None, "user_id": q["user_id"]}, ip=ip(request))
            return decorate([new], c, s)[0]

    @r.get("/calendar")
    def calendar(month: str, s=Depends(need("leave.read"))):
        try: y, m = (int(x) for x in month.split("-")); a = date(y, m, 1)
        except (ValueError, TypeError): raise HTTPException(422, "Month must look like 2026-10.")
        b = date(y + (m == 12), m % 12 + 1, 1)
        with db() as c:
            w, args = "status in ('approved','pending') and start_date<%s and end_date>=%s", [b, a]
            if s["own_only"]: w += " and user_id=%s"; args.append(s["id"])
            rows = c.execute(f"select * from office_dashboard.leave_requests where {w} order by start_date", args).fetchall()
            nm = names(c, [x["user_id"] for x in rows]); tn = {t["id"]: t["name"] for t in c.execute("select id, name from office_dashboard.leave_types").fetchall()}
            for x in rows: x["name"] = nm.get(x["user_id"]); x["type_name"] = tn.get(x["leave_type_id"])
            hol = c.execute("select * from office_dashboard.holidays where holiday_date>=%s and holiday_date<%s order by holiday_date", (a, b)).fetchall()
            return {"month": month, "items": rows, "holidays": hol}
    return r
