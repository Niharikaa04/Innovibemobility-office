"""Metric correctness against seeded rows. The real SQL strings run on SQLite (see intel_fixtures); expected numbers are hand-computed."""
from datetime import date, timedelta
import intel_fixtures as F
from intel_fixtures import SqliteReader, make_ctx, ago, TODAY, AS_OF
import intelligence.metrics as M
from intelligence import results as R
from intelligence.registry import REGISTRY, compute


def tk(r, id, status="NEW", prio="MEDIUM", due=None, created=10, assigned=("u1", "Tech One"), center=None, resolved=None, archived=0):
    r.add("service_tickets", id=id, status=status, priority=prio, due_date=due, created_at=ago(created), updated_at=ago(1), assigned_to=assigned[0] if assigned else None,
          assigned_name=assigned[1] if assigned else None, service_center_id=center, resolved_at=ago(resolved) if resolved is not None else None, archived=archived)


# ---------- tasks ----------
def seed_tasks(r):
    t = lambda id, **k: r.add("tasks", id=id, created_at=ago(k.pop("created", 20)), updated_at=ago(1), assignee_id="a", created_by="a", title="t", **k)
    t("t1", status="open", priority="high", due_date=TODAY - timedelta(days=5))
    t("t2", status="in_progress", priority="low", due_date=TODAY - timedelta(days=1))
    t("t3", status="open", priority="normal", due_date=TODAY)                                 # due today: NOT overdue
    t("t4", status="done", priority="high", due_date=TODAY - timedelta(days=9), completed_at=ago(2))   # done: not overdue
    t("t5", status="open", priority="high", due_date=TODAY - timedelta(days=9), is_archived=1)         # archived: ignored
    t("t6", status="pending_approval", priority="high", due_date=TODAY - timedelta(days=3))            # counted under approvals, not overdue
    t("t7", status="open", priority="normal")                                                           # no due date


def test_tasks_overdue_exact_and_data_quality():
    r = SqliteReader(); seed_tasks(r); res = compute("tasks.overdue", make_ctx(r))
    assert res.state == R.AVAILABLE and res.value == 2 and res.detail["highest_priority"] == "high" and res.detail["max_days_overdue"] == 5
    assert res.detail["active_without_due_date"] == 1 and any("no due date" in l for l in res.limitations)
    assert {b["priority"]: b["count"] for b in res.breakdown} == {"high": 1, "low": 1}


def test_tasks_status_and_pending():
    r = SqliteReader(); seed_tasks(r); ctx = make_ctx(r)
    s = compute("tasks.by_status", ctx); assert s.value == 6 and s.detail["open"] == 3 and s.detail["pending_approval"] == 1 and s.detail["done"] == 1
    assert compute("tasks.pending_approval", ctx).value == 1


def test_empty_source_is_no_data_never_zero():
    r = SqliteReader(); res = compute("tasks.overdue", make_ctx(r)); assert res.state == R.NO_DATA and res.value is None


# ---------- tickets ----------
def seed_tickets(r):
    r.add("service_centers", id="c1", name="Hub A"); r.add("service_centers", id="c2", name="Hub B")
    tk(r, "k1", "NEW", "URGENT", TODAY - timedelta(days=4), created=40, center="c1")
    tk(r, "k2", "IN_PROGRESS", "LOW", TODAY - timedelta(days=1), created=12, center="c1")
    tk(r, "k3", "NEW", "HIGH", TODAY + timedelta(days=3), created=2, assigned=None, center="c2")
    tk(r, "k4", "CLOSED", "URGENT", TODAY - timedelta(days=30), created=60, center="c1", resolved=5)         # finished: excluded
    tk(r, "k5", "WAITING", "MEDIUM", None, created=9, center=None, assigned=("u2", "Tech Two"))              # no due date, no center
    tk(r, "k6", "NEW", "LOW", TODAY - timedelta(days=2), created=3, archived=1)                               # archived: excluded


def test_tickets_backlog_overdue_match_ticketapi_rules():
    r = SqliteReader(); seed_tickets(r); ctx = make_ctx(r)
    assert compute("tickets.open_backlog", ctx).value == 4
    o = compute("tickets.overdue", ctx); assert o.value == 2 and o.detail["highest_priority"] == "URGENT" and o.detail["max_days_overdue"] == 4 and o.detail["open_without_due_date"] == 1
    assert compute("tickets.unassigned", ctx).value == 1


