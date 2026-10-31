import io, sys, pytest
pgserver = pytest.importorskip("pgserver")
import psycopg; from fastapi.testclient import TestClient
import main, tools.create_account as ca
from repo import PostgresUserRepo; from stores import RevocationStore, AuditSink
@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    d = srv.get_uri()
    with psycopg.connect(d, autocommit=True) as c: c.execute(open("../db/001_foundation.sql").read())
    yield d; srv.cleanup()
def run(monkeypatch, dsn, pw, *args):
    monkeypatch.setenv("DATABASE_URL", dsn); monkeypatch.setattr(sys, "stdin", io.StringIO(pw + "\n")); ca.main(list(args) + ["--password-stdin"])
BASE = ["--name", "A B", "--email", "a@x.test"]
def test_create_then_login_and_no_secrets_stored(monkeypatch, dsn, tmp_path, capsys):
    run(monkeypatch, dsn, "a-long-password-1", "--role", "ceo", "--username", "boss", *BASE)
    out = capsys.readouterr().out; assert "a-long-password-1" not in out and "$2b$" not in out
    cfg = dict(table="office_dashboard.login_accounts", id="id", name="full_name", login="username", email="email", password="password_hash", role="role", active="is_active", active_values={"true", "t"}, role_map={})
    cl = TestClient(main.create_app(PostgresUserRepo(dsn, cfg), cfg, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a"))))
    assert cl.post("/api/auth/login", json={"username": "boss", "password": "a-long-password-1"}).json()["role"] == "ceo"
    with psycopg.connect(dsn) as c:
        assert "a-long-password-1" not in c.execute("select password_hash from office_dashboard.users").fetchone()[0]
        assert c.execute("select count(*) from office_dashboard.audit_log where action='account_created'").fetchone()[0] == 1
def test_technician_gets_linked_profile_and_no_duplicates(monkeypatch, dsn):
    run(monkeypatch, dsn, "another-long-pw-2", "--role", "technician", "--username", "tech001", "--name", "T One", "--email", "t1@x.test")
    with psycopg.connect(dsn) as c: assert c.execute("select count(*) from office_dashboard.technicians t join office_dashboard.employees e on e.id=t.employee_id where e.email='t1@x.test'").fetchone()[0] == 1
    for extra in (["--username", "TECH001", "--name", "X", "--email", "z@x.test"], ["--username", "other", "--name", "X", "--email", "T1@X.TEST"]):
        with pytest.raises(SystemExit): run(monkeypatch, dsn, "another-long-pw-2", "--role", "technician", *extra)
def test_weak_or_bad_input_rejected(monkeypatch, dsn):
    for pw in ("short", "x" * 80):
        with pytest.raises(SystemExit): run(monkeypatch, dsn, pw, "--role", "employee", "--username", "emp9", "--name", "E", "--email", "e9@x.test")
    with pytest.raises(SystemExit): run(monkeypatch, dsn, "a-long-password-1", "--role", "employee", "--username", "bad name!", "--name", "E", "--email", "e8@x.test")
