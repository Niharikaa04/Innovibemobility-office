"""Auth configuration. NOTHING here is guessed: the users-table mapping must be supplied via env after running tools/inspect_schema.py."""
import json, os, re
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
PORTAL_ROLES = ("ceo", "coo", "cto", "service_manager", "hr", "technician", "employee")

class ConfigError(RuntimeError): pass

def _ident(name, value):
    if not value or not IDENT.match(value): raise ConfigError(f"{name} is missing or not a plain identifier: {value!r}")
    return value

def load():
    c = dict(table=_ident("USERS_TABLE", os.getenv("USERS_TABLE")),
             id=_ident("COL_ID", os.getenv("COL_ID")), name=_ident("COL_NAME", os.getenv("COL_NAME")),
             login=_ident("COL_LOGIN", os.getenv("COL_LOGIN")), password=_ident("COL_PASSWORD", os.getenv("COL_PASSWORD")),
             role=_ident("COL_ROLE", os.getenv("COL_ROLE")),
             email=os.getenv("COL_EMAIL") or None, active=os.getenv("COL_ACTIVE") or None)
    for k in ("email", "active"):
        if c[k]: _ident("COL_" + k.upper(), c[k])
    c["active_values"] = {v.strip().lower() for v in os.getenv("ACTIVE_VALUES", "true,t,1,active").split(",")}
    rm = json.loads(os.getenv("ROLE_MAP", "{}"))            # {"<db role value>": "<portal role>"}
    bad = {v for v in rm.values() if v not in PORTAL_ROLES}
    if bad: raise ConfigError(f"ROLE_MAP targets must be in {PORTAL_ROLES}; got {bad}")
    c["role_map"] = {str(k).strip().lower(): v for k, v in rm.items()}
    return c