def test_done_statuses_match_the_existing_ticket_module():
    assert M.DONE == ("COMPLETED", "CUSTOMER_CONFIRMATION", "CLOSED")
    try: import opscommon
    except Exception: return              # fastapi not installed in this environment; the literal above is still asserted
    assert tuple(opscommon.DONE) == M.DONE


def test_ageing_buckets_add_up():
    r = SqliteReader(); seed_tickets(r); a = compute("tickets.ageing", make_ctx(r))
    assert a.value == 4 and sum(b["count"] for b in a.breakdown) == 4
    # open tickets were created 40d, 12d, 2d and 9d ago
    assert {b["bucket"]: b["count"] for b in a.breakdown} == {"0-2 days": 1, "3-7 days": 0, "8-14 days": 2, "15-30 days": 0, "31+ days": 1}


def test_service_center_breakdown_reports_unlinked():
    r = SqliteReader(); seed_tickets(r); c = compute("tickets.by_service_center", make_ctx(r))
    by = {x["service_center"]: x for x in c.breakdown}
    assert by["Hub A"]["open"] == 2 and by["Hub A"]["overdue"] == 2 and by["Hub B"]["open"] == 1 and c.detail["unlinked_open"] == 1 and c.value == 4


def test_technician_workload_is_facts_without_judgement():
    r = SqliteReader(); seed_tickets(r); w = compute("tickets.technician_workload", make_ctx(r))
    assert w.value == 3 and w.detail["unassigned_open"] == 1 and w.detail["distribution"]["max"] == 2 and w.threshold == {"configured": False, "label": "No threshold configured"}


def test_flow_comparison_available_when_history_exists():
    r = SqliteReader(); seed_tickets(r); f = compute("tickets.flow", make_ctx(r))          # window = last 7 days; previous = 7 days before; oldest ticket is 60d old
    assert f.detail["created"] == 1 and f.detail["resolved"] == 1 and f.comparison["state"] == R.AVAILABLE and f.comparison["previous_created"] == 2 and f.comparison["previous_resolved"] == 0


def test_flow_comparison_says_not_enough_history():
    r = SqliteReader(); tk(r, "n1", created=3); f = compute("tickets.flow", make_ctx(r))
    assert f.state == R.AVAILABLE and f.comparison["state"] == R.NOT_ENOUGH_HISTORY and f.comparison["message"] == "Not enough history" and "previous_value" not in f.comparison


# ---------- leads / finance ----------
def test_leads_followups():
    r = SqliteReader()
    L = lambda id, **k: r.add("leads", id=id, created_at=ago(30), updated_at=ago(1), **k)
    L("l1", stage="new", value=100.0, next_follow_up=TODAY - timedelta(days=7)); L("l2", stage="proposal", value=None, next_follow_up=TODAY)
    L("l3", stage="won", value=50.0, next_follow_up=TODAY - timedelta(days=20)); L("l4", stage="contacted", value=10.0, next_follow_up=None); L("l5", stage="new", value=1.0, next_follow_up=TODAY - timedelta(days=1), is_archived=1)
    ctx = make_ctx(r); f = compute("leads.followups_overdue", ctx); assert f.value == 1 and f.detail["open_without_follow_up_date"] == 1 and f.detail["max_days_overdue"] == 7
    p = compute("leads.pipeline", ctx); assert p.value == 3 and p.detail["open_value"] == 110.0 and p.detail["open_without_value"] == 1


def seed_invoices(r):
    inv = lambda id, name, total, due, status="SENT", archived=0: r.add("invoices", id=id, customer_name=name, total_amount=total, due_date=due, issue_date=TODAY - timedelta(days=60), status=status, archived=archived, updated_at=ago(1))
    inv("i1", "Acme", 1000.0, TODAY - timedelta(days=45)); inv("i2", "Acme", 500.0, TODAY - timedelta(days=5)); inv("i3", "Beta", 200.0, TODAY + timedelta(days=10))
    inv("i4", "Beta", 300.0, TODAY - timedelta(days=100)); inv("i5", "Gamma", 999.0, TODAY - timedelta(days=50), status="DRAFT"); inv("i6", "Delta", 50.0, TODAY - timedelta(days=50), archived=1)
    r.add("invoice_payments", id="p1", invoice_id="i1", amount=400.0); r.add("invoice_payments", id="p2", invoice_id="i2", amount=500.0)      # i2 fully paid
    r.add("invoice_payments", id="p3", invoice_id="i3", amount=75.0, voided=1)                                                                     # voided: ignored
    r.add("invoice_payments", id="p4", invoice_id="i4", amount=350.0)                                                                              # overpaid -> flagged


