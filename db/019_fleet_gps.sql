-- db/012_fleet_gps.sql  —  Live GPS for Fleet Management
-- Additive only: does not alter office_dashboard.fleet_vehicles.
-- ASSUMPTION: fleet_vehicles.id is uuid (fleetapi.py catches InvalidTextRepresentation on lookups).
-- Verify with:  select pg_typeof(id) from office_dashboard.fleet_vehicles limit 1;   (change the uuid columns below if it differs)

begin;

-- 1) Devices: one row per GPS tracker / app install / provider device, bound to one vehicle.
--    Only a SHA-256 hash of the secret is stored; the plaintext token is shown once at creation.
create table if not exists office_dashboard.fleet_gps_devices (
  id           uuid primary key default gen_random_uuid(),
  vehicle_id   uuid not null references office_dashboard.fleet_vehicles(id) on delete cascade,
  label        text not null check (char_length(label) between 1 and 120),
  external_id  text,                                   -- provider device id / IMEI, used by provider webhooks
  token_hash   text not null unique,                   -- hex sha256 of the bearer token
  active       boolean not null default true,
  last_seen_at timestamptz,
  created_by   uuid,
  created_at   timestamptz not null default now(),
  revoked_at   timestamptz
);
create unique index if not exists fleet_gps_devices_external_uq on office_dashboard.fleet_gps_devices(external_id) where external_id is not null and active;
create index if not exists fleet_gps_devices_vehicle_idx on office_dashboard.fleet_gps_devices(vehicle_id) where active;

-- 2) Current position: exactly one row per vehicle (latest accepted fix). Kept apart from history.
create table if not exists office_dashboard.fleet_vehicle_position (
  vehicle_id   uuid primary key references office_dashboard.fleet_vehicles(id) on delete cascade,
  latitude     double precision not null check (latitude  between -90  and 90),
  longitude    double precision not null check (longitude between -180 and 180),
  gps_time     timestamptz not null,                   -- time the device recorded the fix
  received_at  timestamptz not null default now(),     -- time our server accepted it
  speed_kmh    real check (speed_kmh is null or speed_kmh between 0 and 400),
  heading_deg  real check (heading_deg is null or heading_deg >= 0 and heading_deg < 360),
  accuracy_m   real check (accuracy_m is null or accuracy_m >= 0),
  battery_pct  real check (battery_pct is null or battery_pct between 0 and 100),
  charging     boolean,                                -- only set when the device/provider reports it
  source       text not null default 'device',         -- 'device' | 'provider:<name>' | 'simulator'
  device_id    uuid references office_dashboard.fleet_gps_devices(id) on delete set null
);
create index if not exists fleet_vehicle_position_time_idx on office_dashboard.fleet_vehicle_position(gps_time desc);

-- 3) History: append-only recorded fixes (route trail). (vehicle_id, gps_time) is unique -> replays are no-ops.
create table if not exists office_dashboard.fleet_gps_history (
  id          bigint generated always as identity primary key,
  vehicle_id  uuid not null references office_dashboard.fleet_vehicles(id) on delete cascade,
  latitude    double precision not null check (latitude  between -90  and 90),
  longitude   double precision not null check (longitude between -180 and 180),
  gps_time    timestamptz not null,
  received_at timestamptz not null default now(),
  speed_kmh   real,
  battery_pct real,
  source      text not null default 'device',
  unique (vehicle_id, gps_time)
);
create index if not exists fleet_gps_history_vehicle_time_idx on office_dashboard.fleet_gps_history(vehicle_id, gps_time desc);

-- 4) Access control. The FastAPI backend connects with its own DB role; browsers never talk to these tables.
--    RLS on + no policies = deny-all for any non-owner role (e.g. Supabase anon / authenticated).
alter table office_dashboard.fleet_gps_devices   enable row level security;
alter table office_dashboard.fleet_vehicle_position enable row level security;
alter table office_dashboard.fleet_gps_history   enable row level security;

do $$
declare r text;
begin
  foreach r in array array['anon','authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on office_dashboard.fleet_gps_devices, office_dashboard.fleet_vehicle_position, office_dashboard.fleet_gps_history from %I', r);
    end if;
  end loop;
end $$;

commit;

-- Retention (run from a scheduler, not part of the migration), e.g. keep 90 days:
--   delete from office_dashboard.fleet_gps_history where gps_time < now() - interval '90 days';
