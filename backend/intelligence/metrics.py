"""Metric implementations. Each is registered ONCE in the registry; everything else reuses the result.
Definitions mirror the existing modules (cited per metric): DONE statuses = ticketapi/opscommon, overdue ticket = ticketapi,
receivables/payment status = finance.inv_base, budget actuals = finance (invoices issued by issue date, approved expenses by expense date),
IoT offline = iotapi.CONN_SQL, location policy = locationpolicy. SQL is portable (aggregates, joins, CASE) and takes `as_of`/`today` as
parameters instead of now() so results are reproducible and unit-testable."""
from datetime import timedelta
from decimal import Decimal

import financelogic, locationpolicy
from . import analytics as A
from . import results as R
from .periods import month_start
from .registry import metric, blank, compute, Ctx, MetricDef

S = "office_dashboard."
DONE = locationpolicy.DONE_STATUSES            # same tuple as opscommon.DONE (asserted in tests)
SEV_RANK = {"CRITICAL": 5, "HIGH": 4, "URGENT": 4, "MEDIUM": 3, "WARNING": 3, "LOW": 2, "INFO": 1}


def T(name): return S + name
def ph(vals): return "(" + ",".join(["%s"] * len(vals)) + ")"
def num(x, nd=2):
    return 0.0 if x is None else float(round(Decimal(str(x)), nd))
def n_(x): return int(x or 0)
def fresh(ctx, *latest):
    ts = [A.to_dt(x) for x in latest if x]; m = max(ts) if ts else None
    return {"latest_source_update_at": R.iso(m), "age_hours": A.age_hours(m, ctx.as_of) if m else None}
def ev(source, method, rows=None, ids=None, note=""): return R.Evidence(T(source) if "." not in source else source, method, rows, [str(i) for i in (ids or [])], note)
def ok(ctx, d, value, **kw):
    return R.MetricResult(d.id, d.label, kw.pop("state", R.AVAILABLE), value, kw.pop("unit", d.unit), as_of=ctx.as_of.isoformat(), reliability=d.reliability,
                          period=ctx.period.to_dict() if d.kind == "flow" else None, link=kw.pop("link", {"module": d.module}), **kw)
def one(ctx, sql, params=()):
    r = ctx.reader.rows(sql, params); return r[0] if r else {}
def has_rows(ctx, table, where="1=1"): return bool(ctx.reader.rows(f"select 1 as x from {T(table)} where {where} limit 1"))


def comparison(ctx, cur, prev, earliest):
    """Previous-period block with its OWN state. History is judged by the oldest record in the source: if the system holds nothing
    from before the previous window started, that window is incomplete and no comparison is offered."""
    if ctx.prev is None: return None
    e = A.to_date(earliest); base = {"previous_period": ctx.prev.to_dict()}
    if e is None or e > ctx.prev.start:
        return {"state": R.NOT_ENOUGH_HISTORY, "message": R.NOT_ENOUGH_HISTORY_LABEL, "earliest_record": R.iso(e),
                "reason": "The oldest record in this source is newer than the start of the comparison period.", **base}
    return {"state": R.AVAILABLE, "previous_value": prev, "delta": round(cur - prev, 2), "pct_change": A.pct_change(cur, prev), **base}


def count_in(ctx, table, col, p, where="1=1", params=(), date_col=False):
    lo, hi = (p.start, p.end) if date_col else (p.start_dt, p.end_dt_exclusive)
    op = "<=" if date_col else "<"
    return n_(one(ctx, f"select count(*) as n from {T(table)} where {where} and {col} >= %s and {col} {op} %s", (*params, lo, hi)).get("n"))


def earliest(ctx, table, col, where="1=1"):
    return one(ctx, f"select min({col}) as e from {T(table)} where {where}").get("e")


# ============================== TASKS (tasks.py / tasklogic.py) ==============================
@metric("tasks.by_status", "Tasks by status", "tasks", ["tasks.read"], ["tasks"], "Non-archived tasks grouped by their recorded status.")
def tasks_by_status(ctx, d):
    rows = ctx.reader.rows(f"select status, count(*) as n, max(updated_at) as last_update from {T('tasks')} where not is_archived group by status")
    total = sum(n_(r["n"]) for r in rows)
    if total == 0: return blank(d, ctx, R.NO_DATA, "No tasks have been recorded.")
    by = {r["status"]: n_(r["n"]) for r in rows}
    return ok(ctx, d, total, breakdown=[{"status": k, "count": by.get(k, 0)} for k in ("open", "in_progress", "pending_approval", "done", "cancelled")],
              detail={"active": by.get("open", 0) + by.get("in_progress", 0), **{k: by.get(k, 0) for k in ("open", "in_progress", "pending_approval", "done", "cancelled")}},
              freshness=fresh(ctx, *[r["last_update"] for r in rows]), evidence=[ev("tasks", "count of non-archived tasks grouped by status", total)])


@metric("tasks.overdue", "Overdue tasks", "tasks", ["tasks.read"], ["tasks"],
        "Non-archived tasks that are open or in progress and whose due_date is before today. Tasks waiting for approval are counted under approvals, not here.", reliability="user_entered")
def tasks_overdue(ctx, d):
    act = "not is_archived and status in ('open','in_progress')"
    rows = ctx.reader.rows(f"select priority, count(*) as n, min(due_date) as oldest, max(updated_at) as last_update from {T('tasks')} where {act} and due_date < %s group by priority", (ctx.today,))
    if not has_rows(ctx, "tasks"): return blank(d, ctx, R.NO_DATA, "No tasks have been recorded.")
    total = sum(n_(r["n"]) for r in rows); oldest = min((A.to_date(r["oldest"]) for r in rows), default=None)
    ids = [r["id"] for r in ctx.reader.rows(f"select id from {T('tasks')} where {act} and due_date < %s order by due_date, id limit 10", (ctx.today,))]
    nodue = n_(one(ctx, f"select count(*) as n from {T('tasks')} where {act} and due_date is null").get("n"))
    lim = [f"{nodue} active task(s) have no due date, so they cannot be judged overdue."] if nodue else []
    return ok(ctx, d, total, breakdown=[{"priority": r["priority"], "count": n_(r["n"])} for r in sorted(rows, key=lambda r: ("high", "normal", "low").index(r["priority"]))],
              detail={"oldest_due_date": R.iso(oldest), "max_days_overdue": (ctx.today - oldest).days if oldest else None, "active_without_due_date": nodue,
                      "highest_priority": next((p for p in ("high", "normal", "low") if any(r["priority"] == p for r in rows)), None)},
              freshness=fresh(ctx, *[r["last_update"] for r in rows]), limitations=lim, threshold={"configured": True, "label": "Due date entered on each task"},
              evidence=[ev("tasks", "open/in-progress, non-archived tasks with due_date < today", total, ids)], link={"module": "tasks", "filter": {"overdue": True}})


