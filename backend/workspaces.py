"""Configurable records for business modules that do not yet have a dedicated domain model.
Records are real user-entered data, never seeded/demo data. Provider-dependent actions remain unconfigured.
"""
import functools
from datetime import date
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
import permissions

# URL slug -> permission namespace. These are CRUD workspaces, not claims of domain-specific automation.
MODULES = {
 'startup-metrics':'kpi','kpi-center':'kpi','business-overview':'reports','reports-and-analytics':'reports',
 'customers-fleets-oems':'customers','sales-and-marketing':'sales','waba-whatsapp':'integrations','email':'integrations','unified-inbox':'integrations',
 'quotations-and-orders':'orders','service-tickets':'tickets','fleet-management':'fleet','garages-and-service-centers':'garages','technicians':'technicians',
 'evcare-ai-diagnostics':'diagnostics','iot-and-telemetry':'iot','revenue-and-invoices':'invoices','expenses':'expenses','payments-and-receivables':'payments',
 'budget-and-forecast':'budget','documents':'documents','integrations':'integrations','settings':'settings',
 'organizations':'crm','tags':'crm','activities':'crm','follow-ups':'crm','tech-projects':'reports','ai-and-innovation':'diagnostics',
 'technical-reports':'reports','system-monitoring':'integrations','infrastructure':'integrations','database':'integrations','servers-and-cloud':'integrations',
 'devops-and-deployment':'integrations','security-and-access':'settings','application':'integrations','mobile-app':'integrations','rnd-projects':'reports',
 'service-platform':'tickets','technician-app':'technicians','platform-analytics':'reports','knowledge-base':'documents','announcements':'documents',
 'profile':'employees','add-employee':'employees','team-directory':'employees','vehicle-directory':'fleet','service-history':'tickets',
 'ticket-queue':'tickets','technician-allocation':'technicians','job-cards':'tickets','spare-parts-requests':'fleet','quality-checks':'tickets','escalations':'tickets',
 'my-jobs':'tickets','parts-requests':'fleet','notifications':'tasks','roles-and-access':'settings','audit-history':'audit',
}
class RecordIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    status: str = Field(default='Open', max_length=50)
    description: str = Field(default='', max_length=5000)
    amount: float | None = Field(default=None, ge=0, le=1e12)
    due_date: date | None = None
    fields: dict = Field(default_factory=dict)
    @field_validator('fields')
    @classmethod
    def safe_fields(cls,v):
        if len(v) > 60: raise ValueError('At most 60 custom fields are allowed.')
        for k,val in v.items():
            if not isinstance(k,str) or not k.strip() or len(k)>80: raise ValueError('Custom field names must be non-empty strings of at most 80 characters.')
            if isinstance(val,(dict,list)) or (val is not None and len(str(val))>2000): raise ValueError('Custom field values must be simple values of at most 2,000 characters.')
        return v
    @field_validator('title','status','description', mode='before')
    @classmethod
    def trim(cls,v): return v.strip() if isinstance(v,str) else v

