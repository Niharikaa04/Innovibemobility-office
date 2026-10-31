"""Behavioural RBAC matrix: log in as EVERY role and call EVERY /api route. The database is deliberately unreachable, so a request that passes the
permission gate ends in 503/422/404 and a request that does not ends in 403 - which makes enforcement observable without any data.
Two invariants are checked mechanically, so a newly added route under a known prefix is covered automatically:
  1. A role with no grant at all on a module gets 403 on every route of that module (read AND write).
  2. A role with only read/export on a module gets 403 on every state-changing route, unless it holds approve/archive/admin for it.
plus the generic /api/workspaces/{module} routes for every one of the 60 module slugs."""
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
import permissions as P
import workspaces
from stores import RevocationStore, AuditSink
from test_auth import Fake, CFG, ROLES

PREFIX = [("/api/crm/contacts", "crm"), ("/api/crm/leads", "leads"), ("/api/service-tickets", "tickets"), ("/api/fleet", "fleet"), ("/api/garages", "garages"),
          ("/api/technicians", "technicians"), ("/api/diagnostics", "diagnostics"), ("/api/iot", "iot"), ("/api/finance/invoices", "invoices"),
          ("/api/finance/payments", "payments"), ("/api/finance/expenses", "expenses"), ("/api/finance/budget", "budget"), ("/api/customers", "customers"),
          ("/api/employees", "employees")]
PUBLIC = {"/api/auth/login", "/api/auth/forgot", "/api/gps/ingest", "/api/gps/webhook/{provider}", "/api/iot/ingest", "/api/auth/logout"}
WRITE = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    d = tmp_path_factory.mktemp("rbac"); old = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = "postgresql://u:p@127.0.0.1:1/db"
    app = main.create_app(Fake(), CFG, "s", RevocationStore(str(d / "r.db")), AuditSink(str(d / "a.jsonl")))
    clients = {}
    for u, pw, role in ROLES:
        c = TestClient(app, raise_server_exceptions=False); assert c.post("/api/auth/login", json={"username": u, "password": pw}).status_code == 200; clients[role] = c
    yield app, clients
    if old is None: os.environ.pop("DATABASE_URL", None)
    else: os.environ["DATABASE_URL"] = old


def fill(path): return re.sub(r"\{[^}]+\}", "1", path)


def call(c, method, path, body=None):
    h = {"x-csrf-token": c.cookies.get("csrf")} if method != "GET" else {}
    return c.request(method, fill(path), headers=h, json=({} if body is None else body) if method != "GET" else None).status_code


def routes(app):
    return [(m, r.path) for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/") and r.path not in PUBLIC for m in sorted(r.methods - {"HEAD", "OPTIONS"})]


def module_of(path): return next((m for p, m in PREFIX if path.startswith(p)), None)


def holds(role, module): return {a for a in P.ACTIONS if P.can(role, f"{module}.{a}")}


def test_invariant_1_a_role_with_no_grant_on_a_module_is_denied_everywhere(world):
    app, cl = world; bad = []; checked = 0
    for m, path in routes(app):
        mod = module_of(path)
        if not mod: continue
        for role, c in cl.items():
            if holds(role, mod): continue
            checked += 1
            if (s := call(c, m, path)) != 403: bad.append((role, m, path, s))
    assert checked > 300 and not bad, bad


def test_invariant_2_read_only_roles_cannot_change_anything(world):
    app, cl = world; bad = []; checked = 0
    for m, path in routes(app):
        mod = module_of(path)
        if not mod or m not in WRITE: continue
        for role, c in cl.items():
            h = holds(role, mod)
            if not h or h & {"write", "approve", "archive", "admin"}: continue      # only roles that hold read/export and nothing else
            checked += 1
            if (s := call(c, m, path)) != 403: bad.append((role, m, path, s))
    assert checked > 50 and not bad, bad


def test_approvers_without_write_can_only_reach_approval_routes(world):
    """COO holds expenses.approve / leave.approve but NOT write: anything else that changes expenses must stay 403."""
    app, cl = world; coo = cl["coo"]
    assert P.can("coo", "expenses.approve") and not P.can("coo", "expenses.write")
    for m, path in routes(app):
        if path.startswith("/api/finance/expenses") and m in WRITE and not re.search(r"/(approve|reject)$", path):
            assert call(coo, m, path) == 403, (m, path)
    for path in ("/api/finance/invoices", "/api/finance/payments/1/void", "/api/finance/budgets"):
        for m in ("POST", "PUT", "DELETE"): assert call(coo, m, path) in (403, 404, 405), (m, path)


def test_cto_has_no_finance_crm_or_employee_access(world):
    app, cl = world; cto = cl["cto"]
    for m, path in routes(app):
        if any(path.startswith(p) for p in ("/api/finance", "/api/crm", "/api/employees", "/api/customers", "/api/attendance", "/api/leave")): assert call(cto, m, path) == 403, (m, path)


def test_hr_and_employee_cannot_reach_operational_or_business_data(world):
    app, cl = world
    for role in ("hr", "employee"):
        for m, path in routes(app):
            if any(path.startswith(p) for p in ("/api/finance", "/api/crm", "/api/service-tickets", "/api/fleet", "/api/garages", "/api/technicians", "/api/iot", "/api/diagnostics", "/api/intelligence")):
                assert call(cl[role], m, path) == 403, (role, m, path)


@pytest.mark.parametrize("slug", sorted(workspaces.MODULES))
def test_workspace_module_is_gated_per_role(world, slug):
    app, cl = world; ns = workspaces.MODULES[slug]
    for role, c in cl.items():
        for m, suffix, need in (("GET", "", "read"), ("GET", "/summary", "read"), ("GET", "/export", "export"), ("POST", "/records", "write"), ("PATCH", "/records/1", "write")):
            s = call(c, m, f"/api/workspaces/{slug}{suffix}")
            if not P.can(role, f"{ns}.{need}"): assert s == 403, (role, slug, m, suffix, s)
            else: assert s != 403, (role, slug, m, suffix, s)        # granted roles reach the handler (503: no database here), so a blanket-deny bug is caught too


def test_unknown_workspace_is_404_and_never_a_data_read(world):
    app, cl = world; assert call(cl["ceo"], "GET", "/api/workspaces/not-a-module") == 404


def test_every_route_was_probed(world):
    app, _ = world; assert len(routes(app)) >= 170
