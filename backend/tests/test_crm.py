"""End-to-end CRM tests against a DISPOSABLE local Postgres (schema = db/001 + db/003). Never touches your Supabase."""
import pytest
pgserver = pytest.importorskip("pgserver")
import psycopg, bcrypt
from fastapi.testclient import TestClient
import main
from repo import UserRecord
from stores import RevocationStore, AuditSink
bc = lambda p: bcrypt.hashpw(p.encode(), bcrypt.gensalt(4)).decode()
U = {n: UserRecord(str(i), n, bc("pw"), r, True) for i, (n, r) in enumerate([("ceo", "ceo"), ("coo", "coo"), ("emp", "employee")], 1)}
class Fake:
    def find(self, i): return U.get(i)
    def find_by_id(self, i): return next((u for u in U.values() if u.id == i), None)
CFG = dict(role_map={}, active_values={"true"})
@pytest.fixture(scope="module")
def dsn(tmp_path_factory):
    try: srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e: pytest.skip(str(e))
    d = srv.get_uri()
    with psycopg.connect(d, autocommit=True) as c: c.execute(open("../db/001_foundation.sql").read()); c.execute(open("../db/003_crm.sql").read())
    yield d; srv.cleanup()
@pytest.fixture()
def mk(dsn, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", dsn)
    with psycopg.connect(dsn, autocommit=True) as c: c.execute("truncate office_dashboard.lead_activities, office_dashboard.leads, office_dashboard.contacts cascade")
    def make(user):
        c = TestClient(main.create_app(Fake(), CFG, "s", RevocationStore(str(tmp_path / "r")), AuditSink(str(tmp_path / "a")))); 
        if user: assert c.post("/api/auth/login", json={"username": user, "password": "pw"}).status_code == 200; c.headers["x-csrf-token"] = c.cookies.get("csrf")
        return c
    return make
def test_contact_create_read_update_search_archive_and_persist_across_relogin(mk):
    c = mk("ceo"); r = c.post("/api/crm/contacts", json={"full_name": "Asha Rao", "email": "asha@abc.test", "phone": "+91 98765 43210", "organization": "ABC Logistics"}); assert r.status_code == 201; cid = r.json()["id"]
    assert c.patch(f"/api/crm/contacts/{cid}", json={"organization": "ABC Fleet"}).json()["organization"] == "ABC Fleet"
    assert c.get("/api/crm/contacts?q=abc").json()["total"] == 1 and c.get("/api/crm/contacts?q=zzz").json()["total"] == 0
    c2 = mk("ceo"); assert c2.get(f"/api/crm/contacts/{cid}").json()["full_name"] == "Asha Rao"          # fresh app + new login = persisted
    assert c.delete(f"/api/crm/contacts/{cid}").json() == {"ok": True} and c.get(f"/api/crm/contacts/{cid}").status_code == 404
def test_validation_and_duplicates(mk):
    c = mk("ceo")
    for bad in ({"full_name": "A", "email": "nope"}, {"full_name": "A", "phone": "abc"}, {"email": "a@b.co"}, {"full_name": "x" * 200}): assert c.post("/api/crm/contacts", json=bad).status_code == 422, bad
    assert c.post("/api/crm/contacts", json={"full_name": "A", "email": "d@x.test"}).status_code == 201
    assert c.post("/api/crm/contacts", json={"full_name": "B", "email": "D@X.TEST"}).status_code == 409
    assert c.get("/api/crm/contacts/not-a-uuid").status_code == 404 and c.get("/api/crm/contacts/00000000-0000-0000-0000-000000000000").status_code == 404
def test_search_wildcards_are_literal(mk):
    c = mk("ceo"); c.post("/api/crm/contacts", json={"full_name": "Plain Name"}); assert c.get("/api/crm/contacts?q=%25").json()["total"] == 0
def test_lead_lifecycle_rules_and_link_without_duplicates(mk):
    c = mk("ceo"); cid = c.post("/api/crm/contacts", json={"full_name": "Lead Contact"}).json()["id"]
    l = c.post("/api/crm/leads", json={"title": "10 e-vans", "contact_id": cid, "source": "website", "value": 2500000}); assert l.status_code == 201 and l.json()["stage"] == "new"; lid = l.json()["id"]
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "contacted"}).json()["stage"] == "contacted"
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "proposal"}).json()["stage"] == "proposal"
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "new"}).status_code == 409                       # no going back
    assert c.delete(f"/api/crm/contacts/{cid}").status_code == 409                                          # open lead blocks archive
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "lost"}).status_code == 422                      # reason required
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "lost", "lost_reason": "budget"}).json()["stage"] == "lost"
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "won"}).status_code == 409                       # terminal
    assert c.post("/api/crm/leads", json={"title": "x", "value": -5}).status_code == 422 and c.post("/api/crm/leads", json={"title": "x", "contact_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert c.post(f"/api/crm/leads/{lid}/activities", json={"note": "called"}).status_code == 201 and len(c.get(f"/api/crm/leads/{lid}/activities").json()) == 1
    assert c.get("/api/crm/leads?stage=lost").json()["total"] == 1 and c.get("/api/crm/leads?stage=bogus").status_code == 422
def test_permissions_and_csrf(mk):
    anon = mk(None); assert anon.get("/api/crm/contacts").status_code == 401
    emp = mk("emp"); assert emp.get("/api/crm/contacts").status_code == 403 and emp.post("/api/crm/contacts", json={"full_name": "x"}).status_code == 403
    coo = mk("coo"); assert coo.get("/api/crm/contacts").json()["can_write"] is False and coo.post("/api/crm/contacts", json={"full_name": "x"}).status_code == 403
    ceo = mk("ceo"); del ceo.headers["x-csrf-token"]; assert ceo.post("/api/crm/contacts", json={"full_name": "x"}).status_code == 403
def test_ceo_dashboard_reflects_database_changes(mk):
    c = mk("ceo"); base = c.get("/api/dashboard/ceo").json(); assert base["kpis"]["New Leads"]["value"] == "0"
    for t, st in (("a", "new"), ("b", "new"), ("c", "contacted")): c.post("/api/crm/leads", json={"title": t, "stage": st})
    d = c.get("/api/dashboard/ceo").json(); assert d["kpis"]["New Leads"]["value"] == "3"
    assert {p["name"]: p["value"] for p in d["panels"]["pipeline"]}["New Lead"] == 2 and {p["name"]: p["value"] for p in d["panels"]["pipeline"]}["Contacted"] == 1
def test_dashboard_marks_crm_unavailable_when_db_unreachable(mk, monkeypatch):
    c = mk("ceo"); monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x"); d = c.get("/api/dashboard/ceo").json()
    assert "crm" in d["not_configured"] and "New Leads" not in d["kpis"]

# ---- regression tests for the audited bugs (no live Supabase needed: disposable local Postgres) ----
def test_pipeline_is_exactly_the_decided_stages_and_qualified_cannot_be_set(mk):
    c = mk("ceo"); r = c.get("/api/crm/leads").json()
    assert r["stages"] == ["new", "contacted", "proposal", "negotiation", "won", "lost"] and r["stage_labels"]["proposal"] == "Proposal Sent"
    assert c.post("/api/crm/leads", json={"title": "x", "stage": "qualified"}).status_code == 422
    lid = c.post("/api/crm/leads", json={"title": "x"}).json()["id"]
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "qualified"}).status_code == 422
def test_legacy_qualified_rows_still_work_and_can_only_move_forward(mk, dsn):
    c = mk("ceo"); lid = c.post("/api/crm/leads", json={"title": "legacy"}).json()["id"]
    with psycopg.connect(dsn, autocommit=True) as k: k.execute("update office_dashboard.leads set stage='qualified' where id=%s", (lid,))
    assert c.get("/api/crm/leads?stage=qualified").json()["total"] == 1
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "contacted"}).status_code == 409      # qualified ranks after contacted
    assert c.patch(f"/api/crm/leads/{lid}", json={"stage": "proposal"}).json()["stage"] == "proposal"
