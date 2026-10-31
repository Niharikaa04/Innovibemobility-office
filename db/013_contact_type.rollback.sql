-- Rollback for 013. Drops only the column/indexes it added (contact_type values are lost).
drop index if exists office_dashboard.contacts_type_idx;
drop index if exists office_dashboard.contacts_created_idx;
alter table office_dashboard.contacts drop constraint if exists contacts_contact_type_check;
alter table office_dashboard.contacts drop column if exists contact_type;
