import os, bcrypt, pytest
from fastapi.testclient import TestClient
from werkzeug.security import generate_password_hash
import config, main
from stores import RevocationStore, AuditSink
from repo import UserRecord
bc = lambda p: bcrypt.hashpw(p.encode(), bcrypt.gensalt(4)).decode()
USERS = {"ceo1": UserRecord("1", "Sri Hari", bc("pw-ceo"), "CEO", True),
 "coo1": UserRecord("2", "Coo", bc("pw-coo"), "coo", True), "cto1": UserRecord("3", "Cto", bc("pw-cto"), "cto", True),
 "sm1": UserRecord("4", "SM", bc("pw-sm"), "Service Manager", True), "hr1": UserRecord("5", "HR", bc("pw-hr"), "hr", True),
 "tech001": UserRecord("6", "Tech", bc("pw-t"), "technician", True), "emp001": UserRecord("7", "Emp", generate_password_hash("pw-e"), "employee", True),
 "off": UserRecord("8", "Off", bc("pw-off"), "employee", False), "weird": UserRecord("9", "W", bc("pw-w"), "superuser", True),
 "legacy": UserRecord("10", "L", "plaintext-or-unknown", "employee", True)}
class Fake:
    def __init__(self): self.u = {k: UserRecord(v.id, v.name, v.pw_hash, v.role_raw, v.active) for k, v in USERS.items()}
    def find(self, i): return self.u.get(i)
    def find_by_id(self, i): return next((v for v in self.u.values() if v.id == i), None)
CFG = dict(role_map={"ceo": "ceo", "service manager": "service_manager"}, active_values={"true"})
@pytest.fixture()
def env(tmp_path):
    f = Fake(); db = str(tmp_path / "r.db"); log = str(tmp_path / "a.jsonl")
    mk = lambda: TestClient(main.create_app(f, CFG, "test-secret", RevocationStore(db), AuditSink(log)))
    return f, mk, log
@pytest.fixture()
def c(env): return env[1]()
def csrf(c): return {"x-csrf-token": c.cookies.get("csrf")}
def login(c, u, p, **k): return c.post("/api/auth/login", json={"username": u, "password": p, **k})
ROLES = [("ceo1", "pw-ceo", "ceo"), ("coo1", "pw-coo", "coo"), ("cto1", "pw-cto", "cto"), ("sm1", "pw-sm", "service_manager"),
         ("hr1", "pw-hr", "hr"), ("tech001", "pw-t", "technician"), ("emp001", "pw-e", "employee")]
@pytest.mark.parametrize("u,p,role", ROLES)
def test_login_returns_role_and_session(c, u, p, role):
    r = login(c, u, p); assert r.status_code == 200 and r.json()["role"] == role
    assert "httponly" in r.headers["set-cookie"].lower(); assert c.get("/api/auth/me").json()["role"] == role
def test_username_case_insensitive(c): assert login(c, "CEO1", "pw-ceo").status_code == 200
@pytest.mark.parametrize("u,p", [("ceo1", "bad"), ("nobody", "x"), ("off", "pw-off"), ("weird", "pw-w"), ("legacy", "plaintext-or-unknown")])
def test_login_rejected(c, u, p):
    assert login(c, u, p).status_code == 401; assert c.get("/api/auth/me").status_code == 401
def test_error_does_not_reveal_whether_user_exists(c): assert login(c, "nobody", "x").json() == login(c, "ceo1", "bad").json()
def test_me_requires_session(c): assert c.get("/api/auth/me").status_code == 401
def test_tampered_cookie_rejected(c):
    login(c, "ceo1", "pw-ceo"); c.cookies.set("session", c.cookies.get("session") + "x"); assert c.get("/api/auth/me").status_code == 401
def test_logout_invalidates_even_replayed_cookie(c):
    login(c, "ceo1", "pw-ceo"); tok = c.cookies.get("session"); assert c.post("/api/auth/logout", headers=csrf(c)).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    c.cookies.set("session", tok); assert c.get("/api/auth/me").status_code == 401
def test_session_vs_remember_lifetime(c):
    assert "max-age" not in login(c, "ceo1", "pw-ceo").headers["set-cookie"].lower()
    assert "max-age=2592000" in login(c, "ceo1", "pw-ceo", remember=True).headers["set-cookie"].lower()
@pytest.mark.parametrize("u,p,role", ROLES)
def test_portal_access_matrix(c, u, p, role):
    login(c, u, p)
    for portal in config.PORTAL_ROLES: assert c.get(f"/api/dashboard/{portal}").status_code == (200 if portal == role or (role == "ceo" and portal in ("coo", "cto")) else 403)
def test_dashboard_unauthenticated_and_unknown(c):
    assert c.get("/api/dashboard/ceo").status_code == 401
    login(c, "ceo1", "pw-ceo"); assert c.get("/api/dashboard/cco").status_code == 404
def test_rate_limit(c):
    for _ in range(8): login(c, "ceo1", "bad")
    assert login(c, "ceo1", "pw-ceo").status_code == 429
def test_passwords_detect_and_fail_closed():
    import passwords as P
    assert P.detect_scheme(bc("x")) == "bcrypt" and P.detect_scheme(generate_password_hash("x")) == "werkzeug"
    assert P.verify("x", "") == (False, "unknown") and P.verify("x", "plain")[0] is False
def test_config_refuses_guessing(monkeypatch):
    for k in ("USERS_TABLE", "COL_ID"): monkeypatch.delenv(k, raising=False)
    with pytest.raises(config.ConfigError): config.load()
