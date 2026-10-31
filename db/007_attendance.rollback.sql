-- Rollback for 007. DROPS ALL ATTENDANCE DATA. Take a backup first.
drop table if exists office_dashboard.attendance_corrections;
drop table if exists office_dashboard.attendance_records;
drop table if exists office_dashboard.attendance_config;
