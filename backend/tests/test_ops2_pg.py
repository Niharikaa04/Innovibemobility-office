"""Garages, Technicians, EVcare.AI Diagnostics and IoT end-to-end against a DISPOSABLE local Postgres (pgserver) with the real migrations
(001, 005, 010, 011, 012, 013) and real login/CSRF. Same harness as test_ops_pg.py. Skipped if pgserver is absent."""
import csv, io, pathlib
from datetime import datetime, timedelta, timezone
import bcrypt, pytest
pgserver = pytest.importorskip("pgserver")
import psycopg
from fastapi.testclient import TestClient
import main
from repo import PostgresUserRepo
from stores import RevocationStore, AuditSink

DB = pathlib.Path(__file__).resolve().parents[2] / "db"
CFG = dict(table="office_dashboard.login_accounts", id="id", name="full_name", login="username", email="email", password="password_hash", role="role",
           active="is_active", active_values={"true", "t"}, role_map={})
PEOPLE = [("ceo", "ceo"), ("sm", "service_manager"), ("tech1", "technician"), ("coo", "coo"), ("cto", "cto"), ("hr", "hr"), ("emp", "employee")]

@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(f"cannot start disposable Postgres: {e}")
    d = srv.get_uri(); h = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        for f in ("001_foundation", "005_audit_log", "010_service_tickets", "011_ops_tickets_fleet", "012_garages_technicians_diagnostics_iot", "012_garages_technicians_diagnostics_iot", "013_ops_followup", "013_ops_followup"):   # 012/013 twice: re-runnable
            c.execute((DB / f"{f}.sql").read_text(encoding="utf-8"))
        for u, role in PEOPLE:
            eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email) values(%s,%s,%s) returning id", (u.upper(), f"Person {u}", f"{u}@x.test")).fetchone()[0]
            c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role) values(%s,%s,%s,%s)", (eid, u, h, role))
        c.execute("insert into office_dashboard.employees(employee_code,full_name,email) values('NOUSER','No Login','nologin@x.test')")
    yield d; srv.cleanup()

