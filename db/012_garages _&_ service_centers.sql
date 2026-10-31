-- 012: Garages & Service Centers, Technicians (extended), EVcare.AI diagnostics, IoT & Telemetry.
-- Additive and safe to re-run. Apply AFTER 001, 005, 010, 011. Nothing is seeded: every table starts empty.

-- ===== Service centers =====
create table if not exists office_dashboard.service_centers (
 id uuid primary key default gen_random_uuid(),
 name text not null check (length(trim(name)) between 1 and 180),
 address text not null default '' check (length(address) <= 500),
 city text check (city is null or length(city) <= 100),
 state text check (state is null or length(state) <= 100),
 contact_person text check (contact_person is null or length(contact_person) <= 120),
 phone text check (phone is null or length(phone) <= 20),
 email text check (email is null or length(email) <= 254),
 supported_services text[] not null default '{}',
 status text not null default 'ACTIVE' check (status in ('ACTIVE','INACTIVE','TEMPORARILY_CLOSED')),
 notes text not null default '' check (length(notes) <= 3000),
 created_by text not null, archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create unique index if not exists service_centers_name_city_uq on office_dashboard.service_centers (lower(trim(name)), lower(coalesce(city,''))) where not archived;
create index if not exists service_centers_status_idx on office_dashboard.service_centers(status) where not archived;
create index if not exists service_centers_city_idx on office_dashboard.service_centers(lower(city)) where not archived;
alter table office_dashboard.service_centers enable row level security;

-- ===== Technicians: extend the db/001 table =====
alter table office_dashboard.technicians add column if not exists specialization text;
alter table office_dashboard.technicians add column if not exists service_center_id uuid references office_dashboard.service_centers(id);
alter table office_dashboard.technicians add column if not exists availability text not null default 'AVAILABLE';
alter table office_dashboard.technicians add column if not exists notes text not null default '';
alter table office_dashboard.technicians add column if not exists updated_at timestamptz not null default now();
do $$ begin
  if not exists (select 1 from pg_constraint where conname='technicians_availability_chk') then
    alter table office_dashboard.technicians add constraint technicians_availability_chk check (availability in ('AVAILABLE','BUSY','ON_LEAVE','UNAVAILABLE'));
  end if;
  if not exists (select 1 from pg_constraint where conname='technicians_notes_chk') then
    alter table office_dashboard.technicians add constraint technicians_notes_chk check (length(notes) <= 3000);
  end if;
end $$;
create index if not exists technicians_center_idx on office_dashboard.technicians(service_center_id);

-- ===== Tickets can be linked to a service center =====
alter table office_dashboard.service_tickets add column if not exists service_center_id uuid references office_dashboard.service_centers(id);
create index if not exists service_tickets_center_idx on office_dashboard.service_tickets(service_center_id) where not archived;

-- ===== EVcare.AI diagnostics =====
-- A fault row exists ONLY if a person recorded it, a real EVcare.AI call returned it, or (future) a real device reported it.
create table if not exists office_dashboard.diagnostic_faults (
 id bigserial primary key,
 vehicle_id uuid not null references office_dashboard.fleet_vehicles(id),
 fault_code text not null check (length(trim(fault_code)) between 1 and 40),
 description text not null default '' check (length(description) <= 2000),
 severity text not null check (severity in ('INFO','LOW','MEDIUM','HIGH','CRITICAL')),
 detected_at timestamptz not null,
 source text not null check (source in ('MANUAL','EVCARE_AI','IOT')),
 status text not null default 'ACTIVE' check (status in ('ACTIVE','RESOLVED')),
 resolved_at timestamptz,
 external_ref text check (external_ref is null or length(external_ref) <= 120),
 ticket_id uuid references office_dashboard.service_tickets(id),
 recorded_by text not null, created_at timestamptz not null default now()
);
create index if not exists diagnostic_faults_vehicle_idx on office_dashboard.diagnostic_faults(vehicle_id, detected_at desc, id desc);
create unique index if not exists diagnostic_faults_ext_uq on office_dashboard.diagnostic_faults(vehicle_id, source, external_ref) where external_ref is not null;
alter table office_dashboard.diagnostic_faults enable row level security;

-- Every attempt to call the AI service is logged (success or failure), so history shows what really happened.
create table if not exists office_dashboard.diagnostic_runs (
 id bigserial primary key,
 vehicle_id uuid not null references office_dashboard.fleet_vehicles(id),
 requested_by text not null,
 outcome text not null check (outcome in ('SUCCESS','FAILED')),
 message text not null default '' check (length(message) <= 1000),
 fault_count int not null default 0 check (fault_count >= 0),
 created_at timestamptz not null default now()
);
create index if not exists diagnostic_runs_vehicle_idx on office_dashboard.diagnostic_runs(vehicle_id, created_at desc);
alter table office_dashboard.diagnostic_runs enable row level security;

-- ===== IoT devices and telemetry =====
create table if not exists office_dashboard.iot_devices (
 id uuid primary key default gen_random_uuid(),
 device_identifier text not null check (device_identifier ~ '^[A-Za-z0-9._:-]{3,64}$'),
 name text check (name is null or length(name) <= 120),
 device_type text not null default 'OTHER' check (device_type in ('BMS','TELEMATICS','CHARGER','GPS','OTHER')),
 vehicle_id uuid references office_dashboard.fleet_vehicles(id),
 status text not null default 'ACTIVE' check (status in ('ACTIVE','INACTIVE')),
 offline_after_minutes int not null default 30 check (offline_after_minutes between 1 and 10080),
 token_hash text not null,            -- sha256 of the device token; the token itself is shown once and never stored
 token_hint text not null default '', -- last 4 characters, so people can tell tokens apart
 last_seen_at timestamptz,            -- set only when the device really contacts the server
 notes text not null default '' check (length(notes) <= 2000),
 created_by text not null, archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create unique index if not exists iot_devices_ident_uq on office_dashboard.iot_devices(lower(device_identifier)) where not archived;
create index if not exists iot_devices_vehicle_idx on office_dashboard.iot_devices(vehicle_id) where not archived;
alter table office_dashboard.iot_devices enable row level security;

create table if not exists office_dashboard.iot_readings (
 id bigserial primary key,
 device_id uuid not null references office_dashboard.iot_devices(id),
 vehicle_id uuid references office_dashboard.fleet_vehicles(id),   -- vehicle the device was attached to when the reading arrived
 metric text not null check (metric ~ '^[a-z][a-z0-9_]{1,39}$'),
 value double precision not null,
 unit text check (unit is null or length(unit) <= 16),
 recorded_at timestamptz not null, received_at timestamptz not null default now()
);
create unique index if not exists iot_readings_dedupe_uq on office_dashboard.iot_readings(device_id, metric, recorded_at);
create index if not exists iot_readings_vehicle_idx on office_dashboard.iot_readings(vehicle_id, metric, recorded_at desc);
create index if not exists iot_readings_metric_idx on office_dashboard.iot_readings(metric, recorded_at desc);
alter table office_dashboard.iot_readings enable row level security;

-- Alert limits are entered by an authorised person. None are assumed. Alerts only exist when a real reading breaks one.
create table if not exists office_dashboard.iot_thresholds (
 id bigserial primary key,
 metric text not null check (metric ~ '^[a-z][a-z0-9_]{1,39}$'),
 severity text not null check (severity in ('WARNING','CRITICAL')),
 min_value double precision, max_value double precision,
 created_by text not null, created_at timestamptz not null default now(),
 check (min_value is not null or max_value is not null),
 check (min_value is null or max_value is null or min_value < max_value),
 unique (metric, severity)
);
alter table office_dashboard.iot_thresholds enable row level security;