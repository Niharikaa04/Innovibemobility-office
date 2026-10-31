"""Pure-logic tests: periods, ageing buckets, workload facts, percentage change, anomaly screen."""
from datetime import date
import intel_fixtures as F
from intelligence import analytics as A
from intelligence import periods as P


def test_wow_windows():
    cur, prev = P.resolve("wow", date(2026, 10, 30))
    assert (cur.start, cur.end) == (date(2026, 10, 24), date(2026, 10, 30)) and cur.days == 7
    assert (prev.start, prev.end) == (date(2026, 10, 17), date(2026, 10, 23))


def test_mom_compares_same_elapsed_days_and_clamps_short_months():
    cur, prev = P.resolve("mom", date(2026, 10, 30)); assert (prev.start, prev.end) == (date(2026, 9, 1), date(2026, 9, 30))
    cur, prev = P.resolve("mom", date(2026, 3, 31)); assert (prev.start, prev.end) == (date(2026, 2, 1), date(2026, 2, 28))   # Feb has 28 days
    cur, prev = P.resolve("mom", date(2026, 1, 15)); assert (prev.start, prev.end) == (date(2025, 12, 1), date(2025, 12, 15))


def test_previous_period_is_adjacent_and_same_length():
    cur, prev = P.custom(date(2026, 10, 10), date(2026, 10, 19)); assert prev.end == date(2026, 10, 9) and prev.days == cur.days == 10


def test_period_validation():
    with F.raises(P.PeriodError): P.Period(date(2026, 10, 5), date(2026, 10, 1))
    with F.raises(P.PeriodError): P.Period(date(2025, 1, 1), date(2026, 10, 1))
    with F.raises(P.PeriodError): P.resolve("yearly", date(2026, 10, 1))
    P.Period(date(2025, 10, 30), date(2026, 10, 30))            # 366 days exactly is allowed


def test_pct_change_never_divides_by_zero():
    assert A.pct_change(15, 10) == 50.0 and A.pct_change(5, 10) == -50.0
    assert A.pct_change(5, 0) is None and A.pct_change(None, 3) is None


def test_ageing_buckets_sum_to_total_and_reject_bad_input():
    assert A.bucket_ageing([1, 3, 4, 6], 10) == [1, 2, 1, 2, 4] and sum(A.bucket_ageing([0, 0, 0, 0], 5)) == 5
    with F.raises(ValueError): A.bucket_ageing([3, 2, 4, 6], 10)


def test_workload_distribution_states_facts_only():
    d = A.workload_distribution({"a": 8, "b": 1, "c": 1}); assert d["max_owner"] == "a" and d["max_share_pct"] == 80.0 and d["mean"] == 3.33
    assert A.workload_distribution({}) == {"owners": 0}
    assert "threshold" not in d and "overloaded" not in d


def test_anomaly_needs_history_and_spread():
    base = [10.0 + (i % 3) for i in range(40)]
    assert A.detect_anomaly(base[:29], 11)["state"] == "not_enough_history"
    assert A.detect_anomaly([5.0] * 40, 9.0)["state"] == "not_computable"           # zero spread: no z-score is invented
    assert A.detect_anomaly(base, 11.0)["state"] == "normal"
    r = A.detect_anomaly(base, 30.0); assert r["state"] == "anomalous" and r["modified_z"] > A.MODIFIED_Z_CUTOFF and r["cutoff"] == 3.5


def test_anomaly_uses_meanad_fallback_when_mad_is_zero():
    coarse = [48.0 if i % 2 == 0 else 49.0 for i in range(45)]            # median 48, MAD 0
    assert A.detect_anomaly(coarse, 12.0)["state"] == "anomalous" and A.detect_anomaly(coarse, 49.0)["state"] == "normal"


def test_to_dt_and_date_parsing():
    assert A.to_dt("2026-10-30T12:00:00+00:00").hour == 12 and A.to_dt("2026-10-30").tzinfo is not None and A.to_dt(None) is None
    assert A.to_date("2026-10-30T23:59:00+00:00") == date(2026, 10, 30)
