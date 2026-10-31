"""db/004_pipeline_stages.sql + rollback, proven on a DISPOSABLE local Postgres (never your Supabase)."""
import pytest
pgserver = pytest.importorskip("pgserver")
import psycopg
D = "../db/"
def run(c, f): c.execute(open(D + f).read())
@pytest.fixture()
def c(tmp_path):
    try: srv = pgserver.get_server(tmp_path, cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    with psycopg.connect(srv.get_uri(), autocommit=True) as k:
        run(k, "001_foundation.sql"); run(k, "003_crm.sql"); yield k
    srv.cleanup()
ins = lambda c, st: c.execute("insert into office_dashboard.leads(title,stage) values('t',%s)", (st,))
def test_004_aborts_and_changes_nothing_while_qualified_rows_exist(c):
    ins(c, "qualified")
    with pytest.raises(psycopg.errors.RaiseException): run(c, "004_pipeline_stages.sql")
    ins(c, "qualified")                                   # constraint still the old one
    assert c.execute("select count(*) from office_dashboard.leads").fetchone()[0] == 2
def test_004_applies_is_rerunnable_and_rolls_back(c):
    ins(c, "proposal"); run(c, "004_pipeline_stages.sql"); run(c, "004_pipeline_stages.sql")
    with pytest.raises(psycopg.errors.CheckViolation): ins(c, "qualified")
    ins(c, "negotiation")
    assert c.execute("select count(*) from office_dashboard.leads").fetchone()[0] == 2         # existing data untouched
    run(c, "004_pipeline_stages.rollback.sql"); ins(c, "qualified")                           # old behaviour restored
