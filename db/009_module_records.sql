-- Generic, auditable record store for modules that lack dedicated domain schemas.
-- This is a foundation for user-entered operational records, not a substitute for provider integrations.
create table if not exists office_dashboard.module_records (
 id uuid primary key default gen_random_uuid(),
 module text not null check (module ~ '^[a-z0-9-]{1,80}$'),
 title text not null check (length(trim(title)) between 1 and 180),
 status text not null default 'Open' check (length(status) <= 50),
 description text not null default '' check (length(description) <= 5000),
 amount numeric(14,2) check (amount is null or amount >= 0),
 due_date date,
 fields jsonb not null default '{}'::jsonb check (jsonb_typeof(fields)='object'),
 created_by text not null,
 archived boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index if not exists module_records_module_updated_idx on office_dashboard.module_records(module,updated_at desc) where not archived;
create index if not exists module_records_module_title_idx on office_dashboard.module_records(module,title) where not archived;
alter table office_dashboard.module_records enable row level security;
