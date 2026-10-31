-- Rollback for 006: drops the tasks table and ALL task data. Export first if you need it.
drop table if exists office_dashboard.tasks;
