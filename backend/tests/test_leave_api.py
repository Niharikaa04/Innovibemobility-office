"""API tests for HR & Leave (+ attendance integration). Disposable local Postgres (pgserver) with db/001 + 005 + 007 + 008.
STATUS: written in a sandbox without FastAPI/psycopg/pytest, so these were NOT executed there. Run: cd backend && python -m pytest -q tests/test_leave_api.py
The server clock is fixed to Mon 2026-10-26 12:00 UTC; attendance is configured with UTC and Mon-Fri."""
import pytest
pgserver = pytest.importorskip("pgserver")
from datetime import datetime, timezone
import psycopg, bcrypt
from fastapi.testclient import TestClient
import main, attendance
from repo import PostgresUserRepo
from stores import RevocationStore, AuditSink
from test_tasks_people_api import CFG, ACCOUNTS

@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    d = srv.get_uri(); h = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        for f in ("001_foundation", "005_audit_log", "007_attendance", "008_leave"): c.execute(open(f"../db/{f}.sql").read())
        c.execute("insert into office_dashboard.departments(name) values ('Ops') on conflict do nothing")
        for i, (u, role) in enumerate(ACCOUNTS):
            eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email,department_id) values(%s,%s,%s,(select id from office_dashboard.departments limit 1)) returning id", (f"L-{i}", u.upper(), f"{u}@x.test")).fetchone()[0]
            c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role,must_change_password) values(%s,%s,%s,%s,false)", (eid, u, h, role))
    yield d; srv.cleanup()

