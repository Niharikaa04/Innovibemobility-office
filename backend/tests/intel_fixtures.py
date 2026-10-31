"""Test support for the intelligence package (not a test module). SqliteReader implements the Reader protocol on an in-memory SQLite
database attached under the name `office_dashboard`, so the exact SQL text the metrics send can be executed without PostgreSQL.
It proves the logic and the portable SQL; it does NOT prove PostgreSQL dialect behaviour (see docs/INTELLIGENCE.md, test results)."""
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from intelligence.periods import Period, previous_period
from intelligence.registry import Ctx

AS_OF = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 30)

DDL = """
create table office_dashboard.tasks(id text primary key, title text, assignee_id text, created_by text, status text, priority text, due_date text, requires_approval int default 0, approver_id text, completed_at text, is_archived int default 0, created_at text, updated_at text);
create table office_dashboard.service_tickets(id text primary key, ticket_number text, priority text, status text, assigned_to text, assigned_name text, archived int default 0, created_at text, updated_at text, due_date text, resolved_at text, service_center_id text);
create table office_dashboard.service_centers(id text primary key, name text, archived int default 0, created_at text, updated_at text);
create table office_dashboard.leads(id text primary key, stage text, value real, next_follow_up text, is_archived int default 0, created_at text, updated_at text, converted_at text);
create table office_dashboard.expenses(id text primary key, category text, amount real, expense_date text, status text, archived int default 0, created_at text, updated_at text);
create table office_dashboard.leave_requests(id text primary key, status text, start_date text, end_date text, created_at text);
create table office_dashboard.attendance_config(id int primary key, timezone text);
create table office_dashboard.attendance_records(id text primary key, user_id text, work_date text, check_out text, created_at text, updated_at text);
create table office_dashboard.attendance_corrections(id text primary key, status text, created_at text);
create table office_dashboard.invoices(id text primary key, customer_name text, total_amount real, due_date text, issue_date text, status text, archived int default 0, created_at text, updated_at text);
create table office_dashboard.invoice_payments(id text primary key, invoice_id text, amount real, voided int default 0);
create table office_dashboard.budgets(id text primary key, kind text, category text, period_month text, amount real, created_at text, updated_at text);
create table office_dashboard.fleet_vehicles(id text primary key, registration_number text, status text, archived int default 0, created_at text, updated_at text);
create table office_dashboard.diagnostic_faults(id integer primary key autoincrement, vehicle_id text, fault_code text, severity text, detected_at text, status text, ticket_id text, created_at text);
create table office_dashboard.iot_devices(id text primary key, device_identifier text, vehicle_id text, status text default 'ACTIVE', offline_after_minutes int default 30, last_seen_at text, archived int default 0);
create table office_dashboard.iot_readings(id integer primary key autoincrement, device_id text, metric text, value real, unit text, recorded_at text, received_at text, vehicle_id text);
create table office_dashboard.iot_thresholds(id integer primary key autoincrement, metric text, severity text, min_value real, max_value real);
create table office_dashboard.module_records(id text primary key, module text, archived int default 0, created_at text, updated_at text);
"""
ALL_TABLES = [l.split("office_dashboard.")[1].split("(")[0] for l in DDL.strip().split("\n")]


def adapt(v):
    if isinstance(v, (datetime, date)): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, bool): return int(v)
    return v


class SqliteReader:
    def __init__(self, tables=None):
        self.c = sqlite3.connect(":memory:"); self.c.row_factory = sqlite3.Row; self.c.execute("attach database ':memory:' as office_dashboard")
        for stmt in DDL.strip().split("\n"):
            if tables is None or stmt.split("office_dashboard.")[1].split("(")[0] in tables: self.c.execute(stmt)
        self.queries = []
    def rows(self, sql, params=()):
        self.queries.append(sql)
        assert sql.lstrip().lower().startswith("select"), "intelligence queries must be SELECT only"
        return [dict(r) for r in self.c.execute(sql.replace("%s", "?"), [adapt(p) for p in params]).fetchmany(5001)]
    def has_table(self, name): return bool(self.c.execute("select 1 from office_dashboard.sqlite_master where type='table' and name=?", (name,)).fetchone())
    def close(self): pass      # keep the in-memory db alive between requests in tests
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def add(self, table, **cols):
        keys = list(cols); self.c.execute(f"insert into office_dashboard.{table}({','.join(keys)}) values({','.join('?' * len(keys))})", [adapt(cols[k]) for k in keys])


def ago(days=0, hours=0): return AS_OF - timedelta(days=days, hours=hours)


def make_ctx(reader, role="ceo", period=None, prev=True, **kw):
    period = period or Period(TODAY - timedelta(days=6), TODAY, "last 7 days")
    return Ctx(reader=reader, role=role, user_id="u-1", period=period, prev=(previous_period(period) if prev else None), today=TODAY, as_of=AS_OF, **kw)


from contextlib import contextmanager


@contextmanager
def raises(exc, contains=""):
    """Runner-agnostic replacement for pytest.raises (tests also run under plain pytest)."""
    try: yield
    except exc as e:
        assert contains in str(e), f"{contains!r} not in {e!s}"; return
    raise AssertionError(f"{exc.__name__} not raised")


class FakeAudit:
    def __init__(self): self.events = []
    def write(self, action, user_id=None, ip=None, **detail): self.events.append({"action": action, "user": user_id, "ip": ip, **detail})


class FailingReader:
    """Reader whose every call fails the way the real one does."""
    def __init__(self, kind="query_failed"): self.kind = kind
    def rows(self, sql, params=()):
        from intelligence.reader import ReaderError; raise ReaderError(self.kind)
    has_table = rows
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
