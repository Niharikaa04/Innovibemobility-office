"""Business audit trail in the database (db/005). Call INSIDE the same transaction as the change, so the change and its
audit row commit or roll back together. Never pass passwords, hashes, tokens or API keys in before/after."""
import ipaddress
from psycopg.types.json import Jsonb

SENSITIVE = ("password", "hash", "token", "secret", "api_key", "authorization")

def scrub(d):
    if d is None: return None
    return {k: ("[redacted]" if any(w in k.lower() for w in SENSITIVE) else v) for k, v in dict(d).items()}

def _ip(v):
    try: return str(ipaddress.ip_address(v)) if v else None
    except ValueError: return None

def record(conn, *, actor_id, actor_role, action, entity_type, entity_id=None, before=None, after=None,
           outcome="success", ip=None, request_id=None, source="app"):
    conn.execute(
        "insert into office_dashboard.audit_log(user_id,actor_id,actor_role,action,entity_type,entity_id,before_data,after_data,outcome,source,request_id,ip)"
        " values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::inet)",
        (actor_id, actor_id, actor_role, action, entity_type, None if entity_id is None else str(entity_id),
         Jsonb(scrub(before), dumps=_dumps) if before is not None else None, Jsonb(scrub(after), dumps=_dumps) if after is not None else None,
         outcome, source, request_id, _ip(ip)))

def _dumps(o):
    import json
    return json.dumps(o, default=str)
