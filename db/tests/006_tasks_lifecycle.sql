-- Exercises the exact SQL the Tasks / Employees / Audit endpoints issue. Runs inside run_migration_checks.sh on a SCRATCH database only.
\set ON_ERROR_STOP on
select id as me from office_dashboard.login_accounts where username='Niharika.it' \gset
select id as boss from office_dashboard.login_accounts where username='SriHari.ceo' \gset
truncate office_dashboard.tasks;
insert into office_dashboard.tasks(title,assignee_id,created_by,priority,due_date,requires_approval) values('Prepare report',:'me',:'boss','high','2026-11-01',true) returning id \gset t_
insert into office_dashboard.tasks(title,assignee_id,created_by) values('Someone elses',:'boss',:'boss');
select (select count(*) from office_dashboard.tasks t where not t.is_archived and (t.assignee_id=:'me' or t.created_by=:'me')) = 1 as ok_employee_sees_only_own \gset
select (select count(*) from office_dashboard.tasks t where not t.is_archived) = 2 as ok_ceo_sees_all \gset
\if :ok_employee_sees_only_own \else \echo 'FAIL own-only scoping'  \quit \endif
\if :ok_ceo_sees_all \else \echo 'FAIL ceo scope' \quit \endif
select title from office_dashboard.tasks t where not t.is_archived order by (t.status in ('done','cancelled')), t.due_date nulls last, t.created_at desc limit 20 offset 0;
select id::text as id, full_name as name from office_dashboard.login_accounts where id::text = any(array[:'me',:'boss']);
select id::text as id, full_name as name from office_dashboard.login_accounts where lower(is_active::text) = any(array['true','t','1','active']) and full_name ilike '%kad%' order by full_name limit 100;
update office_dashboard.tasks set status='pending_approval',completed_at=null,updated_at=now() where id=:'t_id' returning status;
update office_dashboard.tasks set status='done',approver_id=:'boss',decision_note=null,decided_at=now(),completed_at=now(),updated_at=now() where id=:'t_id' returning status, approver_id is not null as has_approver;
update office_dashboard.tasks set status='in_progress',completed_at=null,approver_id=null,decision_note=null,decided_at=null,updated_at=now() where id=:'t_id' returning status;
update office_dashboard.tasks set status='done',approver_id=:'boss',decided_at=now() where id=:'t_id';
\set ON_ERROR_STOP off
\echo 'EXPECTED ERROR next (check constraint tasks_check: approver without requires_approval):'
update office_dashboard.tasks set requires_approval=false where id=:'t_id';
\echo 'EXPECTED ERROR next (invalid uuid; the API maps this to 404):'
select * from office_dashboard.tasks where id='not-a-uuid';
\set ON_ERROR_STOP on
update office_dashboard.tasks set requires_approval=false,approver_id=null,decision_note=null,decided_at=null where id=:'t_id' returning requires_approval;
update office_dashboard.tasks set is_archived=true where id=:'t_id';
insert into office_dashboard.audit_log(user_id,actor_id,actor_role,action,entity_type,entity_id,before_data,after_data,outcome,source,request_id,ip)
 values(:'boss',:'boss','ceo','task.created','task',:'t_id',null,'{"title":"Prepare report"}'::jsonb,'success','app',null,'203.0.113.7'::inet);
select action, host(ip) as ip from office_dashboard.audit_log where entity_type='task' and coalesce(actor_id,user_id)=:'boss' order by occurred_at desc, id desc limit 50;
\echo 'EXPECTED ERROR next (audit_log is append-only):'
\set ON_ERROR_STOP off
update office_dashboard.audit_log set action='tampered';
\set ON_ERROR_STOP on
\echo 'LIFECYCLE CHECKS DONE'
