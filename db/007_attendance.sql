-- 007: Attendance. ADDITIVE ONLY. Safe to re-run. Run AFTER 001 (schema) and 005 (audit_log). NOT applied to any real database yet.
-- User references are TEXT with no foreign key (same reason as 006: the login source is configurable).
-- No policy is seeded: the shift/timezone/working days row is created by an administrator in the app.
create table if not exists office_dashboard.attendance_config (
  id             boolean primary key default true check (id),            -- exactly one row
  start_time     time     not null,
  end_time       time     not null,
  grace_minutes  integer  not null default 0 check (grace_minutes between 0 and 240),
  timezone       text     not null check (length(timezone) between 1 and 64),
  working_days   smallint[] not null check (cardinality(working_days) between 1 and 7 and working_days <@ array[1,2,3,4,5,6,7]::smallint[]),
  updated_by     text,
  updated_at     timestamptz not null default now(),
  check (end_time > start_time)
);
create table if not exists office_dashboard.attendance_records (
  id          uuid primary key default gen_random_uuid(),
  user_id     text not null,
  work_date   date not null,                                           -- calendar date in the configured timezone, computed by the server
  check_in    timestamptz not null,
  check_out   timestamptz,
  source      text not null default 'self' check (source in ('self','correction')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (user_id, work_date),                                         -- duplicate check-in protection, enforced by the database
  check (check_out is null or check_out > check_in)
);
create index if not exists attendance_records_date_idx on office_dashboard.attendance_records (work_date);
create table if not exists office_dashboard.attendance_corrections (
  id                  uuid primary key default gen_random_uuid(),
  user_id             text not null,
  work_date           date not null,
  requested_check_in  timestamptz,
  requested_check_out timestamptz,
  reason              text not null check (length(btrim(reason)) between 5 and 500),
  status              text not null default 'pending' check (status in ('pending','approved','rejected')),
  decided_by          text,
  decided_at          timestamptz,
  decision_note       text check (decision_note is null or length(decision_note) <= 1000),
  created_at          timestamptz not null default now(),
  check (requested_check_in is not null or requested_check_out is not null),
  check (requested_check_in is null or requested_check_out is null or requested_check_out > requested_check_in),
  check ((status = 'pending') = (decided_by is null))
);
create unique index if not exists attendance_one_pending on office_dashboard.attendance_corrections (user_id, work_date) where status = 'pending';
create index if not exists attendance_corr_status_idx on office_dashboard.attendance_corrections (status, created_at desc);
alter table office_dashboard.attendance_config      enable row level security;
alter table office_dashboard.attendance_records     enable row level security;
alter table office_dashboard.attendance_corrections enable row level security;
