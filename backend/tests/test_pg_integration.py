"""Integration test of PostgresUserRepo + full login against a DISPOSABLE local Postgres (pgserver). Uses a schema invented for this test, NOT your production schema. Skipped if pgserver is absent."""
import bcrypt, pytest
pgserver = pytest.importorskip("pgserver")
import psycopg
from fastapi.testclient import TestClient
import main
from repo import PostgresUserRepo
from stores import RevocationStore, AuditSink
@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(f"cannot start disposable Postgres: {e}")
    d = srv.get_uri()
    h = lambda p: bcrypt.hashpw(p.encode(), bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        c.execute("create schema hr_test"); c.execute("create table hr_test.accounts(acct_id int primary key, display text, uname text, mail text, pwd text, kind text, status text)")
        for r in [(1,"Sri Hari","srihari.ceo","ceo@x.test",h("ceo-pw"),"Chief Executive","ACTIVE"),(2,"Tech One","tech001","t1@x.test",h("t-pw"),"Technician","ACTIVE"),
                  (3,"Gone","gone","g@x.test",h("g-pw"),"Technician","DISABLED"),(4,"Dup A","dup","dup@x.test",h("a"),"Employee","ACTIVE"),(5,"Dup B","dup","dup2@x.test",h("b"),"Employee","ACTIVE")]:
            c.execute("insert into hr_test.accounts values(%s,%s,%s,%s,%s,%s,%s)", r)
    yield d; srv.cleanup()
CFG = dict(table="hr_test.accounts", id="acct_id", name="display", login="uname", email="mail", password="pwd", role="kind", active="status", active_values={"active"}, role_map={"chief executive": "ceo", "technician": "technician", "employee": "employee"})
@pytest.fixture()
def client(dsn, tmp_path): return TestClient(main.create_app(PostgresUserRepo(dsn, CFG), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a"))))
def test_find_by_login_and_email_case_insensitive(dsn):
    r = PostgresUserRepo(dsn, CFG); assert r.find("srihari.ceo").id == "1" and r.find("CEO@X.TEST".lower()).name == "Sri Hari"
def test_ambiguous_login_refused(dsn): assert PostgresUserRepo(dsn, CFG).find("dup") is None
def test_inactive_flag_read(dsn): assert PostgresUserRepo(dsn, CFG).find("gone").active is False
def test_injection_string_is_just_data(dsn): assert PostgresUserRepo(dsn, CFG).find("x' or '1'='1") is None
def test_full_login_session_and_portals_via_real_postgres(client):
    assert client.post("/api/auth/login", json={"username": "srihari.ceo", "password": "ceo-pw"}).json()["role"] == "ceo"
    assert client.get("/api/dashboard/coo").status_code == 200 and client.get("/api/dashboard/hr").status_code == 403
def test_disabled_and_wrong_password_rejected(client):
    assert client.post("/api/auth/login", json={"username": "gone", "password": "g-pw"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "tech001", "password": "bad"}).status_code == 401
def test_deactivation_in_db_ends_live_session(client, dsn):
    client.post("/api/auth/login", json={"username": "tech001", "password": "t-pw"}); assert client.get("/api/auth/me").status_code == 200
    with psycopg.connect(dsn, autocommit=True) as c: c.execute("update hr_test.accounts set status='DISABLED' where acct_id=2")
    assert client.get("/api/auth/me").status_code == 401
