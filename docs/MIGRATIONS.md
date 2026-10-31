# Database migrations — review before running

**Nothing here was applied to any production or Supabase database.** All checks ran on a throwaway local PostgreSQL 16.
Run each file yourself, in order, in the Supabase SQL editor (or `psql`), after taking a backup. Every file is additive and safe to re-run unless noted.

| # | File | What it does | Status | Rollback |
|---|---|---|---|---|
| 001 | 001_foundation.sql | Schema `office_dashboard`; departments, employees, users, technicians, audit_log (basic), session_revocations; `login_accounts` view; RLS on | Pre-existing. Verified on PG16 | none provided (drops schema = data loss) |
| 002 | 002_seed_accounts.sql | Seeds department labels only; no user accounts or credentials | Sanitized for distribution | none |
| 003 | 003_crm.sql | contacts, leads, lead_activities | Pre-existing. Verified on PG16 | none provided |
| 004 | 004_pipeline_stages.sql | Removes legacy stage `qualified` from the CHECK. **Aborts if any `qualified` rows exist** | Pre-existing, **NOT applied anywhere**. Verified on empty PG16 | 004_pipeline_stages.rollback.sql |
| 005 | 005_audit_log.sql | Extends `audit_log` with actor/entity/before/after/outcome; append-only trigger | **REVISED by this work** (see below). Verified on PG16 | 005_audit_log.rollback.sql (loses the extra columns' data) |
| 006 | 006_tasks.sql | `tasks` table (+ constraints, indexes, RLS) | **NEW**. Verified on PG16 | 006_tasks.rollback.sql (drops all task data) |
| 007 | 007_attendance.sql | attendance_config (single row), attendance_records (unique user+date), attendance_corrections | **NEW. NOT applied anywhere and NOT executed even on a scratch DB** (no Postgres in the build sandbox). Review first | 007_attendance.rollback.sql (drops all attendance data) |
| 008 | 008_leave.sql | leave_types, leave_requests, holidays (nothing seeded) | **NEW. NOT applied anywhere and NOT executed even on a scratch DB.** Needs 007 first (working days) | 008_leave.rollback.sql (drops all leave data) |
| 009 | 009_module_records.sql | Auditable generic records for unimplemented workspace foundations; no seed data | **NEW. NOT applied or database-tested**. Review permissions and ensure the API connects as table owner | 009_module_records.rollback.sql (drops workspace records) |
| 010 | 010_service_tickets.sql | Persisted service tickets and comments; ticket transitions are checked by `backend/tickets.py` | **NEW. NOT applied or database-tested** | 010_service_tickets.rollback.sql (drops all ticket/comment data) |
| 011 | 011_ops_tickets_fleet.sql | Ticket category/due date/technician name/resolved time + ticket history table; fleet_vehicles and fleet_service_history | **NEW.** Executed on a throwaway PG (pgserver) via `backend/tests/test_ops_pg.py`, applied twice (re-runnable). **Not applied to your real database.** Needs 001, 005, 010 first | 011_ops_tickets_fleet.rollback.sql (drops vehicles, service history and ticket history) |

## What was wrong with the original 005 (real defect, found by running it)
001 already creates `office_dashboard.audit_log` with different columns. The original 005 used `create table if not exists` (skipped) and then
indexed `entity_type`, which did not exist, so it **failed with `column "entity_type" does not exist`** on any database that had run 001.
The revised 005 creates the table only if missing and otherwise `add column if not exists`, keeping the 001 columns so
`tools/create_account.py` (which inserts `user_id, action, detail`) still works. Verified: fresh DB, 001-then-005, 005 twice, rollback and re-apply.

## Before you run anything on a real database
1. Back up. 2. `select stage, count(*) from office_dashboard.leads group by 1;` — if `qualified` appears, decide what to do before 004.
3. If your real login table is NOT the `login_accounts` view from 001, run `python tools/inspect_schema.py` and set `USERS_TABLE`/`COL_*`; 006 does not depend on it (task user ids are plain text).
4. Run 005, 006, 007, 008, then 009, 010 and 011. 5. The API must connect as the table owner (RLS is enabled with no policies, so other roles see zero rows).

## Repeating the checks yourself
`SCRATCH_URL='postgresql://user@host/innovibe_scratch_test' db/tests/run_migration_checks.sh` — applies everything to a **disposable** database (refuses any name not containing `scratch` or `test`) and runs `db/tests/006_tasks_lifecycle.sql`.

## Distribution security note

The distributed `002_seed_accounts.sql` contains department labels only. User identities and password hashes from the source archive were intentionally excluded. Provision accounts through the approved administrator workflow; do not reintroduce real account hashes or secrets into this ZIP.
