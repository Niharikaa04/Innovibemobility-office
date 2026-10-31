# InnoVibe Office OS (work in progress, not production-ready)
React+TS+Vite frontend, FastAPI backend. Read docs/PHASE1_AUDIT.md for exact status and AUTH_AUDIT.md for the auth gaps.

## Windows PowerShell
```powershell
# Backend tests (no database needed)
cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
$env:SESSION_SECRET="test"; $env:DATABASE_URL="x"; python -m pytest -q

# Frontend tests, types, build, audit
cd ..\frontend; npm install; npm test; npx tsc --noEmit; npm run build; npm audit

# Real run (needs a verified auth mapping - see AUTH_AUDIT.md)
cd ..\backend; copy .env.example .env      # fill values; python tools\inspect_schema.py is read-only
uvicorn main:app --port 8000               # new window: cd frontend; npm run dev  -> http://localhost:5173
```
Until USERS_TABLE/COL_* are set, the API answers 503 "Auth is not configured" by design.

## Status (2026-10-26)
See docs/MODULE_STATUS.md (every sidebar item), docs/MIGRATIONS.md (SQL to review/run: 004, 005, 006 are pending on any real DB), docs/TEST_REPORT.md (what was and was not executed) and docs/NEEDED_FROM_YOU.md.
New this round: Tasks & Approvals, Employee directory, DB audit log viewer, backend RBAC enforcement (`backend/access.py` + `permissions.py`), revised migration 005, migration 006.
Environment: copy backend/.env.example to backend/.env and fill DATABASE_URL and SESSION_SECRET (a long random string). Never commit .env.