@metric("tasks.pending_approval", "Tasks awaiting approval", "tasks", ["tasks.read"], ["tasks"], "Non-archived tasks in status pending_approval.")
def tasks_pending(ctx, d):
    if not has_rows(ctx, "tasks"): return blank(d, ctx, R.NO_DATA, "No tasks have been recorded.")
    r = one(ctx, f"select count(*) as n, min(updated_at) as oldest, max(updated_at) as newest from {T('tasks')} where not is_archived and status='pending_approval'")
    ids = [x["id"] for x in ctx.reader.rows(f"select id from {T('tasks')} where not is_archived and status='pending_approval' order by updated_at, id limit 10")]
    return ok(ctx, d, n_(r.get("n")), detail={"oldest_waiting_since": R.iso(A.to_dt(r.get("oldest"))), "oldest_waiting_hours": A.age_hours(r.get("oldest"), ctx.as_of) if r.get("oldest") else None},
              freshness=fresh(ctx, r.get("newest")), limitations=["Waiting time uses the task's last-updated time, which may be later than the moment it was submitted."],
              threshold={"configured": False, "label": R.NO_THRESHOLD_LABEL}, evidence=[ev("tasks", "tasks with status pending_approval", n_(r.get("n")), ids)], link={"module": "tasks", "filter": {"status": "pending_approval"}})


@metric("tasks.flow", "Tasks created and completed", "tasks", ["tasks.read"], ["tasks"], "Tasks created and tasks completed (completed_at) in the period, with a previous-period comparison.", kind="flow")
def tasks_flow(ctx, d):
    if not has_rows(ctx, "tasks"): return blank(d, ctx, R.NO_DATA, "No tasks have been recorded.")
    w = "not is_archived"; cur_c, cur_d = count_in(ctx, "tasks", "created_at", ctx.period, w), count_in(ctx, "tasks", "completed_at", ctx.period, w + " and status='done'")
    e = earliest(ctx, "tasks", "created_at", w); cmp_c = cmp_d = None
    if ctx.prev: cmp_c = comparison(ctx, cur_c, count_in(ctx, "tasks", "created_at", ctx.prev, w), e); cmp_d = comparison(ctx, cur_d, count_in(ctx, "tasks", "completed_at", ctx.prev, w + " and status='done'"), e)
    return ok(ctx, d, cur_d, detail={"created": cur_c, "completed": cur_d, "created_comparison": cmp_c}, comparison=cmp_d,
              evidence=[ev("tasks", "created_at / completed_at inside the period (UTC day boundaries)", cur_c + cur_d)], limitations=["Value is tasks completed in the period; 'created' is in detail."])


# ============================== SERVICE TICKETS (ticketapi.py) ==============================
OPEN_T = f"not t.archived and t.status not in {ph(DONE)}"


