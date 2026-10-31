"""Attendance API. Rules live in attendancelogic.py; permissions in permissions.py (module "attendance"), enforced here on the server.
Check-in/out always record the SERVER clock; the client never sends a time. Check-in/out are always for the signed-in user.
Every write is audited in the database inside the same transaction (db/005). Needs db/007."""
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
import attendancelogic as L, auditdb, leavelogic as LV, permissions

clock = lambda: datetime.now(timezone.utc)      # tests replace this

class ConfigIn(BaseModel):
    start_time: time; end_time: time; grace_minutes: int = Field(ge=0, le=240); timezone: str = Field(min_length=1, max_length=64)
    working_days: list[int] = Field(min_length=1, max_length=7)
class CorrectionIn(BaseModel):
    work_date: date; check_in_time: Optional[time] = None; check_out_time: Optional[time] = None; reason: str = Field(min_length=1, max_length=500)
class Decision(BaseModel):
    decision: Literal["approve", "reject"]; note: Optional[str] = Field(None, max_length=1000)

def build_router(dsn, need, cfg, ip):
    r = APIRouter(prefix="/api/attendance")
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def users_table(): return sql.SQL(".").join(map(sql.Identifier, cfg["table"].split(".")))
    def names(c, ids):
        ids = sorted({i for i in ids if i})
        if not ids: return {}
        q = sql.SQL("select {i}::text as id, {n} as name from {t} where {i}::text = any(%s)").format(i=sql.Identifier(cfg["id"]), n=sql.Identifier(cfg["name"]), t=users_table())
        return {x["id"]: x["name"] for x in c.execute(q, (ids,)).fetchall()}
    def rule(e: L.AttendanceError): raise HTTPException(e.status, e.message)
    def shift(c):
        row = c.execute("select * from office_dashboard.attendance_config").fetchone()
        return None if not row else dict(start=row["start_time"], end=row["end_time"], grace_minutes=row["grace_minutes"], timezone=row["timezone"], working_days=list(row["working_days"]))
    def need_shift(c):
        sh = shift(c)
        if not sh: raise HTTPException(409, "Attendance is not set up yet. An administrator must set the shift, timezone and working days first.")
        return sh
    def target(s, user_id):
        who = user_id or s["id"]
        if who != s["id"] and s["own_only"]: raise HTTPException(403, "You can only view your own attendance.")
        return who
    def month_range(month: str):
        try: y, m = (int(x) for x in month.split("-")); first = date(y, m, 1)
        except (ValueError, TypeError): raise HTTPException(422, "Month must look like 2026-10.")
        return y, m, first, date(y + (m == 12), m % 12 + 1, 1)
    def leave_ctx(c, who, y, m, a, b, wd):
        """Holidays + approved leave for the month. Returns empty sets if db/008 has not been applied yet (attendance keeps working)."""
        try:
            with c.transaction():
                hol = {x["holiday_date"] for x in c.execute("select holiday_date from office_dashboard.holidays where holiday_date>=%s and holiday_date<%s", (a, b)).fetchall()}
                reqs = c.execute("select start_date,end_date,half_day from office_dashboard.leave_requests where user_id=%s and status='approved' and start_date<%s and end_date>=%s", (who, b, a)).fetchall()
        except psycopg.errors.UndefinedTable: return set(), {}
        return hol, LV.leave_day_map(reqs, y, m, wd, hol)
    def derive(rows, sh):
        for x in rows:
            x.update(L.classify(x["check_in"], x["check_out"], sh) if sh else {"late_minutes": None, "early_minutes": None, "worked_minutes": None})
        return rows
    def pub(sh): return None if not sh else {"start_time": sh["start"].strftime("%H:%M"), "end_time": sh["end"].strftime("%H:%M"), "grace_minutes": sh["grace_minutes"], "timezone": sh["timezone"], "working_days": sh["working_days"]}

    @r.get("/config")
    def get_config(s=Depends(need("attendance.read"))):
        with db() as c: sh = shift(c)
        return {"configured": bool(sh), "config": pub(sh), "can_configure": permissions.can(s["role"], "attendance.admin"),
                "can_write": permissions.can(s["role"], "attendance.write"), "can_approve": permissions.can(s["role"], "attendance.approve"), "own_only": s["own_only"],
                "definitions": "Late: checked in after shift start + grace (minutes counted from shift start). Early departure: checked out before shift end. Days with no record are not treated as absence: leave and holidays are not connected yet."}

    @r.put("/config")
    def put_config(b: ConfigIn, request: Request, s=Depends(need("attendance.admin", True))):
        try: L.validate_shift(b.start_time, b.end_time, b.grace_minutes, b.timezone, b.working_days)
        except L.AttendanceError as e: rule(e)
        days = sorted(b.working_days)
        with db() as c:
            before = pub(shift(c))
            c.execute("insert into office_dashboard.attendance_config(id,start_time,end_time,grace_minutes,timezone,working_days,updated_by,updated_at) values(true,%s,%s,%s,%s,%s,%s,now())"
                      " on conflict (id) do update set start_time=excluded.start_time,end_time=excluded.end_time,grace_minutes=excluded.grace_minutes,timezone=excluded.timezone,working_days=excluded.working_days,updated_by=excluded.updated_by,updated_at=now()",
                      (b.start_time, b.end_time, b.grace_minutes, b.timezone, days, s["id"]))
            after = pub(shift(c))
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="attendance.config_changed", entity_type="attendance_config", entity_id="1", before=before, after=after, ip=ip(request))
        return {"configured": True, "config": after}

    @r.get("/today")
    def today(s=Depends(need("attendance.read"))):
        with db() as c:
            sh = shift(c)
            if not sh: return {"configured": False, "record": None}
            d = L.work_date(clock(), sh["timezone"])
            row = c.execute("select * from office_dashboard.attendance_records where user_id=%s and work_date=%s", (s["id"], d)).fetchone()
            return {"configured": True, "work_date": d, "server_time": clock(), "record": derive([row], sh)[0] if row else None}

    @r.post("/check-in", status_code=201)
    def check_in(request: Request, s=Depends(need("attendance.write", True))):
        with db() as c:
            sh = need_shift(c); now = clock(); d = L.work_date(now, sh["timezone"])
            row = c.execute("insert into office_dashboard.attendance_records(user_id,work_date,check_in) values(%s,%s,%s) on conflict (user_id, work_date) do nothing returning *", (s["id"], d, now)).fetchone()
            if not row: raise HTTPException(409, "You have already checked in today.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="attendance.check_in", entity_type="attendance", entity_id=row["id"], after={"work_date": d, "check_in": now}, ip=ip(request))
            return derive([row], sh)[0]

    @r.post("/check-out")
    def check_out(request: Request, s=Depends(need("attendance.write", True))):
        with db() as c:
            sh = need_shift(c); now = clock(); d = L.work_date(now, sh["timezone"])
            row = c.execute("select * from office_dashboard.attendance_records where user_id=%s and work_date=%s for update", (s["id"], d)).fetchone()
            if not row: raise HTTPException(409, "You have not checked in today.")
            if row["check_out"]: raise HTTPException(409, "You have already checked out today.")
            if now <= row["check_in"]: raise HTTPException(409, "Check-out must be after check-in.")
            new = c.execute("update office_dashboard.attendance_records set check_out=%s, updated_at=now() where id=%s returning *", (now, row["id"])).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="attendance.check_out", entity_type="attendance", entity_id=row["id"], before={"check_out": None}, after={"check_out": now}, ip=ip(request))
            return derive([new], sh)[0]

    @r.get("/records")
    def records(month: str, user_id: Optional[str] = None, s=Depends(need("attendance.read"))):
        y, m, a, b = month_range(month); who = target(s, user_id)
        with db() as c:
            sh = shift(c)
            rows = c.execute("select * from office_dashboard.attendance_records where user_id=%s and work_date>=%s and work_date<%s order by work_date desc", (who, a, b)).fetchall()
            return {"items": derive(rows, sh), "user_id": who, "name": names(c, [who]).get(who), "configured": bool(sh)}

    @r.get("/summary")
    def summary(month: str, user_id: Optional[str] = None, s=Depends(need("attendance.read"))):
        y, m, a, b = month_range(month); who = target(s, user_id)
        with db() as c:
            sh = need_shift(c)
            rows = c.execute("select work_date, check_in, check_out from office_dashboard.attendance_records where user_id=%s and work_date>=%s and work_date<%s", (who, a, b)).fetchall()
            hol, lv = leave_ctx(c, who, y, m, a, b, sh["working_days"])
            out = L.monthly_summary(rows, y, m, sh, L.work_date(clock(), sh["timezone"]), hol, lv)
            return {"month": month, "user_id": who, "name": names(c, [who]).get(who), **out}

    @r.get("/team")
    def team(day: Optional[date] = Query(None, alias="date"), s=Depends(need("attendance.read"))):
        if s["own_only"]: raise HTTPException(403, "You do not have access to team attendance.")
        with db() as c:
            sh = need_shift(c); d = day or L.work_date(clock(), sh["timezone"])
            rows = c.execute("select * from office_dashboard.attendance_records where work_date=%s order by check_in", (d,)).fetchall()
            nm = names(c, [x["user_id"] for x in rows])
            for x in derive(rows, sh): x["name"] = nm.get(x["user_id"])
            try:
                with c.transaction(): lv = c.execute("select user_id, half_day from office_dashboard.leave_requests where status='approved' and start_date<=%s and end_date>=%s", (d, d)).fetchall()
            except psycopg.errors.UndefinedTable: lv = []
            ln = names(c, [x["user_id"] for x in lv])
            return {"date": d, "items": rows, "on_leave": [{"name": ln.get(x["user_id"]), "half_day": x["half_day"]} for x in lv]}

    def decorate(rows, c, s):
        nm = names(c, [x for q in rows for x in (q["user_id"], q["decided_by"])]); can = permissions.can(s["role"], "attendance.approve")
        for q in rows:
            q["name"] = nm.get(q["user_id"]); q["decided_by_name"] = nm.get(q["decided_by"]); q["can_decide"] = can and q["status"] == "pending" and q["user_id"] != s["id"]
        return rows

    @r.post("/corrections", status_code=201)
    def request_correction(b: CorrectionIn, request: Request, s=Depends(need("attendance.write", True))):
        with db() as c:
            sh = need_shift(c); tz = sh["timezone"]
            ci = L.combine(b.work_date, b.check_in_time, tz) if b.check_in_time else None
            co = L.combine(b.work_date, b.check_out_time, tz) if b.check_out_time else None
            try: L.validate_correction(b.work_date, ci, co, b.reason, L.work_date(clock(), tz))
            except L.AttendanceError as e: rule(e)
            try:
                row = c.execute("insert into office_dashboard.attendance_corrections(user_id,work_date,requested_check_in,requested_check_out,reason) values(%s,%s,%s,%s,%s) returning *",
                                (s["id"], b.work_date, ci, co, b.reason.strip())).fetchone()
            except psycopg.errors.UniqueViolation: raise HTTPException(409, "You already have a pending correction request for that date.")
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="attendance.correction_requested", entity_type="attendance_correction", entity_id=row["id"],
                           after={"work_date": b.work_date, "requested_check_in": ci, "requested_check_out": co, "reason": b.reason.strip()}, ip=ip(request))
            return decorate([row], c, s)[0]

    @r.get("/corrections")
    def list_corrections(status: str = "", s=Depends(need("attendance.read"))):
        if status and status not in ("pending", "approved", "rejected"): raise HTTPException(422, "Unknown status.")
        w, a = "true", []
        if s["own_only"]: w += " and user_id=%s"; a.append(s["id"])
        if status: w += " and status=%s"; a.append(status)
        with db() as c:
            rows = c.execute(f"select * from office_dashboard.attendance_corrections where {w} order by (status<>'pending'), created_at desc limit 200", a).fetchall()
            return {"items": decorate(rows, c, s)}

    @r.post("/corrections/{cid}/decision")
    def decide(cid: str, b: Decision, request: Request, s=Depends(need("attendance.approve", True))):
        if b.decision == "reject" and not (b.note or "").strip(): raise HTTPException(422, "Please give a reason for rejecting.")
        with db() as c:
            try: q = c.execute("select * from office_dashboard.attendance_corrections where id=%s for update", (cid,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: q = None
            if not q: raise HTTPException(404, "Correction request not found.")
            try: L.can_decide_correction(s["id"], q["user_id"], q["status"])
            except L.AttendanceError as e: rule(e)
            after_rec = None
            if b.decision == "approve":
                sh = need_shift(c)
                cur = c.execute("select * from office_dashboard.attendance_records where user_id=%s and work_date=%s for update", (q["user_id"], q["work_date"])).fetchone()
                ci = q["requested_check_in"] or (cur["check_in"] if cur else None); co = q["requested_check_out"] or (cur["check_out"] if cur else None)
                if ci is None: raise HTTPException(422, "This request has no check-in time and no record exists to attach it to.")
                if co is not None and co <= ci: raise HTTPException(422, "The corrected times would put check-out before check-in.")
                after_rec = c.execute("insert into office_dashboard.attendance_records(user_id,work_date,check_in,check_out,source) values(%s,%s,%s,%s,'correction')"
                                      " on conflict (user_id, work_date) do update set check_in=excluded.check_in, check_out=excluded.check_out, source='correction', updated_at=now() returning *",
                                      (q["user_id"], q["work_date"], ci, co)).fetchone()
            new = c.execute("update office_dashboard.attendance_corrections set status=%s, decided_by=%s, decided_at=now(), decision_note=%s where id=%s returning *",
                            ("approved" if b.decision == "approve" else "rejected", s["id"], (b.note or "").strip() or None, cid)).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action=f"attendance.correction_{new['status']}", entity_type="attendance_correction", entity_id=cid,
                           before={"status": "pending"}, after={"status": new["status"], "note": new["decision_note"], **({"check_in": after_rec["check_in"], "check_out": after_rec["check_out"]} if after_rec else {})}, ip=ip(request))
            return decorate([new], c, s)[0]
    return r
