"""Reporting periods. Pure Python. A Period is a closed date range [start, end] (both inclusive).
Timestamp metrics use UTC day boundaries; due-date metrics use the server's local `today` exactly like ticketapi/finance."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import calendar

MAX_RANGE_DAYS = 366
KINDS = ("last_7d", "last_30d", "wow", "mom")   # wow = last 7 days vs the 7 before; mom = month-to-date vs the same elapsed days of last month


class PeriodError(ValueError): pass


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str = ""

    def __post_init__(self):
        if self.start > self.end: raise PeriodError("Start date must be on or before end date.")
        if (self.end - self.start).days + 1 > MAX_RANGE_DAYS: raise PeriodError(f"Date range may not exceed {MAX_RANGE_DAYS} days.")

    @property
    def days(self) -> int: return (self.end - self.start).days + 1
    @property
    def start_dt(self) -> datetime: return datetime.combine(self.start, time.min, tzinfo=timezone.utc)
    @property
    def end_dt_exclusive(self) -> datetime: return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    def to_dict(self) -> dict: return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days, "label": self.label}


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n; y = d.year + m // 12; m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_start(d: date) -> date: return d.replace(day=1)


def previous_period(p: Period) -> Period:
    """Immediately preceding window of the same length."""
    end = p.start - timedelta(days=1)
    return Period(end - timedelta(days=p.days - 1), end, "previous period")


def resolve(kind: str, today: date):
    """-> (current, previous) for a named comparison. Raises PeriodError for unknown kinds."""
    if kind == "last_7d":
        cur = Period(today - timedelta(days=6), today, "last 7 days")
    elif kind == "last_30d":
        cur = Period(today - timedelta(days=29), today, "last 30 days")
    elif kind == "wow":
        cur = Period(today - timedelta(days=6), today, "last 7 days"); return cur, Period(cur.start - timedelta(days=7), cur.start - timedelta(days=1), "previous 7 days")
    elif kind == "mom":
        cur = Period(month_start(today), today, "month to date")
        pm = _add_months(month_start(today), -1); last = calendar.monthrange(pm.year, pm.month)[1]
        return cur, Period(pm, pm.replace(day=min(today.day, last)), "same days of previous month")
    else:
        raise PeriodError(f"Unknown period kind. Use one of {', '.join(KINDS)}.")
    return cur, previous_period(cur)


def custom(date_from: date, date_to: date):
    cur = Period(date_from, date_to, "selected period"); return cur, previous_period(cur)