def test_config_rejects_injection(monkeypatch):
    for k, v in dict(USERS_TABLE="users;drop table x", COL_ID="id", COL_NAME="n", COL_LOGIN="l", COL_PASSWORD="p", COL_ROLE="r").items(): monkeypatch.setenv(k, v)
    with pytest.raises(config.ConfigError): config.load()

def test_remember_me_is_off_by_default(c):
    r = login(c, "ceo1", "pw-ceo"); assert "max-age" not in r.headers["set-cookie"].lower()
def test_deactivated_user_loses_session_immediately(env):
    f, mk, _ = env; c = mk(); login(c, "emp001", "pw-e"); assert c.get("/api/auth/me").status_code == 200
    f.u["emp001"].active = False; assert c.get("/api/auth/me").status_code == 401
def test_role_change_invalidates_session(env):
    f, mk, _ = env; c = mk(); login(c, "emp001", "pw-e"); f.u["emp001"].role_raw = "hr"
    assert c.get("/api/auth/me").status_code == 401 and c.get("/api/dashboard/hr").status_code == 401
def test_logout_survives_restart(env):
    f, mk, _ = env; c = mk(); login(c, "ceo1", "pw-ceo"); tok = c.cookies.get("session"); c.post("/api/auth/logout", headers=csrf(c))
    c2 = mk(); c2.cookies.set("session", tok); assert c2.get("/api/auth/me").status_code == 401   # new app instance, same store
def test_logout_requires_csrf_token(c):
    login(c, "ceo1", "pw-ceo"); assert c.post("/api/auth/logout").status_code == 403
    assert c.post("/api/auth/logout", headers={"x-csrf-token": "wrong"}).status_code == 403; assert c.get("/api/auth/me").status_code == 200
def test_bad_origin_blocked(monkeypatch, env):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://office.example"); c = env[1]()
    assert c.post("/api/auth/login", json={"username": "ceo1", "password": "pw-ceo"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/auth/login", json={"username": "ceo1", "password": "pw-ceo"}, headers={"origin": "https://office.example"}).status_code == 200
def test_login_validation(c):
    assert c.post("/api/auth/login", json={"username": "x"}).status_code == 422; assert c.post("/api/auth/login", json={"username": "x" * 300, "password": "p"}).status_code == 422
def test_ceo_readonly_view_but_coo_cto_not_cross(c):
    login(c, "ceo1", "pw-ceo"); assert c.get("/api/dashboard/coo").status_code == 200 and c.get("/api/dashboard/hr").status_code == 403
def test_coo_cannot_see_cto(c): login(c, "coo1", "pw-coo"); assert c.get("/api/dashboard/cto").status_code == 403
def test_cto_dashboard_reports_unconfigured_sources(c): login(c, "cto1", "pw-cto"); assert c.get("/api/dashboard/cto").json()["not_configured"] == ["monitoring", "billing"]
def test_forgot_password_does_not_pretend(c):
    r = c.post("/api/auth/forgot", json={"identifier": "ceo1"}); assert r.status_code == 200 and r.json()["configured"] is False
def test_audit_log_records_events_without_secrets(env):
    f, mk, log = env; c = mk(); login(c, "ceo1", "bad"); login(c, "ceo1", "pw-ceo"); c.post("/api/auth/logout", headers=csrf(c))
    t = open(log).read(); assert "login_failed" in t and "login_ok" in t and "logout" in t and "pw-ceo" not in t and "$2" not in t
def test_proxy_header_ignored_unless_trusted(c):
    for _ in range(8): c.post("/api/auth/login", json={"username": "ceo1", "password": "bad"}, headers={"x-forwarded-for": f"9.9.9.{_}"})
    assert login(c, "ceo1", "pw-ceo").status_code == 429     # spoofed XFF did not evade the limiter
def test_waba_status_never_returns_values(monkeypatch, c):
    monkeypatch.setenv("WABA_ACCESS_TOKEN", "SECRET-TOKEN-123"); login(c, "cto1", "pw-cto"); r = c.get("/api/integrations/waba")
    assert "SECRET-TOKEN-123" not in r.text and r.json()["live_sending"] is False and r.json()["configured"] is False
def test_waba_forbidden_for_employee(c): login(c, "emp001", "pw-e"); assert c.get("/api/integrations/waba").status_code == 403
def test_notifications_requires_login_and_reports_unconfigured(c):
    assert c.get("/api/notifications").status_code == 401; login(c, "emp001", "pw-e"); assert c.get("/api/notifications").json()["configured"] is False

@pytest.mark.parametrize("u,p", [("", ""), ("ceo1", "")])
def test_empty_credentials_fail_validation(c, u, p): assert login(c, u, p).status_code == 422

def test_loopback_origin_any_port_allowed_in_dev_but_not_in_secure_mode(monkeypatch, env):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://office.example"); body = {"username": "ceo1", "password": "pw-ceo"}
    c = env[1](); assert c.post("/api/auth/login", json=body, headers={"origin": "http://localhost:5199"}).status_code == 200
    assert c.post("/api/auth/login", json=body, headers={"origin": "http://127.0.0.1:5174"}).status_code == 200
    assert c.post("/api/auth/login", json=body, headers={"origin": "http://evil.example"}).status_code == 403
    monkeypatch.setenv("COOKIE_SECURE", "true"); c2 = env[1]()
    assert c2.post("/api/auth/login", json=body, headers={"origin": "http://localhost:5199"}).status_code == 403