def dupe_409(fn):
    """Unique indexes on module_records (e.g. db/018 campaign titles) answer a duplicate with a clear 409 instead of a generic 500."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try: return fn(*a, **k)
        except psycopg.errors.UniqueViolation: raise HTTPException(409, 'A record with this title already exists in this module. Use a different title or edit the existing one.')
    return wrapper

def build_router(dsn, session, csrf, audit):
    r=APIRouter(prefix='/api/workspaces')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def check(module, action, write=False):
        def dep(s=Depends(csrf if write else session)):
            ns=MODULES.get(module)
            if not ns or not permissions.can(s['role'], f'{ns}.{action}'):
                audit.write('workspace_permission_denied',s['id'],None,module=module,action=action)
                raise HTTPException(403,'You do not have permission to access this module.')
            return s
        return dep
    @r.get('/{module}')
    def list_records(module:str, q:str='', status:str='', date_from:date|None=None, date_to:date|None=None, page:int=Query(1,ge=1), limit:int=Query(25,ge=1,le=100), s=Depends(session)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        if not permissions.can(s['role'],f'{MODULES[module]}.read'): raise HTTPException(403,'You do not have permission to access this module.')
        with db() as c:
            args=[]; where='not archived'
            if permissions.is_own_only(s['role'], MODULES[module]): where += ' and created_by=%s'; args.append(s['id'])
            if q.strip(): where += ' and (title ilike %s or description ilike %s or status ilike %s)'; pat='%'+q.strip().replace('%','\\%').replace('_','\\_')+'%'; args += [pat,pat,pat]
            if status.strip(): where += ' and status=%s'; args.append(status.strip())
            if date_from: where += ' and created_at::date >= %s'; args.append(date_from)
            if date_to: where += ' and created_at::date <= %s'; args.append(date_to)
            total=c.execute(f'select count(*) n from office_dashboard.module_records where module=%s and {where}',[module,*args]).fetchone()['n']
            rows=c.execute(f'select id,module,title,status,description,amount,due_date,fields,created_by,created_at,updated_at from office_dashboard.module_records where module=%s and {where} order by updated_at desc limit %s offset %s',[module,*args,limit,(page-1)*limit]).fetchall()
        return {'items':rows,'total':total,'page':page,'limit':limit,'provider_actions_enabled':False if module in ('waba-whatsapp','email','unified-inbox','evcare-ai-diagnostics','iot-and-telemetry','system-monitoring') else None}
    @r.get('/{module}/summary')
    def module_summary(module:str, date_from:date|None=None, date_to:date|None=None, s=Depends(session)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        ns=MODULES[module]
        if not permissions.can(s['role'],f'{ns}.read'): raise HTTPException(403,'You do not have permission to access this module.')
        where='module=%s and not archived'; args=[module]
        if permissions.is_own_only(s['role'], ns): where += ' and created_by=%s'; args.append(s['id'])
        if date_from: where += ' and created_at::date >= %s'; args.append(date_from)
        if date_to: where += ' and created_at::date <= %s'; args.append(date_to)
        with db() as c:
            row=c.execute(f"select count(*)::int as total, count(*) filter (where lower(status) in ('open','new','pending','in progress'))::int as open, count(*) filter (where lower(status) in ('completed','won','paid','closed'))::int as completed, count(*) filter (where lower(status) in ('lost','rejected','failed','cancelled'))::int as lost, coalesce(sum(amount),0)::numeric(14,2) as amount_total from office_dashboard.module_records where {where}",args).fetchone()
            statuses=c.execute(f"select status,count(*)::int as count from office_dashboard.module_records where {where} group by status order by count desc,status",args).fetchall()
        return {'module':module,**row,'statuses':statuses,'source':'office_dashboard.module_records','real_data_only':True}

    @r.get('/{module}/export')
    def export_records(module:str, q:str='', status:str='', date_from:date|None=None, date_to:date|None=None, s=Depends(session)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        ns=MODULES[module]
        if not permissions.can(s['role'],f'{ns}.export'):
            raise HTTPException(403,'You do not have permission to export this module.')
        where='module=%s and not archived'; args=[module]
        if permissions.is_own_only(s['role'], ns): where += ' and created_by=%s'; args.append(s['id'])
        if q.strip():
            where += ' and (title ilike %s or description ilike %s or status ilike %s)'
            pat='%'+q.strip().replace('%','\\%').replace('_','\\_')+'%'; args += [pat,pat,pat]
        if status.strip(): where += ' and status=%s'; args.append(status.strip())
        if date_from: where += ' and created_at::date >= %s'; args.append(date_from)
        if date_to: where += ' and created_at::date <= %s'; args.append(date_to)
        with db() as c:
            rows=c.execute(f'select title,status,description,amount,due_date,fields,created_at,updated_at from office_dashboard.module_records where {where} order by updated_at desc limit 10000',args).fetchall()
        return {'items':rows,'count':len(rows),'truncated':len(rows)>=10000}

    @r.post('/{module}/records')
    @dupe_409
    def create_record(module:str, body:RecordIn, s=Depends(csrf)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        if not permissions.can(s['role'],f'{MODULES[module]}.write'): raise HTTPException(403,'You do not have permission to change records.')
        with db() as c:
            row=c.execute('insert into office_dashboard.module_records(module,title,status,description,amount,due_date,fields,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s) returning id,module,title,status,description,amount,due_date,fields,created_by,created_at,updated_at',(module,body.title,body.status,body.description,body.amount,body.due_date,Jsonb(body.fields),s['id'])).fetchone()
            from auditdb import record
            record(c,actor_id=s['id'],actor_role=s['role'],action='create',entity_type='module_record',entity_id=row['id'],after={'module':module,'title':body.title,'status':body.status})
        audit.write('workspace_record_created',s['id'],None,module=module,record_id=str(row['id']))
        return row
    @r.patch('/{module}/records/{record_id}')
    @dupe_409
    def update_record(module:str,record_id:str,body:RecordIn,s=Depends(csrf)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        if not permissions.can(s['role'],f'{MODULES[module]}.write'): raise HTTPException(403,'You do not have permission to change records.')
        with db() as c:
            old=c.execute('select * from office_dashboard.module_records where id=%s and module=%s and not archived'+(' and created_by=%s' if permissions.is_own_only(s['role'], MODULES[module]) else ''), (record_id,module,s['id']) if permissions.is_own_only(s['role'], MODULES[module]) else (record_id,module)).fetchone()
            if not old: raise HTTPException(404,'Record not found.')
            row=c.execute('update office_dashboard.module_records set title=%s,status=%s,description=%s,amount=%s,due_date=%s,fields=%s,updated_at=now() where id=%s and module=%s'+(' and created_by=%s' if permissions.is_own_only(s['role'], MODULES[module]) else '')+' returning id,module,title,status,description,amount,due_date,fields,created_by,created_at,updated_at',(body.title,body.status,body.description,body.amount,body.due_date,Jsonb(body.fields),record_id,module,s['id']) if permissions.is_own_only(s['role'], MODULES[module]) else (body.title,body.status,body.description,body.amount,body.due_date,Jsonb(body.fields),record_id,module)).fetchone()
            from auditdb import record
            record(c,actor_id=s['id'],actor_role=s['role'],action='update',entity_type='module_record',entity_id=record_id,before={'title':old['title'],'status':old['status']},after={'title':body.title,'status':body.status})
        return row
    @r.delete('/{module}/records/{record_id}')
    def archive_record(module:str,record_id:str,s=Depends(csrf)):
        if module not in MODULES: raise HTTPException(404,'Unknown module.')
        if not permissions.can(s['role'],f'{MODULES[module]}.archive'): raise HTTPException(403,'You do not have permission to archive records.')
        with db() as c:
            row=c.execute('update office_dashboard.module_records set archived=true,updated_at=now() where id=%s and module=%s and not archived'+(' and created_by=%s' if permissions.is_own_only(s['role'], MODULES[module]) else '')+' returning id',(record_id,module,s['id']) if permissions.is_own_only(s['role'], MODULES[module]) else (record_id,module)).fetchone()
            if not row: raise HTTPException(404,'Record not found.')
            from auditdb import record
            record(c,actor_id=s['id'],actor_role=s['role'],action='archive',entity_type='module_record',entity_id=record_id,after={'module':module})
        return {'ok':True,'archived':record_id}
    return r
