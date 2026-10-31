"""Read-only user lookup using existing users and employees tables."""

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

    def find(self, ident: str) -> Optional[UserRecord]:
        return self._q(ident, by_id=False)

    def find_by_id(self, uid: str) -> Optional[UserRecord]:
        return self._q(uid, by_id=True)

    def _q(self, ident: str, by_id: bool) -> Optional[UserRecord]:
        import psycopg
        from psycopg import sql

        c = self.cfg

        users_table = sql.Identifier(*c["table"].split("."))
        employees_table = sql.Identifier("office_dashboard", "employees")

        columns = [
            sql.SQL("u.{}").format(sql.Identifier(c["id"])),
            sql.SQL("COALESCE(e.full_name::text, u.username::text)"),
            sql.SQL("u.{}").format(sql.Identifier(c["password"])),
            sql.SQL("u.{}").format(sql.Identifier(c["role"])),
        ]

        if c.get("active"):
            columns.append(
                sql.SQL("u.{}").format(sql.Identifier(c["active"]))
            )

        if by_id:
            conditions = [
                sql.SQL("u.{}::text = %s").format(
                    sql.Identifier(c["id"])
                )
            ]
        else:
            conditions = [
                sql.SQL("lower(u.{}::text) = lower(%s)").format(
                    sql.Identifier(c["login"])
                )
            ]

            if c.get("email"):
                conditions.append(
                    sql.SQL("lower(u.{}::text) = lower(%s)").format(
                        sql.Identifier(c["email"])
                    )
                )

        query = (
            sql.SQL("SELECT {} FROM {} AS u ").format(
                sql.SQL(", ").join(columns),
                users_table,
            )
            + sql.SQL(
                "LEFT JOIN {} AS e ON u.employee_id = e.id WHERE ("
            ).format(employees_table)
            + sql.SQL(" OR ").join(conditions)
            + sql.SQL(")")
        )

        with psycopg.connect(
            self.dsn, prepare_threshold=None
        ) as conn:
            conn.read_only = True
            rows = conn.execute(
                query, (ident,) * len(conditions)
            ).fetchall()

        if len(rows) != 1:
            return None

        row = rows[0]

        active = (
            True
            if not c.get("active")
            else str(row[4]).strip().lower() in c["active_values"]
        )

        return UserRecord(
            id=str(row[0]),
            name=str(row[1] or ""),
            pw_hash=str(row[2] or ""),
            role_raw=str(row[3] or ""),
            active=active,
        )