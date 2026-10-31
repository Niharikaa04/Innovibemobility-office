-- 006: Tasks & Approvals. ADDITIVE ONLY. Safe to re-run. Run AFTER 001 (schema) and 005 (audit_log).
-- User references are stored as TEXT (the id the API session carries) with no foreign key, because the login source is
-- configurable (USERS_TABLE) and has not been verified against your real database. The API validates assignees through the
-- same user repository the login uses.
create table if not exists office_dashboard.tasks (
  id               uuid primary key default gen_random_uuid(),
  title            text not null check (length(btrim(title)) between 1 and 160),
  description      text check (description is null or length(description) <= 4000),
  assignee_id      text not null,
  created_by       text not null,
  status           text not null default 'open'
                   check (status in ('open','in_progress','pending_approval','done','cancelled')),
  priority         text not null default 'normal' check (priority in ('low','normal','high')),
  due_date         date,
  requires_approval boolean not null default false,
  approver_id      text,
  decision_note    text check (decision_note is null or length(decision_note) <= 1000),
  decided_at       timestamptz,
  completed_at     timestamptz,
  is_archived      boolean not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- a decision (approver) can only exist once the task has been submitted for approval
  check (approver_id is null or requires_approval)
);
create index if not exists tasks_assignee_idx on office_dashboard.tasks (assignee_id, status) where not is_archived;
create index if not exists tasks_creator_idx  on office_dashboard.tasks (created_by) where not is_archived;
create index if not exists tasks_status_idx   on office_dashboard.tasks (status, due_date) where not is_archived;
alter table office_dashboard.tasks enable row level security;
