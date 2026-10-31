-- 013: add contacts.contact_type. ADDITIVE ONLY. Safe to re-run. Run after 003_crm.sql.
-- Existing rows get 'other' (no guessing of business meaning); reclassify them in the UI.
alter table office_dashboard.contacts add column if not exists contact_type text not null default 'other';
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid='office_dashboard.contacts'::regclass and conname='contacts_contact_type_check') then
    alter table office_dashboard.contacts add constraint contacts_contact_type_check
      check (contact_type in ('customer','partner','vendor','internal','other'));
  end if;
end $$;
create index if not exists contacts_type_idx on office_dashboard.contacts (contact_type) where not is_archived;
create index if not exists contacts_created_idx on office_dashboard.contacts (created_at) where not is_archived;
