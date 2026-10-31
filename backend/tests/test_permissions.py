"""RBAC matrix tests. Pure Python: run with `python -m pytest` OR `python tests/test_permissions.py`."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import permissions as P

def test_unknown_role_and_permission_denied():
    assert not P.can("intern", "crm.read") and not P.can("ceo", "nonsense.read") and not P.can("", "")

def test_ceo_has_every_declared_permission():
    mods = {p.split(".")[0] for r in P.GRANTS.values() for p in r}
    assert all(P.can("ceo", f"{m}.{a}") for m in mods for a in P.ACTIONS)

def test_coo_and_cto_are_read_only_on_data_modules():
    for role in ("coo", "cto"):
        assert not any(p.endswith((".archive", ".admin")) for p in P.GRANTS[role])
    assert not P.can("coo", "crm.write") and not P.can("coo", "invoices.write") and not P.can("coo", "settings.admin")
    assert not P.can("cto", "employees.read") and not P.can("cto", "invoices.read") and not P.can("cto", "crm.read")

def test_only_ceo_can_admin_or_archive_anything():
    for role in P.ROLES:
        if role != "ceo":
            assert not any(p.endswith((".admin", ".archive")) for p in P.GRANTS[role]), role

def test_employee_cannot_touch_business_data():
    for m in ("crm", "leads", "invoices", "payments", "employees", "settings", "audit", "integrations"):
        assert not any(p.startswith(m + ".") for p in P.GRANTS["employee"]), m

def test_hr_cannot_touch_finance_or_crm():
    for m in ("invoices", "payments", "crm", "leads", "integrations", "audit"):
        assert not any(p.startswith(m + ".") for p in P.GRANTS["hr"]), m

def test_every_grant_uses_known_role_and_action():
    assert set(P.GRANTS) == set(P.ROLES)
    assert all(p.split(".")[1] in P.ACTIONS for r in P.GRANTS.values() for p in r)

def test_own_only_scoping_flags():
    assert P.is_own_only("employee", "leave") and not P.is_own_only("hr", "leave")

if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns: f(); print("PASS", f.__name__)
    print(f"{len(fns)} passed")
