"""Read-only user lookup. Issues SELECT only, inside a read-only transaction. Never writes to existing tables."""
from dataclasses import dataclass
from typing import Optional, Protocol

@dataclass
class UserRecord:
    id: str; name: str; pw_hash: str; role_raw: str; active: bool

class UserRepo(Protocol):
    def find(self, ident: str) -> Optional[UserRecord]: ...
    def find_by_id(self, uid: str) -> Optional[UserRecord]: ...

class PostgresUserRepo:
    def __init__(self, dsn: str, cfg: dict): self.dsn, self.cfg = dsn, cfg
    def find(self, ident): return self._q(ident, False)
    def find_by_id(self, uid): return self._q(uid, True)
    def _q(self, ident, by_id):
        import psycopg; from psycopg import sql
        c = self.cfg; cols = [c["id"], c["name"], c["password"], c["role"]] + ([c["active"]] if c["active"] else [])
        where = [sql.SQL("{}::text=%s").format(sql.Identifier(c["id"]))] if by_id else [sql.SQL("lower({}::text)=%s").format(sql.Identifier(c["login"]))]
        if c["email"] and not by_id: where.append(sql.SQL("lower({}::text)=%s").format(sql.Identifier(c["email"])))
        q = sql.SQL("select {} from {} where ").format(sql.SQL(",").join(map(sql.Identifier, cols)),
              sql.SQL(".").join(map(sql.Identifier, c["table"].split("."))))+sql.SQL(" or ").join(where)
        with psycopg.connect(self.dsn, prepare_threshold=None) as conn:
            conn.read_only = True
            rows = conn.execute(q, (ident,) * len(where)).fetchall()
        if len(rows) != 1: return None            # none, or ambiguous -> refuse rather than guess
        r = rows[0]
        active = True if not c["active"] else str(r[4]).strip().lower() in c["active_values"]
        return UserRecord(str(r[0]), str(r[1]), str(r[2] or ""), str(r[3] or ""), active)
