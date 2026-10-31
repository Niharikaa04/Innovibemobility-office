"""Pure-Python attendance rules (no third-party imports, no database). The API calls these; tests run without any server.
Nothing here invents policy: the shift (start, end, grace, timezone, working days) is CONFIGURED by an administrator.
Until it is configured the API refuses check-in, because the calendar date of a check-in depends on the timezone.
Definitions (shown to users): late = checked in after shift start + grace; late minutes are counted from shift start.
Early departure = checked out before shift end. Overnight shifts are not supported (end must be after start).
Days with no record are 'no_record_days' (absent without leave): approved leave and company holidays (db/008) are excluded when provided."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class AttendanceError(Exception):
    def __init__(self, status: int, message: str): super().__init__(message); self.status, self.message = status, message

def tzinfo(name: str):
    try: return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError): raise AttendanceError(422, "Unknown timezone.")

def local(ts: datetime, tzname: str) -> datetime:
    if ts.tzinfo is None: raise AttendanceError(500, "Timestamps must be timezone-aware.")
    return ts.astimezone(tzinfo(tzname))

def work_date(ts: datetime, tzname: str) -> date: return local(ts, tzname).date()

def combine(d: date, t: time, tzname: str) -> datetime:
    return datetime.combine(d, t.replace(tzinfo=None), tzinfo=tzinfo(tzname)).astimezone(timezone.utc)

def validate_shift(start: time, end: time, grace_minutes: int, tzname: str, working_days) -> None:
    tzinfo(tzname)
    if end <= start: raise AttendanceError(422, "Shift end must be after shift start (overnight shifts are not supported).")
    if not (0 <= grace_minutes <= 240): raise AttendanceError(422, "Grace period must be between 0 and 240 minutes.")
    days = list(working_days)
    if not days or any((not isinstance(x, int)) or x < 1 or x > 7 for x in days) or len(set(days)) != len(days):
        raise AttendanceError(422, "Working days must be unique numbers 1 (Monday) to 7 (Sunday), at least one.")

def is_working_day(d: date, working_days) -> bool: return d.isoweekday() in set(working_days)

def classify(check_in: datetime, check_out, shift: dict) -> dict:
    """shift: start, end (datetime.time), grace_minutes, timezone. Returns late/early/worked minutes."""
    tz = shift["timezone"]; li = local(check_in, tz); d = li.date()
    start = datetime.combine(d, shift["start"], tzinfo=li.tzinfo); end = datetime.combine(d, shift["end"], tzinfo=li.tzinfo)
    late = 0 if li <= start + timedelta(minutes=shift["grace_minutes"]) else int((li - start).total_seconds() // 60)
    early = worked = None
    if check_out is not None:
        if check_out <= check_in: raise AttendanceError(422, "Check-out must be after check-in.")
        lo = local(check_out, tz); early = max(0, int((end - lo).total_seconds() // 60)); worked = int((check_out - check_in).total_seconds() // 60)
    return {"late_minutes": late, "early_minutes": early, "worked_minutes": worked}

def validate_correction(d: date, ci, co, reason: str, today: date) -> None:
    if d > today: raise AttendanceError(422, "You cannot correct a future date.")
    if ci is None and co is None: raise AttendanceError(422, "Give a corrected check-in, check-out, or both.")
    if ci is not None and co is not None and co <= ci: raise AttendanceError(422, "Corrected check-out must be after check-in.")
    if len((reason or "").strip()) < 5: raise AttendanceError(422, "Please give a reason (at least 5 characters).")

def month_days(year: int, month: int):
    if not (1 <= month <= 12): raise AttendanceError(422, "Month must be 1-12.")
    d = date(year, month, 1)
    while d.month == month: yield d; d += timedelta(days=1)

def monthly_summary(records, year: int, month: int, shift: dict, today: date, holidays=(), leave_days=None) -> dict:
    """records: [{work_date, check_in, check_out}] for ONE person. Counts only days up to today (today counts only if a record exists).
    holidays: set of dates. leave_days: {date: Decimal} of APPROVED leave (>=1 means a full day off). A working day is 'expected' unless it is a
    holiday or full-day leave; an expected day with no record before today is no_record_days (i.e. absent without leave)."""
    by = {r["work_date"]: r for r in records}; wd = shift["working_days"]; hol = set(holidays); lv = leave_days or {}
    out = dict(working_days_elapsed=0, days_present=0, late_days=0, early_departure_days=0, missing_checkout_days=0, no_record_days=0, worked_minutes=0,
               leave_days=0, holiday_days=0)
    for d in month_days(year, month):
        working = is_working_day(d, wd); full_leave = lv.get(d, 0) >= 1; expected = working and d not in hol and not full_leave
        if working and d <= today:
            if d in hol: out["holiday_days"] += 1
            elif lv.get(d): out["leave_days"] += float(lv[d])
        r = by.get(d)
        if r is None:
            if d < today and expected: out["working_days_elapsed"] += 1; out["no_record_days"] += 1
            continue
        if expected and d <= today: out["working_days_elapsed"] += 1
        out["days_present"] += 1
        c = classify(r["check_in"], r["check_out"], shift)
        if c["late_minutes"] > 0: out["late_days"] += 1
        if r["check_out"] is None:
            if d < today: out["missing_checkout_days"] += 1
        else:
            if c["early_minutes"] > 0: out["early_departure_days"] += 1
            out["worked_minutes"] += c["worked_minutes"]
    return out

def can_decide_correction(approver_id: str, requester_id: str, status: str) -> None:
    if status != "pending": raise AttendanceError(409, "This request has already been decided.")
    if approver_id == requester_id: raise AttendanceError(403, "You cannot decide your own correction request.")
