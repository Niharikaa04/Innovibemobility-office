-- 005: business audit trail (who changed what, when, before/after). ADDITIVE ONLY. Safe to re-run.
-- REVISED 2026-10-26: the first version failed on any database that had already run 001_foundation.sql, because 001 already
-- creates office_dashboard.audit_log (columns id, occurred_at, user_id, action, ip, detail). This version EXTENDS that table
-- (add column if not exists) and keeps the 001 columns, so tools/create_account.py (which inserts user_id/action/detail) keeps working.
-- It also creates the full table if 001 was never run. Verified on PostgreSQL 16 on both paths (see docs/MIGRATIONS.md).
-- Append-only: UPDATE and DELETE are blocked by a trigger. Never store passwords, tokens or API keys in before/after/detail.
create table if not exists office_dashboard.audit_log (
  id          bigserial primary key,
  occurred_at timestamptz not null default now(),
  user_id     text,
  action      text not null,
  ip          inet,
  detail      jsonb not null default '{}'
);
alter table office_dashboard.audit_log
  add column if not exists actor_id    text,                 -- users.id of the person (null = system/integration)
  add column if not exists actor_role  text,
  add column if not exists entity_type text,                 -- e.g. task, lead, contact (null for legacy auth/account rows)
  add column if not exists entity_id   text,
  add column if not exists before_data jsonb,
  add column if not exists after_data  jsonb,
  add column if not exists outcome     text not null default 'success',
  add column if not exists source      text not null default 'app',   -- app | webhook:waba | job:reminders ...
  add column if not exists request_id  text;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'audit_log_outcome_check'
                 and conrelid = 'office_dashboard.audit_log'::regclass) then
    alter table office_dashboard.audit_log add constraint audit_log_outcome_check check (outcome in ('success','denied','failed'));
  end if;
end $$;
create index if not exists audit_entity_idx on office_dashboard.audit_log (entity_type, entity_id, occurred_at desc);
create index if not exists audit_actor_idx  on office_dashboard.audit_log (actor_id, occurred_at desc);
create index if not exists audit_time_idx   on office_dashboard.audit_log (occurred_at desc);

create or replace function office_dashboard.audit_log_block_changes() returns trigger language plpgsql as $$
begin raise exception 'audit_log is append-only (% blocked)', tg_op; end $$;
drop trigger if exists audit_log_no_update on office_dashboard.audit_log;
create trigger audit_log_no_update before update or delete on office_dashboard.audit_log
  for each row execute function office_dashboard.audit_log_block_changes();
alter table office_dashboard.audit_log enable row level security;
