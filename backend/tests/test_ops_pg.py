"""Service Tickets + Fleet Management end-to-end against a DISPOSABLE local Postgres (pgserver), applying the real migrations
db/001, 005, 010, 011 and logging in through the real auth routes. Skipped if pgserver is absent."""
import csv, io, pathlib
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
PEOPLE = [("ceo", "ceo"), ("sm", "service_manager"), ("tech1", "technician"), ("tech2", "technician"), ("coo", "coo"), ("hr", "hr")]

@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(f"cannot start disposable Postgres: {e}")
    d = srv.get_uri(); h = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
    with psycopg.connect(d, autocommit=True) as c:
        for f in ("001_foundation", "005_audit_log", "010_service_tickets", "011_ops_tickets_fleet", "011_ops_tickets_fleet"):   # 011 twice: must be re-runnable
            c.execute((DB / f"{f}.sql").read_text(encoding="utf-8"))
        for u, role in PEOPLE:
            eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email) values(%s,%s,%s) returning id", (u.upper(), f"Person {u}", f"{u}@x.test")).fetchone()[0]
            c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role) values(%s,%s,%s,%s)", (eid, u, h, role))
    yield d; srv.cleanup()

@pytest.fixture()
def app(dsn, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", dsn)
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

def parse(resp): return list(csv.reader(io.StringIO(resp.text.lstrip("\ufeff"))))

# ---------------- Service tickets ----------------
def test_ticket_lifecycle_edit_assign_history_and_scoping(who):
    sm, t1, t2, coo = who["sm"], who["tech1"], who["tech2"], who["coo"]
    techs = sm.get("/api/service-tickets/technicians").json()["items"]; assert {x["id"] for x in techs} >= {t1.id, t2.id}
    r = sm.post("/api/service-tickets", {"title": "  Battery not charging ", "category": "BATTERY", "priority": "HIGH", "due_date": "2030-01-01", "customer_name": "Acme", "vehicle_reference": "KA01AB1234"})
    assert r.status_code == 201, r.text; t = r.json(); tid = t["id"]
    assert t["title"] == "Battery not charging" and t["category"] == "BATTERY" and t["status"] == "NEW" and t["ticket_number"].startswith("IVT-")
    # edit records a diff in history; unchanged edit adds nothing
    assert sm.patch(f"/api/service-tickets/{tid}", {"priority": "URGENT", "description": "Charger LED off"}).json()["priority"] == "URGENT"
    n = len(sm.get(f"/api/service-tickets/{tid}/history").json()["items"]); sm.patch(f"/api/service-tickets/{tid}", {"priority": "URGENT"})
    assert len(sm.get(f"/api/service-tickets/{tid}/history").json()["items"]) == n
    assert sm.patch(f"/api/service-tickets/{tid}", {}).status_code == 422 and sm.patch(f"/api/service-tickets/{tid}", {"priority": "P0"}).status_code == 422
    assert sm.patch(f"/api/service-tickets/{tid}", {"title": None}).status_code == 422
    # technicians cannot see an unassigned ticket they did not create, nor assign; coo is read-only
    assert t1.get(f"/api/service-tickets/{tid}").status_code == 403
    assert t1.post(f"/api/service-tickets/{tid}/assign", {"assigned_to": t1.id}).status_code == 403
    assert coo.patch(f"/api/service-tickets/{tid}", {"title": "x"}).status_code == 403
    assert sm.post(f"/api/service-tickets/{tid}/assign", {"assigned_to": who["hr"].id}).status_code == 422      # not a technician
    a = sm.post(f"/api/service-tickets/{tid}/assign", {"assigned_to": t1.id}); assert a.status_code == 200 and a.json()["assigned_name"] == "Person tech1"
    assert t2.get(f"/api/service-tickets/{tid}").status_code == 403 and t2.patch(f"/api/service-tickets/{tid}", {"title": "hack"}).status_code == 403
    assert t1.get(f"/api/service-tickets/{tid}").json()["ticket"]["can_edit"] is True
    # lifecycle: invalid jump refused, valid chain accepted, resolved_at set on COMPLETED
    assert sm.post(f"/api/service-tickets/{tid}/transition", {"status": "CLOSED"}).status_code == 409
    for st, who_ in [("TRIAGED", sm), ("DIAGNOSIS", sm), ("ASSIGNED", sm), ("ACCEPTED", t1), ("IN_PROGRESS", t1), ("REPAIR", t1), ("QUALITY_CHECK", t1), ("COMPLETED", sm)]:
        r = who_.post(f"/api/service-tickets/{tid}/transition", {"status": st}); assert r.status_code == 200, (st, r.text)
    assert r.json()["resolved_at"] and sm.post(f"/api/service-tickets/{tid}/assign", {"assigned_to": t2.id}).status_code == 409
    assert t1.post(f"/api/service-tickets/{tid}/comments", {"comment": "Replaced charger"}).status_code == 201
    d = sm.get(f"/api/service-tickets/{tid}").json()
    kinds = [e["event_type"] for e in d["history"]]; assert kinds[-1] == "created" and {"updated", "assigned", "status_changed", "comment"} <= set(kinds)
    assert d["history"][0]["event_type"] == "status_changed" or d["history"][0]["event_type"] == "comment"   # newest first
    for st in ("CUSTOMER_CONFIRMATION", "CLOSED"): assert sm.post(f"/api/service-tickets/{tid}/transition", {"status": st}).status_code == 200
    assert sm.patch(f"/api/service-tickets/{tid}", {"title": "after close"}).status_code == 409
    assert sm.get("/api/service-tickets/not-a-uuid").status_code == 404

def test_ticket_filters_summary_and_export(who):
    sm, t1, coo, hr = who["sm"], who["tech1"], who["coo"], who["hr"]
    mk = lambda **k: sm.post("/api/service-tickets", {"title": "T", **k}).json()
    base = sm.get("/api/service-tickets/summary").json()
    a = mk(title="=HYPERLINK(\"http://evil\")", category="MOTOR", priority="URGENT", due_date="2020-01-01", customer_name="Zed Fleet", assigned_to=t1.id)
    b = mk(title="Tyre wear", category="TYRES", priority="LOW", vehicle_reference="MH12XY9999")
    s = sm.get("/api/service-tickets/summary").json()
    assert s["total"] == base["total"] + 2 and s["overdue"] == base["overdue"] + 1 and s["unassigned"] == base["unassigned"] + 1 and s["urgent_open"] == base["urgent_open"] + 1
    assert s["groups"]["open"] >= 2
    ids = lambda **p: {x["id"] for x in sm.get("/api/service-tickets", params=p).json()["items"]}
    assert a["id"] in ids(priority="URGENT") and b["id"] not in ids(priority="URGENT")
    assert ids(category="TYRES") >= {b["id"]} and a["id"] not in ids(category="TYRES")
    assert a["id"] in ids(assigned=t1.id) and b["id"] in ids(assigned="unassigned") and a["id"] not in ids(assigned="unassigned")
    assert a["id"] in ids(overdue="true") and b["id"] not in ids(overdue="true")
    assert ids(q="MH12XY") == {b["id"]} and a["id"] in ids(q="zed") and a["id"] in ids(q="person tech1")
    assert ids(q="100%") == set() and ids(q="_") == set()          # wildcard characters are literal
    assert a["id"] in ids(group="open") and ids(group="completed") .isdisjoint({a["id"], b["id"]})
    assert sm.get("/api/service-tickets", params={"priority": "bogus"}).status_code == 422 and sm.get("/api/service-tickets", params={"group": "x"}).status_code == 422
    assert ids(date_from="2999-01-01") == set()
    # export honours filters, neutralises spreadsheet formulas, is permission-gated
    r = sm.get("/api/service-tickets/export", params={"priority": "URGENT"}); assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = parse(r); assert rows[0][:3] == ["Ticket ID", "Title", "Description"] and any(x[1].startswith("'=HYPERLINK") for x in rows[1:]) and all(x[3] == "URGENT" for x in rows[1:])
    assert coo.get("/api/service-tickets/export").status_code == 200   # COO is a read-only role that may export
    assert t1.get("/api/service-tickets/export").status_code == 403 and hr.get("/api/service-tickets").status_code == 403
    # technician sees only their own tickets
    mine = {x["id"] for x in t1.get("/api/service-tickets").json()["items"]}; assert a["id"] in mine and b["id"] not in mine
    assert t1.get("/api/service-tickets/summary").json()["total"] == len(mine)

# ---------------- Fleet ----------------
V = {"registration_number": " ka 01 ab 1234 ", "vehicle_type": "THREE_WHEELER", "make": "Mahindra", "model": "Treo", "battery_capacity_kwh": 7.37, "customer_name": "Acme Logistics"}

def test_fleet_crud_status_service_history_and_rules(who):
    sm, t1, coo, hr, ceo = who["sm"], who["tech1"], who["coo"], who["hr"], who["ceo"]
    r = sm.post("/api/fleet/vehicles", V); assert r.status_code == 201, r.text; v = r.json(); vid = v["id"]
    assert v["registration_number"] == "KA 01 AB 1234" and v["status"] == "ACTIVE" and float(v["battery_capacity_kwh"]) == 7.37
    assert sm.post("/api/fleet/vehicles", {**V, "registration_number": "ka 01 ab 1234"}).status_code == 409        # case-insensitive duplicate
    for bad in ({"registration_number": "!!"}, {"vehicle_type": "BOAT"}, {"battery_capacity_kwh": -5}, {"battery_capacity_kwh": 0}, {"status": "FLYING"}, {"make": " "}):
        assert sm.post("/api/fleet/vehicles", {**V, "registration_number": "TN09ZZ0001", **bad}).status_code == 422, bad
    # permissions
    assert t1.get("/api/fleet/vehicles").status_code == 200 and t1.post("/api/fleet/vehicles", V).status_code == 403
    assert coo.get("/api/fleet/vehicles").status_code == 200 and coo.patch(f"/api/fleet/vehicles/{vid}", {"status": "IDLE"}).status_code == 403 and coo.get("/api/fleet/export").status_code == 200
    assert hr.get("/api/fleet/vehicles").status_code == 403 and t1.get("/api/fleet/export").status_code == 403 and t1.delete(f"/api/fleet/vehicles/{vid}").status_code == 403
    # edit + status management
    e = sm.patch(f"/api/fleet/vehicles/{vid}", {"status": "IN_SERVICE", "odometer_km": 1200}); assert e.status_code == 200 and e.json()["status"] == "IN_SERVICE"
    assert sm.patch(f"/api/fleet/vehicles/{vid}", {"status": None}).status_code == 422 and sm.patch(f"/api/fleet/vehicles/{vid}", {}).status_code == 422
    other = sm.post("/api/fleet/vehicles", {**V, "registration_number": "MH12XY9999"}).json()
    assert sm.patch(f"/api/fleet/vehicles/{other['id']}", {"registration_number": "ka01ab1234"}).status_code == 409
    # service history; odometer only moves forward
    s1 = sm.post(f"/api/fleet/vehicles/{vid}/service-history", {"service_date": "2026-01-10", "service_type": "Battery check", "cost": 1500.5, "odometer_km": 3000, "technician_name": "Ravi"})
    assert s1.status_code == 201, s1.text
    assert sm.post(f"/api/fleet/vehicles/{vid}/service-history", {"service_date": "2026-02-10", "service_type": "Brake pads", "cost": 500, "odometer_km": 100}).status_code == 201
    assert sm.post(f"/api/fleet/vehicles/{vid}/service-history", {"service_date": "2999-01-01", "service_type": "Future"}).status_code == 422
    assert sm.post(f"/api/fleet/vehicles/{vid}/service-history", {"service_date": "2026-01-01", "service_type": "x", "ticket_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    assert sm.post(f"/api/fleet/vehicles/{vid}/service-history", {"service_date": "2026-01-01", "service_type": "x", "cost": -1}).status_code == 422
    d = sm.get(f"/api/fleet/vehicles/{vid}").json()
    assert float(d["vehicle"]["odometer_km"]) == 3000 and len(d["service_history"]) == 2 and d["total_service_cost"] == 2000.5 and d["service_history"][0]["service_type"] == "Brake pads"
    # a ticket whose vehicle reference matches the registration shows up on the vehicle
    sm.post("/api/service-tickets", {"title": "Noise from motor", "vehicle_reference": "ka 01 ab 1234".upper()})
    assert any(t["title"] == "Noise from motor" for t in sm.get(f"/api/fleet/vehicles/{vid}").json()["tickets"])
    # search / filters / summary / export
    ids = lambda **p: {x["id"] for x in sm.get("/api/fleet/vehicles", params=p).json()["items"]}
    assert vid in ids(q="treo") and vid in ids(q="acme") and vid in ids(q="KA 01") and ids(q="100%") == set()
    assert vid in ids(status="IN_SERVICE") and other["id"] not in ids(status="IN_SERVICE") and vid in ids(vehicle_type="THREE_WHEELER") and ids(vehicle_type="BUS") == set()
    assert sm.get("/api/fleet/vehicles", params={"status": "nope"}).status_code == 422
    sm_ = sm.get("/api/fleet/summary").json(); assert sm_["total"] >= 2 and sm_["by_status"]["IN_SERVICE"] >= 1 and sm_["total_kwh"] > 0
    rows = parse(sm.get("/api/fleet/export", params={"status": "IN_SERVICE"})); assert rows[0][0] == "Registration" and rows[1][0] == "KA 01 AB 1234" and rows[1][10] == "2026-02-10" and rows[1][11] == "2"
    # archive frees the registration number, hides the vehicle, keeps history
    assert sm.delete(f"/api/fleet/vehicles/{vid}").status_code == 403          # archiving is CEO-only by policy
    assert ceo.delete(f"/api/fleet/vehicles/{vid}").status_code == 200 and sm.get(f"/api/fleet/vehicles/{vid}").status_code == 404 and vid not in ids()
    assert sm.post("/api/fleet/vehicles", {**V, "registration_number": "KA01AB1234"}).status_code == 201
    assert sm.get("/api/fleet/vehicles/not-a-uuid").status_code == 404
    with psycopg.connect(main.os.environ["DATABASE_URL"]) as c:
        assert c.execute("select count(*) from office_dashboard.audit_log where entity_type='fleet_vehicle'").fetchone()[0] >= 6
        assert c.execute("select count(*) from office_dashboard.fleet_service_history where vehicle_id=%s", (vid,)).fetchone()[0] == 2
