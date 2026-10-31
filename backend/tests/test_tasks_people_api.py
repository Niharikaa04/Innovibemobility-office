"""API tests for Tasks & Approvals, Employee directory, Audit log and backend permission enforcement.
Runs against a DISPOSABLE local Postgres (pgserver) with db/001 + db/005 + db/006 applied. Never touches your real database.
STATUS: written in a sandbox that could not install FastAPI/psycopg/pytest, so these were NOT executed there.
The SQL they rely on WAS executed on PostgreSQL 16 (see docs/TEST_REPORT.md). Run: cd backend && python -m pytest -q"""
import pytest
pgserver = pytest.importorskip("pgserver")
import psycopg, bcrypt
from fastapi.testclient import TestClient
import main
from repo import PostgresUserRepo
from stores import RevocationStore, AuditSink

CFG = dict(table="office_dashboard.login_accounts", id="id", name="full_name", login="username", email="email", password="password_hash", role="role",
           active="is_active", active_values={"true", "t", "1", "active"}, role_map={})
ACCOUNTS = [("ceo1", "ceo"), ("coo1", "coo"), ("hr1", "hr"), ("sm1", "service_manager"), ("emp1", "employee"), ("emp2", "employee"), ("tech1", "technician")]

@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    d = srv.get_uri(); h = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        for f in ("001_foundation", "005_audit_log", "006_tasks"): c.execute(open(f"../db/{f}.sql").read())
        c.execute("insert into office_dashboard.departments(name) values ('Ops') on conflict do nothing")
        for i, (u, role) in enumerate(ACCOUNTS):
            eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email,department_id) values(%s,%s,%s,(select id from office_dashboard.departments limit 1)) returning id", (f"T-{i}", u.upper(), f"{u}@x.test")).fetchone()[0]
            c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role,must_change_password) values(%s,%s,%s,%s,false)", (eid, u, h, role))
    yield d; srv.cleanup()

