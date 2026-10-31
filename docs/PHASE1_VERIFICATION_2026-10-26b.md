# Phase 1 verification (session of 2026-10-26, second pass)

## Environment limits (actual)
Sandbox has Python 3.12 and Node 22 only. No fastapi, psycopg, pytest, vitest, npm packages, or PostgreSQL (and the network is off).
Therefore NO API test, frontend test, tsc, vite build, or database test could run. Original project ZIP kept unmodified outside this tree.

## Executed
| Check | Result |
|---|---|
| py_compile of every backend file/test/tool | PASS (syntax only) |
| tests/test_tasklogic.py | 7 passed |
| tests/test_permissions.py | 8 passed |
| tests/test_financelogic.py (NEW) | 10 passed |

## Audit findings (read from source; not yet fixed - each needs a runnable test environment)
1. **Two RBAC systems.** `crm.py` decides access with env vars (`CRM_WRITE_ROLES`, `CRM_READ_ROLES`, `CRM_ARCHIVE_ROLES`), while tasks/people use `permissions.py` via `access.need()`. They can disagree (e.g. matrix gives COO crm.read+export; CRM default env gives COO read only; matrix grants nothing for CRM to the CTO but env could). Fix: make crm.py use `need("crm.read")`, `need("crm.write", True)`, `need("crm.archive", True)` and update tests/test_crm.py, which assume the env roles.
2. **Hard-coded role checks** in `main.py`: `/api/dashboard/{portal}` and `/api/integrations/waba` (`ceo`/`cto`) bypass the matrix. Route them through `permissions` (integrations.read).
3. **Audit split.** CRM, login, logout and denial events go to the JSONL `AuditSink`; only tasks/employees write to `office_dashboard.audit_log` (auditdb.py). Spec requires all critical operations in the DB log. Migration 005 must be applied first.
4. **Menu vs permission mismatch** (already listed in NEEDED_FROM_YOU #2): COO "Audit Log" and HR "Audit History" have no `audit.read`.
5. **Rate limiting and session revocation are in-process memory** (`fails`, `RevocationStore`): they reset on restart and do not work across multiple workers. Needs a DB/Redis-backed store before production.
6. **Unhandled-exception handler** returns a generic 500 and discards the error: add logging with a correlation id (needed for the CTO dashboard and audit "correlation ID").
7. Never executed: tasks.py, people.py, access.py, auditdb.py wiring, test_tasks_people_api.py, tasks.render.test.tsx. Expect small defects on first run.

## New in this pass
`backend/financelogic.py` + `tests/test_financelogic.py`: Decimal-only totals, per-line rounding, invoice status derivation from verified allocations, oldest-first payment allocation without over-allocation, aging buckets, idempotency helper. Not yet wired to any table or route (no quotation/invoice/payment tables exist). Module status for Quotations, Invoices, Payments therefore remains **NOT IMPLEMENTED**; only the tested calculation foundation exists.