def test_null_or_blank_required_fields_are_422_not_500(mk):
    c = mk("ceo"); lid = c.post("/api/crm/leads", json={"title": "ok"}).json()["id"]
    for bad in ({"stage": None}, {"title": None}, {"title": "   "}): assert c.patch(f"/api/crm/leads/{lid}", json=bad).status_code == 422, bad
    assert c.post("/api/crm/leads", json={"title": "   "}).status_code == 422
    assert c.patch(f"/api/crm/leads/{lid}", json={"title": "  Trimmed  "}).json()["title"] == "Trimmed"
def test_lead_can_be_unlinked_from_its_contact(mk):
    c = mk("ceo"); cid = c.post("/api/crm/contacts", json={"full_name": "P"}).json()["id"]
    lid = c.post("/api/crm/leads", json={"title": "t", "contact_id": cid}).json()["id"]
    assert c.patch(f"/api/crm/leads/{lid}", json={"contact_id": None}).json()["contact_id"] is None
def test_lead_note_is_audited_and_listed(mk, tmp_path):
    c = mk("ceo"); lid = c.post("/api/crm/leads", json={"title": "t"}).json()["id"]
    assert c.post(f"/api/crm/leads/{lid}/activities", json={"note": "called"}).status_code == 201
    assert "lead_note_added" in (tmp_path / "a").read_text() and c.get(f"/api/crm/leads/{lid}/activities").json()[0]["note"] == "called"
def test_snapshot_failure_is_logged_without_secrets(caplog):
    import crm; caplog.set_level("WARNING", logger="crm")
    assert crm.snapshot("postgresql://u:SECRETPW@127.0.0.1:1/x") is None
    assert "CRM snapshot unavailable" in caplog.text and "SECRETPW" not in caplog.text