@metric("tickets.open_backlog", "Open service tickets", "tickets", ["tickets.read"], ["service_tickets"], "Non-archived tickets whose status is not COMPLETED, CUSTOMER_CONFIRMATION or CLOSED.")
def tickets_open(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    rows = ctx.reader.rows(f"select t.status, t.priority, count(*) as n, max(t.updated_at) as last_update from {T('service_tickets')} t where {OPEN_T} group by t.status, t.priority", DONE)
    total = sum(n_(r["n"]) for r in rows); bs, bp = {}, {}
    for r in rows: bs[r["status"]] = bs.get(r["status"], 0) + n_(r["n"]); bp[r["priority"]] = bp.get(r["priority"], 0) + n_(r["n"])
    return ok(ctx, d, total, breakdown=[{"status": k, "count": v} for k, v in sorted(bs.items(), key=lambda x: (-x[1], x[0]))],
              detail={"by_priority": {p: bp.get(p, 0) for p in ("URGENT", "HIGH", "MEDIUM", "LOW")}}, freshness=fresh(ctx, *[r["last_update"] for r in rows]),
              evidence=[ev("service_tickets", "non-archived tickets not in a finished status", total)], link={"module": "tickets", "filter": {"group": "open"}})


@metric("tickets.overdue", "Overdue service tickets", "tickets", ["tickets.read"], ["service_tickets"],
        "Open tickets whose due_date is before today (same rule as the Service Tickets screen).", reliability="user_entered")
def tickets_overdue(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    rows = ctx.reader.rows(f"select t.priority, count(*) as n, min(t.due_date) as oldest, max(t.updated_at) as last_update from {T('service_tickets')} t where {OPEN_T} and t.due_date < %s group by t.priority", (*DONE, ctx.today))
    ids = [r["id"] for r in ctx.reader.rows(f"select t.id from {T('service_tickets')} t where {OPEN_T} and t.due_date < %s order by t.due_date, t.id limit 10", (*DONE, ctx.today))]
    nodue = n_(one(ctx, f"select count(*) as n from {T('service_tickets')} t where {OPEN_T} and t.due_date is null", DONE).get("n"))
    total = sum(n_(r["n"]) for r in rows); oldest = min((A.to_date(r["oldest"]) for r in rows), default=None)
    top = max((r["priority"] for r in rows), key=lambda p: SEV_RANK.get(p, 0), default=None)
    return ok(ctx, d, total, breakdown=[{"priority": r["priority"], "count": n_(r["n"])} for r in sorted(rows, key=lambda r: -SEV_RANK.get(r["priority"], 0))],
              detail={"oldest_due_date": R.iso(oldest), "max_days_overdue": (ctx.today - oldest).days if oldest else None, "open_without_due_date": nodue, "highest_priority": top},
              freshness=fresh(ctx, *[r["last_update"] for r in rows]), threshold={"configured": True, "label": "Due date entered on each ticket"},
              limitations=[f"{nodue} open ticket(s) have no due date and cannot be judged overdue."] if nodue else [],
              evidence=[ev("service_tickets", "open, non-archived tickets with due_date < today", total, ids)], link={"module": "tickets", "filter": {"overdue": True}})


@metric("tickets.ageing", "Open ticket ageing", "tickets", ["tickets.read"], ["service_tickets"], "Open tickets bucketed by days since created_at. Descriptive buckets only: no SLA is assumed.")
def tickets_ageing(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    edges = [ctx.as_of - timedelta(days=e) for e in A.AGEING_EDGES_DAYS]
    cols = ", ".join(f"coalesce(sum(case when t.created_at > %s then 1 else 0 end),0) as c{i}" for i in range(len(edges)))
    r = one(ctx, f"select count(*) as total, min(t.created_at) as oldest, {cols} from {T('service_tickets')} t where {OPEN_T}", (*edges, *DONE))
    total = n_(r.get("total")); counts = A.bucket_ageing([n_(r[f"c{i}"]) for i in range(len(edges))], total)
    return ok(ctx, d, total, breakdown=[{"bucket": l, "count": c, "share_pct": A.share_pct(c, total)} for l, c in zip(A.AGEING_LABELS, counts)],
              detail={"oldest_open_age_days": round(A.age_hours(r["oldest"], ctx.as_of) / 24, 1) if r.get("oldest") else None},
              threshold={"configured": False, "label": R.NO_THRESHOLD_LABEL}, evidence=[ev("service_tickets", "open tickets bucketed by now - created_at", total)],
              limitations=["Ageing is time since creation; it is not measured against a service-level target because none is configured."])


@metric("tickets.unassigned", "Open tickets with no technician", "tickets", ["tickets.read"], ["service_tickets"], "Open tickets whose assigned_to is empty.")
def tickets_unassigned(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    r = one(ctx, f"select count(*) as n, max(t.updated_at) as lu from {T('service_tickets')} t where {OPEN_T} and t.assigned_to is null", DONE)
    ids = [x["id"] for x in ctx.reader.rows(f"select t.id from {T('service_tickets')} t where {OPEN_T} and t.assigned_to is null order by t.created_at, t.id limit 10", DONE)]
    return ok(ctx, d, n_(r.get("n")), freshness=fresh(ctx, r.get("lu")), evidence=[ev("service_tickets", "open tickets with assigned_to is null", n_(r.get("n")), ids)],
              link={"module": "tickets", "filter": {"assigned": "unassigned"}})


@metric("tickets.by_service_center", "Open tickets by service center", "tickets", ["tickets.read", "garages.read"], ["service_tickets", "service_centers"],
        "Open tickets grouped by the service_center_id foreign key. Tickets with no service center are reported as unlinked, never merged by name.")
def tickets_by_center(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    rows = ctx.reader.rows(f"select t.service_center_id as cid, max(sc.name) as name, count(*) as open_n, sum(case when t.due_date < %s then 1 else 0 end) as overdue_n from {T('service_tickets')} t "
                           f"left join {T('service_centers')} sc on sc.id = t.service_center_id where {OPEN_T} group by t.service_center_id order by open_n desc limit 50", (ctx.today, *DONE))
    total = sum(n_(r["open_n"]) for r in rows); linked = [r for r in rows if r["cid"] is not None]; unl = next((r for r in rows if r["cid"] is None), None)
    bd = [{"service_center_id": str(r["cid"]), "service_center": r["name"], "open": n_(r["open_n"]), "overdue": n_(r["overdue_n"]), "share_pct": A.share_pct(n_(r["open_n"]), total)} for r in linked]
    return ok(ctx, d, total, breakdown=bd, detail={"unlinked_open": n_(unl["open_n"]) if unl else 0, "unlinked_overdue": n_(unl["overdue_n"]) if unl else 0, "centers_with_backlog": len(linked)},
              evidence=[ev("service_tickets", "open tickets joined to service_centers on service_center_id", total)],
              limitations=["Tickets without a service center are listed as unlinked." if unl else "All open tickets are linked to a service center."])


@metric("tickets.technician_workload", "Open tickets per technician", "tickets", ["tickets.read", "technicians.read"], ["service_tickets"],
        "Open tickets grouped by assigned_to. Reports the distribution as facts; no 'too much work' limit is configured.")
def tickets_workload(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    rows = ctx.reader.rows(f"select t.assigned_to as uid, max(t.assigned_name) as name, count(*) as open_n, sum(case when t.due_date < %s then 1 else 0 end) as overdue_n from {T('service_tickets')} t "
                           f"where {OPEN_T} and t.assigned_to is not null group by t.assigned_to order by open_n desc, t.assigned_to limit 100", (ctx.today, *DONE))
    un = n_(one(ctx, f"select count(*) as n from {T('service_tickets')} t where {OPEN_T} and t.assigned_to is null", DONE).get("n"))
    dist = A.workload_distribution({str(r["uid"]): n_(r["open_n"]) for r in rows})
    if dist.get("max_owner"): dist["max_owner_name"] = next((r["name"] for r in rows if str(r["uid"]) == dist["max_owner"]), None)
    total = dist.get("total", 0)
    return ok(ctx, d, total, breakdown=[{"technician_id": str(r["uid"]), "technician_name": r["name"], "open": n_(r["open_n"]), "overdue": n_(r["overdue_n"]), "share_pct": A.share_pct(n_(r["open_n"]), total)} for r in rows],
              detail={"distribution": dist, "unassigned_open": un}, threshold={"configured": False, "label": R.NO_THRESHOLD_LABEL},
              evidence=[ev("service_tickets", "open assigned tickets grouped by assigned_to", total)],
              limitations=["Assigned name is the name captured at assignment time.", "Ticket counts are not weighted by job size or priority; workload balance cannot be judged without a configured limit."])


@metric("tickets.flow", "Tickets created and resolved", "tickets", ["tickets.read"], ["service_tickets"],
        "Tickets created and tickets resolved (resolved_at) in the period. Created minus resolved is the net change in open work caused by new activity.", kind="flow")
def tickets_flow(ctx, d):
    if not has_rows(ctx, "service_tickets"): return blank(d, ctx, R.NO_DATA, "No service tickets have been recorded.")
    w = "not archived"; cc, cr = count_in(ctx, "service_tickets", "created_at", ctx.period, w), count_in(ctx, "service_tickets", "resolved_at", ctx.period, w)
    e = earliest(ctx, "service_tickets", "created_at", w); cmp = None
    if ctx.prev:
        pc, pr = count_in(ctx, "service_tickets", "created_at", ctx.prev, w), count_in(ctx, "service_tickets", "resolved_at", ctx.prev, w)
        cmp = comparison(ctx, cc - cr, pc - pr, e)
        if cmp["state"] == R.AVAILABLE: cmp.update(previous_created=pc, previous_resolved=pr)
    return ok(ctx, d, cc - cr, unit="net tickets", detail={"created": cc, "resolved": cr, "net_inflow": cc - cr}, comparison=cmp,
              evidence=[ev("service_tickets", "created_at and resolved_at inside the period (UTC day boundaries)", cc + cr)],
              limitations=["The size of the open backlog at an earlier date is not stored (no snapshots); net inflow is the verifiable measure of change."])


# ============================== LEADS (crm.py) ==============================
OPEN_L = "not is_archived and stage not in ('won','lost')"


@metric("leads.pipeline", "Open leads in pipeline", "leads", ["leads.read"], ["leads"], "Non-archived leads not yet won or lost, by stage. Value is the sum of user-entered lead values.", reliability="user_entered")
def leads_pipeline(ctx, d):
    if not has_rows(ctx, "leads"): return blank(d, ctx, R.NO_DATA, "No leads have been recorded.")
    rows = ctx.reader.rows(f"select stage, count(*) as n, coalesce(sum(value),0) as v, sum(case when value is null then 1 else 0 end) as nv, max(updated_at) as lu from {T('leads')} where not is_archived group by stage")
    op = [r for r in rows if r["stage"] not in ("won", "lost")]; total = sum(n_(r["n"]) for r in op); nv = sum(n_(r["nv"]) for r in op)
    return ok(ctx, d, total, breakdown=[{"stage": r["stage"], "count": n_(r["n"]), "value": num(r["v"])} for r in rows], detail={"open_value": num(sum(Decimal(str(r["v"])) for r in op)), "open_without_value": nv},
              freshness=fresh(ctx, *[r["lu"] for r in rows]), evidence=[ev("leads", "non-archived leads grouped by stage", sum(n_(r["n"]) for r in rows))],
              limitations=["Lead values are entered by users; they are not forecasts." + (f" {nv} open lead(s) have no value." if nv else "")])


@metric("leads.followups_overdue", "Leads with overdue follow-up", "leads", ["leads.read"], ["leads"], "Open leads whose next_follow_up date is before today.", reliability="user_entered")
def leads_followups(ctx, d):
    if not has_rows(ctx, "leads"): return blank(d, ctx, R.NO_DATA, "No leads have been recorded.")
    rows = ctx.reader.rows(f"select stage, count(*) as n, min(next_follow_up) as oldest, max(updated_at) as lu from {T('leads')} where {OPEN_L} and next_follow_up < %s group by stage", (ctx.today,))
    ids = [r["id"] for r in ctx.reader.rows(f"select id from {T('leads')} where {OPEN_L} and next_follow_up < %s order by next_follow_up, id limit 10", (ctx.today,))]
    nofu = n_(one(ctx, f"select count(*) as n from {T('leads')} where {OPEN_L} and next_follow_up is null").get("n")); total = sum(n_(r["n"]) for r in rows); oldest = min((A.to_date(r["oldest"]) for r in rows), default=None)
    return ok(ctx, d, total, breakdown=[{"stage": r["stage"], "count": n_(r["n"])} for r in rows], detail={"oldest_follow_up": R.iso(oldest), "max_days_overdue": (ctx.today - oldest).days if oldest else None, "open_without_follow_up_date": nofu},
              freshness=fresh(ctx, *[r["lu"] for r in rows]), threshold={"configured": True, "label": "Follow-up date entered on each lead"},
              limitations=[f"{nofu} open lead(s) have no follow-up date and cannot be assessed."] if nofu else [], evidence=[ev("leads", "open leads with next_follow_up < today", total, ids)], link={"module": "leads", "filter": {"follow_up": "overdue"}})


@metric("leads.flow", "Leads created and converted", "leads", ["leads.read"], ["leads"], "Leads created in the period and leads converted (converted_at) in the period.", kind="flow")
def leads_flow(ctx, d):
    if not has_rows(ctx, "leads"): return blank(d, ctx, R.NO_DATA, "No leads have been recorded.")
    w = "not is_archived"; cc, cv = count_in(ctx, "leads", "created_at", ctx.period, w), count_in(ctx, "leads", "converted_at", ctx.period, w)
    e = earliest(ctx, "leads", "created_at", w); cmp = comparison(ctx, cc, count_in(ctx, "leads", "created_at", ctx.prev, w), e) if ctx.prev else None
    return ok(ctx, d, cc, detail={"created": cc, "converted": cv}, comparison=cmp, evidence=[ev("leads", "created_at / converted_at inside the period", cc + cv)],
              limitations=["converted_at is not back-filled for leads won before it existed, so 'converted' may be understated."])


# ============================== OTHER APPROVALS ==============================
@metric("expenses.pending_review", "Expenses awaiting review", "expenses", ["expenses.read"], ["expenses"], "Non-archived expenses in status PENDING.")
def expenses_pending(ctx, d):
    if not has_rows(ctx, "expenses"): return blank(d, ctx, R.NO_DATA, "No expenses have been recorded.")
    r = one(ctx, f"select count(*) as n, coalesce(sum(amount),0) as t, min(created_at) as oldest, max(updated_at) as lu from {T('expenses')} where not archived and status='PENDING'")
    return ok(ctx, d, n_(r.get("n")), detail={"amount": num(r.get("t")), "oldest_submitted_at": R.iso(A.to_dt(r.get("oldest")))}, freshness=fresh(ctx, r.get("lu")),
              evidence=[ev("expenses", "expenses with status PENDING", n_(r.get("n")))], link={"module": "expenses", "filter": {"status": "PENDING"}})


@metric("leave.pending", "Leave requests awaiting decision", "leave", ["leave.read"], ["leave_requests"], "Leave requests in status pending.")
def leave_pending(ctx, d):
    if not has_rows(ctx, "leave_requests"): return blank(d, ctx, R.NO_DATA, "No leave requests have been recorded.")
    r = one(ctx, f"select count(*) as n, min(created_at) as oldest from {T('leave_requests')} where status='pending'")
    return ok(ctx, d, n_(r.get("n")), detail={"oldest_submitted_at": R.iso(A.to_dt(r.get("oldest")))}, evidence=[ev("leave_requests", "leave requests with status pending", n_(r.get("n")))], link={"module": "leave", "filter": {"status": "pending"}})


@metric("attendance.pending_corrections", "Attendance corrections awaiting decision", "attendance", ["attendance.read"], ["attendance_corrections"], "Attendance correction requests in status pending.")
def att_corr(ctx, d):
    if not has_rows(ctx, "attendance_corrections"): return blank(d, ctx, R.NO_DATA, "No attendance corrections have been recorded.")
    r = one(ctx, f"select count(*) as n, min(created_at) as oldest from {T('attendance_corrections')} where status='pending'")
    return ok(ctx, d, n_(r.get("n")), detail={"oldest_submitted_at": R.iso(A.to_dt(r.get("oldest")))}, evidence=[ev("attendance_corrections", "corrections with status pending", n_(r.get("n")))], link={"module": "attendance", "filter": {"status": "pending"}})


APPROVAL_PARTS = (("tasks.pending_approval", "Tasks"), ("expenses.pending_review", "Expenses"), ("leave.pending", "Leave"), ("attendance.pending_corrections", "Attendance corrections"))


@metric("approvals.pending", "Pending approvals (all modules)", "approvals", [], [], "Sum of the per-module pending decisions. Each module is a different table, so nothing is double-counted. Service tickets have no approval state in the schema.", kind="composite", reliability="derived", any_of=("tasks.read", "expenses.read", "leave.read", "attendance.read"))
def approvals(ctx, d):
    parts, missing, total = [], [], 0
    for mid, name in APPROVAL_PARTS:
        r = compute(mid, ctx)          # reuse: the same number the module card shows
        if r.usable(): parts.append({"module": name, "metric_id": mid, "count": r.value}); total += r.value
        elif r.state == R.NO_DATA: parts.append({"module": name, "metric_id": mid, "count": 0}); 
        else: missing.append(f"{name}: {r.state}")
    if not parts: return blank(d, ctx, R.NO_PERMISSION if all(compute(m, ctx).state == R.NO_PERMISSION for m, _ in APPROVAL_PARTS) else R.UNAVAILABLE, "No approval source could be read.")
    return ok(ctx, d, total, state=R.PARTIAL if missing else R.AVAILABLE, breakdown=parts, detail={"unavailable_sources": missing},
              limitations=[f"Not included ({'; '.join(missing)})."] if missing else [], evidence=[ev("tasks, expenses, leave_requests, attendance_corrections", "sum of each module's pending-decision metric", total)])


# ============================== FINANCE (finance.py / financelogic.py) ==============================
INV_LIMIT = 4000


@metric("invoices.receivables", "Receivables", "payments", ["invoices.read", "payments.read"], ["invoices", "invoice_payments"],
        "Sent, non-archived invoices: total billed, non-voided payments received, outstanding balance, overdue balance (due_date < today and balance > 0) and ageing. Same rule as finance.inv_base.", unit="amount", reliability="user_entered")
def receivables(ctx, d):
    if not has_rows(ctx, "invoices", "not archived and status='SENT'"): return blank(d, ctx, R.NO_DATA, "No sent invoices have been recorded.")
    rows = ctx.reader.rows(f"select i.id, i.customer_name, i.total_amount, i.due_date, coalesce(p.paid,0) as paid, i.updated_at from {T('invoices')} i left join "
                           f"(select invoice_id, sum(amount) as paid from {T('invoice_payments')} where not voided group by invoice_id) p on p.invoice_id = i.id where not i.archived and i.status='SENT' order by i.due_date, i.id limit {INV_LIMIT + 1}")
    trunc = len(rows) > INV_LIMIT; rows = rows[:INV_LIMIT]; billed = paid = Decimal("0.00"); inv, over, over_n, over_ids, anomalies, by_cust = [], Decimal("0.00"), 0, [], 0, {}
    for r in rows:
        # str() so Decimal (psycopg) and float inputs both work; financelogic itself still rejects floats
        tot, pd = financelogic.money(Decimal(str(r["total_amount"]))), financelogic.money(Decimal(str(r["paid"]))); bal = tot - pd; billed += tot; paid += pd
        if bal < 0: anomalies += 1; bal = Decimal("0.00")
        due = A.to_date(r["due_date"]); inv.append({"outstanding": bal, "due": due})
        if bal > 0:
            by_cust[r["customer_name"]] = by_cust.get(r["customer_name"], Decimal("0.00")) + bal
            if due < ctx.today: over += bal; over_n += 1; over_ids.append(r["id"])
    ag = financelogic.aging(inv, ctx.today); outstanding = ag["total"]
    top = sorted(by_cust.items(), key=lambda kv: (-kv[1], kv[0]))[:5]; lim = []
    if trunc: lim.append(f"Only the first {INV_LIMIT} sent invoices (by due date) were included.")
    if anomalies: lim.append(f"{anomalies} invoice(s) have payments above their total; their balance was treated as zero.")
    lim.append("Amounts are in the currency recorded on the invoices; no currency conversion is applied.")
    return ok(ctx, d, num(outstanding), state=R.PARTIAL if trunc else R.AVAILABLE, unit="amount",
              breakdown=[{"bucket": k, "amount": num(v)} for k, v in ag.items() if k != "total"],
              detail={"billed": num(billed), "received": num(paid), "outstanding": num(outstanding), "overdue_amount": num(over), "overdue_count": over_n, "invoices_counted": len(rows),
                      "top_debtors": [{"customer_name": k, "outstanding": num(v)} for k, v in top]},
              freshness=fresh(ctx, *[r["updated_at"] for r in rows]), limitations=lim, threshold={"configured": True, "label": "Due date on each invoice"},
              evidence=[ev("invoices", "sent invoices minus non-voided invoice_payments; overdue = due_date < today and balance > 0", len(rows), over_ids)], link={"module": "payments", "filter": {"payment_status": "OVERDUE"}})


@metric("expenses.summary", "Approved expenses", "expenses", ["expenses.read"], ["expenses"], "Approved, non-archived expenses by expense_date in the period, by category, with a previous-period comparison.", unit="amount", kind="flow", reliability="user_entered")
def expenses_summary(ctx, d):
    if not has_rows(ctx, "expenses"): return blank(d, ctx, R.NO_DATA, "No expenses have been recorded.")
    q = f"select category, count(*) as n, coalesce(sum(amount),0) as t, max(updated_at) as lu from {T('expenses')} where not archived and status='APPROVED' and expense_date >= %s and expense_date <= %s group by category"
    rows = ctx.reader.rows(q, (ctx.period.start, ctx.period.end)); cur = sum((Decimal(str(r["t"])) for r in rows), Decimal("0"))
    cmp = None
    if ctx.prev:
        prev = sum((Decimal(str(r["t"])) for r in ctx.reader.rows(q, (ctx.prev.start, ctx.prev.end))), Decimal("0"))
        cmp = comparison(ctx, num(cur), num(prev), earliest(ctx, "expenses", "expense_date", "not archived and status='APPROVED'"))
    return ok(ctx, d, num(cur), breakdown=[{"category": r["category"], "count": n_(r["n"]), "amount": num(r["t"])} for r in sorted(rows, key=lambda r: (-Decimal(str(r["t"])), r["category"]))],
              comparison=cmp, freshness=fresh(ctx, *[r["lu"] for r in rows]), evidence=[ev("expenses", "sum of amount where status APPROVED and expense_date in the period", sum(n_(r["n"]) for r in rows))],
              limitations=["Pending and rejected expenses are excluded."])


@metric("budget.variance", "Budget versus actual (month)", "budget", ["budget.read", "invoices.read", "expenses.read"], ["budgets", "invoices", "expenses"],
        "For the month containing the period end: budget lines vs actuals. Actual revenue = sent invoices by issue date; actual expense = approved expenses by expense date (finance.py). Variance = actual - budget.", unit="amount", reliability="user_entered")
def budget_variance(ctx, d):
    m0 = month_start(ctx.period.end); m1 = month_start(m0 + timedelta(days=32)); lines = ctx.reader.rows(f"select kind, category, amount from {T('budgets')} where period_month = %s order by kind, category", (m0,))
    if not lines: return blank(d, ctx, R.NO_DATA, f"No budget has been entered for {m0:%B %Y}.")
    rev = Decimal(str(one(ctx, f"select coalesce(sum(total_amount),0) as t from {T('invoices')} where not archived and status='SENT' and issue_date >= %s and issue_date < %s", (m0, m1)).get("t")))
    exp = {r["category"]: Decimal(str(r["t"])) for r in ctx.reader.rows(f"select category, coalesce(sum(amount),0) as t from {T('expenses')} where not archived and status='APPROVED' and expense_date >= %s and expense_date < %s group by category", (m0, m1))}
    rows, over, budgeted = [], 0, set()
    for l in lines:
        b = Decimal(str(l["amount"])); a = rev if l["kind"] == "REVENUE" else exp.get(l["category"], Decimal("0")); budgeted.add((l["kind"], l["category"])); v = a - b
        if l["kind"] == "EXPENSE" and v > 0: over += 1
        rows.append({"kind": l["kind"], "category": l["category"], "budget": num(b), "actual": num(a), "variance": num(v), "variance_pct": A.pct_change(float(a), float(b)) if b else None})
    unb = sum((v for k, v in exp.items() if ("EXPENSE", k) not in budgeted), Decimal("0"))
    lim = ["Actuals are month-to-date; variance is not final until the month ends."] if m1 - timedelta(days=1) >= ctx.today else []
    return ok(ctx, d, over, unit="expense lines over budget", breakdown=rows, detail={"month": m0.isoformat(), "expense_lines_over_budget": over, "unbudgeted_expense_actual": num(unb)}, limitations=lim,
              threshold={"configured": True, "label": f"Budget lines entered for {m0:%B %Y}"}, evidence=[ev("budgets", "budgets joined (by kind/category/month) to invoice and expense actuals", len(lines))], link={"module": "budget"})


# ============================== PEOPLE (aggregates only) ==============================
@metric("attendance.today", "Checked in today", "attendance", ["attendance.read"], ["attendance_config", "attendance_records"],
        "Attendance records for today's work date in the configured timezone. Aggregate counts only.")
def attendance_today(ctx, d):
    cfg = ctx.reader.rows(f"select timezone from {T('attendance_config')} limit 1")
    if not cfg: return blank(d, ctx, R.NOT_CONFIGURED, "The attendance policy (shift, timezone, working days) has not been set up.")
    lim = []
    try:
        from zoneinfo import ZoneInfo; today = ctx.as_of.astimezone(ZoneInfo(cfg[0]["timezone"])).date()
    except Exception: today = ctx.today; lim.append("The configured timezone could not be applied; the server date was used.")
    r = one(ctx, f"select count(*) as n, coalesce(sum(case when check_out is null then 1 else 0 end),0) as still_in, max(updated_at) as lu from {T('attendance_records')} where work_date = %s", (today,))
    lim.append("No attendance rate is given: attendance user ids cannot be reliably linked to employee records.")
    return ok(ctx, d, n_(r.get("n")), detail={"work_date": today.isoformat(), "not_checked_out": n_(r.get("still_in"))}, freshness=fresh(ctx, r.get("lu")), limitations=lim, evidence=[ev("attendance_records", "records with work_date = today", n_(r.get("n")))])


@metric("leave.on_leave_today", "On approved leave today", "leave", ["leave.read"], ["leave_requests"], "Approved leave requests whose date range includes today. Aggregate count only.")
def on_leave(ctx, d):
    if not has_rows(ctx, "leave_requests"): return blank(d, ctx, R.NO_DATA, "No leave requests have been recorded.")
    r = one(ctx, f"select count(*) as n from {T('leave_requests')} where status='approved' and start_date <= %s and end_date >= %s", (ctx.today, ctx.today))
    return ok(ctx, d, n_(r.get("n")), evidence=[ev("leave_requests", "approved requests with start_date <= today <= end_date", n_(r.get("n")))], limitations=["Counts requests (people), not working days."])


# ============================== FLEET / DIAGNOSTICS / IOT ==============================
@metric("fleet.status", "Fleet by status", "fleet", ["fleet.read"], ["fleet_vehicles"], "Non-archived vehicles grouped by status.")
def fleet_status(ctx, d):
    rows = ctx.reader.rows(f"select status, count(*) as n, max(updated_at) as lu from {T('fleet_vehicles')} where not archived group by status")
    total = sum(n_(r["n"]) for r in rows)
    if not total: return blank(d, ctx, R.NO_DATA, "No vehicles have been recorded.")
    return ok(ctx, d, total, breakdown=[{"status": r["status"], "count": n_(r["n"])} for r in sorted(rows, key=lambda r: -n_(r["n"]))], freshness=fresh(ctx, *[r["lu"] for r in rows]), evidence=[ev("fleet_vehicles", "non-archived vehicles by status", total)])


@metric("diagnostics.active_unlinked", "Active faults without a linked ticket", "diagnostics", ["diagnostics.read", "fleet.read"], ["diagnostic_faults", "fleet_vehicles"],
        "ACTIVE diagnostic faults on non-archived vehicles whose ticket_id is empty. The link is the explicit ticket_id column only; it is never inferred from free-text vehicle references.")
def faults_unlinked(ctx, d):
    base = f"from {T('diagnostic_faults')} f join {T('fleet_vehicles')} v on v.id = f.vehicle_id where f.status='ACTIVE' and not v.archived"
    if not has_rows(ctx, "diagnostic_faults"): return blank(d, ctx, R.NO_DATA, "No diagnostic faults have been recorded.")
    r = one(ctx, f"select count(*) as active, coalesce(sum(case when f.ticket_id is null then 1 else 0 end),0) as unlinked, max(f.created_at) as lu {base}")
    rows = ctx.reader.rows(f"select f.id, f.severity, f.fault_code, f.detected_at, f.vehicle_id, v.registration_number as vehicle_ref {base} and f.ticket_id is null order by f.detected_at desc, f.id limit 200")
    rows.sort(key=lambda x: (-SEV_RANK.get(x["severity"], 0), str(x["detected_at"]))); sev = {}
    for x in rows: sev[x["severity"]] = sev.get(x["severity"], 0) + 1
    return ok(ctx, d, n_(r.get("unlinked")), detail={"active_faults": n_(r.get("active")), "unlinked_by_severity": sev, "highest_severity": rows[0]["severity"] if rows else None},
              breakdown=[{"fault_id": str(x["id"]), "severity": x["severity"], "fault_code": x["fault_code"], "detected_at": R.iso(A.to_dt(x["detected_at"])), "vehicle_id": str(x["vehicle_id"]), "vehicle_ref": x["vehicle_ref"]} for x in rows[:20]],
              freshness=fresh(ctx, r.get("lu")), threshold={"configured": True, "label": "Severity recorded on each fault"},
              limitations=["A ticket may exist for the vehicle without being linked through ticket_id; such cases are counted as unlinked."], evidence=[ev("diagnostic_faults", "ACTIVE faults with ticket_id is null", n_(r.get("unlinked")), [x["id"] for x in rows[:10]])], link={"module": "diagnostics"})


@metric("diagnostics.repeated", "Vehicles with repeated faults", "diagnostics", ["diagnostics.read", "fleet.read"], ["diagnostic_faults", "fleet_vehicles"],
        "Vehicle + fault code pairs recorded 2 or more times with detected_at in the period (two occurrences is the definition of 'repeated').", kind="flow")
def faults_repeated(ctx, d):
    if not has_rows(ctx, "diagnostic_faults"): return blank(d, ctx, R.NO_DATA, "No diagnostic faults have been recorded.")
    rows = ctx.reader.rows(f"select f.vehicle_id, max(v.registration_number) as vehicle_ref, f.fault_code, count(*) as n, max(f.detected_at) as last_detected from {T('diagnostic_faults')} f join {T('fleet_vehicles')} v on v.id = f.vehicle_id "
                           "where not v.archived and f.detected_at >= %s and f.detected_at < %s group by f.vehicle_id, f.fault_code having count(*) >= 2 order by n desc, f.fault_code, f.vehicle_id limit 20", (ctx.period.start_dt, ctx.period.end_dt_exclusive))
    return ok(ctx, d, len(rows), unit="vehicle/fault pairs", breakdown=[{"vehicle_id": str(r["vehicle_id"]), "vehicle_ref": r["vehicle_ref"], "fault_code": r["fault_code"], "occurrences": n_(r["n"]), "last_detected": R.iso(A.to_dt(r["last_detected"]))} for r in rows],
              evidence=[ev("diagnostic_faults", "group by vehicle_id, fault_code having count >= 2 in the period", len(rows))], limitations=["Top 20 pairs by occurrences."], link={"module": "diagnostics"})


@metric("iot.connectivity", "Devices beyond offline limit", "iot", ["iot.read"], ["iot_devices"],
        "ACTIVE, non-archived devices whose last contact is older than the device's own offline_after_minutes (iotapi rule). Devices that never reported are counted separately.")
def iot_connectivity(ctx, d):
    rows = ctx.reader.rows(f"select id, device_identifier, vehicle_id, last_seen_at, offline_after_minutes from {T('iot_devices')} where not archived and status='ACTIVE' order by id limit 5001")
    if not rows: return blank(d, ctx, R.NO_DATA, "No active devices are registered.")
    trunc = len(rows) > 5000; rows = rows[:5000]; off, never, on = [], 0, 0
    for r in rows:
        ls = A.to_dt(r["last_seen_at"])
        if ls is None: never += 1
        elif ls < ctx.as_of - timedelta(minutes=int(r["offline_after_minutes"])): off.append((ls, r))
        else: on += 1
    off.sort(key=lambda x: (x[0], str(x[1]["id"])))
    return ok(ctx, d, len(off), state=R.PARTIAL if trunc else R.AVAILABLE, unit="devices", detail={"active_devices": len(rows), "online": on, "never_reported": never},
              breakdown=[{"device_id": str(r["id"]), "device_identifier": r["device_identifier"], "vehicle_id": str(r["vehicle_id"]) if r["vehicle_id"] else None, "last_seen_at": R.iso(ls),
                          "offline_after_minutes": int(r["offline_after_minutes"]), "minutes_since_seen": int((ctx.as_of - ls).total_seconds() // 60)} for ls, r in off[:10]],
              freshness=fresh(ctx, *[r["last_seen_at"] for r in rows]), threshold={"configured": True, "label": "Per-device offline_after_minutes (database default 30 when not set)"},
              limitations=(["Only the first 5000 devices were read."] if trunc else []) + ["Offline limits come from each device's setting; the 30-minute default is a system default, not a company decision."],
              evidence=[ev("iot_devices", "last_seen_at older than offline_after_minutes before as_of", len(rows))], link={"module": "iot", "filter": {"connection": "OFFLINE"}})


def _drop_location(ctx, rows):
    if ctx.location_access() == "full": return rows
    return [r for r in rows if not locationpolicy.is_location_metric(r["metric"], ctx.extra_location_metrics)]


@metric("iot.threshold_alerts", "Telemetry readings outside configured limits", "iot", ["iot.read"], ["iot_readings", "iot_devices", "iot_thresholds"],
        "Latest reading per device and metric (last 7 days) that breaks an alert limit entered in iot_thresholds. CRITICAL wins over WARNING (iotapi.pick_alerts).", reliability="derived")
def iot_alerts(ctx, d):
    th = ctx.reader.rows(f"select metric, severity, min_value, max_value from {T('iot_thresholds')}")
    if not th: return blank(d, ctx, R.NO_THRESHOLD, R.NO_THRESHOLD_LABEL + ": no telemetry alert limits have been entered.")
    since = ctx.as_of - timedelta(days=7)
    rows = ctx.reader.rows(f"select r.device_id, r.metric, r.value, r.unit, r.recorded_at, r.vehicle_id, dv.offline_after_minutes from {T('iot_readings')} r join {T('iot_devices')} dv on dv.id = r.device_id "
                           f"join (select device_id, metric, max(recorded_at) as m from {T('iot_readings')} where recorded_at >= %s group by device_id, metric) l on l.device_id = r.device_id and l.metric = r.metric and l.m = r.recorded_at "
                           f"where not dv.archived and dv.status='ACTIVE' and r.recorded_at >= %s order by r.device_id, r.metric limit 5001", (since, since))
    trunc = len(rows) > 5000; rows = _drop_location(ctx, rows[:5000]); best = {}
    for r in rows:
        for t in th:
            if t["metric"] != r["metric"]: continue
            lo, hi, v = t["min_value"], t["max_value"], float(r["value"])
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                k = (str(r["device_id"]), r["metric"]); c = {**r, "severity": t["severity"], "breach": "BELOW_MIN" if (lo is not None and v < lo) else "ABOVE_MAX"}
                if k not in best or (t["severity"] == "CRITICAL" and best[k]["severity"] != "CRITICAL"): best[k] = c
    al = sorted(best.values(), key=lambda x: (x["severity"] != "CRITICAL", str(x["recorded_at"]), str(x["device_id"])))
    for x in al: x["stale"] = A.to_dt(x["recorded_at"]) < ctx.as_of - timedelta(minutes=int(x["offline_after_minutes"]))
    crit = sum(1 for x in al if x["severity"] == "CRITICAL")
    return ok(ctx, d, len(al), state=R.PARTIAL if trunc else R.AVAILABLE, detail={"critical": crit, "warning": len(al) - crit, "stale_readings": sum(1 for x in al if x["stale"])},
              breakdown=[{"device_id": str(x["device_id"]), "vehicle_id": str(x["vehicle_id"]) if x["vehicle_id"] else None, "metric": x["metric"], "value": x["value"], "unit": x["unit"], "severity": x["severity"], "breach": x["breach"],
                          "recorded_at": R.iso(A.to_dt(x["recorded_at"])), "stale": x["stale"]} for x in al[:20]],
              threshold={"configured": True, "label": "Limits entered in iot_thresholds"}, limitations=["Location metrics are excluded unless your role may see location data."] + (["Only the first 5000 latest readings were examined."] if trunc else []),
              evidence=[ev("iot_readings", "latest reading per device+metric compared with iot_thresholds", len(rows))], link={"module": "iot"})


@metric("iot.anomalies", "Unusual telemetry readings", "iot", ["iot.read"], ["iot_readings", "iot_devices"],
        f"Latest reading (last 24h) per device+metric compared with up to 100 earlier readings (last 30 days) using the modified z-score on median/MAD; |z| > {A.MODIFIED_Z_CUTOFF} is flagged. Needs at least {A.MIN_BASELINE_POINTS} baseline readings. This is a statistical screen, not a company threshold.", reliability="statistical")
def iot_anomalies(ctx, d):
    rows = ctx.reader.rows(f"select device_id, metric, value, recorded_at from (select r.device_id, r.metric, r.value, r.recorded_at, row_number() over (partition by r.device_id, r.metric order by r.recorded_at desc) as rn "
                           f"from {T('iot_readings')} r join {T('iot_devices')} dv on dv.id = r.device_id where not dv.archived and dv.status='ACTIVE' and r.recorded_at >= %s) x where rn <= 101 order by device_id, metric, recorded_at desc limit 5001", (ctx.as_of - timedelta(days=30),))
    if not rows: return blank(d, ctx, R.NO_DATA, "No telemetry readings in the last 30 days.")
    trunc = len(rows) > 5000; rows = _drop_location(ctx, rows[:5000]); groups = {}
    for r in rows: groups.setdefault((str(r["device_id"]), r["metric"]), []).append(r)
    found, tested, short = [], 0, 0
    for (dev, met), rs in groups.items():
        latest = rs[0]
        if A.to_dt(latest["recorded_at"]) < ctx.as_of - timedelta(hours=24): continue
        res = A.detect_anomaly([float(x["value"]) for x in rs[1:]], float(latest["value"]))
        if res["state"] == "not_enough_history": short += 1
        else:
            tested += 1
            if res["state"] == "anomalous": found.append({"device_id": dev, "metric": met, "value": latest["value"], "recorded_at": R.iso(A.to_dt(latest["recorded_at"])), **{k: res[k] for k in ("modified_z", "baseline_median", "baseline_points")}})
    if tested == 0: return blank(d, ctx, R.NOT_ENOUGH_HISTORY, R.NOT_ENOUGH_HISTORY_LABEL + f": no device/metric has {A.MIN_BASELINE_POINTS}+ earlier readings and a reading in the last 24h.", detail={"series_too_short": short})
    found.sort(key=lambda x: (-abs(x["modified_z"]), x["device_id"], x["metric"]))
    return ok(ctx, d, len(found), state=R.PARTIAL if (trunc or short) else R.AVAILABLE, unit="readings", breakdown=found[:20], detail={"series_tested": tested, "series_too_short": short},
              limitations=[f"{short} series had too little history to test."] * bool(short) + (["Up to ~50 device/metric series are examined per request."] if trunc else []) + ["A flagged reading is unusual relative to its own history; it is not necessarily a fault."],
              threshold={"configured": False, "label": "Statistical method (not a company threshold)"}, evidence=[ev("iot_readings", "modified z-score vs the series' own recent readings", len(rows))], link={"module": "iot"})


# ============================== KPI CENTER / STARTUP METRICS (user-entered) ==============================
@metric("kpi.user_entered", "KPI Center and Startup Metrics records", "kpi", ["kpi.read"], ["module_records"],
        "Records users entered in the KPI Center and Startup Metrics workspaces. Counts only; the values are not validated against any system of record.", reliability="user_entered")
def kpi_records(ctx, d):
    rows = ctx.reader.rows(f"select module, count(*) as n, max(updated_at) as lu from {T('module_records')} where not archived and module in ('kpi-center','startup-metrics') group by module")
    if not rows: return blank(d, ctx, R.NO_DATA, "No KPI Center or Startup Metrics records have been entered.")
    return ok(ctx, d, sum(n_(r["n"]) for r in rows), breakdown=[{"module": r["module"], "records": n_(r["n"]), "last_updated": R.iso(A.to_dt(r["lu"]))} for r in rows], freshness=fresh(ctx, *[r["lu"] for r in rows]),
              limitations=["User-entered figures; reliability depends on who entered them and when."], evidence=[ev("module_records", "records in the kpi-center and startup-metrics workspaces", sum(n_(r["n"]) for r in rows))])


# ============================== WEEKLY TREND SERIES (flow history) ==============================
TREND_WEEKS = 8


def _weeks(ctx, n=TREND_WEEKS):
    from .periods import Period
    out, end = [], ctx.period.end
    for _ in range(n): out.append(Period(end - timedelta(days=6), end)); end = end - timedelta(days=7)
    return list(reversed(out))


def _series(ctx, d, table, series, where="not archived", label_cols=None):
    """series: {name: (column, extra_where)}. Weeks that end before the oldest record are None ('before history'), never 0."""
    if not has_rows(ctx, table): return blank(d, ctx, R.NO_DATA, "No records exist in this source.")
    first = A.to_date(earliest(ctx, table, "created_at", where)); rows, usable = [], 0
    for w in _weeks(ctx):
        row = {"week_start": w.start.isoformat(), "week_end": w.end.isoformat()}
        if first is None or w.end < first: row.update({k: None for k in series}); row["history"] = False
        else:
            row["history"] = True; usable += 1
            for k, (col, extra) in series.items(): row[k] = count_in(ctx, table, col, w, f"{where} and {extra}" if extra else where)
        rows.append(row)
    if usable < 2: return blank(d, ctx, R.NOT_ENOUGH_HISTORY, R.NOT_ENOUGH_HISTORY_LABEL + ": fewer than 2 weeks of history are available.", detail={"weeks_with_history": usable})
    return ok(ctx, d, usable, unit="weeks", breakdown=rows, detail={"weeks_with_history": usable, "oldest_record": R.iso(first)},
              state=R.AVAILABLE if usable == len(rows) else R.PARTIAL, limitations=[] if usable == len(rows) else ["Earlier weeks are blank because no records exist from before the source's first record."],
              evidence=[ev(table, "weekly counts by timestamp column (UTC day boundaries)", None)])


@metric("tickets.trend", "Tickets created vs resolved by week", "tickets", ["tickets.read"], ["service_tickets"], "Weekly created and resolved ticket counts (last 8 weeks ending at the period end).", unit="weeks", kind="flow")
def tickets_trend(ctx, d): return _series(ctx, d, "service_tickets", {"created": ("created_at", ""), "resolved": ("resolved_at", "")})


@metric("tasks.trend", "Tasks created vs completed by week", "tasks", ["tasks.read"], ["tasks"], "Weekly created and completed task counts (last 8 weeks ending at the period end).", unit="weeks", kind="flow")
def tasks_trend(ctx, d): return _series(ctx, d, "tasks", {"created": ("created_at", ""), "completed": ("completed_at", "status='done'")}, where="not is_archived")


@metric("leads.trend", "Leads created by week", "leads", ["leads.read"], ["leads"], "Weekly new lead counts (last 8 weeks ending at the period end).", unit="weeks", kind="flow")
def leads_trend(ctx, d): return _series(ctx, d, "leads", {"created": ("created_at", "")}, where="not is_archived")
