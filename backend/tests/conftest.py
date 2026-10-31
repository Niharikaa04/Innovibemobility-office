"""Shared pytest configuration.

Several integration suites build a DISPOSABLE PostgreSQL (pgserver) from the project's db/*.sql migrations. Those migration files live in the
full project repository (<project>/db), not inside every packaged copy of backend/ + frontend/. When the folder is absent those suites cannot
run at all, and the honest result is an explicit SKIP naming the reason, not 75 confusing fixture errors and not a silent pass.
Nothing is skipped when db/ exists: run the suite from the full repository to execute them."""
import re
from pathlib import Path

import pytest

DB_DIR = Path(__file__).resolve().parents[2] / "db"
NEEDS_DB = re.compile(r"\.\./db/|\bDB\s*=|\bDB\s*/")


def pytest_collection_modifyitems(config, items):
    if DB_DIR.is_dir(): return
    skip = pytest.mark.skip(reason=f"db/*.sql migrations not found at {DB_DIR}; run from the full repository to execute this PostgreSQL suite")
    cache = {}
    for item in items:
        f = str(item.fspath)
        if f not in cache: cache[f] = bool(NEEDS_DB.search(Path(f).read_text(encoding="utf-8", errors="ignore")))
        if cache[f]: item.add_marker(skip)


# ---- migration lookup shared by the PostgreSQL suites --------------------------------------------------------------------------------
ALIASES = {"012_garages_technicians_diagnostics_iot": "012_garages*service_centers"}      # the 012 forward file is saved under this name in some copies of the repo


def migration_path(name: str) -> Path:
    """Path of db/<name>.sql, falling back to a known alternative file name. Raises FileNotFoundError when the migration is really absent."""
    p = DB_DIR / f"{name}.sql"
    if p.exists(): return p
    if name in ALIASES:
        hits = sorted(DB_DIR.glob(ALIASES[name] + ".sql"))
        if hits: return hits[0]
    raise FileNotFoundError(f"migration {name}.sql is not in {DB_DIR}")


def migration_sql(name: str) -> str: return migration_path(name).read_text(encoding="utf-8")
