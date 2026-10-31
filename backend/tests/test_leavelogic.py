"""Pure-Python tests for leave rules. Run `python tests/test_leavelogic.py` or pytest."""
import os, sys
from datetime import date
from decimal import Decimal as D
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import leavelogic as L
WD = [1, 2, 3, 4, 5]
T = dict(is_active=True, allow_half_day=True, min_notice_days=2, allow_backdated_days=0, max_consecutive_days=5)
def err(fn, *a, **k):
    try: fn(*a, **k)
    except L.LeaveError as e: return e.status
    return None

def test_count_skips_weekends_and_holidays():
    assert L.count_days(date(2026, 10, 26), date(2026, 10, 30), WD, set()) == D(5)                       # Mon-Fri
    assert L.count_days(date(2026, 10, 26), date(2026, 11, 2), WD, set()) == D(6)                        # Mon..next Mon
    assert L.count_days(date(2026, 10, 26), date(2026, 10, 30), WD, {date(2026, 10, 28)}) == D(4)
def test_no_working_days_rejected():
    assert err(L.count_days, date(2026, 10, 24), date(2026, 10, 25), WD, set()) == 422                    # Sat-Sun
    assert err(L.count_days, date(2026, 10, 28), date(2026, 10, 28), WD, {date(2026, 10, 28)}) == 422
def test_half_day():
    assert L.count_days(date(2026, 10, 26), date(2026, 10, 26), WD, set(), "first_half") == D("0.5")
    assert err(L.count_days, date(2026, 10, 26), date(2026, 10, 27), WD, set(), "first_half") == 422
    assert err(L.count_days, date(2026, 10, 26), date(2026, 10, 26), WD, set(), "noon") == 422
    assert err(L.count_days, date(2026, 10, 27), date(2026, 10, 26), WD, set()) == 422
def test_validate_request():
    today = date(2026, 10, 26)
    assert err(L.validate_request, date(2026, 10, 28), date(2026, 10, 29), today, "family event", T) is None
    assert err(L.validate_request, date(2026, 10, 27), date(2026, 10, 27), today, "family event", T) == 422        # notice 2 days
    assert err(L.validate_request, date(2026, 10, 20), date(2026, 10, 20), today, "family event", T) == 422        # backdated
    assert err(L.validate_request, date(2026, 10, 20), date(2026, 10, 20), today, "sick", {**T, "allow_backdated_days": 7, "min_notice_days": 0}) is None
    assert err(L.validate_request, date(2026, 12, 30), date(2027, 1, 2), today, "trip", T) == 422                   # crosses year
    assert err(L.validate_request, date(2026, 10, 28), date(2026, 10, 28), today, " ", T) == 422
    assert err(L.validate_request, date(2026, 10, 28), date(2026, 10, 28), today, "ok", {**T, "is_active": False}) == 422
    assert err(L.validate_request, date(2026, 10, 28), date(2026, 10, 28), today, "ok", {**T, "allow_half_day": False}, "first_half") == 422
def test_max_length():
    assert err(L.check_length, D(5), T) is None and err(L.check_length, D(6), T) == 422 and err(L.check_length, D(99), {**T, "max_consecutive_days": None}) is None
def test_balance():
    b = L.balance("12", "3", "2"); assert b["available"] == D(7) and b["used"] == D(3) and b["pending"] == D(2)
    assert err(L.check_balance, D(7), b) is None and err(L.check_balance, D("7.5"), b) == 409
    u = L.balance(None, "30", "0"); assert u["available"] is None and err(L.check_balance, D(100), u) is None      # uncapped type
def test_overlap():
    a, b = date(2026, 10, 1), date(2026, 10, 5)
    assert L.overlaps(a, b, date(2026, 10, 5), date(2026, 10, 9)) and not L.overlaps(a, b, date(2026, 10, 6), date(2026, 10, 9)) and L.overlaps(a, b, date(2026, 9, 1), date(2026, 12, 1))
def test_decide_and_cancel_rules():
    assert err(L.can_decide, "hr", "emp", "pending") is None and err(L.can_decide, "emp", "emp", "pending") == 403 and err(L.can_decide, "hr", "emp", "approved") == 409
    t = date(2026, 10, 26)
    assert err(L.can_cancel, "pending", date(2026, 10, 1), t, True, False) is None            # owner, pending, even if started
    assert err(L.can_cancel, "approved", date(2026, 11, 1), t, True, False) is None            # owner, future approved
    assert err(L.can_cancel, "approved", date(2026, 10, 20), t, True, False) == 403            # owner, already started
    assert err(L.can_cancel, "approved", date(2026, 10, 20), t, False, True) is None           # approver correction
    assert err(L.can_cancel, "approved", date(2026, 11, 1), t, False, False) == 403
    assert err(L.can_cancel, "rejected", date(2026, 11, 1), t, True, True) == 409
def test_leave_day_map():
    reqs = [dict(start_date=date(2026, 10, 26), end_date=date(2026, 10, 30), half_day=None), dict(start_date=date(2026, 10, 27), end_date=date(2026, 10, 27), half_day="first_half"),
            dict(start_date=date(2026, 10, 30), end_date=date(2026, 11, 3), half_day=None)]
    m = L.leave_day_map(reqs, 2026, 10, WD, {date(2026, 10, 28)})
    assert date(2026, 10, 28) not in m and m[date(2026, 10, 26)] == D(1) and m[date(2026, 10, 27)] == D(1) and m[date(2026, 10, 30)] == D(1)   # overlaps capped at 1
    assert date(2026, 11, 2) not in m                                                                                                         # other month
if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); n += 1; print("PASS", k)
    print(n, "passed")
