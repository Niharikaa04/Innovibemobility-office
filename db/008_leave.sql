-- 008: HR & Leave. ADDITIVE ONLY. Safe to re-run. Run AFTER 001, 005 and 007 (it reads attendance_config for working days). NOT applied to any real database yet.
-- No leave type, entitlement or holiday is seeded: they are company policy and are entered by an administrator in the app.
create table if not exists office_dashboard.leave_types (
  id                      uuid primary key default gen_random_uuid(),
  code                    text not null unique check (code ~ '^[a-z0-9_]{2,30}$'),
  name                    text not null check (length(btrim(name)) between 1 and 80),
  is_paid                 boolean not null default true,
  annual_entitlement_days numeric(5,1) check (annual_entitlement_days is null or annual_entitlement_days >= 0),   -- NULL = no cap tracked (e.g. unpaid)
  allow_half_day          boolean not null default false,
  min_notice_days         integer not null default 0 check (min_notice_days between 0 and 365),
  allow_backdated_days    integer not null default 0 check (allow_backdated_days between 0 and 365),
  max_consecutive_days    integer check (max_consecutive_days is null or max_consecutive_days between 1 and 366),
  is_active               boolean not null default true,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create table if not exists office_dashboard.leave_requests (
  id             uuid primary key default gen_random_uuid(),
  user_id        text not null,
  leave_type_id  uuid not null references office_dashboard.leave_types(id),
  start_date     date not null,
  end_date       date not null,
  half_day       text check (half_day in ('first_half','second_half')),
  days           numeric(4,1) not null check (days > 0),                -- working days, computed by the server when requested
  reason         text not null check (length(btrim(reason)) between 3 and 500),
  status         text not null default 'pending' check (status in ('pending','approved','rejected','cancelled')),
  decided_by     text,
  decided_at     timestamptz,
  decision_note  text check (decision_note is null or length(decision_note) <= 1000),
  cancelled_by   text,
  cancelled_at   timestamptz,
  created_at     timestamptz not null default now(),
  check (end_date >= start_date),
  check (extract(year from start_date) = extract(year from end_date)),
  check (half_day is null or start_date = end_date),
  check ((status = 'pending'   and decided_by is null and cancelled_by is null)
      or (status in ('approved','rejected') and decided_by is not null and cancelled_by is null)
      or (status = 'cancelled' and cancelled_by is not null))
);
create index if not exists leave_requests_user_idx  on office_dashboard.leave_requests (user_id, start_date);
create index if not exists leave_requests_state_idx on office_dashboard.leave_requests (status, start_date);
create index if not exists leave_requests_range_idx on office_dashboard.leave_requests (start_date, end_date);
create table if not exists office_dashboard.holidays (
  id           uuid primary key default gen_random_uuid(),
  holiday_date date not null unique,
  name         text not null check (length(btrim(name)) between 1 and 120),
  created_by   text,
  created_at   timestamptz not null default now()
);
alter table office_dashboard.leave_types    enable row level security;
alter table office_dashboard.leave_requests enable row level security;
alter table office_dashboard.holidays       enable row level security;
