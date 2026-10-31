"""Tasks & Approvals API. Permissions come from permissions.py (module "tasks"), enforced here on the server.
Row scoping: roles flagged own-only (employee, technician) only ever see/touch tasks assigned to or created by themselves.
Every write is audited in the database inside the same transaction (db/005)."""
from datetime import date
from typing import Literal, Optional
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
import auditdb, permissions, tasklogic as L

class TaskIn(BaseModel):
    title: Optional[str] = Field(None, max_length=160); description: Optional[str] = Field(None, max_length=4000)
    assignee_id: Optional[str] = Field(None, max_length=64); priority: Optional[Literal["low", "normal", "high"]] = None
    due_date: Optional[date] = None; requires_approval: Optional[bool] = None
    status: Optional[Literal["open", "in_progress", "pending_approval", "done", "cancelled"]] = None
    @field_validator("title", "description", mode="before")
    def strip(cls, v): return v.strip() if isinstance(v, str) else v
class Decision(BaseModel):
    decision: Literal["approve", "reject"]; note: Optional[str] = Field(None, max_length=1000)

def build_router(dsn, session, csrf, audit, need, repo, cfg, ip):
    r = APIRouter(prefix="/api/tasks")
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def like(q): return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    def users_table(): return sql.SQL(".").join(map(sql.Identifier, cfg["table"].split(".")))
    def names(c, ids):
        ids = sorted({i for i in ids if i})
        if not ids: return {}
        q = sql.SQL("select {i}::text as id, {n} as name from {t} where {i}::text = any(%s)").format(i=sql.Identifier(cfg["id"]), n=sql.Identifier(cfg["name"]), t=users_table())
        return {x["id"]: x["name"] for x in c.execute(q, (ids,)).fetchall()}
    def snap(row): return {k: row[k] for k in ("title", "assignee_id", "status", "priority", "due_date", "requires_approval", "approver_id", "decision_note", "is_archived")}
    def fetch(c, tid, s, for_update=False):
        try: row = c.execute("select * from office_dashboard.tasks where id=%s and not is_archived" + (" for update" if for_update else ""), (tid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row or not L.can_see(s["own_only"], s["id"], row["assignee_id"], row["created_by"]): raise HTTPException(404, "Task not found.")   # same answer for "hidden" and "missing"
        return row
    def rule(e: L.RuleError): raise HTTPException(e.status, e.message)
    def valid_assignee(uid):
        u = repo.find_by_id(uid)
        if not (u and u.active): raise HTTPException(422, "That person does not exist or is not active.")
    def decorate(rows, c, s):
        nm = names(c, [x for t in rows for x in (t["assignee_id"], t["created_by"])]); can_decide_role = permissions.can(s["role"], "tasks.approve")
        for t in rows:
            t["assignee_name"] = nm.get(t["assignee_id"]); t["created_by_name"] = nm.get(t["created_by"])
            t["can_edit"] = L.can_edit_content(s["own_only"], s["id"], t["assignee_id"], t["created_by"]) and t["status"] in ("open", "in_progress")
            t["can_change_status"] = L.can_change_status(s["own_only"], s["id"], t["assignee_id"]) and t["status"] != "pending_approval"
            t["can_decide"] = can_decide_role and t["status"] == "pending_approval" and t["assignee_id"] != s["id"]
        return rows

    @r.get("")
    def list_tasks(q: str = "", status: str = "", mine: bool = False, page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), s=Depends(need("tasks.read"))):
        if status and status not in L.STATUSES: raise HTTPException(422, "Unknown status.")
        w, a = "not t.is_archived", []
        if s["own_only"]: w += " and (t.assignee_id=%s or t.created_by=%s)"; a += [s["id"]] * 2
        if mine: w += " and t.assignee_id=%s"; a.append(s["id"])
        if status: w += " and t.status=%s"; a.append(status)
        if q.strip(): w += " and (t.title ilike %s or t.description ilike %s)"; a += [like(q)] * 2
        with db() as c:
            total = c.execute(f"select count(*) as n from office_dashboard.tasks t where {w}", a).fetchone()["n"]
            rows = c.execute(f"select t.* from office_dashboard.tasks t where {w} order by (t.status in ('done','cancelled')), t.due_date nulls last, t.created_at desc limit %s offset %s", a + [page_size, (page_no - 1) * page_size]).fetchall()
            rows = decorate(rows, c, s)
        return {"items": rows, "total": total, "page": page_no, "page_size": page_size, "statuses": L.STATUSES, "status_labels": L.STATUS_LABELS,
                "can_write": permissions.can(s["role"], "tasks.write"), "can_archive": permissions.can(s["role"], "tasks.archive"), "can_assign": L.can_reassign(s["own_only"]), "me": s["id"]}

    @r.get("/assignees")
    def assignees(q: str = "", s=Depends(need("tasks.write"))):
        """People a task can be assigned to. Own-only roles can only pick themselves."""
        with db() as c:
            if s["own_only"]: return {"items": [{"id": s["id"], "name": s["name"]}]}
            cond, args = [], []
            if cfg.get("active"): cond.append(sql.SQL("lower({}::text) = any(%s)").format(sql.Identifier(cfg["active"]))); args.append(sorted(cfg["active_values"]))
            if q.strip(): cond.append(sql.SQL("{} ilike %s").format(sql.Identifier(cfg["name"]))); args.append(like(q))
            qry = sql.SQL("select {i}::text as id, {n} as name from {t}").format(i=sql.Identifier(cfg["id"]), n=sql.Identifier(cfg["name"]), t=users_table())
            if cond: qry += sql.SQL(" where ") + sql.SQL(" and ").join(cond)
            qry += sql.SQL(" order by {} limit 100").format(sql.Identifier(cfg["name"]))
            return {"items": c.execute(qry, args).fetchall()}

    @r.post("", status_code=201)
    def create(b: TaskIn, request: Request, s=Depends(need("tasks.write", True))):
        if not b.title: raise HTTPException(422, "Title is required.")
        if b.status not in (None, "open"): raise HTTPException(422, "A new task starts as open.")
        who = b.assignee_id or s["id"]
        if s["own_only"] and who != s["id"]: raise HTTPException(403, "You can only create tasks for yourself.")
        if who != s["id"]: valid_assignee(who)
        with db() as c:
            row = c.execute("insert into office_dashboard.tasks(title,description,assignee_id,created_by,priority,due_date,requires_approval) values(%s,%s,%s,%s,%s,%s,%s) returning *",
                            (b.title, b.description or None, who, s["id"], b.priority or "normal", b.due_date, bool(b.requires_approval))).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="task.created", entity_type="task", entity_id=row["id"], after=snap(row), ip=ip(request))
            return decorate([row], c, s)[0]

    @r.get("/{tid}")
    def get_task(tid: str, s=Depends(need("tasks.read"))):
        with db() as c: return decorate([fetch(c, tid, s)], c, s)[0]

    @r.patch("/{tid}")
    def edit(tid: str, b: TaskIn, request: Request, s=Depends(need("tasks.write", True))):
        d = b.model_dump(exclude_unset=True)
        if not d: raise HTTPException(422, "Nothing to update.")
        for k in ("title", "assignee_id", "priority", "requires_approval", "status"):
            if k in d and d[k] is None or (k == "title" and k in d and not d[k]): raise HTTPException(422, f"{k.replace('_', ' ').capitalize()} cannot be empty.")
        with db() as c:
            cur = fetch(c, tid, s, for_update=True); mgr = not s["own_only"]; content = {k: v for k, v in d.items() if k != "status"}
            if cur["status"] == "pending_approval": raise HTTPException(409, "This task is waiting for approval. Use approve or reject.")
            if content:
                if not L.can_edit_content(s["own_only"], s["id"], cur["assignee_id"], cur["created_by"]): raise HTTPException(403, "You can only change the details of tasks you made for yourself.")
                if cur["status"] in ("done", "cancelled"): raise HTTPException(409, "Reopen the task before editing it.")
            if "assignee_id" in content and content["assignee_id"] != cur["assignee_id"]:
                if not L.can_reassign(s["own_only"]): raise HTTPException(403, "You cannot reassign tasks.")
                valid_assignee(content["assignee_id"])
            sets = dict(content)
            if "status" in d:
                if not L.can_change_status(s["own_only"], s["id"], cur["assignee_id"]): raise HTTPException(403, "Only the assignee or a manager can change the status.")
                try: ns = L.new_status(cur["status"], d["status"], content.get("requires_approval", cur["requires_approval"]), mgr)
                except L.RuleError as e: rule(e)
                if ns != cur["status"]:
                    sets["status"] = ns; sets["completed_at"] = None
                    if ns == "done": sets["completed_at"] = sql.SQL("now()")
                    if cur["status"] == "done": sets.update(approver_id=None, decision_note=None, decided_at=None)
            if "requires_approval" in sets and not sets["requires_approval"] and cur["approver_id"]: sets.update(approver_id=None, decision_note=None, decided_at=None)
            assigns, args = [], []
            for k, v in sets.items():
                if isinstance(v, sql.SQL): assigns.append(f"{k}=now()")
                else: assigns.append(f"{k}=%s"); args.append(v)
            row = c.execute("update office_dashboard.tasks set " + ",".join(assigns) + ",updated_at=now() where id=%s returning *", [*args, tid]).fetchone()
            only_status = set(sets) <= {"status", "completed_at", "approver_id", "decision_note", "decided_at"}
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="task.status_changed" if only_status else "task.updated",
                           entity_type="task", entity_id=tid, before=snap(cur), after=snap(row), ip=ip(request))
            return decorate([row], c, s)[0]

    @r.post("/{tid}/decision")
    def decide(tid: str, b: Decision, request: Request, s=Depends(need("tasks.approve", True))):
        with db() as c:
            cur = fetch(c, tid, s, for_update=True)
            try: ns = L.check_decision(s["id"], cur["assignee_id"], cur["status"], b.decision, b.note or "")
            except L.RuleError as e:
                auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action=f"task.{b.decision}", entity_type="task", entity_id=tid, outcome="denied", ip=ip(request)); c.commit(); rule(e)
            row = c.execute("update office_dashboard.tasks set status=%s,approver_id=%s,decision_note=%s,decided_at=now(),completed_at=case when %s='done' then now() else null end,updated_at=now() where id=%s returning *",
                            (ns, s["id"], (b.note or "").strip() or None, ns, tid)).fetchone()
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action=f"task.{b.decision}d" if b.decision == "approve" else "task.rejected", entity_type="task", entity_id=tid, before=snap(cur), after=snap(row), ip=ip(request))
            return decorate([row], c, s)[0]

    @r.delete("/{tid}")
    def archive(tid: str, request: Request, s=Depends(need("tasks.archive", True))):
        with db() as c:
            cur = fetch(c, tid, s, for_update=True)
            c.execute("update office_dashboard.tasks set is_archived=true,updated_at=now() where id=%s", (tid,))
            auditdb.record(c, actor_id=s["id"], actor_role=s["role"], action="task.archived", entity_type="task", entity_id=tid, before=snap(cur), after={**snap(cur), "is_archived": True}, ip=ip(request))
        return {"ok": True}
    return r
