"""Performance work must not cost correctness or isolation: shared metric memo across endpoints."""
import json
import intel_fixtures as F
from intelligence.guard import TTLCache
from intelligence import results as R
import test_intel_security as TS
from test_intel_security import svc, seeded, CEO, CTO

COO = {"id": "u-coo", "role": "coo"}
Q = "What is delayed right now?"


def count(r): return len(r.queries)


def test_second_endpoint_reuses_the_first_endpoints_calculations():
    r = seeded(); s, _, _ = svc(r)
    s.overview(CEO); after_overview = count(r)
    s.alerts(CEO); s.insights(CEO); s.ask(CEO, "What needs my attention today?"); s.ask(CEO, Q)
    assert count(r) == after_overview, "alerts/insights/ask re-ran queries that overview had already run"


def test_shared_memo_is_per_user_so_nothing_crosses_users():
    r = seeded(); s, _, _ = svc(r)
    s.overview(CEO); n = count(r)
    s.overview({"id": "someone-else", "role": "ceo"})
    assert count(r) > n, "a different user must trigger their own calculation (key includes the user id)"


def test_shared_memo_is_per_role_so_permission_results_never_cross_roles():
    r = seeded(); s, _, _ = svc(r)
    ceo = s.ask(CEO, Q); cto = s.ask(CTO, Q); again = s.ask(CEO, Q)
    assert "No permission" in " ".join(x["text"] for x in cto["statements"]) and "Acme" not in json.dumps(cto)
    assert ceo["statements"] == again["statements"] and ceo["statements"] != cto["statements"]
    inv = next(x for x in cto["sources"] if x["metric_id"] == "invoices.receivables"); assert inv["state"] == R.NO_PERMISSION and inv["evidence"] == []


def test_shared_memo_is_per_period():
    r = seeded(); s, _, _ = svc(r)
    s.overview(CEO, "wow"); n = count(r); s.overview(CEO, "last_30d"); assert count(r) > n


def test_memo_expires_after_the_ttl_so_fresh_data_is_picked_up():
    r = seeded(); t = [0.0]; s, _, _ = svc(r); s.memos = TTLCache(30, clock=lambda: t[0]); s.cache = TTLCache(30, clock=lambda: t[0])
    s.overview(CEO); n = count(r); s.alerts(CEO); assert count(r) == n
    t[0] = 31; s.alerts(CEO); assert count(r) > n, "after the TTL the metrics must be recalculated from the database"


def test_a_failed_metric_is_not_replayed_from_the_shared_memo():
    bad = F.FailingReader("timeout"); good = seeded(); cur = {"r": bad}
    s, _, _ = svc(); s.reader_factory = lambda: cur["r"]
    first = s.ask(CEO, Q); assert all(x["kind"] == "unavailable" for x in first["statements"])
    cur["r"] = good; s.cache = TTLCache(30)
    second = s.ask(CEO, Q); assert any(x["kind"] != "unavailable" for x in second["statements"]), "a transient failure was replayed from the memo instead of retried"


def test_answers_still_match_the_metric_endpoint_after_sharing():
    r = seeded(); s, _, _ = svc(r)
    body = s.ask(CEO, Q); v = s.metric(CEO, "tickets.overdue")["metric"]["value"]
    assert f"{v} open service ticket" in " ".join(x["text"] for x in body["statements"])