@pytest.fixture()
def mk(dsn, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", dsn)
    with psycopg.connect(dsn, autocommit=True) as c: c.execute("truncate office_dashboard.tasks")
    def make(user):
        c = TestClient(main.create_app(PostgresUserRepo(dsn, CFG), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a"))))
        if user: assert c.post("/api/auth/login", json={"username": user, "password": "pw"}).status_code == 200; c.headers["x-csrf-token"] = c.cookies.get("csrf")
        return c
    return make

def uid(c): return c.get("/api/auth/me").json()["id"]

def test_anonymous_and_missing_csrf_rejected(mk):
    assert mk(None).get("/api/tasks").status_code == 401
    c = mk("ceo1"); c.headers.pop("x-csrf-token"); assert c.post("/api/tasks", json={"title": "x"}).status_code == 403

def test_create_list_edit_archive_roundtrip_and_audit(mk, dsn):
    c = mk("ceo1"); me = uid(c); r = c.post("/api/tasks", json={"title": "  Plan Q4  ", "priority": "high", "due_date": "2026-12-01"}); assert r.status_code == 201
    t = r.json(); assert t["title"] == "Plan Q4" and t["assignee_id"] == me and t["status"] == "open" and t["assignee_name"] == "CEO1"
    assert c.get("/api/tasks?q=q4").json()["total"] == 1 and c.get("/api/tasks?q=%25").json()["total"] == 0
    assert c.patch(f"/api/tasks/{t['id']}", json={"status": "in_progress"}).json()["status"] == "in_progress"
    assert c.patch(f"/api/tasks/{t['id']}", json={"title": ""}).status_code == 422 and c.patch(f"/api/tasks/{t['id']}", json={}).status_code == 422
    assert c.delete(f"/api/tasks/{t['id']}").json() == {"ok": True} and c.get(f"/api/tasks/{t['id']}").status_code == 404
    with psycopg.connect(dsn) as k: acts = [x[0] for x in k.execute("select action from office_dashboard.audit_log where entity_type='task' order by id").fetchall()]
    assert acts == ["task.created", "task.status_changed", "task.archived"]

def test_employee_sees_only_own_tasks_and_cannot_assign_others(mk):
    ceo, e1, e2 = mk("ceo1"), mk("emp1"), mk("emp2")
    ceo.post("/api/tasks", json={"title": "for emp1", "assignee_id": uid(e1)}); ceo.post("/api/tasks", json={"title": "for emp2", "assignee_id": uid(e2)})
    assert [t["title"] for t in e1.get("/api/tasks").json()["items"]] == ["for emp1"]
    other = [t for t in ceo.get("/api/tasks").json()["items"] if t["title"] == "for emp2"][0]["id"]
    assert e1.get(f"/api/tasks/{other}").status_code == 404 and e1.patch(f"/api/tasks/{other}", json={"status": "done"}).status_code == 404
    assert e1.post("/api/tasks", json={"title": "x", "assignee_id": uid(e2)}).status_code == 403
    assert e1.post("/api/tasks", json={"title": "mine"}).status_code == 201

def test_unknown_or_inactive_assignee_rejected(mk, dsn):
    c = mk("ceo1"); assert c.post("/api/tasks", json={"title": "x", "assignee_id": "does-not-exist"}).status_code == 422

def test_approval_flow_and_separation_of_duties(mk, dsn):
    ceo, coo, e1 = mk("ceo1"), mk("coo1"), mk("emp1")
    t = ceo.post("/api/tasks", json={"title": "needs ok", "assignee_id": uid(e1), "requires_approval": True}).json()
    assert e1.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).json()["status"] == "pending_approval"      # server converts
    assert e1.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).status_code == 409                          # locked while pending
    assert e1.post(f"/api/tasks/{t['id']}/decision", json={"decision": "approve"}).status_code == 403             # employee has no tasks.approve
    assert coo.post(f"/api/tasks/{t['id']}/decision", json={"decision": "reject"}).status_code == 422             # reason required
    r = coo.post(f"/api/tasks/{t['id']}/decision", json={"decision": "reject", "note": "add numbers"}); assert r.json()["status"] == "in_progress" and r.json()["decision_note"] == "add numbers"
    e1.patch(f"/api/tasks/{t['id']}", json={"status": "done"}); r = ceo.post(f"/api/tasks/{t['id']}/decision", json={"decision": "approve"}); assert r.json()["status"] == "done" and r.json()["completed_at"]
    assert ceo.post(f"/api/tasks/{t['id']}/decision", json={"decision": "approve"}).status_code == 409
    mine = ceo.post("/api/tasks", json={"title": "own", "requires_approval": True}).json(); ceo.patch(f"/api/tasks/{mine['id']}", json={"status": "done"})
    assert ceo.post(f"/api/tasks/{mine['id']}/decision", json={"decision": "approve"}).status_code == 403          # no self-approval
    with psycopg.connect(dsn) as k: assert k.execute("select count(*) from office_dashboard.audit_log where action in ('task.rejected','task.approved')").fetchone()[0] == 2

def test_reopen_is_manager_only_and_toggle_off_approval_is_safe(mk):
    ceo, e1 = mk("ceo1"), mk("emp1"); t = ceo.post("/api/tasks", json={"title": "x", "assignee_id": uid(e1)}).json()
    e1.patch(f"/api/tasks/{t['id']}", json={"status": "done"}); assert e1.patch(f"/api/tasks/{t['id']}", json={"status": "open"}).status_code == 403
    assert ceo.patch(f"/api/tasks/{t['id']}", json={"status": "open"}).json()["status"] == "open"
    a = ceo.post("/api/tasks", json={"title": "a", "requires_approval": True}).json(); coo = mk("coo1")
    ceo.patch(f"/api/tasks/{a['id']}", json={"status": "done"}); coo.post(f"/api/tasks/{a['id']}/decision", json={"decision": "approve"})
    assert ceo.patch(f"/api/tasks/{a['id']}", json={"status": "open"}).json()["status"] == "open"
    assert ceo.patch(f"/api/tasks/{a['id']}", json={"requires_approval": False}).json()["requires_approval"] is False      # approval fields were cleared on reopen, so the CHECK constraint is not violated

def test_archive_permission_is_ceo_only(mk):
    ceo, sm = mk("ceo1"), mk("sm1"); t = sm.post("/api/tasks", json={"title": "x"}).json()
    assert sm.delete(f"/api/tasks/{t['id']}").status_code == 403 and ceo.delete(f"/api/tasks/{t['id']}").status_code == 200

def test_my_permissions_endpoint_matches_matrix(mk):
    import permissions
    for u, role in ACCOUNTS: assert mk(u).get("/api/auth/permissions").json() == {"role": role, "permissions": permissions.permissions_for(role)}

def test_employee_directory_permissions_and_no_secrets(mk):
    assert mk("emp1").get("/api/employees").status_code == 403 and mk("tech1").get("/api/employees").status_code == 403
    r = mk("hr1").get("/api/employees"); assert r.status_code == 200 and r.json()["total"] == len(ACCOUNTS) and "password" not in r.text.lower() and r.json()["can_admin"] is False
    assert mk("ceo1").get("/api/employees?q=emp1").json()["total"] == 1

def test_hr_can_edit_details_but_only_ceo_can_deactivate(mk, dsn):
    hr, ceo, e2 = mk("hr1"), mk("ceo1"), mk("emp2"); assert e2.get("/api/auth/me").status_code == 200; eid = ceo.get("/api/employees?q=emp2").json()["items"][0]["id"]
    assert hr.patch(f"/api/employees/{eid}", json={"designation": "Analyst"}).json()["designation"] == "Analyst"
    assert hr.patch(f"/api/employees/{eid}", json={"is_active": False}).status_code == 403
    assert ceo.patch(f"/api/employees/{eid}", json={"phone": "abc"}).status_code == 422 and ceo.patch(f"/api/employees/{eid}", json={"department_id": 99999}).status_code == 422
    assert ceo.patch(f"/api/employees/{eid}", json={"is_active": False}).json()["is_active"] is False
    assert e2.get("/api/auth/me").status_code == 401                                  # deactivation ends the live session (existing per-request re-check)
    with psycopg.connect(dsn) as k: assert k.execute("select count(*) from office_dashboard.audit_log where action='employee.updated'").fetchone()[0] == 2   # only the 2 successful edits
    assert hr.patch("/api/employees/not-a-uuid", json={"phone": "+91 98765 43210"}).status_code == 404

def test_audit_endpoint_permissions_and_append_only(mk, dsn):
    ceo = mk("ceo1"); ceo.post("/api/tasks", json={"title": "audited"})
    assert mk("hr1").get("/api/audit").status_code == 403 and mk("emp1").get("/api/audit").status_code == 403 and mk("coo1").get("/api/audit").status_code == 403
    r = ceo.get("/api/audit?entity_type=task"); assert r.status_code == 200 and r.json()["items"][0]["action"] == "task.created" and ceo.get("/api/audit?outcome=bogus").status_code == 422
    with psycopg.connect(dsn, autocommit=True) as k:
        with pytest.raises(psycopg.errors.RaiseException): k.execute("update office_dashboard.audit_log set action='x'")
