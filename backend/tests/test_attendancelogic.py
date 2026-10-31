"""Pure-Python tests for attendance rules. Run `python tests/test_attendancelogic.py` or pytest."""
import os, sys
from datetime import date, datetime, time, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attendancelogic as A
IST = "Asia/Kolkata"
SHIFT = dict(start=time(9, 30), end=time(18, 30), grace_minutes=10, timezone=IST, working_days=[1, 2, 3, 4, 5])
def ist(y, m, d, h, mi): return A.combine(date(y, m, d), time(h, mi), IST)
def err(fn, *a, **k):
    try: fn(*a, **k)
    except A.AttendanceError as e: return e.status
    return None

def test_work_date_uses_timezone():
    t = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)      # 01:30 next day in IST
    assert A.work_date(t, IST) == date(2026, 10, 27) and A.work_date(t, "UTC") == date(2026, 10, 26)
def test_naive_and_unknown_tz_rejected():
    assert err(A.local, datetime(2026, 1, 1), IST) == 500 and err(A.tzinfo, "Mars/Base") == 422
def test_late_with_grace():
    assert A.classify(ist(2026, 10, 26, 9, 40), None, SHIFT)["late_minutes"] == 0      # exactly at grace limit: not late
    assert A.classify(ist(2026, 10, 26, 9, 41), None, SHIFT)["late_minutes"] == 11     # counted from shift start
    assert A.classify(ist(2026, 10, 26, 9, 0), None, SHIFT)["late_minutes"] == 0
def test_early_and_worked():
    c = A.classify(ist(2026, 10, 26, 9, 30), ist(2026, 10, 26, 17, 30), SHIFT)
    assert c == {"late_minutes": 0, "early_minutes": 60, "worked_minutes": 480}
    assert A.classify(ist(2026, 10, 26, 9, 30), ist(2026, 10, 26, 19, 0), SHIFT)["early_minutes"] == 0
def test_checkout_before_checkin_rejected():
    assert err(A.classify, ist(2026, 10, 26, 10, 0), ist(2026, 10, 26, 9, 0), SHIFT) == 422
def test_shift_validation():
    ok = (time(9), time(17), 5, IST, [1, 2, 3])
    assert err(A.validate_shift, *ok) is None
    assert err(A.validate_shift, time(17), time(9), 5, IST, [1]) == 422 and err(A.validate_shift, time(9), time(17), 999, IST, [1]) == 422
    assert err(A.validate_shift, time(9), time(17), 5, IST, []) == 422 and err(A.validate_shift, time(9), time(17), 5, IST, [8]) == 422
    assert err(A.validate_shift, time(9), time(17), 5, IST, [1, 1]) == 422 and err(A.validate_shift, time(9), time(17), 5, "Nope/Zone", [1]) == 422
def test_working_day(): assert A.is_working_day(date(2026, 10, 26), [1, 2, 3, 4, 5]) and not A.is_working_day(date(2026, 10, 25), [1, 2, 3, 4, 5])   # Mon / Sun
def test_correction_validation():
    t = date(2026, 10, 26); a, b = ist(2026, 10, 20, 9, 0), ist(2026, 10, 20, 18, 0)
    assert err(A.validate_correction, date(2026, 10, 20), a, b, "forgot to punch", t) is None
    assert err(A.validate_correction, date(2026, 10, 27), a, b, "forgot to punch", t) == 422
    assert err(A.validate_correction, date(2026, 10, 20), None, None, "forgot to punch", t) == 422
    assert err(A.validate_correction, date(2026, 10, 20), b, a, "forgot to punch", t) == 422
    assert err(A.validate_correction, date(2026, 10, 20), a, b, "  hi ", t) == 422
def test_decide_rules():
    assert err(A.can_decide_correction, "m", "e", "pending") is None
    assert err(A.can_decide_correction, "e", "e", "pending") == 403 and err(A.can_decide_correction, "m", "e", "approved") == 409
def test_monthly_summary():
    today = date(2026, 10, 15)   # Thu. Oct 2026: 1st is Thu
    recs = [dict(work_date=date(2026, 10, 1), check_in=ist(2026, 10, 1, 9, 30), check_out=ist(2026, 10, 1, 18, 30)),
            dict(work_date=date(2026, 10, 2), check_in=ist(2026, 10, 2, 10, 0), check_out=ist(2026, 10, 2, 17, 0)),       # late 30, early 90
            dict(work_date=date(2026, 10, 5), check_in=ist(2026, 10, 5, 9, 0), check_out=None),                            # missing checkout
            dict(work_date=date(2026, 10, 15), check_in=ist(2026, 10, 15, 9, 0), check_out=None)]                          # today, still open: fine
    s = A.monthly_summary(recs, 2026, 10, SHIFT, today)
    # working days 1,2,5,6,7,8,9,12,13,14,15 = 11; present 4; no record 7 (6,7,8,9,12,13,14)
    assert s == dict(working_days_elapsed=11, days_present=4, late_days=1, early_departure_days=1, missing_checkout_days=1, no_record_days=7, worked_minutes=540 + 420, leave_days=0, holiday_days=0)
def test_summary_excludes_holidays_and_leave():
    from decimal import Decimal as D
    today = date(2026, 10, 15)
    recs = [dict(work_date=date(2026, 10, 1), check_in=ist(2026, 10, 1, 9, 30), check_out=ist(2026, 10, 1, 18, 30))]
    s = A.monthly_summary(recs, 2026, 10, SHIFT, today, holidays={date(2026, 10, 2)}, leave_days={date(2026, 10, 5): D(1), date(2026, 10, 6): D("0.5")})
    # expected days: 1,(2 hol),(5 leave),6(half leave still expected),7,8,9,12,13,14,15 -> elapsed counts 1 + 6,7,8,9,12,13,14 = 8; no_record 7
    assert s["holiday_days"] == 1 and s["leave_days"] == 1.5 and s["no_record_days"] == 7 and s["working_days_elapsed"] == 8 and s["days_present"] == 1
def test_bad_month(): assert err(lambda: list(A.month_days(2026, 13))) == 422

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); n += 1; print("PASS", k)
    print(n, "passed")
