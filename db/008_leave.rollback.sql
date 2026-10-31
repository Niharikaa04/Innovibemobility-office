-- Rollback for 008. DROPS ALL LEAVE TYPES, REQUESTS AND HOLIDAYS. Take a backup first.
drop table if exists office_dashboard.leave_requests;
drop table if exists office_dashboard.holidays;
drop table if exists office_dashboard.leave_types;
