-- 004: restrict lead stages to New Lead / Contacted / Proposal Sent / Negotiation / Won / Lost (removes legacy 'qualified').
-- NOT APPLIED to any database yet. Review first. Reversible with 004_pipeline_stages.rollback.sql.
-- STEP 0 (read-only, run first): select stage, count(*) from office_dashboard.leads group by 1 order by 1;
--   If 'qualified' rows exist this script ABORTS and changes nothing. Decide per business (e.g. qualified -> contacted or proposal),
--   then move those rows explicitly with your own reviewed UPDATE. This script never rewrites data.
-- The enum VALUE 'proposal' is kept (the app displays it as "Proposal Sent"), so no data rewrite is needed.
do $$
declare n bigint; c text;
begin
  select count(*) into n from office_dashboard.leads where stage = 'qualified';
  if n > 0 then raise exception '004 aborted: % lead(s) are still in legacy stage "qualified". Move them first.', n; end if;
  for c in select conname from pg_constraint
           where conrelid = 'office_dashboard.leads'::regclass and contype = 'c' and pg_get_constraintdef(oid) ilike '%stage%' loop
    execute format('alter table office_dashboard.leads drop constraint %I', c);
  end loop;
  alter table office_dashboard.leads add constraint leads_stage_check
    check (stage in ('new','contacted','proposal','negotiation','won','lost'));
end $$;
