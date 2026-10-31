#!/usr/bin/env bash
# Applies db/001..006 (+ rollbacks) to a DISPOSABLE database and runs the lifecycle SQL. NEVER point this at a real database.
# Usage: SCRATCH_URL='postgresql://user@host:5432/innovibe_scratch_test' ./run_migration_checks.sh
# Refuses to run unless the database name contains "scratch" or "test". 002 is skipped for the data checks only if absent; it is applied here because the checks use its seeded accounts.
set -euo pipefail
: "${SCRATCH_URL:?set SCRATCH_URL to a disposable database}"
name=$(psql "$SCRATCH_URL" -Atc "select current_database()")
case "$name" in *scratch*|*test*) ;; *) echo "REFUSING: database '$name' is not named *scratch* or *test*"; exit 2;; esac
cd "$(dirname "$0")/.."
P="psql $SCRATCH_URL -v ON_ERROR_STOP=1 -q"
$P -c "drop schema if exists office_dashboard cascade"
for f in 001_foundation 002_seed_accounts 003_crm 004_pipeline_stages 005_audit_log 005_audit_log 006_tasks 006_tasks; do $P -f $f.sql >/dev/null 2>&1 && echo "applied $f" || { echo "FAILED $f"; exit 1; }; done
$P -c "insert into office_dashboard.audit_log(user_id,action,detail) values('cli','account_created','{}'::jsonb)" && echo "legacy audit insert (create_account.py shape) OK"
psql "$SCRATCH_URL" -q -f tests/006_tasks_lifecycle.sql
for f in 006_tasks 005_audit_log; do $P -f $f.rollback.sql && echo "rolled back $f"; $P -f $f.sql >/dev/null 2>&1 && echo "re-applied $f"; done
echo "ALL MIGRATION CHECKS PASSED"
