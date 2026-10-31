"""Persistence for session revocation and the security audit trail. Neither touches your business database."""
import json, os, sqlite3, threading, time
class RevocationStore:
    """SQLite file: survives restarts and is shared by all workers on one host. For multi-host deployments use a shared store (Redis/Postgres) - needs your approval."""
    def __init__(self, path=None):
        self.path = path or os.getenv("REVOCATION_DB", "sessions.sqlite3"); self.lock = threading.Lock()
        with self._c() as c: c.execute("create table if not exists revoked(jti text primary key, exp real)")
    def _c(self): return sqlite3.connect(self.path, timeout=5)
    def revoke(self, jti, exp):
        with self.lock, self._c() as c: c.execute("insert or replace into revoked values(?,?)", (jti, exp)); c.execute("delete from revoked where exp<?", (time.time(),))
    def is_revoked(self, jti):
        with self._c() as c: return c.execute("select 1 from revoked where jti=?", (jti,)).fetchone() is not None
class AuditSink:
    """Append-only JSON lines. Never logs passwords, hashes or tokens."""
    def __init__(self, path=None): self.path = path or os.getenv("AUDIT_LOG", "audit.jsonl")
    def write(self, action, user_id=None, ip=None, **detail):
        rec = {"ts": time.time(), "action": action, "user": user_id, "ip": ip, **detail}
        with open(self.path, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
