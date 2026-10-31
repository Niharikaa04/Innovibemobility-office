-- Rollback for 005: removes the append-only trigger and the columns 005 added. The 001 columns and ALL rows are kept.
-- Note: the extra columns' data (before/after, entity) is lost on rollback. Export first if you need it.
drop trigger if exists audit_log_no_update on office_dashboard.audit_log;
drop function if exists office_dashboard.audit_log_block_changes();
drop index if exists office_dashboard.audit_entity_idx, office_dashboard.audit_actor_idx, office_dashboard.audit_time_idx;
alter table office_dashboard.audit_log drop constraint if exists audit_log_outcome_check;
alter table office_dashboard.audit_log
  drop column if exists actor_id, drop column if exists actor_role, drop column if exists entity_type, drop column if exists entity_id,
  drop column if exists before_data, drop column if exists after_data, drop column if exists outcome, drop column if exists source,
  drop column if exists request_id;
