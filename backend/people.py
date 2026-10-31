"""Employee directory + audit-log viewer. Reads the db/001 tables (employees, departments, technicians) and db/005 audit_log.
Never returns password hashes. Writes are limited to non-login fields; account (de)activation needs employees.admin."""
import re
from typing import Optional
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
import auditdb
from permissions import can

class EmployeeEdit(BaseModel):
    designation: Optional[str] = Field(None, max_length=120); phone: Optional[str] = None
    department_id: Optional[int] = Field(None, ge=1); is_active: Optional[bool] = None
    @field_validator("designation", "phone", mode="before")
    def blank(cls, v): return (v.strip() or None) if isinstance(v, str) else v
    @field_validator("phone")
    def ph(cls, v):
        if v and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", v): raise ValueError("Enter a valid phone number")
        return v

def build_router(dsn, need, ip):
    r = APIRouter(prefix="/api")
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def like(q): return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    def missing(e): raise HTTPException(503, "The employee tables are not set up in this database (run db/001_foundation.sql).")

    BASE = ("select e.id, e.employee_code, e.full_name, e.email, e.phone, e.designation, e.is_active, e.department_id, d.name as department,"
            " m.full_name as manager_name, exists(select 1 from office_dashboard.technicians t where t.employee_id=e.id) as is_technician"
            " from office_dashboard.employees e left join office_dashboard.departments d on d.id=e.department_id"
            " left join office_dashboard.employees m on m.id=e.reporting_manager_id")

    @r.get("/employees")
    def employees(q: str = "", department_id: Optional[int] = None, active: Optional[bool] = None, page_no: int = Query(1, alias="page", ge=1),
                  page_size: int = Query(20, ge=1, le=100), s=Depends(need("employees.read"))):
        w, a = ["true"], []
        if q.strip(): w.append("(e.full_name ilike %s or e.email ilike %s or e.employee_code ilike %s or e.designation ilike %s)"); a += [like(q)] * 4
        if department_id: w.append("e.department_id=%s"); a.append(department_id)
        if active is not None: w.append("e.is_active=%s"); a.append(active)
        where = " and ".join(w)
        try:
            with db() as c:
                total = c.execute(f"select count(*) as n from office_dashboard.employees e where {where}", a).fetchone()["n"]
                rows = c.execute(f"{BASE} where {where} order by e.employee_code limit %s offset %s", a + [page_size, (page_no - 1) * page_size]).fetchall()
                deps = c.execute("select id, name from office_dashboard.departments order by name").fetchall()
        except psycopg.errors.UndefinedTable as e: missing(e)
        return {"items": rows, "total": total, "page": page_no, "page_size": page_size, "departments": deps,
                "can_write": can(s["role"], "employees.write"), "can_admin": can(s["role"], "employees.admin")}

    @r.patch("/employees/{eid}")
    def edit_employee(eid: str, b: EmployeeEdit, request: Request, s=Depends(need("employees.write", True))):
        d = b.model_dump(exclude_unset=True)
        if not d: raise HTTPException(422, "Nothing to update.")
        if "is_active" in d and not can(s["role"], "employees.admin"): raise HTTPException(403, "Only an administrator can activate or deactivate an account.")
        if d.get("is_active") is None and "is_active" in d: raise HTTPException(422, "is_active must be true or false.")
        try:
            with db() as c:
                try: cur = c.execute(f"{BASE} where e.id=%s for update of e", (eid,)).fetchone()
                except psycopg.errors.InvalidTextRepresentation: cur = None
                if not cur: raise HTTPException(404, "Employee not found.")
                if d.get("is_active") is False and c.execute("select 1 from office_dashboard.users u where u.employee_id=%s and u.id::text=%s", (eid, s["id"])).fetchone(): raise HTTPException(409, "You cannot deactivate your own account.")
                if d.get("department_id") and not c.execute("select 1 from office_dashboard.departments where id=%s", (d["department_id"],)).fetchone(): raise HTTPException(422, "Unknown department.")
                c.execute("update office_dashboard.employees set " + ",".join(f"{k}=%s" for k in d) + " where id=%s", [*d.values(), eid])
                row = c.execute(f"{BASE} where e.id=%s", (eid,)).fetchone()
                keep = ("designation", "phone", "department_id", "is_active")
                auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="employee.updated", entity_type="employee", entity_id=eid,
                               before={k: cur[k] for k in keep}, after={k: row[k] for k in keep}, ip=ip(request))
                return row
        except psycopg.errors.UndefinedTable as e: missing(e)

    @r.get("/audit")
    def audit_log(entity_type: str = "", action: str = "", actor: str = "", outcome: str = "", page_no: int = Query(1, alias="page", ge=1),
                  page_size: int = Query(50, ge=1, le=200), s=Depends(need("audit.read"))):
        w, a = ["true"], []
        if entity_type: w.append("entity_type=%s"); a.append(entity_type)
        if action: w.append("action ilike %s"); a.append(like(action))
        if actor: w.append("coalesce(actor_id,user_id)=%s"); a.append(actor)
        if outcome:
            if outcome not in ("success", "denied", "failed"): raise HTTPException(422, "Unknown outcome.")
            w.append("outcome=%s"); a.append(outcome)
        where = " and ".join(w)
        try:
            with db() as c:
                total = c.execute(f"select count(*) as n from office_dashboard.audit_log where {where}", a).fetchone()["n"]
                rows = c.execute(f"select id, occurred_at, coalesce(actor_id,user_id) as actor_id, actor_role, action, entity_type, entity_id, before_data, after_data, outcome, source, host(ip) as ip"
                                 f" from office_dashboard.audit_log where {where} order by occurred_at desc, id desc limit %s offset %s", a + [page_size, (page_no - 1) * page_size]).fetchall()
        except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn): raise HTTPException(503, "The audit table is not set up in this database (run db/005_audit_log.sql).")
        return {"items": rows, "total": total, "page": page_no, "page_size": page_size}
    return r
