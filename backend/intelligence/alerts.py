"""Deterministic alerts, ranked issues, insights and the executive overview. Built ONLY from registry results (compute()), so every
number matches the metric catalogue. No thresholds, SLAs or policies are invented: an alert exists only when a limit that someone
entered in the system (a due date, a device offline limit, an iot_threshold, a budget line) is broken, or an explicit state
(pending, unlinked, unassigned) needs a decision. `severity_basis` always says where the severity came from.

Severity levels: critical > high > medium > low > attention.
  * critical/high/medium/low are taken from a severity or priority field already recorded on the underlying records
    (ticket priority, fault severity, task priority, iot_thresholds.severity).
  * 'attention' is used when the system holds a broken limit or pending decision but NO severity information. It is not a risk rating.
Ranking (documented, deterministic): severity rank desc, then oldest-item age in days desc (0 when unknown), then affected count desc, then rule id."""
from dataclasses import dataclass
from . import results as R
from .registry import Ctx, compute

SEV = {"critical": 5, "high": 4, "medium": 3, "low": 2, "attention": 1}
TICKET_PRIO = {"URGENT": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
TASK_PRIO = {"high": "high", "normal": "medium", "low": "low"}
FAULT_SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "INFO": "low"}


def _a(rule, r, title, severity, basis, step, *, count=None, age_days=None, facts=None, link=None):
    return {"id": f"{rule}", "rule_id": rule, "title": title, "severity": severity, "severity_basis": basis, "metric_id": r.metric_id, "value": r.value if count is None else count,
            "facts": facts or [], "evidence": [e.to_dict() for e in r.evidence], "source": [e.source for e in r.evidence], "reported_at": r.as_of, "data_freshness": r.freshness,
            "threshold": r.threshold, "reliability": r.reliability, "limitations": r.limitations, "recommended_next_step": step, "link": link or r.link,
            "_rank": (SEV[severity], age_days or 0, (r.value if count is None else count) or 0)}


def _plural(n, one, many=None): return f"{n} {one if n == 1 else (many or one + 's')}"