# ---- Delete = archive: permissions enforced server-side, soft delete, audit trail ----
import json
def audit_rows(tmp_path): return [json.loads(l) for l in (tmp_path / "a").read_text().splitlines()]
def test_ceo_delete_is_a_soft_archive_with_full_audit_record(mk, dsn, tmp_path):
    c = mk("ceo"); cid = c.post("/api/crm/contacts", json={"full_name": "Gone", "email": "g@x.test"}).json()["id"]
    assert c.get("/api/crm/contacts").json()["can_archive"] is True
    assert c.delete(f"/api/crm/contacts/{cid}").status_code == 200
    assert c.get("/api/crm/contacts").json()["total"] == 0 and c.get(f"/api/crm/contacts/{cid}").status_code == 404      # hidden from active views
    with psycopg.connect(dsn) as k: assert k.execute("select is_archived from office_dashboard.contacts where id=%s", (cid,)).fetchone()[0] is True   # row kept
    a = [r for r in audit_rows(tmp_path) if r["action"] == "contact_archived"][0]
    assert a["user"] == "1" and a["record_type"] == "contact" and a["record"] == cid and a["ts"] > 0
    assert c.post("/api/crm/contacts", json={"full_name": "Again", "email": "g@x.test"}).status_code == 201                  # email reusable after archive
def test_lead_delete_keeps_notes_hides_lead_and_leaves_dashboard_counts(mk, dsn, tmp_path):
    c = mk("ceo"); lid = c.post("/api/crm/leads", json={"title": "bye"}).json()["id"]; c.post(f"/api/crm/leads/{lid}/activities", json={"note": "n"})
    assert c.get("/api/dashboard/ceo").json()["kpis"]["New Leads"]["value"] == "1"
    assert c.delete(f"/api/crm/leads/{lid}").status_code == 200
    assert c.get("/api/crm/leads").json()["total"] == 0 and c.get("/api/dashboard/ceo").json()["kpis"]["New Leads"]["value"] == "0"
    with psycopg.connect(dsn) as k: assert k.execute("select count(*) from office_dashboard.lead_activities where lead_id=%s", (lid,)).fetchone()[0] == 1
    a = [r for r in audit_rows(tmp_path) if r["action"] == "lead_archived"][0]; assert a["record_type"] == "lead" and a["record"] == lid and a["user"] == "1"
def test_write_permission_alone_does_not_allow_delete(mk, monkeypatch, tmp_path):
    monkeypatch.setenv("CRM_WRITE_ROLES", "ceo,coo"); ceo = mk("ceo"); coo = mk("coo")
    cid = ceo.post("/api/crm/contacts", json={"full_name": "K"}).json()["id"]; lid = ceo.post("/api/crm/leads", json={"title": "K"}).json()["id"]
    assert coo.post("/api/crm/contacts", json={"full_name": "by coo"}).status_code == 201 and coo.get("/api/crm/contacts").json()["can_archive"] is False
    assert coo.delete(f"/api/crm/contacts/{cid}").status_code == 403 and coo.delete(f"/api/crm/leads/{lid}").status_code == 403
    assert ceo.get(f"/api/crm/contacts/{cid}").status_code == 200                                                            # nothing was archived
    d = [r for r in audit_rows(tmp_path) if r["action"] == "crm_archive_denied"]; assert d and d[0]["user"] == "2"
def test_delete_can_be_granted_to_coo_by_config_only(mk, monkeypatch):
    monkeypatch.setenv("CRM_ARCHIVE_ROLES", "ceo,coo"); ceo = mk("ceo"); coo = mk("coo"); cid = ceo.post("/api/crm/contacts", json={"full_name": "K"}).json()["id"]
    assert coo.delete(f"/api/crm/contacts/{cid}").status_code == 200
def test_archive_role_must_also_have_crm_read_access_and_others_never_delete(mk, monkeypatch):
    monkeypatch.setenv("CRM_ARCHIVE_ROLES", "ceo,employee"); ceo = mk("ceo"); emp = mk("emp"); cid = ceo.post("/api/crm/contacts", json={"full_name": "K"}).json()["id"]
    assert emp.delete(f"/api/crm/contacts/{cid}").status_code == 403                                                          # listed, but no CRM read access
    anon = mk(None); assert anon.delete(f"/api/crm/contacts/{cid}").status_code == 401
    ceo2 = mk("ceo"); del ceo2.headers["x-csrf-token"]; assert ceo2.delete(f"/api/crm/contacts/{cid}").status_code == 403    # CSRF still enforced
def test_deleting_twice_or_unknown_id_is_404_and_not_audited_as_success(mk, tmp_path):
    c = mk("ceo"); cid = c.post("/api/crm/contacts", json={"full_name": "K"}).json()["id"]; c.delete(f"/api/crm/contacts/{cid}")
    assert c.delete(f"/api/crm/contacts/{cid}").status_code == 404 and c.delete("/api/crm/leads/not-a-uuid").status_code == 404
    assert len([r for r in audit_rows(tmp_path) if r["action"] == "contact_archived"]) == 1
