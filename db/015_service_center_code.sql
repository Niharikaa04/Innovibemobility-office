-- 015: human-readable service center IDs (SC-00001, SC-00002, ...). ADDITIVE ONLY. Safe to re-run. Run after 012.
-- garageapi.py searches, lists, exports and displays service_centers.center_code and never sets it on insert, so the database must generate it.
-- Existing centers are numbered once, oldest first. No center is renamed, deleted or otherwise changed.
create sequence if not exists office_dashboard.service_center_code_seq;
alter table office_dashboard.service_centers add column if not exists center_code text;
update office_dashboard.service_centers c set center_code = 'SC-' || lpad(n.rn::text, 5, '0')
  from (select id, row_number() over (order by created_at, id) as rn from office_dashboard.service_centers where center_code is null) n
 where c.id = n.id and c.center_code is null;
select setval('office_dashboard.service_center_code_seq', greatest(coalesce((select max(substring(center_code from 4)::int) from office_dashboard.service_centers where center_code ~ '^SC-[0-9]+$'), 0), 1),
              exists (select 1 from office_dashboard.service_centers where center_code ~ '^SC-[0-9]+$'));
alter table office_dashboard.service_centers alter column center_code set default ('SC-' || lpad(nextval('office_dashboard.service_center_code_seq')::text, 5, '0'));
alter table office_dashboard.service_centers alter column center_code set not null;
create unique index if not exists service_centers_code_uq on office_dashboard.service_centers (center_code);