def test_receivables_match_finance_rules():
    r = SqliteReader(); seed_invoices(r); x = compute("invoices.receivables", make_ctx(r)); d = x.detail
    assert d["billed"] == 2000.0 and d["received"] == 1250.0                     # i1+i2+i3+i4 totals; p1+p2+p4 (voided p3 excluded)
    assert d["outstanding"] == 800.0 and d["overdue_amount"] == 600.0 and d["overdue_count"] == 1      # i1 600 overdue; i3 200 not yet due; i4 overpaid -> 0
    ag = {b["bucket"]: b["amount"] for b in x.breakdown}; assert ag["31-60"] == 600.0 and ag["current"] == 200.0 and ag["90+"] == 0.0
    assert any("above their total" in l for l in x.limitations) and d["top_debtors"][0] == {"customer_name": "Acme", "outstanding": 600.0}


def test_expenses_and_budget_variance():
    r = SqliteReader(); e = lambda id, cat, amt, day, st="APPROVED": r.add("expenses", id=id, category=cat, amount=amt, expense_date=date(2026, 10, day), status=st, archived=0, created_at=ago(60), updated_at=ago(1))
    e("e1", "RENT", 800.0, 2); e("e2", "TRAVEL", 150.0, 10); e("e3", "TRAVEL", 100.0, 11, "PENDING"); e("e4", "SOFTWARE", 60.0, 12); e("e5", "RENT", 10.0, 1, "REJECTED")
    r.add("budgets", id="b1", kind="EXPENSE", category="RENT", period_month=date(2026, 10, 1), amount=700.0); r.add("budgets", id="b2", kind="EXPENSE", category="TRAVEL", period_month=date(2026, 10, 1), amount=500.0)
    r.add("budgets", id="b3", kind="REVENUE", category="REVENUE", period_month=date(2026, 10, 1), amount=2000.0)
    r.add("invoices", id="i1", customer_name="A", total_amount=1500.0, due_date=TODAY, issue_date=date(2026, 10, 5), status="SENT", archived=0, updated_at=ago(1))
    v = compute("budget.variance", make_ctx(r)); rows = {(x["kind"], x["category"]): x for x in v.breakdown}
    assert rows[("EXPENSE", "RENT")]["variance"] == 100.0 and rows[("EXPENSE", "TRAVEL")]["variance"] == -350.0 and rows[("REVENUE", "REVENUE")]["actual"] == 1500.0 and rows[("REVENUE", "REVENUE")]["variance"] == -500.0
    assert v.value == 1 and v.detail["unbudgeted_expense_actual"] == 60.0 and any("month-to-date" in l for l in v.limitations)
    s = compute("expenses.summary", make_ctx(r, period=__import__("intelligence.periods", fromlist=["Period"]).Period(date(2026, 10, 1), date(2026, 10, 30), "october")))
    assert s.value == 1010.0 and s.comparison["state"] in (R.AVAILABLE, R.NOT_ENOUGH_HISTORY)


def test_budget_missing_is_no_data_not_zero():
    r = SqliteReader(); v = compute("budget.variance", make_ctx(r)); assert v.state == R.NO_DATA and v.value is None and "October 2026" in v.message


# ---------- approvals composite ----------
def seed_approvals(r):
    seed_tasks(r); r.add("expenses", id="e1", category="RENT", amount=5.0, expense_date=TODAY, status="PENDING", archived=0, created_at=ago(3), updated_at=ago(1))
    r.add("leave_requests", id="lv1", status="pending", start_date=TODAY, end_date=TODAY, created_at=ago(2)); r.add("leave_requests", id="lv2", status="approved", start_date=TODAY, end_date=TODAY + timedelta(days=1), created_at=ago(9))
    r.add("attendance_corrections", id="ac1", status="pending", created_at=ago(1))


