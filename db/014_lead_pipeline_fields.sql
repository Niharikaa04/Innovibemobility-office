-- 014: Leads & Pipeline fields. ADDITIVE ONLY. Safe to re-run. Run after 003_crm.sql (and 013 if not yet applied).
-- Adds: expected closure date, notes, converted_at. Nothing is renamed, rewritten or deleted, and existing lead stages are NOT changed:
-- the New / Contacted / In Discussion / Proposal / Converted / Lost-Closed names are a read-time mapping in the API
-- (qualified + negotiation -> In Discussion, won -> Converted, lost -> Lost / Closed).
-- Existing rows get NULL in all three new columns; converted_at is deliberately NOT back-filled for old 'won' rows (no guessing of dates).
-- Not included yet (needs the users / campaigns / customers tables): owner, campaign, customer links.
alter table office_dashboard.leads
  add column if not exists expected_closure date,
  add column if not exists notes text,
  add column if not exists converted_at timestamptz;
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid='office_dashboard.leads'::regclass and conname='leads_notes_len_check') then
    alter table office_dashboard.leads add constraint leads_notes_len_check check (notes is null or char_length(notes) <= 2000);
  end if;
end $$;
create index if not exists leads_created_idx on office_dashboard.leads (created_at) where not is_archived;
create index if not exists leads_contact_idx on office_dashboard.leads (contact_id) where not is_archived;
create index if not exists lead_activities_lead_idx on office_dashboard.lead_activities (lead_id, created_at desc);
