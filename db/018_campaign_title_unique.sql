-- 018: stop duplicate Sales & Marketing campaigns (same title, ignoring case and spaces) in the generic module_records store.
-- Additive and safe to re-run. Apply after 009. Only affects module 'sales-and-marketing'; other modules are untouched.
-- Existing data is NEVER changed or deleted: if duplicate live campaign titles already exist the index is skipped with a notice.
do $$ begin
 if exists (select 1 from office_dashboard.module_records where module='sales-and-marketing' and not archived group by lower(btrim(title)) having count(*) > 1) then
  raise notice '018 skipped: duplicate live campaign titles exist. Find them with: select lower(btrim(title)), count(*) from office_dashboard.module_records where module=''sales-and-marketing'' and not archived group by 1 having count(*)>1; then rename or archive the extras and re-run this file.';
 else
  create unique index if not exists module_records_campaign_title_uq on office_dashboard.module_records ((lower(btrim(title)))) where module = 'sales-and-marketing' and not archived;
 end if;
end $$;
