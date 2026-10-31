"""Every intelligence metric against the project's REAL migrated schema (db/*.sql applied to a disposable PostgreSQL, never your database).
The SQLite and inferred-schema tests prove logic; this proves the metric SQL names only columns/tables that your migrations actually create.
Skipped (with a reason, by conftest) when db/ is not present."""
import glob, os, re

import pytest

pgserver = pytest.importorskip("pgserver")
import psycopg  # noqa: E402

import intel_fixtures as F  # noqa: E402
import intelligence.metrics  # noqa: E402,F401  (registers the metrics)
from conftest import DB_DIR, migration_sql  # noqa: E402
from intelligence import results as R  # noqa: E402
from intelligence.reader import PgReader  # noqa: E402
from intelligence.registry import REGISTRY, compute  # noqa: E402

SKIP_SEED = {"002_seed_accounts"}      # creates accounts, irrelevant to metrics


def forward_migrations():
    names = sorted({os.path.basename(f)[:-4] for f in glob.glob(str(DB_DIR / "*.sql")) if not f.endswith(".rollback.sql") and re.match(r"\d{3}_", os.path.basename(f))})
    return [("012_garages_technicians_diagnostics_iot" if n.startswith("012_") else n) for n in names if n not in SKIP_SEED]


@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pgreal"), cleanup_mode="stop")
    except Exception as e: pytest.skip(f"cannot start disposable Postgres: {e}")
    uri = srv.get_uri()
    with psycopg.connect(uri, autocommit=True) as c:
        for n in forward_migrations(): c.execute(migration_sql(n))
    yield uri; srv.cleanup()


def run_all(uri, role="ceo"):
    with PgReader(uri) as pg:
        ctx = F.make_ctx(pg, role=role); return {m: compute(m, ctx) for m in sorted(REGISTRY)}


def test_all_migrations_apply_cleanly_in_order(dsn):
    assert len(forward_migrations()) >= 15


def test_no_metric_fails_on_the_real_schema(dsn):
    res = run_all(dsn); broken = {m: r.message for m, r in res.items() if r.state == R.UNAVAILABLE}
    assert not broken, f"metric SQL does not match your migrations: {broken}"
    assert len(res) >= 30


def test_empty_database_reports_no_data_or_not_configured_never_invented_numbers(dsn):
    res = run_all(dsn)
    for m, r in res.items():
        if r.state == R.AVAILABLE: assert m == "approvals.pending" and r.value == 0, f"{m} reports {r.value!r} on an empty database"      # its source tables exist and hold no pending rows: a true zero
        else: assert r.value is None, f"{m}: state {r.state} must carry no number"
    assert res["attendance.today"].state == R.NOT_CONFIGURED and res["iot.threshold_alerts"].state == R.NO_THRESHOLD


def test_cto_is_still_gated_on_the_real_schema(dsn):
    res = run_all(dsn, "cto"); assert res["invoices.receivables"].state == R.NO_PERMISSION and res["invoices.receivables"].value is None
