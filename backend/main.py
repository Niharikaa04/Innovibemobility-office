"""InnoVibe Office OS API: authentication, session security and portal authorization."""
import logging, os, secrets, time, uuid
import psycopg
from urllib.parse import urlparse
from collections import defaultdict
from typing import Optional
from datetime import date
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
import access, attendance, leave, config, passwords, crm, people, permissions, tasks, workspaces, ticketapi, fleetapi, garageapi, technicianapi, diagapi, iotapi, finance, customerapi
import fleet_gps
import intelligence.api as intelligence_api
from repo import PostgresUserRepo, UserRepo
from stores import AuditSink, RevocationStore
load_dotenv(encoding="utf-8-sig")
log = logging.getLogger("innovibe.api")
SHORT, LONG = 12 * 3600, 30 * 86400
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=254); password: str = Field(min_length=1, max_length=256); remember: bool = False
class ForgotIn(BaseModel): identifier: str = Field(min_length=1, max_length=254)

def create_app(repo: Optional[UserRepo] = None, cfg: Optional[dict] = None, secret: Optional[str] = None,
               revoked: Optional[RevocationStore] = None, audit: Optional[AuditSink] = None) -> FastAPI:
    app = FastAPI(title="InnoVibe Office OS", docs_url=None, redoc_url=None)
    cfg = cfg or config.load(); repo = repo or PostgresUserRepo(os.environ["DATABASE_URL"], cfg)
    ser = URLSafeTimedSerializer(secret or os.environ["SESSION_SECRET"]); revoked = revoked or RevocationStore(); audit = audit or AuditSink()
    origins = {o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    fails: dict = defaultdict(list)

    def ip(r: Request):  # X-Forwarded-For is trusted ONLY when TRUSTED_PROXY=true (i.e. you sit behind your own proxy)
        if os.getenv("TRUSTED_PROXY") == "true" and r.headers.get("x-forwarded-for"): return r.headers["x-forwarded-for"].split(",")[-1].strip()
        return r.client.host if r.client else "unknown"
    def portal_role(u):
        raw = u.role_raw.strip().lower(); return cfg["role_map"].get(raw) or (raw if raw in config.PORTAL_ROLES else None)
    def check_origin(r: Request):
        o = r.headers.get("origin")
        if not (origins and o) or o in origins: return
        # Local development only (COOKIE_SECURE is not "true"): any localhost/127.0.0.1 port is fine. Deployments must list real origins.
        if os.getenv("COOKIE_SECURE") != "true" and urlparse(o).hostname in ("localhost", "127.0.0.1", "::1"): return
        raise HTTPException(403, "Request origin is not allowed.")

    @app.exception_handler(psycopg.OperationalError)
    async def _db_down(request, e):
        log.error("database unavailable (%s) on %s %s", type(e).__name__, request.method, request.url.path)     # never the driver message: it can contain the host and user
        return JSONResponse({"detail": "The database is temporarily unavailable. Try again shortly."}, 503)

    @app.exception_handler(Exception)
    async def _err(request, e):
        log.error("unhandled %s on %s %s", type(e).__name__, request.method, request.url.path)     # exception CLASS and route only: messages can contain SQL, hosts or data
        return JSONResponse({"detail": "Something went wrong on the server."}, 500)

    @app.middleware("http")
    async def _api_headers(request: Request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/api/"):     # API responses hold business data: never store them in a shared/browser cache
            resp.headers.setdefault("Cache-Control", "no-store"); resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    def session(request: Request):
        try: s = ser.loads(request.cookies.get("session", ""), max_age=LONG)
        except BadSignature: raise HTTPException(401, "Not signed in.")
        if time.time() > s["exp"] or revoked.is_revoked(s["jti"]): raise HTTPException(401, "Session ended. Sign in again.")
        u = repo.find_by_id(s["id"]); role = portal_role(u) if u else None   # re-checked on EVERY request
        if not (u and u.active and role): revoked.revoke(s["jti"], s["exp"]); raise HTTPException(401, "Your account is no longer active.")
        if role != s["role"]: revoked.revoke(s["jti"], s["exp"]); audit.write("session_role_changed", s["id"], ip(request)); raise HTTPException(401, "Your access changed. Sign in again.")
        return {**s, "name": u.name}
    def csrf(request: Request, s=Depends(session)):
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), s["csrf"]): raise HTTPException(403, "Security check failed. Reload and try again.")
        return s

    def dsn():
        v = os.environ.get("DATABASE_URL")
        if not v: raise HTTPException(503, "The database is not configured.")      # a clear, safe 503 instead of a KeyError -> 500
        return v
    need = access.make_need(session, csrf, audit)
    app.include_router(crm.build_router(dsn, session, csrf, audit))
    app.include_router(tasks.build_router(dsn, session, csrf, audit, need, repo, cfg, ip))
    app.include_router(people.build_router(dsn, need, ip))
    app.include_router(attendance.build_router(dsn, need, cfg, ip))
    app.include_router(leave.build_router(dsn, need, cfg, ip))
    app.include_router(workspaces.build_router(dsn, session, csrf, audit))
    app.include_router(ticketapi.build_router(dsn, session, csrf, audit))
    app.include_router(fleetapi.build_router(dsn, session, csrf, audit))
    app.include_router(fleet_gps.build_router(dsn, session, csrf, audit))
    app.include_router(fleet_gps.build_ingest_router(dsn))   # device-token auth, no session/CSRF
    app.include_router(garageapi.build_router(dsn, session, csrf, audit))
    app.include_router(technicianapi.build_router(dsn, session, csrf, audit))
    app.include_router(diagapi.build_router(dsn, session, csrf, audit))
    app.include_router(iotapi.build_router(dsn, session, csrf, audit))
    app.include_router(finance.build_router(dsn, session, csrf, audit))
    app.include_router(customerapi.build_router(dsn, session, csrf, audit))
    app.include_router(intelligence_api.build_router(dsn, session, csrf, audit))   # read-only business intelligence (executive roles only)
    @app.get("/api/auth/permissions")
    def my_permissions(s=Depends(session)):   # lets the UI show/hide controls; the server still enforces every call
        return {"role": s["role"], "permissions": permissions.permissions_for(s["role"])}

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request, response: Response):
        check_origin(request); ident = body.username.strip().lower(); key = f"{ip(request)}|{ident}"
        fails[key] = [t for t in fails[key] if time.time() - t < 300]
        if len(fails[key]) >= 8: audit.write("login_throttled", None, ip(request)); raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        u = repo.find(ident); good, _ = passwords.verify(body.password, u.pw_hash) if u else (False, ""); role = portal_role(u) if u else None
        if not (u and good and u.active and role):
            fails[key].append(time.time()); audit.write("login_failed", u.id if u else None, ip(request)); raise HTTPException(401, "Incorrect username or password.")
        ttl = LONG if body.remember else SHORT; token = secrets.token_urlsafe(24)
        tok = ser.dumps({"id": u.id, "role": role, "jti": uuid.uuid4().hex, "exp": time.time() + ttl, "csrf": token})
        sec = os.getenv("COOKIE_SECURE") == "true"; age = ttl if body.remember else None
        response.set_cookie("session", tok, httponly=True, samesite="lax", secure=sec, max_age=age)
        response.set_cookie("csrf", token, httponly=False, samesite="lax", secure=sec, max_age=age)
        audit.write("login_ok", u.id, ip(request), remember=body.remember); return {"id": u.id, "name": u.name, "role": role}

    @app.get("/api/auth/me")
    def me(s=Depends(session)): return {"id": s["id"], "name": s["name"], "role": s["role"]}
    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, s=Depends(csrf)):
        revoked.revoke(s["jti"], s["exp"]); audit.write("logout", s["id"], ip(request))
        response.delete_cookie("session"); response.delete_cookie("csrf"); return {"ok": True}
    @app.post("/api/auth/forgot")
    def forgot(body: ForgotIn, request: Request):
        check_origin(request); audit.write("password_reset_requested", None, ip(request))   # identifier deliberately not logged
        return {"configured": False, "message": "Password reset by email is not configured yet. Ask your HR or CEO administrator to reset your password."}
    @app.get("/api/notifications")
    def notifications(s=Depends(session)): return {"configured": False, "items": []}

    @app.get("/api/dashboard/{portal}")
    def dashboard(portal: str, date_from: date | None = None, date_to: date | None = None, s=Depends(session)):
        if date_from and date_to and date_from > date_to: raise HTTPException(422, "Start date must be on or before end date.")
        if portal not in config.PORTAL_ROLES: raise HTTPException(404, "Unknown portal.")
        if s["role"] != portal and not (s["role"] == "ceo" and portal in ("coo", "cto")):   # CEO: authorised read-only view of COO/CTO
            audit.write("portal_denied", s["id"], None, portal=portal); raise HTTPException(403, "This portal is not available for your role.")
        out = {"kpis": {}, "panels": {}, "not_configured": ["monitoring", "billing"] if portal == "cto" else []}
        if portal == "ceo":
            url = os.environ.get("DATABASE_URL"); snap = crm.snapshot(url, date_from, date_to) if url else None    # no database -> "crm" is reported as not configured, never as zero
            if snap: out["kpis"].update(snap["kpis"]); out["panels"].update(snap["panels"])
            else: out["not_configured"].append("crm")
        return out

    @app.get("/api/integrations/waba")
    def waba(s=Depends(session)):
        if s["role"] not in ("ceo", "cto"): raise HTTPException(403, "Not permitted.")
        need = ["WABA_PROVIDER", "WABA_ID", "WABA_PHONE_NUMBER_ID", "WABA_ACCESS_TOKEN", "WABA_BUSINESS_PHONE"]
        have = {k: bool(os.getenv(k)) for k in need}   # presence only; values are never returned
        return {"configured": all(have.values()), "fields": have, "live_sending": False}
    return app

try: app = create_app()
except (config.ConfigError, KeyError) as _e:
    app = FastAPI(); _m = f"Auth is not configured: {_e}"
    @app.api_route("/api/{p:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def _unconfigured(p: str): raise HTTPException(503, _m)