"""Stage 4 guards that apply to the whole app, not one module."""
import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

import main
from stores import RevocationStore, AuditSink
from test_auth import Fake, CFG

# The ONLY /api routes allowed to run without a user session, and why. Anything new must be added here deliberately (and justified in review).
PUBLIC = {
    ("POST", "/api/auth/login"): "creates the session",
    ("POST", "/api/auth/forgot"): "generic response, no account enumeration",
    ("POST", "/api/gps/ingest"): "device token / HMAC authenticated",
    ("POST", "/api/gps/webhook/{provider}"): "provider signature authenticated",
    ("POST", "/api/iot/ingest"): "device token authenticated",
}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)       # also proves the app starts and degrades safely with no database configured
    return main.create_app(Fake(), CFG, "s", RevocationStore(str(tmp_path / "r.db")), AuditSink(str(tmp_path / "a.jsonl")))


def _deps(d):
    for x in d.dependencies:
        yield x.call; yield from _deps(x)


def test_every_api_route_requires_a_session_except_the_documented_public_ones(app):
    open_routes = {}
    for r in app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"): continue
        names = {getattr(c, "__name__", "") for c in _deps(r.dependant)}
        if not names & {"session", "csrf", "dep"}:
            for m in r.methods: open_routes[(m, r.path)] = names
    assert set(open_routes) == set(PUBLIC), f"unexpected unauthenticated routes: {set(open_routes) ^ set(PUBLIC)}"


def test_every_state_changing_route_requires_csrf_or_is_a_documented_public_route(app):
    for r in app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"): continue
        for m in r.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            if (m, r.path) in PUBLIC: continue
            names = {getattr(c, "__name__", "") for c in _deps(r.dependant)}
            assert "csrf" in names or "dep" in names, f"{m} {r.path} has no CSRF protection"


def test_unauthenticated_get_routes_return_401_not_data(app):
    c = TestClient(app)
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/") and "GET" in r.methods and "{" not in r.path and ("GET", r.path) not in PUBLIC:
            assert c.get(r.path).status_code in (401, 403), r.path


def test_ceo_dashboard_without_a_database_degrades_instead_of_failing(app):
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/auth/login", json={"username": "ceo1", "password": "pw-ceo"}).status_code == 200
    r = c.get("/api/dashboard/ceo")
    assert r.status_code == 200, r.text
    b = r.json(); assert b["not_configured"] == ["crm"] and b["kpis"] == {} and b["panels"] == {}, "missing database must be reported as not configured: no KPI value, no zero"


def test_routes_needing_the_database_return_503_when_it_is_not_configured(app):
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/api/auth/login", json={"username": "ceo1", "password": "pw-ceo"})
    r = c.get("/api/intelligence/overview"); assert r.status_code == 503 and "DATABASE_URL" not in r.text


def test_api_responses_are_not_cacheable_and_errors_do_not_leak(app):
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/auth/me"); assert r.status_code == 401 and r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    r = c.get("/api/does-not-exist"); assert r.status_code == 404 and "Traceback" not in r.text