def test_approvals_sum_each_module_once_and_reuse_module_numbers():
    r = SqliteReader(); seed_approvals(r); ctx = make_ctx(r); a = compute("approvals.pending", ctx)
    assert a.value == 4 and a.state == R.AVAILABLE and {p["module"]: p["count"] for p in a.breakdown} == {"Tasks": 1, "Expenses": 1, "Leave": 1, "Attendance corrections": 1}
    assert a.breakdown[0]["count"] == compute("tasks.pending_approval", ctx).value
    assert compute("leave.on_leave_today", ctx).value == 1


def test_approvals_partial_when_role_cannot_see_some_sources():
    r = SqliteReader(); seed_approvals(r); a = compute("approvals.pending", make_ctx(r, role="cto"))     # cto: tasks.read only among these
    assert a.state == R.PARTIAL and a.value == 1 and len(a.detail["unavailable_sources"]) == 3 and "Not included" in a.limitations[0]


# ---------- fleet / diagnostics / iot ----------
def seed_fleet(r):
    for i, reg in enumerate(("KA01AB1234", "KA01AB9999")): r.add("fleet_vehicles", id=f"v{i}", registration_number=reg, status="ACTIVE", archived=0, created_at=ago(90), updated_at=ago(1))
    f = lambda vid, code, sev, days, st="ACTIVE", ticket=None: r.add("diagnostic_faults", vehicle_id=vid, fault_code=code, severity=sev, detected_at=ago(days), status=st, ticket_id=ticket, created_at=ago(days))
    f("v0", "P0A80", "CRITICAL", 1); f("v0", "P0A80", "CRITICAL", 3); f("v0", "U0100", "LOW", 2, ticket="k1"); f("v1", "P0AA6", "HIGH", 2); f("v1", "P0A80", "LOW", 20, "RESOLVED")


def test_unlinked_and_repeated_faults():
    r = SqliteReader(); seed_fleet(r); ctx = make_ctx(r); u = compute("diagnostics.active_unlinked", ctx)
    assert u.value == 3 and u.detail["active_faults"] == 4 and u.detail["highest_severity"] == "CRITICAL" and u.breakdown[0]["severity"] == "CRITICAL" and "ticket_id" in u.limitations[0]
    rp = compute("diagnostics.repeated", ctx); assert rp.value == 1 and rp.breakdown[0]["occurrences"] == 2 and rp.breakdown[0]["fault_code"] == "P0A80"


def seed_devices(r):
    r.add("iot_devices", id="d1", device_identifier="DEV-001", vehicle_id="v0", offline_after_minutes=30, last_seen_at=AS_OF - timedelta(minutes=10))
    r.add("iot_devices", id="d2", device_identifier="DEV-002", vehicle_id="v1", offline_after_minutes=30, last_seen_at=AS_OF - timedelta(minutes=45))
    r.add("iot_devices", id="d3", device_identifier="DEV-003", offline_after_minutes=1440, last_seen_at=AS_OF - timedelta(hours=5))
    r.add("iot_devices", id="d4", device_identifier="DEV-004", last_seen_at=None); r.add("iot_devices", id="d5", device_identifier="DEV-005", last_seen_at=AS_OF - timedelta(days=9), archived=1)


def test_iot_offline_uses_each_devices_own_limit():
    r = SqliteReader(); seed_devices(r); c = compute("iot.connectivity", make_ctx(r))
    assert c.value == 1 and c.detail == {"active_devices": 4, "online": 2, "never_reported": 1} and c.breakdown[0]["device_identifier"] == "DEV-002" and c.breakdown[0]["minutes_since_seen"] == 45


def test_iot_threshold_alerts_none_configured_then_breach_and_precedence():
    r = SqliteReader(); seed_devices(r); assert compute("iot.threshold_alerts", make_ctx(r)).state == R.NO_THRESHOLD
    r.add("iot_thresholds", metric="battery_temp", severity="WARNING", min_value=None, max_value=45.0); r.add("iot_thresholds", metric="battery_temp", severity="CRITICAL", min_value=None, max_value=55.0)
    rd = lambda dev, m, v, mins: r.add("iot_readings", device_id=dev, metric=m, value=v, unit="C", recorded_at=AS_OF - timedelta(minutes=mins), received_at=AS_OF, vehicle_id="v0")
    rd("d1", "battery_temp", 58.0, 5); rd("d1", "battery_temp", 20.0, 60)          # latest reading is 58 -> CRITICAL (older normal reading ignored)
    rd("d2", "battery_temp", 47.0, 50); rd("d3", "battery_temp", 30.0, 5)          # d2 warning (stale: 50 min > 30), d3 fine
    a = compute("iot.threshold_alerts", make_ctx(r)); assert a.value == 2 and a.detail == {"critical": 1, "warning": 1, "stale_readings": 1}
    assert a.breakdown[0]["severity"] == "CRITICAL" and a.breakdown[0]["breach"] == "ABOVE_MAX"