@pytest.fixture()
def app(dsn, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", dsn); monkeypatch.delenv("EVCARE_AI_URL", raising=False); monkeypatch.delenv("EVCARE_AI_API_KEY", raising=False)
    return main.create_app(PostgresUserRepo(dsn, CFG), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a")))

class As:
    def __init__(self, app, user):
        self.c = TestClient(app); r = self.c.post("/api/auth/login", json={"username": user, "password": "pw"}); assert r.status_code == 200, r.text; self.id = r.json()["id"]
    def h(self): return {"x-csrf-token": self.c.cookies.get("csrf")}
    def get(self, u, **kw): return self.c.get(u, **kw)
    def post(self, u, j=None): return self.c.post(u, json=j or {}, headers=self.h())
    def patch(self, u, j): return self.c.patch(u, json=j, headers=self.h())
    def delete(self, u): return self.c.delete(u, headers=self.h())

@pytest.fixture()
def who(app): return {u: As(app, u) for u, _ in PEOPLE}
T0 = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(microsecond=0)   # real "recent" time; ingest refuses readings older than 30 days
ISO = T0.isoformat()
def parse(resp): return list(csv.reader(io.StringIO(resp.text.lstrip("\ufeff"))))
def vehicle(who, reg): 
    r = who["sm"].post("/api/fleet/vehicles", {"registration_number": reg, "make": "Tata", "model": "Ace EV", "customer_name": "Acme"}); assert r.status_code == 201, r.text; return r.json()


# ---------------- Garages ----------------
def test_garage_crud_filters_duplicates_and_permissions(who):
    sm, ceo, coo, t1 = who["sm"], who["ceo"], who["coo"], who["tech1"]
    r = sm.post("/api/garages", {"name": " Hyderabad Hub ", "city": "Hyderabad", "phone": "+91 98765 43210", "email": "HUB@X.TEST", "supported_services": ["BATTERY", "MOTOR", "BATTERY"]})
    assert r.status_code == 201, r.text; c = r.json(); cid = c["id"]
    assert c["center_code"].startswith("SC-") and c["name"] == "Hyderabad Hub" and c["supported_services"] == ["BATTERY", "MOTOR"] and c["email"] == "hub@x.test"
    assert sm.post("/api/garages", {"name": "hyderabad hub", "city": "HYDERABAD"}).status_code == 409           # duplicate ignoring case
    assert sm.post("/api/garages", {"name": "Bad", "phone": "abc"}).status_code == 422 and sm.post("/api/garages", {"name": "Bad", "supported_services": ["FLYING"]}).status_code == 422
    assert sm.patch(f"/api/garages/{cid}", {"status": "TEMPORARILY_CLOSED"}).json()["status"] == "TEMPORARILY_CLOSED" and sm.patch(f"/api/garages/{cid}", {}).status_code == 422
    assert [x["id"] for x in sm.get("/api/garages?service=BATTERY&status=TEMPORARILY_CLOSED&city=hyder&q=hub").json()["items"]] == [cid] and sm.get("/api/garages?service=BODY").json()["total"] == 0
    assert coo.get("/api/garages").status_code == 200 and coo.post("/api/garages", {"name": "X"}).status_code == 403   # COO read-only
    assert t1.get("/api/garages").status_code == 403
    assert sm.delete(f"/api/garages/{cid}").status_code == 403                                                  # archive is CEO-only
    rows = parse(sm.get("/api/garages/export"))
    assert rows[0][:2] == ["Service center ID", "Name"] and rows[1][0] == c["center_code"] and rows[1][1] == "Hyderabad Hub"
    assert sm.get(f"/api/garages?q={c['center_code']}").json()["total"] == 1                                   # search by ID
    assert ceo.delete(f"/api/garages/{cid}").status_code == 200 and sm.get(f"/api/garages/{cid}").status_code == 404

def test_garage_links_technicians_and_tickets_and_blocks_archive(who):
    sm, ceo = who["sm"], who["ceo"]
    cid = sm.post("/api/garages", {"name": "Link Center", "city": "Pune"}).json()["id"]
    cand = {x["name"]: x["id"] for x in sm.get("/api/technicians/candidates").json()["items"]}
    tid = sm.post("/api/technicians", {"employee_id": cand["Person coo"], "service_center_id": cid, "specialization": "EV"}).json()["id"]
    d = sm.get(f"/api/garages/{cid}").json(); assert [x["id"] for x in d["technicians"]] == [tid]
    tk = sm.post("/api/service-tickets", {"title": "Charger dead", "category": "CHARGER"}).json()
    assert sm.post(f"/api/garages/{cid}/tickets", {"ticket_id": tk["id"]}).status_code == 200
    assert [x["id"] for x in sm.get(f"/api/garages/{cid}").json()["tickets"]] == [tk["id"]]
    assert any(h["event_type"] == "updated" for h in sm.get(f"/api/service-tickets/{tk['id']}/history").json()["items"])
    assert ceo.delete(f"/api/garages/{cid}").status_code == 409                                                 # open ticket + active technician
    assert sm.delete(f"/api/garages/{cid}/tickets/{tk['id']}").status_code == 200
    assert sm.patch(f"/api/technicians/{tid}", {"service_center_id": None}).status_code == 200
    assert ceo.delete(f"/api/garages/{cid}").status_code == 200


# ---------------- Technicians ----------------
def test_technician_workload_assignment_and_deactivation_rules(who):
    sm, coo = who["sm"], who["coo"]
    cand = {x["name"]: x["id"] for x in sm.get("/api/technicians/candidates").json()["items"]}
    assert "Person tech1" in cand and "Person ceo" in cand
    r = sm.post("/api/technicians", {"employee_id": cand["Person tech1"], "skills": ["Battery", "battery", " Motor "], "availability": "BUSY"}); assert r.status_code == 201, r.text
    t = r.json(); assert t["skills"] == ["Battery", "Motor"] and t["user_id"] == who["tech1"].id and t["open_tickets"] == 0
    assert sm.post("/api/technicians", {"employee_id": cand["Person tech1"]}).status_code == 409               # already a technician
    assert sm.post("/api/technicians", {"employee_id": "nope"}).status_code == 422 and sm.post("/api/technicians", {"employee_id": cand["Person tech1"], "availability": "SLEEPING"}).status_code == 422
    tk = sm.post("/api/service-tickets", {"title": "Noise", "assigned_to": who["tech1"].id}).json()
    d = sm.get(f"/api/technicians/{t['id']}").json(); assert d["technician"]["open_tickets"] == 1 and [x["id"] for x in d["tickets"]] == [tk["id"]]
    assert sm.patch(f"/api/technicians/{t['id']}", {"is_active": False}).status_code == 409                    # still has open work
    sm.post(f"/api/service-tickets/{tk['id']}/assign", {"assigned_to": None})                                   # reuse the existing assign endpoint
    assert sm.patch(f"/api/technicians/{t['id']}", {"is_active": False}).json()["is_active"] is False
    assert sm.get("/api/technicians?active=false").json()["total"] >= 1 and sm.get("/api/technicians?skill=motor").json()["total"] >= 1
    s = sm.get("/api/technicians/summary").json(); assert s["total"] >= 1 and "by_availability" in s
    assert coo.get("/api/technicians").status_code == 200 and coo.patch(f"/api/technicians/{t['id']}", {"availability": "AVAILABLE"}).status_code == 403
    assert who["tech1"].get("/api/technicians").status_code == 403 and who["hr"].get("/api/technicians").status_code == 403
    assert parse(sm.get("/api/technicians/export"))[0][:2] == ["Technician ID (employee code)", "Name"]
    r2 = sm.post("/api/technicians", {"employee_id": cand["Person cto"]}); assert r2.status_code == 201 and r2.json()["availability"] is None   # never defaulted
    assert sm.get("/api/technicians?availability=NOT_SET").json()["total"] >= 1 and sm.get("/api/technicians/summary").json()["by_availability"].get("NOT_SET", 0) >= 1


# ---------------- Diagnostics ----------------
def test_diagnostics_not_configured_manual_faults_and_ticket_creation(who):
    sm, cto, t1 = who["sm"], who["cto"], who["tech1"]
    v = vehicle(who, "TS09DG0001"); vid = v["id"]
    st = sm.get("/api/diagnostics/status").json(); assert st["ai_configured"] is False and "Not configured" in st["message"]
    h = sm.get(f"/api/diagnostics/vehicles/{vid}").json(); assert h["faults"] == [] and h["runs"] == []        # no fabricated data
    assert sm.post(f"/api/diagnostics/vehicles/{vid}/run").status_code == 503
    assert sm.post(f"/api/diagnostics/vehicles/{vid}/faults", {"fault_code": "p0a80", "severity": "high", "detected_at": "2999-01-01T00:00:00Z"}).status_code == 422   # future
    r = sm.post(f"/api/diagnostics/vehicles/{vid}/faults", {"fault_code": "p0a80", "description": "Weak cell", "severity": "high", "detected_at": "2026-10-01T10:00:00Z"}); assert r.status_code == 201, r.text
    f = r.json(); assert f["fault_code"] == "P0A80" and f["severity"] == "HIGH" and f["source"] == "MANUAL"
    assert sm.get("/api/diagnostics/vehicles?q=TS09DG0001&with_faults=true").json()["items"][0]["active_faults"] == 1
    tk = sm.post(f"/api/diagnostics/faults/{f['id']}/ticket"); assert tk.status_code == 201, tk.text
    assert tk.json()["priority"] == "HIGH"
    assert sm.post(f"/api/diagnostics/faults/{f['id']}/ticket").status_code == 409                              # one ticket per fault
    assert sm.get(f"/api/diagnostics/vehicles/{vid}").json()["faults"][0]["ticket_number"] == tk.json()["ticket_number"]
    assert sm.get(f"/api/fleet/vehicles/{vid}").json()["tickets"][0]["ticket_number"] == tk.json()["ticket_number"]   # linked via registration
    assert sm.patch(f"/api/diagnostics/faults/{f['id']}", {"status": "RESOLVED"}).json()["resolved_at"] is not None
    assert sm.get(f"/api/diagnostics/vehicles/{vid}?status=ACTIVE").json()["faults"] == []
    assert cto.get("/api/diagnostics/status").status_code == 200 and cto.post(f"/api/diagnostics/vehicles/{vid}/faults", {"fault_code": "X1", "severity": "LOW", "detected_at": "2026-10-01T10:00:00Z"}).status_code == 403
    assert t1.post(f"/api/diagnostics/vehicles/{vid}/faults", {"fault_code": "U0100", "severity": "LOW", "detected_at": "2026-10-02T10:00:00Z"}).status_code == 201
    assert parse(cto.get("/api/diagnostics/export"))[0][1] == "Fault code"

def test_diagnostics_ai_run_stores_only_real_reply_and_logs_failures(who, monkeypatch):
    import diagapi
    sm = who["sm"]; vid = vehicle(who, "TS09DG0002")["id"]
    monkeypatch.setenv("EVCARE_AI_URL", "https://ai.example.test/diagnose"); monkeypatch.setenv("EVCARE_AI_API_KEY", "k")
    assert sm.get("/api/diagnostics/status").json()["ai_configured"] is True and "ai.example.test" not in sm.get("/api/diagnostics/status").text
    reply = {"faults": [{"id": "e1", "code": "P1", "severity": "critical", "detected_at": "2026-10-01T10:00:00Z"}, {"code": "bad", "severity": "nope", "detected_at": "2026-10-01T10:00:00Z"}]}
    monkeypatch.setattr(diagapi, "call_ai", lambda payload, telemetry=None: reply)
    r = sm.post(f"/api/diagnostics/vehicles/{vid}/run").json(); assert r["new_faults"] == 1 and r["skipped"] == 1
    assert sm.post(f"/api/diagnostics/vehicles/{vid}/run").json()["new_faults"] == 0                           # idempotent
    def boom(payload, telemetry=None): raise RuntimeError("Could not reach the AI service.")
    monkeypatch.setattr(diagapi, "call_ai", boom)
    assert sm.post(f"/api/diagnostics/vehicles/{vid}/run").status_code == 502
    h = sm.get(f"/api/diagnostics/vehicles/{vid}").json(); assert [x["source"] for x in h["faults"]] == ["EVCARE_AI"] and h["runs"][0]["outcome"] == "FAILED"


# ---------------- IoT ----------------
def test_iot_ingest_auth_latest_history_alerts_export_and_no_fake_data(who):
    ceo, sm, cto = who["ceo"], who["sm"], who["cto"]; c = ceo.c
    assert ceo.get("/api/iot/latest").json()["items"] == [] and ceo.get("/api/iot/summary").json()["devices"] == 0     # empty until real data arrives
    vid = vehicle(who, "TS09IO0001")["id"]
    r = ceo.post("/api/iot/devices", {"device_identifier": "BMS-001", "device_type": "BMS", "vehicle_id": vid, "offline_after_minutes": 5}); assert r.status_code == 201, r.text
    d = r.json(); tok = d["device_token"]; did = d["id"]; assert d["connection"] == "NEVER" and "token_hash" not in d
    assert ceo.post("/api/iot/devices", {"device_identifier": "bms-001"}).status_code == 409 and ceo.post("/api/iot/devices", {"device_identifier": "a b"}).status_code == 422
    H = {"X-Device-Id": "BMS-001", "X-Device-Token": tok}; anon = TestClient(c.app)
    body = {"readings": [{"metric": "battery_voltage", "value": 51.3, "unit": "V", "recorded_at": ISO}, {"metric": "temperature", "value": 41.5, "unit": "C", "recorded_at": ISO},
                         {"metric": "state_of_charge", "value": 80, "unit": "%", "recorded_at": ISO}]}
    assert anon.post("/api/iot/ingest", json=body).status_code == 422                                           # no credentials
    assert anon.post("/api/iot/ingest", json=body, headers={**H, "X-Device-Token": "wrong"}).status_code == 401
    assert anon.post("/api/iot/ingest", json=body, headers={"X-Device-Id": "nobody", "X-Device-Token": tok}).status_code == 401
    assert anon.post("/api/iot/ingest", json={"readings": [{"metric": "state_of_charge", "value": 140}]}, headers=H).status_code == 422   # impossible value
    assert anon.post("/api/iot/ingest", json={"readings": [{"metric": "Bad Name", "value": 1}]}, headers=H).status_code == 422
    assert anon.post("/api/iot/ingest", json={"readings": [{"metric": "x_y", "value": 1, "recorded_at": "2999-01-01T00:00:00Z"}]}, headers=H).status_code == 422
    r = anon.post("/api/iot/ingest", json=body, headers=H); assert r.status_code == 200 and r.json() == {"accepted": 3, "duplicates": 0}
    assert anon.post("/api/iot/ingest", json=body, headers=H).json()["accepted"] == 0                           # safe retry
    latest = {x["metric"]: x for x in sm.get("/api/iot/latest").json()["items"]}
    assert latest["battery_voltage"]["value"] == 51.3 and latest["battery_voltage"]["registration_number"] == "TS09IO0001" and latest["temperature"]["unit"] == "C"
    assert sm.get(f"/api/iot/devices?connection=ONLINE").json()["total"] == 1
    pts = sm.get(f"/api/iot/readings?metric=battery_voltage&device_id={did}&date_from={T0.date()}&date_to={T0.date()}").json(); assert len(pts["points"]) == 1 and pts["truncated"] is False
    assert sm.get("/api/iot/readings").status_code == 422                                                       # metric required for charts
    # alerts: none until a person enters limits
    assert sm.get("/api/iot/alerts").json() == {"threshold_alerts": [], "offline_devices": [], "limits_configured": False}
    assert sm.post("/api/iot/thresholds", {"metric": "temperature", "severity": "WARNING", "max_value": 40}).status_code == 403     # service manager cannot set limits
    assert ceo.post("/api/iot/thresholds", {"metric": "temperature", "severity": "WARNING", "max_value": 40}).status_code == 201
    assert ceo.post("/api/iot/thresholds", {"metric": "temperature", "severity": "CRITICAL", "max_value": 45}).status_code == 201
    assert ceo.post("/api/iot/thresholds", {"metric": "temperature", "severity": "CRITICAL", "min_value": 9, "max_value": 3}).status_code == 422
    a = sm.get("/api/iot/alerts").json()["threshold_alerts"]; assert [(x["metric"], x["severity"], x["breach"]) for x in a] == [("temperature", "WARNING", "ABOVE_MAX")]
    # offline detection from real last contact
    with psycopg.connect(main.os.environ["DATABASE_URL"], autocommit=True) as pg: pg.execute("update office_dashboard.iot_devices set last_seen_at=now()-interval '2 hours' where id=%s", (did,))
    assert [x["device_identifier"] for x in sm.get("/api/iot/alerts").json()["offline_devices"]] == ["BMS-001"] and sm.get("/api/iot/summary").json()["by_connection"] == {"OFFLINE": 1}
    # export honours filters; header-injection-safe cells
    rows = parse(cto.get("/api/iot/export?metric=temperature")); assert rows[0][0] == "Device ID" and len(rows) == 2 and rows[1][3] == "temperature"
    assert cto.post("/api/iot/devices", {"device_identifier": "X-1"}).status_code == 403 and who["hr"].get("/api/iot/latest").status_code == 403
    # token rotation invalidates the old token; deactivated devices are refused
    new = ceo.post(f"/api/iot/devices/{did}/rotate-token").json()["device_token"]; assert new != tok
    assert anon.post("/api/iot/ingest", json=body, headers=H).status_code == 401
    ceo.patch(f"/api/iot/devices/{did}", {"status": "INACTIVE"}); assert anon.post("/api/iot/ingest", json=body, headers={**H, "X-Device-Token": new}).status_code == 403
    assert sm.delete(f"/api/iot/devices/{did}").status_code == 403 and ceo.delete(f"/api/iot/devices/{did}").status_code == 200


# ======================= follow-up features (migration 013) =======================
CHAIN = ["NEW", "TRIAGED", "DIAGNOSIS", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "REPAIR", "QUALITY_CHECK", "COMPLETED"]
def move(sm, tk, target):
    cur = sm.get(f"/api/service-tickets/{tk['id']}").json()["ticket"]["status"]
    for st in CHAIN[CHAIN.index(cur) + 1: CHAIN.index(target) + 1]:
        r = sm.post(f"/api/service-tickets/{tk['id']}/transition", {"status": st}); assert r.status_code == 200, (st, r.text)

def test_technician_counts_workload_and_contact_protection(who, monkeypatch):
    import permissions
    sm, coo = who["sm"], who["coo"]
    cand = {x["name"]: x["id"] for x in sm.get("/api/technicians/candidates").json()["items"]}
    tid = sm.post("/api/technicians", {"employee_id": cand["Person sm"], "skills": ["Diagnostics"]}).json()["id"]    # the service manager's login can hold tickets too
    a, b, c = (sm.post("/api/service-tickets", {"title": f"T{i}", "assigned_to": sm.id}).json() for i in range(3))
    move(sm, b, "IN_PROGRESS"); move(sm, c, "COMPLETED")
    t = sm.get(f"/api/technicians/{tid}").json()["technician"]
    assert (t["assigned_tickets"], t["pending_tickets"], t["in_progress_tickets"], t["completed_tickets"], t["open_tickets"]) == (3, 1, 1, 1, 2)
    assert t["created_at"] is not None and t["employee_code"] == "SM"
    w = sm.get("/api/technicians/workload").json(); me = next(x for x in w["items"] if x["id"] == tid)
    assert (me["pending"], me["in_progress"], me["completed"], me["open"]) == (1, 1, 1, 2) and isinstance(w["unassigned_open_tickets"], int)
    assert sm.get(f"/api/technicians/{tid}").json()["technician"]["email"] == "sm@x.test"                          # authorised role sees contact details
    monkeypatch.setitem(permissions.GRANTS, "coo", permissions.GRANTS["coo"] - {"technician_contact.read"})         # a role WITHOUT the contact grant
    listing = coo.get("/api/technicians").json()
    assert listing["can_see_contact"] is False and all(x["email"] is None and x["phone"] is None and x["contact_hidden"] for x in listing["items"])
    assert coo.get(f"/api/technicians/{tid}").json()["technician"]["email"] is None
    assert "Email" not in parse(coo.get("/api/technicians/export"))[0] and "sm@x.test" not in coo.get("/api/technicians/export").text

def test_ticket_service_center_field_history_and_service_history(who):
    sm, t1 = who["sm"], who["tech1"]
    cid = sm.post("/api/garages", {"name": "Field Center", "city": "Nagpur"}).json()["id"]
    tk = sm.post("/api/service-tickets", {"title": "With center", "service_center_id": cid}).json()
    assert tk["service_center_name"] == "Field Center" and sm.get(f"/api/garages/{cid}").json()["tickets"][0]["id"] == tk["id"]
    assert t1.post("/api/service-tickets", {"title": "x", "service_center_id": cid}).status_code == 403              # technicians cannot choose a center
    assert sm.post("/api/service-tickets", {"title": "x", "service_center_id": "not-a-uuid"}).status_code == 422
    move(sm, tk, "COMPLETED")
    d = sm.get(f"/api/garages/{cid}").json(); assert d["tickets"] == [] and [x["id"] for x in d["service_history"]] == [tk["id"]]   # completed work moves to service history
    other = sm.post("/api/garages", {"name": "Second Center", "city": "Nagpur"}).json()["id"]
    r = sm.patch(f"/api/service-tickets/{tk['id']}", {"service_center_id": other}); assert r.status_code == 200 and r.json()["service_center_name"] == "Second Center"
    ev = [h for h in sm.get(f"/api/service-tickets/{tk['id']}/history").json()["items"] if h["event_type"] == "updated"][0]
    assert ev["detail"]["changes"]["service_center"] == {"from": "Field Center", "to": "Second Center"}               # names, not ids
    assert sm.patch(f"/api/service-tickets/{tk['id']}", {"service_center_id": other}).status_code == 200            # no-op edit is fine

def test_ticket_detail_shows_diagnostic_fault_it_came_from(who):
    sm = who["sm"]; vid = vehicle(who, "TS09DG0003")["id"]
    f = sm.post(f"/api/diagnostics/vehicles/{vid}/faults", {"fault_code": "P1111", "severity": "low", "detected_at": ISO}).json()
    tk = sm.post(f"/api/diagnostics/faults/{f['id']}/ticket").json()
    assert [x["fault_code"] for x in sm.get(f"/api/service-tickets/{tk['ticket_id']}").json()["diagnostic_faults"]] == ["P1111"]

def test_diagnostic_history_filters_by_vehicle_date_status_and_severity(who):
    sm = who["sm"]; v1, v2 = vehicle(who, "TS09DG0004")["id"], vehicle(who, "TS09DG0005")["id"]
    sm.post(f"/api/diagnostics/vehicles/{v1}/faults", {"fault_code": "A1", "severity": "low", "detected_at": "2026-01-10T10:00:00Z"})
    f2 = sm.post(f"/api/diagnostics/vehicles/{v1}/faults", {"fault_code": "A2", "severity": "critical", "detected_at": "2026-02-10T10:00:00Z"}).json()
    sm.post(f"/api/diagnostics/vehicles/{v2}/faults", {"fault_code": "B1", "severity": "high", "detected_at": "2026-02-11T10:00:00Z"})
    sm.patch(f"/api/diagnostics/faults/{f2['id']}", {"status": "RESOLVED"})
    codes = lambda q: sorted(x["fault_code"] for x in sm.get(f"/api/diagnostics/faults?{q}").json()["items"])
    assert codes(f"vehicle_id={v1}") == ["A1", "A2"] and codes("date_from=2026-02-01&date_to=2026-02-28&q=TS09DG000") == ["A2", "B1"]
    assert codes(f"vehicle_id={v1}&status=RESOLVED") == ["A2"] and codes("severity=HIGH&q=TS09DG0005") == ["B1"] and codes("source=MANUAL&q=TS09DG0005") == ["B1"]
    assert sm.get("/api/diagnostics/faults?date_from=2026-03-01&date_to=2026-01-01").status_code == 422
    assert [x["fault_code"] for x in sm.get(f"/api/diagnostics/vehicles/{v1}?date_from=2026-02-01").json()["faults"]] == ["A2"]
    assert sm.get("/api/diagnostics/faults?q=TS09DG0004").json()["items"][0]["registration_number"] == "TS09DG0004"
    assert who["hr"].get("/api/diagnostics/faults").status_code == 403

def test_ai_run_can_send_real_telemetry_but_never_location(who, monkeypatch):
    import diagapi
    ceo, sm = who["ceo"], who["sm"]; vid = vehicle(who, "TS09DG0006")["id"]
    monkeypatch.setenv("EVCARE_AI_URL", "https://ai.example.test/diagnose"); monkeypatch.setenv("EVCARE_AI_API_KEY", "k")
    tok = ceo.post("/api/iot/devices", {"device_identifier": "AI-DEV-1", "vehicle_id": vid}).json()["device_token"]
    TestClient(sm.c.app).post("/api/iot/ingest", headers={"X-Device-Id": "AI-DEV-1", "X-Device-Token": tok}, json={"readings": [
        {"metric": "battery_voltage", "value": 48.5, "unit": "V", "recorded_at": ISO}, {"metric": "latitude", "value": 17.38, "recorded_at": ISO}, {"metric": "longitude", "value": 78.48, "recorded_at": ISO}]})
    seen = {}
    monkeypatch.setattr(diagapi, "call_ai", lambda payload, telemetry=None: seen.update(telemetry=telemetry) or {"faults": []})
    r = sm.post(f"/api/diagnostics/vehicles/{vid}/run", {"include_telemetry": True}).json()
    assert r["telemetry_sent"] == 1 and [x["metric"] for x in seen["telemetry"]] == ["battery_voltage"]               # latitude/longitude never leave the system
    seen.clear(); sm.post(f"/api/diagnostics/vehicles/{vid}/run", {}); assert seen["telemetry"] == []                  # off by default
    assert who["tech1"].post(f"/api/diagnostics/vehicles/{vid}/run", {"include_telemetry": True}).status_code in (200, 403)

# ---------------- LOCATION ACCESS (CEO + Operations roles; technicians only for assigned vehicles; everyone else none) ----------------
_SEEDED = {}
def seed_location(who):
    if _SEEDED: return _SEEDED["v"]                        # the database is shared by the tests in this module: seed once
    ceo, sm = who["ceo"], who["sm"]
    v1, v2 = vehicle(who, "TS09LC0001"), vehicle(who, "TS09LC0002")
    anon = TestClient(ceo.c.app); toks = {}
    for ident, v in (("LOC-BMS-1", v1), ("LOC-GPS-1", v1), ("LOC-GPS-2", v2)):
        r = ceo.post("/api/iot/devices", {"device_identifier": ident, "device_type": "GPS" if "GPS" in ident else "BMS", "vehicle_id": v["id"]}); assert r.status_code == 201, r.text
        toks[ident] = r.json()["device_token"]
    send = lambda ident, readings: anon.post("/api/iot/ingest", headers={"X-Device-Id": ident, "X-Device-Token": toks[ident]}, json={"readings": readings})
    assert send("LOC-BMS-1", [{"metric": "battery_voltage", "value": 50.1, "unit": "V", "recorded_at": ISO}]).status_code == 200
    assert send("LOC-GPS-1", [{"metric": "latitude", "value": 17.385, "recorded_at": ISO}, {"metric": "longitude", "value": 78.486, "recorded_at": ISO}, {"metric": "gps_satellites", "value": 9, "recorded_at": ISO}]).status_code == 200
    assert send("LOC-GPS-2", [{"metric": "latitude", "value": 12.97, "recorded_at": ISO}, {"metric": "battery_voltage", "value": 49, "recorded_at": ISO}]).status_code == 200
    assert ceo.post("/api/iot/thresholds", {"metric": "latitude", "severity": "WARNING", "max_value": 10}).status_code == 201   # a limit that WOULD alert on location
    _SEEDED["v"] = (v1, v2); return v1, v2
LOC = {"latitude", "longitude", "gps_satellites"}
def metrics_of(resp, key="items"): return {x["metric"] for x in resp.json()[key]}

def test_location_full_access_for_ceo_and_operations_roles(who):
    seed_location(who)
    for role in ("ceo", "coo", "sm"):
        u = who[role]; assert u.get("/api/iot/summary").json()["location_access"] == "full"
        assert LOC <= metrics_of(u.get("/api/iot/latest")) and LOC <= metrics_of(u.get("/api/iot/metrics")) and LOC <= metrics_of(u.get("/api/iot/records?limit=200"))
        assert u.get("/api/iot/readings?metric=latitude").status_code == 200 and u.get("/api/iot/export?metric=latitude").status_code == 200
        assert any(a["metric"] == "latitude" for a in u.get("/api/iot/alerts").json()["threshold_alerts"])

def test_location_is_hidden_from_cto_everywhere_even_when_asked_by_name(who):
    seed_location(who); cto = who["cto"]
    assert cto.get("/api/iot/summary").json()["location_access"] == "none"
    assert not (LOC & metrics_of(cto.get("/api/iot/latest"))) and "battery_voltage" in metrics_of(cto.get("/api/iot/latest"))      # non-location telemetry still visible
    assert not (LOC & metrics_of(cto.get("/api/iot/metrics"))) and not (LOC & metrics_of(cto.get("/api/iot/records?limit=200")))
    assert cto.get("/api/iot/alerts").json()["threshold_alerts"] == []                                                              # a location limit never leaks as an alert
    assert [x for x in cto.get("/api/iot/thresholds").json()["items"] if x["metric"] == "latitude"] == []
    for url in ("/api/iot/latest?metric=latitude", "/api/iot/readings?metric=longitude", "/api/iot/records?metric=gps_satellites", "/api/iot/export?metric=latitude"):
        assert cto.get(url).status_code == 403, url
    ex = parse(cto.get("/api/iot/export")); assert len(ex) > 1 and not any(r[3] in LOC for r in ex[1:])                         # CSV export has no location rows
    dev = next(d for d in cto.get("/api/iot/devices").json()["items"] if d["device_identifier"] == "LOC-GPS-1")
    assert cto.get(f"/api/iot/devices/{dev['id']}").json()["latest"] == [] and cto.get(f"/api/iot/devices/{dev['id']}").json()["recent"] == []
    assert cto.post("/api/iot/thresholds", {"metric": "latitude", "severity": "CRITICAL", "max_value": 5}).status_code == 403

def test_roles_without_iot_access_get_nothing(who):
    seed_location(who)
    for role in ("hr", "emp"):
        for url in ("/api/iot/summary", "/api/iot/latest", "/api/iot/devices", "/api/iot/records", "/api/iot/readings?metric=latitude", "/api/iot/export"):
            assert who[role].get(url).status_code in (403,), (role, url)
    assert TestClient(who["ceo"].c.app).get("/api/iot/latest").status_code == 401                                                   # not signed in

def test_technician_sees_location_only_for_vehicles_with_an_open_ticket_assigned_to_them(who):
    v1, v2 = seed_location(who); t1, sm = who["tech1"], who["sm"]
    s = t1.get("/api/iot/summary").json(); assert s["location_access"] == "assigned_only" and s["scoped_to_assigned_vehicles"] is True
    assert t1.get("/api/iot/latest").json()["items"] == [] and t1.get("/api/iot/devices").json()["total"] == 0 and t1.get("/api/iot/records").json()["total"] == 0   # nothing assigned yet
    assert t1.get("/api/iot/readings?metric=latitude").json()["points"] == [] and t1.get("/api/iot/alerts").json()["threshold_alerts"] == []
    tk = sm.post("/api/service-tickets", {"title": "Check tracker", "vehicle_reference": "ts09 lc-0001", "assigned_to": t1.id}).json()      # formatting differences in the reference are ignored
    items = t1.get("/api/iot/latest").json()["items"]
    assert {x["registration_number"] for x in items} == {"TS09LC0001"} and LOC <= {x["metric"] for x in items}                     # own vehicle: incl. location
    assert {d["device_identifier"] for d in t1.get("/api/iot/devices").json()["items"]} == {"LOC-BMS-1", "LOC-GPS-1"}               # other vehicle's device is invisible
    assert t1.get(f"/api/iot/records?vehicle_id={v2['id']}").json()["total"] == 0 and t1.get(f"/api/iot/readings?metric=latitude&vehicle_id={v2['id']}").json()["points"] == []
    other = next(d for d in who["ceo"].get("/api/iot/devices").json()["items"] if d["device_identifier"] == "LOC-GPS-2")
    assert t1.get(f"/api/iot/devices/{other['id']}").status_code == 404
    own = next(d for d in t1.get("/api/iot/devices").json()["items"] if d["device_identifier"] == "LOC-GPS-1"); assert t1.get(f"/api/iot/devices/{own['id']}").status_code == 200
    assert t1.get("/api/iot/export").status_code == 403 and t1.post("/api/iot/devices", {"device_identifier": "NOPE-1"}).status_code == 403 and t1.post("/api/iot/thresholds", {"metric": "x_y", "severity": "WARNING", "max_value": 1}).status_code == 403
    sm.post(f"/api/service-tickets/{tk['id']}/assign", {"assigned_to": None})                                                        # reassigned away -> access ends immediately
    assert t1.get("/api/iot/latest").json()["items"] == [] and t1.get(f"/api/iot/devices/{own['id']}").status_code == 404
    tk2 = sm.post("/api/service-tickets", {"title": "Done job", "vehicle_reference": "TS09LC0001", "assigned_to": t1.id}).json(); move(sm, tk2, "COMPLETED")
    assert t1.get("/api/iot/latest").json()["items"] == []                                                                            # completed work no longer grants location access

def test_extra_location_metric_names_from_environment_are_protected(who, monkeypatch):
    seed_location(who); monkeypatch.setenv("IOT_EXTRA_LOCATION_METRICS", "battery_voltage")      # pretend the operator classes this name as location
    assert "battery_voltage" not in metrics_of(who["cto"].get("/api/iot/latest")) and who["cto"].get("/api/iot/latest?metric=battery_voltage").status_code == 403

# ---------------- IoT: device detail, raw records, stale flags ----------------
def test_iot_device_detail_records_and_stale_readings(who):
    ceo, sm = who["ceo"], who["sm"]; vid = vehicle(who, "TS09IO0009")["id"]
    d = ceo.post("/api/iot/devices", {"device_identifier": "DET-1", "vehicle_id": vid, "offline_after_minutes": 5}).json()
    assert TestClient(ceo.c.app).post("/api/iot/ingest", headers={"X-Device-Id": "DET-1", "X-Device-Token": d["device_token"]}, json={"readings": [
        {"metric": "temperature", "value": 30, "unit": "C", "recorded_at": (T0 - timedelta(minutes=30)).isoformat()}, {"metric": "temperature", "value": 31, "unit": "C", "recorded_at": ISO}]}).status_code == 200
    det = sm.get(f"/api/iot/devices/{d['id']}").json()
    assert det["device"]["device_identifier"] == "DET-1" and det["device"]["offline_after_minutes"] == 5 and len(det["recent"]) == 2 and det["recent"][0]["value"] == 31
    assert det["latest"][0]["value"] == 31 and det["latest"][0]["stale"] is True and det["latest"][0]["age_seconds"] >= 540          # recorded 10 min ago, limit 5 min -> stale, never "live"
    rec = sm.get(f"/api/iot/records?device_id={d['id']}&page=1&limit=1").json(); assert rec["total"] == 2 and len(rec["items"]) == 1 and rec["items"][0]["received_at"]
    assert sm.get("/api/iot/records?date_from=2026-03-01&date_to=2026-01-01").status_code == 422
    assert sm.get("/api/iot/devices/00000000-0000-0000-0000-000000000000").status_code == 404 and sm.get("/api/iot/devices/not-a-uuid").status_code == 404
