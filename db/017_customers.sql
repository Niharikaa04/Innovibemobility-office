-- 017: Customers (Fleets / OEMs). Additive and safe to re-run. Apply after 003 (contacts) and, for vehicle counts, 011 (fleet_vehicles).
-- A customer is an organisation. Its contact person is NOT copied: primary_contact_id points at the existing CRM contact (office_dashboard.contacts).
-- Vehicle counts are never stored: they are derived from fleet_vehicles.customer_name at read time (see customerapi.py).
create table if not exists office_dashboard.customers (
 id uuid primary key default gen_random_uuid(),
 name text not null check (length(btrim(name)) between 1 and 180),
 customer_type text not null check (customer_type in ('FLEET','OEM')),
 status text not null default 'NEW' check (status in ('NEW','ACTIVE','INACTIVE')),
 primary_contact_id uuid references office_dashboard.contacts(id),
 city text check (city is null or length(city) <= 80),
 description text not null default '' check (length(description) <= 3000),
 created_by text not null, updated_by text,
 archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
-- No two live customers may share a name (ignoring case and extra spaces), and a CRM contact can be primary for only one live customer.
create unique index if not exists customers_name_uq on office_dashboard.customers ((lower(regexp_replace(btrim(name),'\s+',' ','g')))) where not archived;
create unique index if not exists customers_contact_uq on office_dashboard.customers (primary_contact_id) where not archived and primary_contact_id is not null;
create index if not exists customers_type_status_idx on office_dashboard.customers (customer_type, status) where not archived;
create index if not exists customers_city_idx on office_dashboard.customers (lower(city)) where not archived;
alter table office_dashboard.customers enable row level security;