@pytest.fixture()
def mk(dsn, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", dsn); monkeypatch.setattr(attendance, "clock", lambda: datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc))
    with psycopg.connect(dsn, autocommit=True) as c: c.execute("truncate office_dashboard.leave_requests, office_dashboard.holidays, office_dashboard.attendance_records, office_dashboard.attendance_corrections, office_dashboard.attendance_config; delete from office_dashboard.leave_types")
    def make(user):
        c = TestClient(main.create_app(PostgresUserRepo(dsn, CFG), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a"))))
        if user: assert c.post("/api/auth/login", json={"username": user, "password": "pw"}).status_code == 200; c.headers["x-csrf-token"] = c.cookies.get("csrf")
        return c
    return make
ATT = {"start_time": "09:30", "end_time": "18:30", "grace_minutes": 10, "timezone": "UTC", "working_days": [1, 2, 3, 4, 5]}
def setup(mk, **kw):
    ceo = mk("ceo1"); ceo.put("/api/attendance/config", json=ATT)
    t = {"code": "casual", "name": "Casual", "annual_entitlement_days": 3, "allow_half_day": True, "min_notice_days": 1, **kw}
    r = ceo.post("/api/leave/types", json=t); assert r.status_code == 201; return ceo, r.json()["id"]
def body(tid, a="2026-10-28", b="2026-10-29", reason="family event", **kw): return {"leave_type_id": tid, "start_date": a, "end_date": b, "reason": reason, **kw}

def test_anonymous_rejected(mk): assert mk(None).get("/api/leave/meta").status_code == 401
def test_only_admin_manages_types_and_holidays(mk):
    ceo, tid = setup(mk)
    assert mk("emp1").post("/api/leave/types", json={"code": "sick", "name": "Sick"}).status_code == 403 and mk("hr1").post("/api/leave/types", json={"code": "sick", "name": "Sick"}).status_code == 403
    assert mk("hr1").post("/api/leave/holidays", json={"holiday_date": "2026-11-01", "name": "X"}).status_code == 403
    assert ceo.post("/api/leave/types", json={"code": "casual", "name": "dup"}).status_code == 409
    assert ceo.patch(f"/api/leave/types/{tid}", json={"name": None}).status_code == 422
def test_request_blocked_until_attendance_configured(mk):
    ceo = mk("ceo1"); tid = ceo.post("/api/leave/types", json={"code": "casual", "name": "Casual"}).json()["id"]
    assert mk("emp1").post("/api/leave/requests", json=body(tid)).status_code == 409
def test_request_counts_working_days_and_holidays(mk):
    ceo, tid = setup(mk, annual_entitlement_days=10); ceo.post("/api/leave/holidays", json={"holiday_date": "2026-10-29", "name": "Local holiday"})
    r = mk("emp1").post("/api/leave/requests", json=body(tid)); assert r.status_code == 201 and float(r.json()["days"]) == 1.0      # 28th only
    assert mk("emp1").post("/api/leave/requests", json=body(tid, "2026-10-31", "2026-11-01")).status_code == 422                      # Sat-Sun
def test_validation_rules(mk):
    ceo, tid = setup(mk, annual_entitlement_days=10, max_consecutive_days=2); e = mk("emp1")          # today = Mon 2026-10-26, notice 1 day
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-26", "2026-10-26")).status_code == 422      # no notice
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-20", "2026-10-20")).status_code == 422      # in the past (backdating 0)
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-28", "2026-10-30")).status_code == 422      # 3 days > max 2
    assert e.post("/api/leave/requests", json=body(tid, "2026-12-30", "2027-01-02")).status_code == 422      # crosses year
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-28", "2026-10-28", reason=" ")).status_code == 422
    assert e.post("/api/leave/requests", json=body("not-a-uuid")).status_code == 422
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-28", "2026-10-28", half_day="first_half")).status_code == 201
def test_overlap_and_balance(mk):
    ceo, tid = setup(mk); e = mk("emp1")                                                                       # entitlement 3
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-28", "2026-10-29")).status_code == 201
    assert e.post("/api/leave/requests", json=body(tid, "2026-10-29", "2026-10-30")).status_code == 409      # overlaps
    assert e.post("/api/leave/requests", json=body(tid, "2026-11-02", "2026-11-03")).status_code == 409      # 2 pending + 2 > 3
    assert mk("emp2").post("/api/leave/requests", json=body(tid, "2026-10-28", "2026-10-29")).status_code == 201   # other people unaffected
def test_decision_flow_and_scoping(mk):
    ceo, tid = setup(mk); e = mk("emp1"); rid = e.post("/api/leave/requests", json=body(tid)).json()["id"]
    assert e.post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"}).status_code == 403          # no approve permission
    h = mk("hr1"); assert h.post(f"/api/leave/requests/{rid}/decision", json={"decision": "reject"}).status_code == 422   # reason needed
    assert h.post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"}).status_code == 200
    assert h.post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"}).status_code == 409
    me = e.get("/api/auth/me").json()["id"]
    b = e.get("/api/leave/balances").json()["items"][0]; assert float(b["used"]) == 2.0 and float(b["available"]) == 1.0
    assert mk("emp2").get(f"/api/leave/balances?user_id={me}").status_code == 403
    assert len(mk("emp2").get("/api/leave/requests").json()["items"]) == 0 and len(h.get("/api/leave/requests").json()["items"]) == 1
    assert len(mk("emp2").get("/api/leave/calendar?month=2026-10").json()["items"]) == 0 and len(h.get("/api/leave/calendar?month=2026-10").json()["items"]) == 1
def test_no_self_approval(mk):
    ceo, tid = setup(mk); h = mk("hr1"); rid = h.post("/api/leave/requests", json=body(tid)).json()["id"]
    assert h.post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"}).status_code == 403
    assert mk("ceo1").post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"}).status_code == 200
def test_cancel_rules(mk):
    ceo, tid = setup(mk); e = mk("emp1"); rid = e.post("/api/leave/requests", json=body(tid)).json()["id"]
    assert mk("emp2").post(f"/api/leave/requests/{rid}/cancel", json={}).status_code == 404                        # not yours
    mk("hr1").post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"})
    assert e.post(f"/api/leave/requests/{rid}/cancel", json={}).status_code == 200                                  # owner, approved, future
    assert e.post(f"/api/leave/requests/{rid}/cancel", json={}).status_code == 409                                  # already cancelled
    rid2 = e.post("/api/leave/requests", json=body(tid)).json()["id"]; mk("hr1").post(f"/api/leave/requests/{rid2}/decision", json={"decision": "approve"})
    assert mk("hr1").post(f"/api/leave/requests/{rid2}/cancel", json={}).status_code == 422                       # approver needs a reason
    assert mk("hr1").post(f"/api/leave/requests/{rid2}/cancel", json={"note": "business need"}).status_code == 200
def test_leave_reflected_in_attendance(mk):
    ceo, tid = setup(mk, annual_entitlement_days=10, allow_backdated_days=7); e = mk("emp1")
    rid = e.post("/api/leave/requests", json=body(tid, "2026-10-20", "2026-10-21", reason="sick")).json()["id"]      # Tue-Wed, in the past
    mk("hr1").post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"})
    ceo.post("/api/leave/holidays", json={"holiday_date": "2026-10-22", "name": "Holiday"})
    s = e.get("/api/attendance/summary?month=2026-10").json()
    assert s["leave_days"] == 2.0 and s["holiday_days"] == 1 and s["no_record_days"] == 14     # 17 working days to the 23rd - 2 leave - 1 holiday
    assert any(x["name"] for x in mk("hr1").get("/api/attendance/team?date=2026-10-20").json()["on_leave"])
def test_audit_rows_written(mk, dsn):
    ceo, tid = setup(mk); rid = mk("emp1").post("/api/leave/requests", json=body(tid)).json()["id"]; mk("hr1").post(f"/api/leave/requests/{rid}/decision", json={"decision": "approve"})
    with psycopg.connect(dsn) as c: acts = {r[0] for r in c.execute("select action from office_dashboard.audit_log where action like 'leave.%'")}
    assert {"leave.type_created", "leave.requested", "leave.approved"} <= acts
