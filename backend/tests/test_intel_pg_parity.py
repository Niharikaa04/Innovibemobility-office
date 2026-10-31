"""PostgreSQL dialect + parity test for the intelligence layer.

The metric tests run on SQLite (fast, no server). That proves the logic but NOT that the same SQL text is valid PostgreSQL. This module creates
the metric source tables with real PostgreSQL types in a DISPOSABLE server (pgserver, never your database), loads the SAME seed data the SQLite
tests use, runs EVERY registered metric through the production PgReader (read-only transaction, statement timeout) and requires:
  1. no metric ends UNAVAILABLE because of a query error, and
  2. state and value are identical to the SQLite run on the same data.
The tables are a faithful column subset (names/types inferred from the columns the metrics read), not your production DDL. Skipped without pgserver."""
import re
from datetime import date, datetime
from decimal import Decimal

import pytest

pgserver = pytest.importorskip("pgserver")
import psycopg  # noqa: E402

import intel_fixtures as F  # noqa: E402
import test_intel_metrics as TM  # noqa: E402
from intelligence import results as R  # noqa: E402
from intelligence.reader import PgReader  # noqa: E402
from intelligence.registry import REGISTRY, compute  # noqa: E402

BOOL = re.compile(r"^(archived|is_archived|voided|requires_approval)$")
TS = re.compile(r"(_at)$")
DT = re.compile(r"(due_date|next_follow_up|period_month|work_date|start_date|end_date|expense_date|issue_date)$")
NUM = re.compile(r"^(value|amount|total_amount|min_value|max_value)$")


def pg_type(col, decl):
    if BOOL.match(col): return "boolean not null default false"
    if TS.search(col): return "timestamptz"
    if DT.search(col): return "date"
    if NUM.match(col): return "numeric(14,2)"
    if "int" in decl and "primary key" in decl and "autoincrement" in decl: return "bigserial primary key"
    if "primary key" in decl: return ("int" if decl.startswith("int ") else "text") + " primary key"
    if col in ("offline_after_minutes",): return "int not null default 30"
    if col == "status" and "default" in decl: return "text not null default 'ACTIVE'"
    if col in ("id", "check_out"): return "text"
    return "int" if decl.startswith("int") else "text"


def pg_ddl():
    out = []
    for stmt in F.DDL.strip().split("\n"):
        name = stmt.split("office_dashboard.")[1].split("(")[0]; body = stmt[stmt.index("(") + 1: stmt.rindex(")")]
        cols = []
        for part in body.split(","):
            col, decl = part.strip().split(" ", 1); cols.append(f"{col} {pg_type(col, decl.lower())}")
        out.append(f"create table office_dashboard.{name}({', '.join(cols)})")
    return out


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pgintel"), cleanup_mode="stop")
    except Exception as e: pytest.skip(f"cannot start disposable Postgres: {e}")
    yield srv; srv.cleanup()


class PgSeeder:
    """Same .add(table, **cols) interface as SqliteReader so the existing seed functions run unchanged."""
    def __init__(self, conn): self.c = conn
    def add(self, table, **cols):
        keys = list(cols); vals = []
        for k in keys:
            v = cols[k]
            if BOOL.match(k) and v is not None: v = bool(v)
            vals.append(v)
        self.c.execute(f"insert into office_dashboard.{table}({','.join(keys)}) values({','.join(['%s'] * len(keys))})", vals)


def seed_all(r):
    TM.seed_approvals(r); TM.seed_tickets(r); TM.seed_invoices(r); TM.seed_fleet(r); TM.seed_devices(r)      # seed_approvals also seeds tasks


@pytest.fixture(scope="module")
def dsn(server):
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as c:
        c.execute("drop schema if exists office_dashboard cascade"); c.execute("create schema office_dashboard")
        for ddl in pg_ddl(): c.execute(ddl)
        seed_all(PgSeeder(c))
    return uri


def normalise(v):
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, (datetime, date)): return v.isoformat()[:10]
    if isinstance(v, float): return round(v, 2)
    if isinstance(v, dict): return {k: normalise(x) for k, x in v.items() if k not in ("as_of", "freshness", "evidence", "link")}
    if isinstance(v, list): return [normalise(x) for x in v]
    return v


def run_all(reader, role="ceo"):
    ctx = F.make_ctx(reader, role=role)
    return {mid: compute(mid, ctx) for mid in sorted(REGISTRY)}


def test_every_metric_runs_on_real_postgres_without_query_errors(dsn):
    with PgReader(dsn) as pg: res = run_all(pg)
    broken = {m: r.message for m, r in res.items() if r.state == R.UNAVAILABLE}
    assert not broken, f"metric SQL failed on PostgreSQL: {broken}"
    assert sum(1 for r in res.values() if r.state in R.USABLE) >= 20       # the seeded data really produced numbers, not just empty states


def test_postgres_results_equal_sqlite_results(dsn):
    sq = F.SqliteReader(); seed_all(sq); a = run_all(sq)
    with PgReader(dsn) as pg: b = run_all(pg)
    diffs = []
    for mid in sorted(REGISTRY):
        x, y = a[mid], b[mid]
        if x.state != y.state or normalise(x.value) != normalise(y.value): diffs.append((mid, x.state, normalise(x.value), y.state, normalise(y.value)))
    assert not diffs, f"SQLite and PostgreSQL disagree: {diffs}"


def test_postgres_cto_role_is_gated_the_same_way(dsn):
    with PgReader(dsn) as pg: res = run_all(pg, role="cto")
    assert res["invoices.receivables"].state == R.NO_PERMISSION and res["invoices.receivables"].value is None
    assert res["tickets.open_backlog"].state == R.AVAILABLE


def test_pgreader_is_read_only_on_a_real_server(dsn):
    with PgReader(dsn) as pg:
        with pytest.raises(Exception): pg.rows("insert into office_dashboard.tasks(id) values ('zz')")
        assert pg.rows("select count(*) as n from office_dashboard.tasks where id='zz'")[0]["n"] == 0


def test_pgreader_statement_timeout_becomes_a_safe_timeout_error(dsn):
    from intelligence.reader import ReaderError
    with PgReader(dsn, timeout_ms=100) as pg:
        with pytest.raises(ReaderError) as e: pg.rows("select pg_sleep(2)")
        assert e.value.kind == "timeout"
        assert pg.rows("select 1 as ok")[0]["ok"] == 1          # connection is usable again after the timeout


def test_missing_table_is_reported_as_unavailable_on_real_postgres(dsn):
    from intelligence.reader import ReaderError
    with PgReader(dsn) as pg:
        with pytest.raises(ReaderError) as e: pg.rows("select * from office_dashboard.no_such_table")
        assert e.value.kind == "missing_table" and "no_such_table" not in str(e.value)
