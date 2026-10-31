-- DESTRUCTIVE: permanently removes fleet vehicles, vehicle service history and ticket history, and the new ticket columns.
drop table if exists office_dashboard.fleet_service_history;
drop table if exists office_dashboard.fleet_vehicles;
drop table if exists office_dashboard.service_ticket_events;
alter table office_dashboard.service_tickets drop constraint if exists service_tickets_category_chk;
alter table office_dashboard.service_tickets drop column if exists category, drop column if exists due_date, drop column if exists assigned_name, drop column if exists resolved_at;
