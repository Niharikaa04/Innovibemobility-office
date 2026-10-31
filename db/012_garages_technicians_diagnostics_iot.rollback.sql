-- DESTRUCTIVE: permanently removes service centers, diagnostic faults/runs, IoT devices, readings and thresholds,
-- and the extra technician / ticket columns added by 012.
drop table if exists office_dashboard.iot_thresholds;
drop table if exists office_dashboard.iot_readings;
drop table if exists office_dashboard.iot_devices;
drop table if exists office_dashboard.diagnostic_runs;
drop table if exists office_dashboard.diagnostic_faults;
alter table office_dashboard.service_tickets drop column if exists service_center_id;
alter table office_dashboard.technicians drop constraint if exists technicians_availability_chk, drop constraint if exists technicians_notes_chk;
alter table office_dashboard.technicians drop column if exists specialization, drop column if exists service_center_id, drop column if exists availability, drop column if exists notes, drop column if exists updated_at;
drop table if exists office_dashboard.service_centers;
