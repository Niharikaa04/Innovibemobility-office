-- InnoVibe Office OS: foundation schema. ADDITIVE ONLY (no drops, no changes to existing objects).
-- Run ONLY in an empty/dev project. Safe to re-run (IF NOT EXISTS).
create schema if not exists office_dashboard;

create table if not exists office_dashboard.departments (
  id   bigserial primary key,
  name text not null unique
);

create table if not exists office_dashboard.employees (
  id                  uuid primary key default gen_random_uuid(),
  employee_code       text not null unique,
  full_name           text not null,
  email               text not null,
  phone               text,
  department_id       bigint references office_dashboard.departments(id),
  designation         text,
  reporting_manager_id uuid references office_dashboard.employees(id),
  is_active           boolean not null default true,
  created_at          timestamptz not null default now()
);
create unique index if not exists employees_email_uq on office_dashboard.employees (lower(email));

create table if not exists office_dashboard.users (
  id                   uuid primary key default gen_random_uuid(),
  employee_id          uuid not null unique references office_dashboard.employees(id),
  username             text not null,
  password_hash        text not null,
  role                 text not null check (role in ('ceo','coo','cto','service_manager','hr','technician','employee')),
  is_active            boolean not null default true,
  must_change_password boolean not null default true,
  created_at           timestamptz not null default now(),
  last_login_at        timestamptz
);
create unique index if not exists users_username_uq on office_dashboard.users (lower(username));

create table if not exists office_dashboard.technicians (
  id          uuid primary key default gen_random_uuid(),
  employee_id uuid not null unique references office_dashboard.employees(id),
  skills      text[] not null default '{}',
  is_active   boolean not null default true
);

create table if not exists office_dashboard.audit_log (
  id bigserial primary key, occurred_at timestamptz not null default now(),
  user_id text, action text not null, ip inet, detail jsonb not null default '{}'
);
create table if not exists office_dashboard.session_revocations (jti text primary key, expires_at timestamptz not null);

-- What the backend reads for login (SELECT only). An account is active only if BOTH the user and the employee are active.
create or replace view office_dashboard.login_accounts as
select u.id::text as id, e.full_name, u.username, e.email, u.password_hash, u.role,
       (u.is_active and e.is_active) as is_active
from office_dashboard.users u join office_dashboard.employees e on e.id = u.employee_id;

-- Lock out Supabase's public API; only the backend's direct database connection may use these tables.
alter table office_dashboard.departments         enable row level security;
alter table office_dashboard.employees           enable row level security;
alter table office_dashboard.users               enable row level security;
alter table office_dashboard.technicians         enable row level security;
alter table office_dashboard.audit_log           enable row level security;
alter table office_dashboard.session_revocations enable row level security;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on schema office_dashboard from anon, authenticated;
    revoke all on all tables in schema office_dashboard from anon, authenticated;
  end if;
end $$;
