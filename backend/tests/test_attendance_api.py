"""API tests for Attendance. Run against a DISPOSABLE local Postgres (pgserver) with db/001 + 005 + 007 applied.
STATUS: written in a sandbox without FastAPI/psycopg/pytest, so these were NOT executed there. Run: cd backend && python -m pytest -q tests/test_attendance_api.py
The server clock is replaced with a fixed one so late/early/date logic is deterministic."""
import pytest
pgserver = pytest.importorskip("pgserver")
from datetime import datetime, timezone
import psycopg, bcrypt
from fastapi.testclient import TestClient
import main, attendance
from repo import PostgresUserRepo
from stores import RevocationStore, AuditSink
from test_tasks_people_api import CFG, ACCOUNTS   # same accounts: ceo1 coo1 hr1 sm1 emp1 emp2 tech1

@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    d = srv.get_uri(); h = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        for f in ("001_foundation", "005_audit_log", "007_attendance"): c.execute(open(f"../db/{f}.sql").read())
        c.execute("insert into office_dashboard.departments(name) values ('Ops') on conflict do nothing")
        for i, (u, role) in enumerate(ACCOUNTS):
            eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email,department_id) values(%s,%s,%s,(select id from office_dashboard.departments limit 1)) returning id", (f"A-{i}", u.upper(), f"{u}@x.test")).fetchone()[0]
            c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role,must_change_password) values(%s,%s,%s,%s,false)", (eid, u, h, role))
    yield d; srv.cleanup()

T = lambda h, m=0, d=26: datetime(2026, 10, d, h, m, tzinfo=timezone.utc)
CONF = {"start_time": "09:30", "end_time": "18:30", "grace_minutes": 10, "timezone": "UTC", "working_days": [1, 2, 3, 4, 5]}

@pytest.fixture()
def mk(dsn, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", dsn)
    with psycopg.connect(dsn, autocommit=True) as c: c.execute("truncate office_dashboard.attendance_records, office_dashboard.attendance_corrections, office_dashboard.attendance_config")
    def make(user):
        c = TestClient(main.create_app(PostgresUserRepo(dsn, CFG), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a"))))
        if user: assert c.post("/api/auth/login", json={"username": user, "password": "pw"}).status_code == 200; c.headers["x-csrf-token"] = c.cookies.get("csrf")
        return c
    return make
def at(monkeypatch, t): monkeypatch.setattr(attendance, "clock", lambda: t)
def uid(c): return c.get("/api/auth/me").json()["id"]

def test_anonymous_rejected(mk): assert mk(None).get("/api/attendance/config").status_code == 401
def test_checkin_blocked_until_configured(mk):
    assert mk("emp1").post("/api/attendance/check-in").status_code == 409
def test_only_admin_configures(mk):
    assert mk("emp1").put("/api/attendance/config", json=CONF).status_code == 403 and mk("hr1").put("/api/attendance/config", json=CONF).status_code == 403
    assert mk("ceo1").put("/api/attendance/config", json=CONF).status_code == 200
def test_config_validation(mk):
    c = mk("ceo1"); assert c.put("/api/attendance/config", json={**CONF, "timezone": "Mars/Base"}).status_code == 422
    assert c.put("/api/attendance/config", json={**CONF, "end_time": "08:00"}).status_code == 422 and c.put("/api/attendance/config", json={**CONF, "working_days": [9]}).status_code == 422
def test_check_in_out_and_duplicates(mk, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); e = mk("emp1")
    at(monkeypatch, T(9, 55)); r = e.post("/api/attendance/check-in"); assert r.status_code == 201 and r.json()["late_minutes"] == 25
    assert e.post("/api/attendance/check-in").status_code == 409                       # duplicate protected
    at(monkeypatch, T(18, 0)); r = e.post("/api/attendance/check-out"); assert r.status_code == 200 and r.json()["early_minutes"] == 30
    assert e.post("/api/attendance/check-out").status_code == 409
    assert mk("emp2").post("/api/attendance/check-out").status_code == 409             # never checked in
def test_scoping(mk, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); at(monkeypatch, T(9, 0)); e1 = mk("emp1"); e1.post("/api/attendance/check-in"); me = uid(e1)
    assert mk("emp2").get(f"/api/attendance/records?month=2026-10&user_id={me}").status_code == 403
    assert mk("emp2").get("/api/attendance/team").status_code == 403
    assert len(mk("hr1").get(f"/api/attendance/records?month=2026-10&user_id={me}").json()["items"]) == 1
    assert len(mk("hr1").get("/api/attendance/team?date=2026-10-26").json()["items"]) == 1
    assert mk("coo1").post("/api/attendance/check-in").status_code == 403              # COO is read-only in the proposed matrix
def test_correction_flow(mk, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); at(monkeypatch, T(12)); e = mk("emp1")
    body = {"work_date": "2026-10-20", "check_in_time": "09:00", "check_out_time": "18:00", "reason": "Forgot to punch in"}
    r = e.post("/api/attendance/corrections", json=body); assert r.status_code == 201; cid = r.json()["id"]
    assert e.post("/api/attendance/corrections", json=body).status_code == 409        # one pending per date
    assert e.post("/api/attendance/corrections", json={**body, "work_date": "2026-10-30"}).status_code == 422   # future
    assert e.post(f"/api/attendance/corrections/{cid}/decision", json={"decision": "approve"}).status_code == 403   # no approve permission
    h = mk("hr1"); assert h.post(f"/api/attendance/corrections/{cid}/decision", json={"decision": "reject"}).status_code == 422   # reason needed
    assert h.post(f"/api/attendance/corrections/{cid}/decision", json={"decision": "approve"}).status_code == 200
    assert h.post(f"/api/attendance/corrections/{cid}/decision", json={"decision": "approve"}).status_code == 409   # already decided
    rec = e.get("/api/attendance/records?month=2026-10").json()["items"]; assert len(rec) == 1 and rec[0]["source"] == "correction" and rec[0]["worked_minutes"] == 540
def test_hr_cannot_approve_own_correction(mk, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); at(monkeypatch, T(12)); h = mk("hr1")
    cid = h.post("/api/attendance/corrections", json={"work_date": "2026-10-20", "check_in_time": "09:00", "reason": "Forgot to punch in"}).json()["id"]
    assert h.post(f"/api/attendance/corrections/{cid}/decision", json={"decision": "approve"}).status_code == 403
def test_audit_rows_written(mk, dsn, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); at(monkeypatch, T(9)); mk("emp1").post("/api/attendance/check-in")
    with psycopg.connect(dsn) as c: acts = {r[0] for r in c.execute("select action from office_dashboard.audit_log where action like 'attendance.%'")}
    assert {"attendance.config_changed", "attendance.check_in"} <= acts
def test_summary(mk, monkeypatch):
    mk("ceo1").put("/api/attendance/config", json=CONF); at(monkeypatch, T(9, 0)); e = mk("emp1"); e.post("/api/attendance/check-in")
    s = e.get("/api/attendance/summary?month=2026-10").json(); assert s["days_present"] == 1 and s["late_days"] == 0
    assert e.get("/api/attendance/summary?month=bad").status_code == 422
