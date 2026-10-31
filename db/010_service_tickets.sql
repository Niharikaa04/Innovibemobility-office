-- Service ticket records and comments. Apply after 009_module_records.sql.
create table if not exists office_dashboard.service_tickets (
 id uuid primary key default gen_random_uuid(), ticket_number text not null unique,
 title text not null check(length(trim(title)) between 1 and 180), description text not null default '' check(length(description)<=5000),
 customer_name text, vehicle_reference text, priority text not null default 'MEDIUM' check(priority in ('LOW','MEDIUM','HIGH','URGENT')),
 status text not null default 'NEW' check(status in ('NEW','TRIAGED','DIAGNOSIS','ASSIGNED','ACCEPTED','IN_PROGRESS','PARTS_REQUIRED','WAITING','REPAIR','QUALITY_CHECK','COMPLETED','CUSTOMER_CONFIRMATION','CLOSED')),
 assigned_to text, created_by text not null, archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists service_tickets_status_updated_idx on office_dashboard.service_tickets(status,updated_at desc) where not archived;
create index if not exists service_tickets_assigned_idx on office_dashboard.service_tickets(assigned_to,status) where not archived;
create table if not exists office_dashboard.service_ticket_comments (
 id bigserial primary key, ticket_id uuid not null references office_dashboard.service_tickets(id),
 comment text not null check(length(trim(comment)) between 1 and 3000), created_by text not null, created_at timestamptz not null default now()
);
create index if not exists service_ticket_comments_ticket_idx on office_dashboard.service_ticket_comments(ticket_id,created_at);
alter table office_dashboard.service_tickets enable row level security;
alter table office_dashboard.service_ticket_comments enable row level security;
