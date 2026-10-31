"""Company context engine: what information ACTUALLY exists, for THIS user. It answers "what can we trust and what is missing" before
any insight is shown. Reads only through the registry (metric states) plus a few small existence/freshness probes."""
from datetime import timedelta

from . import analytics as A
from . import results as R
from .reader import ReaderError
from .registry import REGISTRY, Ctx, compute

# key, label, tables that must exist, permission needed to look inside, probe table, freshness column, history column.
# Probe columns are the real ones from db/*.sql (e.g. leave_requests and diagnostic_faults have no updated_at).
MODULES = (
    ("tasks", "Tasks & Approvals", ("tasks",), "tasks.read", "tasks", "updated_at", "created_at"),
    ("tickets", "Service Tickets", ("service_tickets",), "tickets.read", "service_tickets", "updated_at", "created_at"),
    ("service_centers", "Service Centers", ("service_centers",), "garages.read", "service_centers", "updated_at", "created_at"),
    ("leads", "Leads & Pipeline", ("leads",), "leads.read", "leads", "updated_at", "created_at"),
    ("invoices", "Invoices & Receivables", ("invoices", "invoice_payments"), "invoices.read", "invoices", "updated_at", "created_at"),
    ("expenses", "Expenses", ("expenses",), "expenses.read", "expenses", "updated_at", "created_at"),
    ("budgets", "Budget", ("budgets",), "budget.read", "budgets", "updated_at", "created_at"),
    ("attendance", "Attendance", ("attendance_config", "attendance_records"), "attendance.read", "attendance_records", "updated_at", "created_at"),
    ("leave", "Leave", ("leave_requests",), "leave.read", "leave_requests", "created_at", "created_at"),
    ("fleet", "Fleet", ("fleet_vehicles",), "fleet.read", "fleet_vehicles", "updated_at", "created_at"),
    ("diagnostics", "Diagnostics", ("diagnostic_faults",), "diagnostics.read", "diagnostic_faults", "created_at", "detected_at"),
    ("iot", "IoT & Telemetry", ("iot_devices", "iot_readings"), "iot.read", "iot_readings", "received_at", "recorded_at"),
    ("kpi", "KPI Center & Startup Metrics", ("module_records",), "kpi.read", "module_records", "updated_at", "created_at"),
)
GAP_STATES = (R.NO_DATA, R.NOT_CONFIGURED, R.NO_THRESHOLD, R.UNAVAILABLE, R.NOT_ENOUGH_HISTORY, R.NO_PERMISSION)


def _module(ctx: Ctx, key, label, tables, perm, probe, fcol, hcol):
    m = {"module": key, "label": label, "permitted": ctx.can(perm) and not ctx.own_only(perm.split(".")[0]), "connected": False, "has_data": None, "latest_update_at": None, "oldest_record_at": None, "history_days": None}
    if not m["permitted"]: return m
    try:
        m["connected"] = all(ctx.reader.has_table(t) for t in tables)
        if not m["connected"]: return m
        r = ctx.reader.rows(f"select count(*) as n, max({fcol}) as latest, min({hcol}) as oldest from office_dashboard.{probe}")[0]
        m["has_data"] = bool(r["n"]); m["latest_update_at"] = R.iso(A.to_dt(r["latest"])); m["oldest_record_at"] = R.iso(A.to_dt(r["oldest"]))
        if r["oldest"]: m["history_days"] = (ctx.as_of - A.to_dt(r["oldest"])).days
    except ReaderError: m["connected"] = None; m["has_data"] = None      # None = could not be determined (never shown as "no")
    return m


def build_context(ctx: Ctx) -> dict:
    mods = [_module(ctx, *m) for m in MODULES]
    results = {mid: compute(mid, ctx) for mid in sorted(REGISTRY)}
    counts = {s: 0 for s in R.STATES}
    for r in results.values(): counts[r.state] += 1
    gaps = [{"metric_id": r.metric_id, "label": r.label, "state": r.state, "message": r.message or ("No history" if r.state == R.NOT_ENOUGH_HISTORY else "")} for r in results.values() if r.state in GAP_STATES]
    unlinked = []
    c = results["tickets.by_service_center"]
    if c.usable() and c.detail.get("unlinked_open"): unlinked.append({"what": "open tickets with no service center", "count": c.detail["unlinked_open"], "metric_id": c.metric_id})
    f = results["diagnostics.active_unlinked"]
    if f.usable() and f.value: unlinked.append({"what": "active diagnostic faults with no ticket_id", "count": f.value, "metric_id": f.metric_id})
    u = results["tickets.unassigned"]
    if u.usable() and u.value: unlinked.append({"what": "open tickets with no technician", "count": u.value, "metric_id": u.metric_id})
    dq = []
    for mid, key in (("tasks.overdue", "active_without_due_date"), ("tickets.overdue", "open_without_due_date"), ("leads.followups_overdue", "open_without_follow_up_date")):
        r = results[mid]
        if r.usable() and r.detail.get(key): dq.append({"metric_id": mid, "issue": key, "count": r.detail[key]})
    thresholds = [
        {"name": "Task due dates", "configured": True, "source": "due_date on each task"}, {"name": "Ticket due dates", "configured": True, "source": "due_date on each ticket"},
        {"name": "Lead follow-up dates", "configured": True, "source": "next_follow_up on each lead"}, {"name": "Invoice due dates", "configured": True, "source": "due_date on each invoice"},
        {"name": "Device offline limit", "configured": True, "source": "offline_after_minutes per device (default 30 from the database)"},
        {"name": "Telemetry alert limits", "configured": results["iot.threshold_alerts"].state not in (R.NO_THRESHOLD, R.UNAVAILABLE, R.NO_PERMISSION), "source": "iot_thresholds"},
        {"name": "Monthly budget", "configured": results["budget.variance"].state in R.USABLE, "source": "budgets for the current month"},
        {"name": "Service-level targets (SLA)", "configured": False, "source": "none exist in the system; no SLA is assumed"},
        {"name": "Technician workload limit", "configured": False, "source": "none exists in the system"},
        {"name": "Performance targets", "configured": False, "source": "none exist in the system"}]
    return {"as_of": ctx.as_of.isoformat(), "period": ctx.period.to_dict(), "modules": mods, "metric_state_counts": counts, "metric_count": len(results), "gaps": gaps,
            "unlinked": unlinked, "data_quality": dq, "thresholds": thresholds,
            "history": [{"module": m["module"], "oldest_record_at": m["oldest_record_at"], "history_days": m["history_days"],
                         "supports_previous_period_comparison": bool(m["oldest_record_at"]) and A.to_date(m["oldest_record_at"]) <= (ctx.prev.start if ctx.prev else ctx.period.start)} for m in mods if m["permitted"] and m["connected"] and m["has_data"]],
            "notes": ["Metrics are calculated from records in the database; user-entered figures are labelled as such.",
                      "Revenue, profit, cash balance and employee performance are not reported: no approved definition exists in the system.",
                      "No point-in-time history of backlog size is stored; changes are measured as created-minus-resolved flows."]}
