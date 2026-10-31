-- Rollback for 015. Removes the generated center IDs (the SC-xxxxx values are lost) and the Garages page stops working until 015 is re-applied.
drop index if exists office_dashboard.service_centers_code_uq;
alter table office_dashboard.service_centers drop column if exists center_code;
drop sequence if exists office_dashboard.service_center_code_seq;
