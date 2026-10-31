-- Rollback for 004: restores the original stage constraint from 003 (re-allows 'qualified'). No data is changed.
do $$
declare c text;
begin
  for c in select conname from pg_constraint
           where conrelid = 'office_dashboard.leads'::regclass and contype = 'c' and pg_get_constraintdef(oid) ilike '%stage%' loop
    execute format('alter table office_dashboard.leads drop constraint %I', c);
  end loop;
  alter table office_dashboard.leads add constraint leads_stage_check
    check (stage in ('new','contacted','qualified','proposal','negotiation','won','lost'));
end $$;
