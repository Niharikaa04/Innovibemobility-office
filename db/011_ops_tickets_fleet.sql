-- 011: Service Tickets (category, due date, history, technician name) and Fleet Management (vehicles + service history).
-- Additive and safe to re-run. Apply after 005 (audit_log) and 010 (service_tickets).

-- ===== Service tickets: new columns =====
alter table office_dashboard.service_tickets add column if not exists category text not null default 'GENERAL';
alter table office_dashboard.service_tickets add column if not exists due_date date;
alter table office_dashboard.service_tickets add column if not exists assigned_name text;
alter table office_dashboard.service_tickets add column if not exists resolved_at timestamptz;
do $$ begin
  if not exists (select 1 from pg_constraint where conname='service_tickets_category_chk') then
    alter table office_dashboard.service_tickets add constraint service_tickets_category_chk
      check (category in ('GENERAL','BATTERY','MOTOR','CHARGER','BRAKES','ELECTRICAL','SOFTWARE','BODY','TYRES','PREVENTIVE','OTHER'));
  end if;
end $$;
create index if not exists service_tickets_priority_idx on office_dashboard.service_tickets(priority) where not archived;
create index if not exists service_tickets_category_idx on office_dashboard.service_tickets(category) where not archived;
create index if not exists service_tickets_due_idx on office_dashboard.service_tickets(due_date) where not archived and due_date is not null;

-- ===== Ticket history: every create / edit / assignment / status change / comment =====
create table if not exists office_dashboard.service_ticket_events (
 id bigserial primary key,
 ticket_id uuid not null references office_dashboard.service_tickets(id),
 event_type text not null check (event_type in ('created','updated','assigned','status_changed','comment')),
 actor_id text not null, actor_name text,
 detail jsonb not null default '{}'::jsonb check (jsonb_typeof(detail)='object'),
 created_at timestamptz not null default now()
);
create index if not exists service_ticket_events_ticket_idx on office_dashboard.service_ticket_events(ticket_id, created_at, id);
alter table office_dashboard.service_ticket_events enable row level security;

-- ===== Fleet vehicles =====
create table if not exists office_dashboard.fleet_vehicles (
 id uuid primary key default gen_random_uuid(),
 registration_number text not null check (length(trim(registration_number)) between 4 and 20),
 vehicle_type text not null check (vehicle_type in ('TWO_WHEELER','THREE_WHEELER','CAR','VAN','BUS','TRUCK','OTHER')),
 make text not null check (length(trim(make)) between 1 and 80),
 model text not null check (length(trim(model)) between 1 and 80),
 battery_capacity_kwh numeric(8,2) check (battery_capacity_kwh is null or (battery_capacity_kwh > 0 and battery_capacity_kwh <= 2000)),
 status text not null default 'ACTIVE' check (status in ('ACTIVE','IN_SERVICE','IDLE','OUT_OF_SERVICE','DECOMMISSIONED')),
 vin text check (vin is null or length(vin) <= 40),
 manufacture_year int check (manufacture_year is null or manufacture_year between 1990 and 2100),
 customer_name text check (customer_name is null or length(customer_name) <= 180),
 odometer_km numeric(10,1) check (odometer_km is null or odometer_km >= 0),
 notes text not null default '' check (length(notes) <= 5000),
 created_by text not null, archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
-- A registration number is unique among live (non-archived) vehicles, ignoring case, spaces and hyphens (KA01AB1234 = KA 01 AB-1234).
create unique index if not exists fleet_vehicles_reg_uq on office_dashboard.fleet_vehicles((regexp_replace(upper(registration_number),'[^A-Z0-9]','','g'))) where not archived;
create index if not exists fleet_vehicles_status_idx on office_dashboard.fleet_vehicles(status, updated_at desc) where not archived;
create index if not exists fleet_vehicles_type_idx on office_dashboard.fleet_vehicles(vehicle_type) where not archived;
alter table office_dashboard.fleet_vehicles enable row level security;

-- ===== Vehicle service history =====
create table if not exists office_dashboard.fleet_service_history (
 id bigserial primary key,
 vehicle_id uuid not null references office_dashboard.fleet_vehicles(id),
 service_date date not null,
 service_type text not null check (length(trim(service_type)) between 1 and 120),
 description text not null default '' check (length(description) <= 3000),
 cost numeric(12,2) check (cost is null or cost >= 0),
 odometer_km numeric(10,1) check (odometer_km is null or odometer_km >= 0),
 technician_name text check (technician_name is null or length(technician_name) <= 180),
 ticket_id uuid references office_dashboard.service_tickets(id),
 created_by text not null, created_at timestamptz not null default now()
);
create index if not exists fleet_service_history_vehicle_idx on office_dashboard.fleet_service_history(vehicle_id, service_date desc, id desc);
alter table office_dashboard.fleet_service_history enable row level security;