def test_location_metrics_hidden_without_location_access():
    r = SqliteReader(); seed_devices(r); r.add("iot_thresholds", metric="gps_speed", severity="WARNING", min_value=None, max_value=80.0)
    r.add("iot_readings", device_id="d1", metric="gps_speed", value=120.0, unit="kmh", recorded_at=AS_OF - timedelta(minutes=2), received_at=AS_OF, vehicle_id="v0")
    assert compute("iot.threshold_alerts", make_ctx(r, role="ceo")).value == 1          # ceo holds location.read
    assert compute("iot.threshold_alerts", make_ctx(r, role="cto")).value == 0          # cto does not: location metric excluded, not shown


def test_anomaly_flagged_only_with_enough_history_else_not_enough_history():
    r = SqliteReader(); seed_devices(r)
    for i in range(10): r.add("iot_readings", device_id="d1", metric="voltage", value=48.0 + (i % 2), unit="V", recorded_at=AS_OF - timedelta(hours=2 + i), received_at=AS_OF)
    assert compute("iot.anomalies", make_ctx(r)).state == R.NOT_ENOUGH_HISTORY
    for i in range(10, 45): r.add("iot_readings", device_id="d1", metric="voltage", value=48.0 + (i % 2), unit="V", recorded_at=AS_OF - timedelta(hours=2 + i), received_at=AS_OF)
    r.add("iot_readings", device_id="d1", metric="voltage", value=12.0, unit="V", recorded_at=AS_OF - timedelta(minutes=5), received_at=AS_OF)
    a = compute("iot.anomalies", make_ctx(r)); assert a.state == R.AVAILABLE and a.value == 1 and a.breakdown[0]["metric"] == "voltage" and a.reliability == "statistical"
    assert a.threshold["label"].startswith("Statistical")


# ---------- trends ----------
def test_trend_blank_weeks_before_history_are_null_not_zero():
    r = SqliteReader(); tk(r, "a", created=20); tk(r, "b", created=5, resolved=2); t = compute("tickets.trend", make_ctx(r))
    assert t.state == R.PARTIAL and t.breakdown[0]["created"] is None and t.breakdown[0]["history"] is False and t.breakdown[-1]["created"] == 1 and t.breakdown[-1]["resolved"] == 1
    r2 = SqliteReader(); tk(r2, "x", created=3); assert compute("tickets.trend", make_ctx(r2)).state == R.NOT_ENOUGH_HISTORY


# ---------- registry guarantees ----------
def test_missing_tables_and_failures_are_unavailable_not_zero():
    r = SqliteReader(tables=["tasks"]); res = compute("tickets.open_backlog", make_ctx(r)); assert res.state == R.UNAVAILABLE and res.value is None and "migration" in res.message
    f = compute("tasks.overdue", make_ctx(F.FailingReader("timeout"))); assert f.state == R.UNAVAILABLE and f.value is None and "timed out" in f.message
    g = compute("tasks.overdue", make_ctx(F.FailingReader("query_failed"))); assert "psycopg" not in g.message and "select" not in g.message.lower()


def test_every_metric_on_an_empty_database_has_no_invented_value():
    r = SqliteReader(); ctx = make_ctx(r)
    for mid in REGISTRY:
        res = compute(mid, ctx); d = res.to_dict()
        assert res.state in R.STATES and (res.value is None or res.state in R.USABLE), mid
        assert res.state != R.AVAILABLE or mid.endswith(".flow") or mid == "approvals.pending", f"{mid} claims data on an empty database"


def test_each_number_is_computed_once_per_request():
    r = SqliteReader(); seed_tasks(r); ctx = make_ctx(r); a = compute("tasks.overdue", ctx); n = len(r.queries); b = compute("tasks.overdue", ctx)
    assert a is b and len(r.queries) == n


def test_metric_definitions_are_complete():
    for d in REGISTRY.values(): assert d.description and d.label and d.reliability in ("system_recorded", "user_entered", "derived", "statistical") and d.id.count(".") == 1
