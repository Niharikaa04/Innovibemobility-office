-- Rollback for 017. Drops the customers table (CRM contacts and fleet vehicles are untouched).
drop table if exists office_dashboard.customers;
