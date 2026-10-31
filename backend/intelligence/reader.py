"""The ONLY database access for intelligence. Every query runs in a read-only transaction with a statement timeout.
Anything the database raises is converted to ReaderError(kind) so callers never see (or leak) driver messages, hosts or SQL."""
import logging
from typing import Protocol

log = logging.getLogger("intelligence")
SCHEMA = "office_dashboard"
STATEMENT_TIMEOUT_MS = 5000
ROW_LIMIT = 5000          # hard cap for any row-returning query (callers also add their own LIMIT)


class ReaderError(Exception):
    def __init__(self, kind: str): super().__init__(kind); self.kind = kind     # "timeout" | "missing_table" | "query_failed" | "connect_failed"


class Reader(Protocol):
    def rows(self, sql: str, params: tuple = ()) -> list: ...
    def has_table(self, name: str) -> bool: ...
    def close(self) -> None: ...


class PgReader:
    """psycopg-backed Reader. Use as a context manager. Read-only transaction; `set local statement_timeout` is re-applied after any
    rollback (SET LOCAL, not SET, so it is safe behind a transaction-mode pooler such as pgbouncer/Supabase)."""
    def __init__(self, dsn: str, timeout_ms: int = STATEMENT_TIMEOUT_MS):
        self.dsn, self.timeout_ms, self.conn, self._armed, self._tables = dsn, int(timeout_ms), None, False, {}
    def __enter__(self): self._connect(); return self
    def __exit__(self, *a): self.close(); return False
    def _connect(self):
        import psycopg
        try:
            self.conn = psycopg.connect(self.dsn, connect_timeout=5, prepare_threshold=None); self.conn.read_only = True
        except Exception as e: log.warning("intelligence connect failed: %s", type(e).__name__); raise ReaderError("connect_failed")
    def _arm(self):
        if not self._armed: self.conn.execute(f"set local statement_timeout = {int(self.timeout_ms)}"); self._armed = True
    def rows(self, sql, params=()):
        import psycopg; from psycopg.rows import dict_row
        if self.conn is None: self._connect()
        try:
            self._arm()
            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params); return cur.fetchmany(ROW_LIMIT + 1)
        except psycopg.errors.QueryCanceled: self._reset(); raise ReaderError("timeout")
        except psycopg.errors.UndefinedTable: self._reset(); raise ReaderError("missing_table")
        except Exception as e:
            log.warning("intelligence query failed: %s", type(e).__name__); self._reset(); raise ReaderError("query_failed")
    def _reset(self):
        try: self.conn.rollback()
        except Exception: pass
        self._armed = False
    def has_table(self, name):
        if name not in self._tables:
            self._tables[name] = bool(self.rows("select to_regclass(%s) is not null as ok", (f"{SCHEMA}.{name}",))[0]["ok"])   # ReaderError propagates: "cannot read" is not "table missing"
        return self._tables[name]
    def close(self):
        if self.conn is not None:
            try: self.conn.rollback()      # nothing to commit: read-only
            finally: self.conn.close(); self.conn = None
