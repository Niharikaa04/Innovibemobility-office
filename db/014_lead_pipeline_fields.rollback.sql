-- Rollback for 014. Drops only the columns/indexes it added (expected_closure, notes, converted_at values are lost). Stages and all other lead data are untouched.
drop index if exists office_dashboard.lead_activities_lead_idx;
drop index if exists office_dashboard.leads_contact_idx;
drop index if exists office_dashboard.leads_created_idx;
alter table office_dashboard.leads drop constraint if exists leads_notes_len_check;
alter table office_dashboard.leads
  drop column if exists converted_at, drop column if exists notes, drop column if exists expected_closure;
