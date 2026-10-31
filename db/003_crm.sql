-- CRM: contacts, leads, lead activities. ADDITIVE ONLY. Run after 001_foundation.sql. Safe to re-run.
create table if not exists office_dashboard.contacts (
  id uuid primary key default gen_random_uuid(), full_name text not null, email text, phone text, organization text, notes text,
  is_archived boolean not null default false, created_by text, updated_by text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create unique index if not exists contacts_email_uq on office_dashboard.contacts (lower(email)) where email is not null and not is_archived;
create table if not exists office_dashboard.leads (
  id uuid primary key default gen_random_uuid(), contact_id uuid references office_dashboard.contacts(id), title text not null, source text,
  stage text not null default 'new' check (stage in ('new','contacted','qualified','proposal','negotiation','won','lost')),
  value numeric(14,2) check (value is null or value >= 0), next_follow_up date, lost_reason text,
  is_archived boolean not null default false, created_by text, updated_by text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create index if not exists leads_stage_idx on office_dashboard.leads (stage) where not is_archived;
create table if not exists office_dashboard.lead_activities (
  id bigserial primary key, lead_id uuid not null references office_dashboard.leads(id), note text not null, created_by text, created_at timestamptz not null default now());
alter table office_dashboard.contacts enable row level security; alter table office_dashboard.leads enable row level security; alter table office_dashboard.lead_activities enable row level security;
