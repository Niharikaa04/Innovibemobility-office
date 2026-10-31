"""Central RBAC matrix: ONE place that says which role may do what. No third-party imports.
PROPOSED DEFAULTS - not confirmed company policy. Change the table below, nothing else, to change who can do what.
Permission format: "<module>.<action>". Actions: read, write, approve, archive, export, admin.
"""
ROLES = ("ceo", "coo", "cto", "service_manager", "hr", "technician", "employee")
ACTIONS = ("read", "write", "approve", "archive", "export", "admin")

def _p(module, *actions): return {f"{module}.{a}" for a in actions}
ALL = ("read", "write", "approve", "archive", "export", "admin")
RO = ("read", "export")          # read-only roles: view + export, never change data

GRANTS = {
    # CEO: everything. (Permanent deletion is a separate, not-yet-built permission.)
    "ceo": set().union(*[_p(m, *ALL) for m in (
        "crm", "leads", "customers", "sales", "quotations", "orders", "invoices", "payments", "expenses", "budget",
        "employees", "attendance", "tasks", "leave", "documents", "tickets", "fleet", "garages", "technicians",
        "diagnostics", "iot", "location", "technician_contact", "kpi", "reports", "integrations", "settings", "audit")]),
    # COO: read-only across operations; may approve tasks/leave/expenses in their chain. No admin, no finance writes.
    "coo": set().union(*[_p(m, *RO) for m in (
        "crm", "leads", "customers", "sales", "quotations", "orders", "invoices", "payments", "expenses", "budget",
        "employees", "attendance", "tasks", "leave", "tickets", "fleet", "garages", "technicians", "kpi", "reports")],
        _p("tasks", "write", "approve"), _p("leave", "approve"), _p("expenses", "approve"),
        _p("iot", "read", "export"), _p("location", "read"), _p("technician_contact", "read")),   # Operations manager: telemetry incl. location + technician contact details
    # CTO: read-only on technical modules. No employee data, no finance, no CRM.
    "cto": set().union(*[_p(m, *RO) for m in ("integrations", "iot", "diagnostics", "fleet", "tickets", "reports")],
        _p("audit", "read"), _p("tasks", "read", "write")),
    "service_manager": set().union(
        _p("tickets", "read", "write", "approve", "export"), _p("fleet", "read", "write", "export"), _p("garages", "read", "write", "export"),
        _p("technicians", "read", "write", "export"), _p("diagnostics", "read", "write", "export"), _p("iot", "read", "export"), _p("location", "read"), _p("technician_contact", "read"),
        _p("customers", "read"), _p("tasks", "read", "write"), _p("attendance", "read"), _p("reports", "read")),
    "hr": set().union(
        _p("employees", "read", "write", "export"), _p("attendance", "read", "write", "approve", "export"),
        _p("leave", "read", "write", "approve", "export"), _p("documents", "read", "write"),
        _p("tasks", "read", "write"), _p("reports", "read")),
    "technician": set().union(
        _p("tickets", "read", "write"), _p("diagnostics", "read", "write"), _p("fleet", "read"),
        _p("iot", "read"),   # telemetry, limited in iotapi.py to vehicles with an open ticket assigned to the technician (this includes location data)
        _p("tasks", "read", "write"), _p("attendance", "read", "write"), _p("leave", "read", "write")),
    "employee": set().union(_p("tasks", "read", "write"), _p("attendance", "read", "write"), _p("leave", "read", "write"),
        _p("documents", "read")),
}
# "attendance.read" / "leave.read" / "tasks.*" for ordinary employees means OWN records only. Row-level scoping
# ("own" vs "team" vs "all") must be enforced in each module's queries - this table only gates the action.
OWN_ONLY = {("employee", "attendance"), ("employee", "leave"), ("employee", "tasks"), ("employee", "documents"),
            ("technician", "attendance"), ("technician", "leave"), ("technician", "tasks"), ("technician", "iot")}

def can(role: str, permission: str) -> bool:
    """Deny by default: unknown role or unknown permission -> False."""
    return permission in GRANTS.get(role, set())

def is_own_only(role: str, module: str) -> bool:
    return (role, module) in OWN_ONLY

def permissions_for(role: str) -> list:
    return sorted(GRANTS.get(role, set()))