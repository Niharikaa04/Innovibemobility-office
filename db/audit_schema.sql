-- READ-ONLY schema audit for office_dashboard. Changes nothing. Run each query separately
-- (Supabase SQL editor runs only the last result of a multi-statement script) and paste the results back.

-- 1. Tables and approximate row counts
select c.relname as table_name, c.reltuples::bigint as approx_rows
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'office_dashboard' and c.relkind = 'r' order by 1;

-- 2. Do shared-entity tables already exist under any spelling?
select table_name from information_schema.tables
where table_schema = 'office_dashboard'
  and table_name ~* '(customer|client|organi[sz]ation|compan|account|campaign|lead|contact)' order by 1;

-- 3. Every foreign key (what is already linked)
select conrelid::regclass as table_name, conname, pg_get_constraintdef(oid) as definition
from pg_constraint where contype = 'f' and connamespace = 'office_dashboard'::regnamespace order by 1, 2;

-- 4. Columns that probably hold a shared entity as free text or an id (possible duplicate storage)
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'office_dashboard'
  and column_name ~* '(customer|client|company|organi[sz]ation|account|owner|contact|lead|campaign)'
order by 1, 2;

-- 5. Records held in the generic module_records store, per module (active vs archived)
select module, count(*) filter (where not archived) as active, count(*) filter (where archived) as archived
from office_dashboard.module_records group by 1 order by 1;

-- 6. Organization names that differ only by case/spacing in contacts (candidates to merge)
select lower(btrim(organization)) as key, count(*) as contacts, array_agg(distinct organization) as spellings
from office_dashboard.contacts
where not is_archived and organization is not null
group by 1 having count(distinct organization) > 1 order by 2 desc;

-- 7. Lead health: leads without a contact, and counts per stage
select count(*) filter (where contact_id is null) as leads_without_contact, count(*) as total_leads
from office_dashboard.leads where not is_archived;
select stage, count(*) from office_dashboard.leads where not is_archived group by 1 order by 1;

-- 8. Has migration 013 been applied?
select column_name from information_schema.columns
where table_schema = 'office_dashboard' and table_name = 'contacts' and column_name = 'contact_type';

-- 9. Every unique constraint/index (what is already protected from duplicates)
select schemaname, tablename, indexname, indexdef
from pg_indexes where schemaname = 'office_dashboard' and indexdef ilike '%unique%' order by tablename, indexname;

-- 10. Text columns that look like a copied name/identifier of a shared entity (candidates to become foreign keys)
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'office_dashboard' and data_type in ('text', 'character varying')
  and column_name ~* '(name|reg|vin|plate|owner|customer|client|garage|technician|assignee|assigned|city|phone|email)'
order by table_name, column_name;
