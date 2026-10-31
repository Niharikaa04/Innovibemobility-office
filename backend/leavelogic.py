"""Pure-Python leave rules (no third-party imports, no database). No entitlement, notice or limit is invented: every number comes from
a leave type that an administrator configured. A request may not span two calendar years (balances are per calendar year; no carry-forward yet).
Days = working days in the range (per the attendance working-days setting) minus company holidays; a half day counts 0.5 (single day only)."""
from datetime import date, timedelta
from decimal import Decimal

HALF = Decimal("0.5"); ONE = Decimal("1")
STATUSES = ("pending", "approved", "rejected", "cancelled")

class LeaveError(Exception):
    def __init__(self, status: int, message: str): super().__init__(message); self.status, self.message = status, message

def daterange(a: date, b: date):
    d = a
    while d <= b: yield d; d += timedelta(days=1)

def count_days(start: date, end: date, working_days, holidays, half_day=None) -> Decimal:
    if end < start: raise LeaveError(422, "End date cannot be before start date.")
    if half_day is not None:
        if start != end: raise LeaveError(422, "A half day can only be requested for a single date.")
        if half_day not in ("first_half", "second_half"): raise LeaveError(422, "Half day must be first_half or second_half.")
    wd, hol = set(working_days), set(holidays)
    n = sum(1 for d in daterange(start, end) if d.isoweekday() in wd and d not in hol)
    if n == 0: raise LeaveError(422, "That range has no working days (weekends and holidays are not counted).")
    return HALF if half_day is not None else Decimal(n)

def validate_request(start: date, end: date, today: date, reason: str, t: dict, half_day=None) -> None:
    """t: leave type config: allow_half_day, min_notice_days, allow_backdated_days, max_consecutive_days (None = no limit), is_active."""
    if not t["is_active"]: raise LeaveError(422, "This leave type is not active.")
    if start.year != end.year: raise LeaveError(422, "Split a request that crosses a year end into two requests.")
    if len((reason or "").strip()) < 3: raise LeaveError(422, "Please give a reason.")
    if half_day is not None and not t["allow_half_day"]: raise LeaveError(422, "This leave type does not allow half days.")
    if start < today - timedelta(days=t["allow_backdated_days"]): raise LeaveError(422, f"This leave type cannot be requested more than {t['allow_backdated_days']} day(s) in the past.")
    if start >= today and (start - today).days < t["min_notice_days"]: raise LeaveError(422, f"This leave type needs at least {t['min_notice_days']} day(s) notice.")

def check_length(days: Decimal, t: dict) -> None:
    m = t.get("max_consecutive_days")
    if m is not None and days > m: raise LeaveError(422, f"This leave type allows at most {m} day(s) per request.")

def balance(entitlement, approved_days, pending_days) -> dict:
    """entitlement None = no cap tracked (e.g. unpaid leave). available is None in that case."""
    a, p = Decimal(approved_days), Decimal(pending_days)
    return {"entitlement": None if entitlement is None else Decimal(entitlement), "used": a, "pending": p,
            "available": None if entitlement is None else Decimal(entitlement) - a - p}

def check_balance(days: Decimal, bal: dict) -> None:
    if bal["available"] is not None and days > bal["available"]:
        raise LeaveError(409, f"Not enough balance: {days} day(s) requested, {bal['available']} available.")

def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool: return a_start <= b_end and b_start <= a_end

def can_decide(approver_id: str, requester_id: str, status: str) -> None:
    if status != "pending": raise LeaveError(409, "This request has already been decided.")
    if approver_id == requester_id: raise LeaveError(403, "You cannot decide your own leave request.")

def can_cancel(status: str, start: date, today: date, is_owner: bool, is_approver: bool) -> None:
    """Owner: pending any time, approved only before it starts. Approver (not owner): approved any time (a correction), needs a note upstream."""
    if status not in ("pending", "approved"): raise LeaveError(409, "Only pending or approved requests can be cancelled.")
    if is_owner and (status == "pending" or start > today): return
    if is_approver and status == "approved": return
    raise LeaveError(403, "You cannot cancel this request." if not is_owner else "Leave that has already started can only be cancelled by HR.")

def leave_day_map(requests, year: int, month: int, working_days, holidays) -> dict:
    """APPROVED requests only -> {date: Decimal} for dates in the month that are working days and not holidays (0.5 for half days)."""
    out, wd, hol = {}, set(working_days), set(holidays)
    for r in requests:
        for d in daterange(r["start_date"], r["end_date"]):
            if d.year == year and d.month == month and d.isoweekday() in wd and d not in hol:
                out[d] = out.get(d, Decimal(0)) + (HALF if r.get("half_day") else ONE)
    return {d: min(v, ONE) for d, v in out.items()}