def build_alerts(ctx: Ctx) -> list:
    out, g = [], lambda m: compute(m, ctx)
    r = g("tasks.overdue")
    if r.usable() and r.value:
        top = r.detail.get("highest_priority"); out.append(_a("tasks.overdue", r, f"{_plural(r.value, 'task')} overdue", TASK_PRIO.get(top, "attention"), f"Highest task priority among overdue tasks ('{top}'), from the priority field.",
              "Review the overdue tasks with their owners and decide whether to reschedule, reassign or close them.", age_days=r.detail.get("max_days_overdue"),
              facts=[f"Oldest due date: {r.detail.get('oldest_due_date')} ({r.detail.get('max_days_overdue')} days ago)."]))
    r = g("tickets.overdue")
    if r.usable() and r.value:
        top = r.detail.get("highest_priority"); out.append(_a("tickets.overdue", r, f"{_plural(r.value, 'service ticket')} overdue", TICKET_PRIO.get(top, "attention"), f"Highest ticket priority among overdue tickets ('{top}'), from the priority field.",
              "Open the overdue tickets, starting with the highest priority, and confirm owner and next action.", age_days=r.detail.get("max_days_overdue"),
              facts=[f"Oldest due date: {r.detail.get('oldest_due_date')} ({r.detail.get('max_days_overdue')} days ago)."]))
    r = g("tickets.unassigned")
    if r.usable() and r.value:
        out.append(_a("tickets.unassigned", r, f"{_plural(r.value, 'open ticket')} with no technician", "attention", "No severity information exists for unassigned tickets; flagged because assigned_to is empty.", "Assign a technician to each unassigned ticket."))
    r = g("approvals.pending")
    if r.usable() and r.value:
        parts = ", ".join(f"{p['module']}: {p['count']}" for p in r.breakdown if p["count"]); t = g("tasks.pending_approval")
        out.append(_a("approvals.pending", r, f"{_plural(r.value, 'decision')} waiting for approval", "attention", "No severity information exists for pending approvals; flagged because a decision is outstanding.", "Open each module's approval queue and decide, starting with the oldest.",
              age_days=int((t.detail.get("oldest_waiting_hours") or 0) // 24), facts=[parts], link={"module": "approvals"}))
    r = g("leads.followups_overdue")
    if r.usable() and r.value:
        out.append(_a("leads.followups_overdue", r, f"{_plural(r.value, 'lead')} past their follow-up date", "attention", "Leads carry no priority; flagged because next_follow_up is in the past.", "Contact these leads or move their follow-up date.", age_days=r.detail.get("max_days_overdue"),
              facts=[f"Oldest follow-up date: {r.detail.get('oldest_follow_up')}."]))
    r = g("invoices.receivables")
    if r.usable() and r.detail.get("overdue_count"):
        out.append(_a("invoices.overdue", r, f"{_plural(r.detail['overdue_count'], 'invoice')} overdue", "attention", "Invoices carry no severity; flagged because due_date has passed with a balance outstanding.", "Review overdue invoices and follow up on collection.",
              count=r.detail["overdue_count"], facts=[f"Overdue balance: {r.detail['overdue_amount']:,.2f} of {r.detail['outstanding']:,.2f} outstanding."], link={"module": "payments", "filter": {"payment_status": "OVERDUE"}}))
    r = g("budget.variance")
    if r.usable() and r.value:
        over = [x for x in r.breakdown if x["kind"] == "EXPENSE" and x["variance"] > 0]
        out.append(_a("budget.over", r, f"{_plural(r.value, 'expense category', 'expense categories')} over budget", "attention", "Budget lines have no severity; flagged because approved spend exceeds the entered budget.", "Review the over-budget categories and decide whether to adjust the budget or the spending.",
              facts=[f"{x['category']}: {x['actual']:,.2f} vs budget {x['budget']:,.2f}." for x in over[:5]]))
    r = g("diagnostics.active_unlinked")
    if r.usable() and r.value:
        top = r.detail.get("highest_severity"); out.append(_a("diagnostics.unlinked", r, f"{_plural(r.value, 'active fault')} with no linked ticket", FAULT_SEV.get(top, "attention"), f"Highest fault severity among unlinked faults ('{top}'), from the severity field.",
              "Create or link a service ticket for each active fault, starting with the highest severity.", facts=[f"By severity: {r.detail.get('unlinked_by_severity')}."]))
    r = g("iot.connectivity")
    if r.usable() and r.value:
        out.append(_a("iot.offline", r, f"{_plural(r.value, 'device')} beyond offline limit", "attention", "Devices carry no severity; flagged because last contact exceeds the device's own offline limit.", "Check power and connectivity of these devices.",
              age_days=int((r.breakdown[0]["minutes_since_seen"] if r.breakdown else 0) // 1440), facts=[f"{r.detail.get('never_reported', 0)} further device(s) have never reported."]))
    r = g("iot.threshold_alerts")
    if r.usable() and r.value:
        sev = "critical" if r.detail.get("critical") else "medium"
        out.append(_a("iot.threshold", r, f"{_plural(r.value, 'telemetry reading')} outside configured limits", sev, "Severity from iot_thresholds (CRITICAL -> critical, WARNING -> medium).", "Inspect the affected devices and vehicles.",
              facts=[f"{r.detail.get('critical', 0)} critical, {r.detail.get('warning', 0)} warning; {r.detail.get('stale_readings', 0)} reading(s) are stale."]))
    r = g("iot.anomalies")
    if r.usable() and r.value:
        out.append(_a("iot.anomalies", r, f"{_plural(r.value, 'unusual telemetry reading')}", "attention", "Statistical screen (modified z-score); no company threshold or severity applies.", "Compare these readings with the vehicle's recent behaviour before acting."))
    out.sort(key=lambda a: (-a["_rank"][0], -a["_rank"][1], -a["_rank"][2], a["rule_id"]))
    for i, a in enumerate(out, 1): a["rank"] = i; a.pop("_rank")
    return out


def build_gaps(ctx: Ctx) -> list:
    """Missing-data warnings: every metric that is not usable, with the reason. Never hidden, never shown as zero."""
    from .registry import REGISTRY
    out = []
    for mid in sorted(REGISTRY):
        r = compute(mid, ctx)
        if r.state in (R.NO_DATA, R.NOT_CONFIGURED, R.NO_THRESHOLD, R.UNAVAILABLE, R.NOT_ENOUGH_HISTORY, R.NO_PERMISSION):
            out.append({"metric_id": mid, "label": r.label, "state": r.state, "message": r.message or R.NOT_ENOUGH_HISTORY_LABEL})
    return out


def _st(kind, text, metric_id=None): return {"kind": kind, "text": text, "metric_id": metric_id}


def build_insights(ctx: Ctx) -> list:
    """Evidence-backed insight cards. Every statement is tagged: verified_fact | calculated_metric | possible_explanation | recommendation | unavailable."""
    g, cards = (lambda m: compute(m, ctx)), []
    f = g("tickets.flow")
    if f.usable():
        s = [_st(R.CALCULATED, f"{f.detail['created']} tickets were created and {f.detail['resolved']} resolved in the period; net inflow {f.detail['net_inflow']:+d}.", f.metric_id)]
        c = f.comparison or {}
        if c.get("state") == R.AVAILABLE: s.append(_st(R.CALCULATED, f"Previous period: {c['previous_created']} created, {c['previous_resolved']} resolved (net {c['previous_value']:+.0f}).", f.metric_id))
        elif c: s.append(_st(R.UNAVAILABLE_INFO, "Not enough history to compare with the previous period.", f.metric_id))
        un, ag, ov = g("tickets.unassigned"), g("tickets.ageing"), g("tickets.overdue")
        if un.usable() and un.value: s.append(_st(R.FACT, f"{un.value} open ticket(s) have no technician assigned.", un.metric_id)); s.append(_st(R.POSSIBLE, "Unassigned tickets cannot progress until someone is assigned, which may be adding to the open backlog.", un.metric_id))
        if ag.usable() and ag.value:
            old = sum(b["count"] for b in ag.breakdown[3:]); s.append(_st(R.CALCULATED, f"{old} of {ag.value} open tickets are older than 14 days (no service-level target is configured).", ag.metric_id))
        if ov.usable() and ov.value: s.append(_st(R.FACT, f"{ov.value} open ticket(s) are past their due date.", ov.metric_id))
        s.append(_st(R.UNAVAILABLE_INFO, "The size of the backlog at an earlier date is not stored, so a true before/after backlog comparison is not available.", f.metric_id))
        s.append(_st(R.RECOMMENDATION, "Open the ticket list filtered to overdue and unassigned tickets.", None))
        cards.append({"id": "service_backlog", "title": "Service backlog movement", "state": f.state, "statements": s, "metric_ids": [f.metric_id, "tickets.unassigned", "tickets.ageing", "tickets.overdue"], "link": {"module": "tickets", "filter": {"overdue": True}}})
    w = g("tickets.technician_workload")
    if w.usable() and w.detail["distribution"].get("owners"):
        dd = w.detail["distribution"]
        s = [_st(R.CALCULATED, f"{dd['owners']} technicians hold {dd['total']} open tickets (average {dd['mean']}); the busiest holds {dd['max']} ({dd['max_share_pct']}%).", w.metric_id),
             _st(R.UNAVAILABLE_INFO, "No workload limit is configured, so the system does not judge any technician's load as disproportionate.", w.metric_id)]
        if w.detail.get("unassigned_open"): s.append(_st(R.FACT, f"{w.detail['unassigned_open']} open ticket(s) are not assigned to anyone.", w.metric_id))
        cards.append({"id": "technician_workload", "title": "Technician workload distribution", "state": w.state, "statements": s, "metric_ids": [w.metric_id], "link": {"module": "technicians"}})
    t, tk, ap = g("tasks.overdue"), g("tasks.by_status"), g("approvals.pending")
    if t.usable() or ap.usable():
        s = []
        if tk.usable(): s.append(_st(R.CALCULATED, f"{tk.detail['active']} tasks are active, {tk.detail['pending_approval']} await approval and {tk.detail['done']} are done.", tk.metric_id))
        if t.usable(): s.append(_st(R.FACT, f"{t.value} active task(s) are past their due date.", t.metric_id))
        if ap.usable(): s.append(_st(R.CALCULATED, f"{ap.value} decision(s) are waiting across modules.", ap.metric_id))
        s.append(_st(R.RECOMMENDATION, "Clear approvals first: they block other people's work.", None))
        cards.append({"id": "work_and_approvals", "title": "Work and approvals", "state": R.PARTIAL if ap.state == R.PARTIAL else R.AVAILABLE, "statements": s, "metric_ids": [m.metric_id for m in (t, tk, ap) if m.usable()], "link": {"module": "tasks"}})
    rc, ex = g("invoices.receivables"), g("expenses.summary")
    if rc.usable() or ex.usable():
        s = []
        if rc.usable(): s.append(_st(R.CALCULATED, f"Outstanding receivables {rc.detail['outstanding']:,.2f}, of which {rc.detail['overdue_amount']:,.2f} is past due ({rc.detail['overdue_count']} invoices).", rc.metric_id))
        if ex.usable():
            s.append(_st(R.CALCULATED, f"Approved expenses in the period: {ex.value:,.2f}.", ex.metric_id)); c = ex.comparison or {}
            if c.get("state") == R.AVAILABLE: s.append(_st(R.CALCULATED, f"Previous period: {c['previous_value']:,.2f}" + (f" ({c['pct_change']:+.1f}%)." if c.get("pct_change") is not None else "."), ex.metric_id))
            elif c: s.append(_st(R.UNAVAILABLE_INFO, "Not enough history to compare expenses with the previous period.", ex.metric_id))
        s.append(_st(R.UNAVAILABLE_INFO, "Profit, margin and cash balance are not reported: the system has no approved definition or ledger for them.", None))
        cards.append({"id": "receivables_expenses", "title": "Receivables and expenses", "state": R.AVAILABLE, "statements": s, "metric_ids": [m.metric_id for m in (rc, ex) if m.usable()], "link": {"module": "payments"}})
    fa, rp, ic = g("diagnostics.active_unlinked"), g("diagnostics.repeated"), g("iot.connectivity")
    if any(m.usable() for m in (fa, rp, ic)):
        s = []
        if fa.usable(): s.append(_st(R.FACT, f"{fa.value} active fault(s) have no linked ticket (of {fa.detail['active_faults']} active).", fa.metric_id))
        if rp.usable(): s.append(_st(R.CALCULATED, f"{rp.value} vehicle/fault-code pair(s) recurred 2+ times in the period.", rp.metric_id))
        if ic.usable(): s.append(_st(R.FACT, f"{ic.value} of {ic.detail['active_devices']} active devices are beyond their offline limit; {ic.detail['never_reported']} never reported.", ic.metric_id))
        cards.append({"id": "fleet_health", "title": "Fleet, diagnostics and telemetry", "state": R.AVAILABLE, "statements": s, "metric_ids": [m.metric_id for m in (fa, rp, ic) if m.usable()], "link": {"module": "diagnostics"}})
    return cards


CARD_METRICS = ("tasks.overdue", "tasks.pending_approval", "tickets.open_backlog", "tickets.overdue", "tickets.unassigned", "approvals.pending", "leads.pipeline", "leads.followups_overdue",
                "invoices.receivables", "expenses.summary", "budget.variance", "attendance.today", "leave.on_leave_today", "fleet.status", "diagnostics.active_unlinked",
                "iot.connectivity", "iot.threshold_alerts", "iot.anomalies", "kpi.user_entered")


def compact(r) -> dict:
    d = r.to_dict()
    return {k: d[k] for k in ("metric_id", "label", "state", "value", "unit", "message", "as_of", "freshness", "threshold", "reliability", "link", "limitations")} | {"comparison": d["comparison"], "period": d["period"], "detail": d["detail"]}


def build_overview(ctx: Ctx) -> dict:
    alerts = build_alerts(ctx); cards = [compact(compute(m, ctx)) for m in CARD_METRICS]
    return {"as_of": ctx.as_of.isoformat(), "period": ctx.period.to_dict(), "previous_period": ctx.prev.to_dict() if ctx.prev else None,
            "cards": cards, "top_risks": alerts[:3], "alerts": alerts, "insights": build_insights(ctx), "gaps": build_gaps(ctx),
            "summary": {"alerts_total": len(alerts), "by_severity": {s: sum(1 for a in alerts if a["severity"] == s) for s in SEV}, "metrics_available": sum(1 for c in cards if c["state"] in R.USABLE), "metrics_total": len(cards)}}
