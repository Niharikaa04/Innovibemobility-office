"""Read-only user lookup. Uses existing users and employees tables."""
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class UserRecord:
    id: str
    name: str
    pw_hash: str
    role_raw: str
    active: bool


class UserRepo(Protocol):
    def find(self, ident: str) -> Optional[UserRecord]: ...
    def find_by_id(self, uid: str) -> Optional[UserRecord]: ...


class PostgresUserRepo:
    def __init__(self, dsn: str, cfg: dict):
        self.dsn = dsn
        self.cfg = cfg

    def find(self, ident):
        return self._q(ident, False)

    def find_by_id(self, uid):
        return self._q(uid, True)

    def _q(self, ident, by_id):
        import psycopg
        from psycopg import sql

        c = self.cfg

        # Safely construct the configured users table identifier.
        users_table = sql.Identifier(*c["table"].split("."))
        employees_table = sql.Identifier("office_dashboard", "employees")

        # Fetch the employee's real name through employee_id.
        cols = [
            sql.SQL("u.{}").format(sql.Identifier(c["id"])),
            sql.SQL("COALESCE(e.full_name::text, u.{}::text)").format(
                sql.Identifier(c["login"])
            ),
            sql.SQL("u.{}").format(sql.Identifier(c["password"])),
            sql.SQL("u.{}").format(sql.Identifier(c["role"])),
        ]

        if c["active"]:
            cols.append(sql.SQL("u.{}").format(sql.Identifier(c["active"])))

        if by_id:
            where = [
                sql.SQL("u.{}::text = %s").format(
                    sql.Identifier(c["id"])
                )
            ]
        else:
            where = [
                sql.SQL("lower(u.{}::text) = %s").format(
                    sql.Identifier(c["login"])
                )
            ]

            # Only enable email lookup if the configured users table
            # actually contains the configured email column.
            if c.get("email"):
                where.append(
                    sql.SQL("lower(u.{}::text) = %s").format(
                        sql.Identifier(c["email"])
                    )
                )

        query = (
            sql.SQL("SELECT {} FROM {} AS u ")
            .format(sql.SQL(", ").join(cols), users_table)
            + sql.SQL(
                "LEFT JOIN {} AS e ON u.employee_id = e.id WHERE ("
            ).format(employees_table)
            + sql.SQL(" OR ").join(where)
            + sql.SQL(")")
        )

        with psycopg.connect(
            self.dsn, prepare_threshold=None
        ) as conn:
            conn.read_only = True
            rows = conn.execute(
                query, (ident,) * len(where)
            ).fetchall()

        # Refuse ambiguous matches rather than selecting an arbitrary user.
        if len(rows) != 1:
            return None

        r = rows[0]

        active = (
            True
            if not c["active"]
            else str(r[4]).strip().lower() in c["active_values"]
        )

        return UserRecord(
            id=str(r[0]),
            name=str(r[1] or ""),
            pw_hash=str(r[2] or ""),
            role_raw=str(r[3] or ""),
            active=active,
        )