"""Persisted service-ticket API (db/010 + db/011). Lifecycle transitions always delegate to backend/tickets.py.
Every change writes a row to service_ticket_events (ticket history) and to the business audit log, in the same transaction."""
import uuid
from datetime import date
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions, tickets

PRIORITIES = ('LOW', 'MEDIUM', 'HIGH', 'URGENT')
CATEGORIES = ('GENERAL', 'BATTERY', 'MOTOR', 'CHARGER', 'BRAKES', 'ELECTRICAL', 'SOFTWARE', 'BODY', 'TYRES', 'PREVENTIVE', 'OTHER')
DONE = ('COMPLETED', 'CUSTOMER_CONFIRMATION', 'CLOSED')
GROUPS = {   # summary cards; each is also a list filter (?group=)
    'open': ('NEW', 'TRIAGED', 'DIAGNOSIS', 'ASSIGNED', 'ACCEPTED'),
    'in_progress': ('IN_PROGRESS', 'REPAIR', 'QUALITY_CHECK'),
    'waiting': ('PARTS_REQUIRED', 'WAITING'),
    'completed': DONE,
}
EDITABLE = ('title', 'description', 'customer_name', 'vehicle_reference', 'priority', 'category', 'due_date', 'service_center_id')

def _trim(v): return v.strip() if isinstance(v, str) else v
def _blank_none(v):
    v = _trim(v)
    return (v or None) if isinstance(v, str) else v

class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=5000)
    customer_name: str | None = Field(default=None, max_length=180)
    vehicle_reference: str | None = Field(default=None, max_length=180)
    priority: str = 'MEDIUM'
    category: str = 'GENERAL'
    due_date: date | None = None
    assigned_to: str | None = Field(default=None, max_length=180)
    service_center_id: str | None = Field(default=None, max_length=64)
    @field_validator('title', 'description', 'priority', 'category', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('customer_name', 'vehicle_reference', 'assigned_to', 'service_center_id', mode='before')
    @classmethod
    def blank(cls, v): return _blank_none(v)
    @field_validator('priority')
    @classmethod
    def valid_priority(cls, v):
        if v not in PRIORITIES: raise ValueError('Invalid priority.')
        return v
    @field_validator('category')
    @classmethod
    def valid_category(cls, v):
        if v not in CATEGORIES: raise ValueError('Invalid category.')
        return v

class TicketUpdate(BaseModel):
    """Partial edit. Only fields actually sent are changed."""
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    customer_name: str | None = Field(default=None, max_length=180)
    vehicle_reference: str | None = Field(default=None, max_length=180)
    priority: str | None = None
    category: str | None = None
    due_date: date | None = None
    service_center_id: str | None = Field(default=None, max_length=64)
    @field_validator('title', 'description', 'priority', 'category', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('customer_name', 'vehicle_reference', 'service_center_id', mode='before')
    @classmethod
    def blank(cls, v): return _blank_none(v)
    @field_validator('priority')
    @classmethod
    def valid_priority(cls, v):
        if v is not None and v not in PRIORITIES: raise ValueError('Invalid priority.')
        return v
    @field_validator('category')
    @classmethod
    def valid_category(cls, v):
        if v is not None and v not in CATEGORIES: raise ValueError('Invalid category.')
        return v

class AssignIn(BaseModel): assigned_to: str | None = Field(default=None, max_length=180)
class TransitionIn(BaseModel): status: str = Field(min_length=1, max_length=40)
class CommentIn(BaseModel): comment: str = Field(min_length=1, max_length=3000)

def like(q: str) -> str: return '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/service-tickets')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def read(s=Depends(session)):
        if not permissions.can(s['role'], 'tickets.read'): raise HTTPException(403, 'You do not have permission to view service tickets.')
        return s
    def write(s=Depends(csrf)):
        if not permissions.can(s['role'], 'tickets.write'): raise HTTPException(403, 'You do not have permission to change service tickets.')
        return s
    def assigner(s=Depends(csrf)):
        if not permissions.can(s['role'], 'tickets.approve'): raise HTTPException(403, 'Only a service manager or executive can assign tickets.')
        return s
    def exporter(s=Depends(session)):
        if not permissions.can(s['role'], 'tickets.export'): raise HTTPException(403, 'You do not have permission to export service tickets.')
        return s

    def own(row, s): return s['role'] != 'technician' or row['assigned_to'] == s['id'] or row['created_by'] == s['id']
    def decorate(row, s):
        row = dict(row); row['next_states'] = tickets.next_states(row['status'], s['role']) if own(row, s) else []
        row['can_edit'] = own(row, s) and row['status'] != 'CLOSED' and permissions.can(s['role'], 'tickets.write')
        row['overdue'] = bool(row.get('due_date') and row['due_date'] < date.today() and row['status'] not in DONE)
        return row
    def get_ticket(c, tid, lock=False):
        try: row = c.execute('select *, (select sc.name from office_dashboard.service_centers sc where sc.id=service_tickets.service_center_id) as service_center_name from office_dashboard.service_tickets where id=%s and not archived' + (' for update' if lock else ''), (tid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Service ticket not found.')
        return row
    def check_center(c, s, cid):
        """A ticket may be linked to a service center only by roles that can manage garages, and only to an existing, non-archived one."""
        if not cid: return
        if not permissions.can(s['role'], 'garages.write'): raise HTTPException(403, 'Only a service manager or executive can choose the service center.')
        try: ok = c.execute('select 1 from office_dashboard.service_centers where id=%s and not archived', (cid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: ok = None
        except psycopg.errors.UndefinedTable: raise HTTPException(503, 'Service centers are not set up in this database (run db/012).')
        if not ok: raise HTTPException(422, 'Choose an existing service center.')
    def center_name(c, cid):
        return (c.execute('select name from office_dashboard.service_centers where id=%s', (cid,)).fetchone() or {}).get('name') if cid else None
    def event(c, tid, kind, s, **detail):
        c.execute('insert into office_dashboard.service_ticket_events(ticket_id,event_type,actor_id,actor_name,detail) values(%s,%s,%s,%s,%s)', (tid, kind, s['id'], s.get('name'), Jsonb(detail, dumps=auditdb._dumps)))
    def technician_name(c, uid):
        try: row = c.execute("select e.full_name from office_dashboard.users u join office_dashboard.employees e on e.id=u.employee_id where u.id::text=%s and u.role in ('technician','service_manager') and u.is_active and e.is_active", (uid,)).fetchone()
        except psycopg.errors.UndefinedTable: raise HTTPException(503, 'The employee tables are not set up in this database (run db/001_foundation.sql).')
        if not row: raise HTTPException(422, 'Choose an active technician from the list.')
        return row['full_name']

    def where_for(s, q='', status='', priority='', category='', assigned='', group='', overdue=False, date_from=None, date_to=None):
        w = ['not archived']; a = []
        if s['role'] == 'technician': w.append('(assigned_to=%s or created_by=%s)'); a += [s['id'], s['id']]
        if q.strip(): w.append("(ticket_number ilike %s or title ilike %s or coalesce(customer_name,'') ilike %s or coalesce(vehicle_reference,'') ilike %s or coalesce(assigned_name,'') ilike %s)"); a += [like(q)] * 5
        if status.strip():
            if status not in tickets.ORDER: raise HTTPException(422, 'Unknown ticket status.')
            w.append('status=%s'); a.append(status)
        if group.strip():
            if group not in GROUPS: raise HTTPException(422, 'Unknown status group.')
            w.append('status = any(%s)'); a.append(list(GROUPS[group]))
        if priority.strip():
            if priority not in PRIORITIES: raise HTTPException(422, 'Unknown priority.')
            w.append('priority=%s'); a.append(priority)
        if category.strip():
            if category not in CATEGORIES: raise HTTPException(422, 'Unknown category.')
            w.append('category=%s'); a.append(category)
        if assigned.strip():
            if assigned == 'unassigned': w.append('assigned_to is null')
            else: w.append('assigned_to=%s'); a.append(s['id'] if assigned == 'me' else assigned)
        if overdue: w.append('due_date < current_date and status <> all(%s)'); a.append(list(DONE))
        if date_from: w.append('created_at::date >= %s'); a.append(date_from)
        if date_to: w.append('created_at::date <= %s'); a.append(date_to)
        return ' and '.join(w), a

    @r.get('/summary')
    def summary(date_from: date | None = None, date_to: date | None = None, s=Depends(read)):
        where, a = where_for(s, date_from=date_from, date_to=date_to)
        with db() as c:
            tot = c.execute(f"select count(*)::int total, count(*) filter (where assigned_to is null and status <> all(%s))::int unassigned,"
                            f" count(*) filter (where due_date < current_date and status <> all(%s))::int overdue,"
                            f" count(*) filter (where priority='URGENT' and status <> all(%s))::int urgent_open"
                            f" from office_dashboard.service_tickets where {where}", [list(DONE)] * 3 + a).fetchone()
            by_status = {x['status']: x['n'] for x in c.execute(f'select status, count(*)::int n from office_dashboard.service_tickets where {where} group by status', a).fetchall()}
            by_priority = {x['priority']: x['n'] for x in c.execute(f'select priority, count(*)::int n from office_dashboard.service_tickets where {where} group by priority', a).fetchall()}
        groups = {g: sum(by_status.get(x, 0) for x in sts) for g, sts in GROUPS.items()}
        return {**tot, 'groups': groups, 'by_status': by_status, 'by_priority': by_priority}

    @r.get('/technicians')
    def technicians(s=Depends(read)):
        with db() as c:
            try: rows = c.execute("select u.id::text as id, e.full_name as name, u.role from office_dashboard.users u join office_dashboard.employees e on e.id=u.employee_id where u.role in ('technician','service_manager') and u.is_active and e.is_active order by e.full_name").fetchall()
            except psycopg.errors.UndefinedTable: rows = []
        return {'items': rows}

    @r.get('/export')
    def export(q: str = '', status: str = '', priority: str = '', category: str = '', assigned: str = '', group: str = '', overdue: bool = False,
               date_from: date | None = None, date_to: date | None = None, s=Depends(exporter)):
        where, a = where_for(s, q, status, priority, category, assigned, group, overdue, date_from, date_to)
        with db() as c:
            rows = c.execute(f'select *, (select sc.name from office_dashboard.service_centers sc where sc.id=service_tickets.service_center_id) as service_center_name from office_dashboard.service_tickets where {where} order by created_at desc limit 10000', a).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='service_ticket', after={'rows': len(rows)})
        head = ['Ticket ID', 'Title', 'Description', 'Priority', 'Category', 'Status', 'Technician', 'Customer', 'Vehicle', 'Due date', 'Created', 'Updated', 'Resolved']
        return csvutil.csv_response('service-tickets.csv', head, [[x['ticket_number'], x['title'], x['description'], x['priority'], x['category'], x['status'], x['assigned_name'] or x['assigned_to'],
                                                                   x['customer_name'], x['vehicle_reference'], x['due_date'], x['created_at'], x['updated_at'], x['resolved_at']] for x in rows])

    @r.get('')
    def list_tickets(q: str = '', status: str = '', priority: str = '', category: str = '', assigned: str = '', group: str = '', overdue: bool = False,
                     date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(read)):
        where, a = where_for(s, q, status, priority, category, assigned, group, overdue, date_from, date_to)
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.service_tickets where {where}', a).fetchone()['n']
            rows = c.execute(f'select *, (select sc.name from office_dashboard.service_centers sc where sc.id=service_tickets.service_center_id) as service_center_name from office_dashboard.service_tickets where {where} order by updated_at desc limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        role = s['role']
        return {'items': [decorate(x, s) for x in rows], 'total': total, 'page': page, 'limit': limit, 'statuses': tickets.ORDER, 'priorities': PRIORITIES, 'categories': CATEGORIES,
                'can_write': permissions.can(role, 'tickets.write'), 'can_assign': permissions.can(role, 'tickets.approve'), 'can_export': permissions.can(role, 'tickets.export')}

    @r.post('', status_code=201)
    def create_ticket(b: TicketIn, s=Depends(write)):
        if b.assigned_to and not permissions.can(s['role'], 'tickets.approve'): raise HTTPException(403, 'Only a service manager or executive can assign tickets.')
        with db() as c:
            name = technician_name(c, b.assigned_to) if b.assigned_to else None
            check_center(c, s, b.service_center_id)
            number = 'IVT-' + uuid.uuid4().hex[:10].upper()   # server-generated; no dependency on user input
            row = c.execute('insert into office_dashboard.service_tickets(ticket_number,title,description,customer_name,vehicle_reference,priority,category,due_date,assigned_to,assigned_name,created_by,service_center_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                            (number, b.title, b.description, b.customer_name, b.vehicle_reference, b.priority, b.category, b.due_date, b.assigned_to, name, s['id'], b.service_center_id)).fetchone()
            row = get_ticket(c, row['id'])
            event(c, row['id'], 'created', s, priority=b.priority, category=b.category, assigned_to=name)
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='service_ticket', entity_id=row['id'], after={'status': row['status'], 'priority': row['priority'], 'category': row['category']})
        audit.write('service_ticket_created', s['id'], None, ticket_id=str(row['id']))
        return decorate(row, s)

    @r.get('/{ticket_id}')
    def detail(ticket_id: str, s=Depends(read)):
        with db() as c:
            row = get_ticket(c, ticket_id)
            if not own(row, s): raise HTTPException(403, 'Technicians can only view their assigned tickets.')
            events = c.execute('select id,event_type,actor_id,actor_name,detail,created_at from office_dashboard.service_ticket_events where ticket_id=%s order by created_at desc, id desc', (ticket_id,)).fetchall()
            comments = c.execute('select id,ticket_id,comment,created_by,created_at from office_dashboard.service_ticket_comments where ticket_id=%s order by created_at', (ticket_id,)).fetchall()
            try: faults = c.execute('select id, fault_code, severity, detected_at, status from office_dashboard.diagnostic_faults where ticket_id=%s order by id', (ticket_id,)).fetchall()   # diagnostics that produced this ticket
            except psycopg.errors.UndefinedTable: faults = []
        return {'ticket': decorate(row, s), 'history': events, 'comments': comments, 'diagnostic_faults': faults}

    @r.patch('/{ticket_id}')
    def edit(ticket_id: str, b: TicketUpdate, s=Depends(write)):
        changes = b.model_dump(exclude_unset=True)
        if not changes: raise HTTPException(422, 'Nothing to update.')
        for k in ('title', 'priority', 'category'):
            if k in changes and changes[k] is None: raise HTTPException(422, f'{k.title()} cannot be empty.')
        if 'description' in changes and changes['description'] is None: changes['description'] = ''
        with db() as c:
            old = get_ticket(c, ticket_id, lock=True)
            if not own(old, s): raise HTTPException(403, 'Technicians can only edit their assigned tickets.')
            if old['status'] == 'CLOSED': raise HTTPException(409, 'A closed ticket cannot be edited.')
            norm = lambda x: str(x) if isinstance(x, uuid.UUID) else x          # uuid column vs text from the form
            diff = {k: {'from': old[k], 'to': v} for k, v in changes.items() if k in EDITABLE and norm(old[k]) != norm(v)}
            if not diff: return decorate(old, s)
            if 'service_center_id' in diff: check_center(c, s, changes['service_center_id'])
            c.execute('update office_dashboard.service_tickets set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_at=now() where id=%s', [*[changes[k] for k in diff], ticket_id])
            row = get_ticket(c, ticket_id)
            shown = {k: v for k, v in diff.items() if k != 'service_center_id'}
            if 'service_center_id' in diff: shown['service_center'] = {'from': center_name(c, norm(old['service_center_id'])), 'to': center_name(c, changes['service_center_id'])}   # readable names in history
            event(c, ticket_id, 'updated', s, changes=shown)
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='update', entity_type='service_ticket', entity_id=ticket_id, before={k: v['from'] for k, v in diff.items() if k != 'description'}, after={k: v['to'] for k, v in diff.items() if k != 'description'})
        audit.write('service_ticket_updated', s['id'], None, ticket_id=ticket_id, fields=sorted(diff))
        return decorate(row, s)

    @r.post('/{ticket_id}/assign')
    def assign(ticket_id: str, b: AssignIn, s=Depends(assigner)):
        with db() as c:
            old = get_ticket(c, ticket_id, lock=True)
            if old['status'] in DONE: raise HTTPException(409, 'A completed or closed ticket cannot be reassigned.')
            target = (b.assigned_to or '').strip() or None
            name = technician_name(c, target) if target else None
            if target == old['assigned_to']: return decorate(old, s)
            row = c.execute('update office_dashboard.service_tickets set assigned_to=%s,assigned_name=%s,updated_at=now() where id=%s returning *', (target, name, ticket_id)).fetchone()
            event(c, ticket_id, 'assigned', s, **{'from': old['assigned_name'] or old['assigned_to'], 'to': name})
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='assign', entity_type='service_ticket', entity_id=ticket_id, before={'assigned_to': old['assigned_to']}, after={'assigned_to': target})
        audit.write('service_ticket_assigned', s['id'], None, ticket_id=ticket_id)
        return decorate(row, s)

    @r.post('/{ticket_id}/transition')
    def transition(ticket_id: str, b: TransitionIn, s=Depends(write)):
        target = b.status.upper()
        if target not in tickets.ORDER: raise HTTPException(422, 'Unknown ticket status.')
        with db() as c:
            old = get_ticket(c, ticket_id, lock=True)
            if not own(old, s): raise HTTPException(403, 'Technicians can only update their assigned tickets.')
            if not tickets.can_transition(old['status'], target, s['role']): raise HTTPException(409, f"Transition {old['status']} → {target} is not allowed for your role.")
            resolved = 'resolved_at=now()' if target == 'COMPLETED' else ('resolved_at=null' if old['status'] in DONE and target not in DONE else 'resolved_at=resolved_at')
            row = c.execute(f'update office_dashboard.service_tickets set status=%s,{resolved},updated_at=now() where id=%s returning *', (target, ticket_id)).fetchone()
            event(c, ticket_id, 'status_changed', s, **{'from': old['status'], 'to': target})
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='transition', entity_type='service_ticket', entity_id=ticket_id, before={'status': old['status']}, after={'status': target})
        audit.write('service_ticket_transition', s['id'], None, ticket_id=ticket_id, from_status=old['status'], to_status=target)
        return decorate(row, s)

    @r.get('/{ticket_id}/history')
    def history(ticket_id: str, s=Depends(read)):
        with db() as c:
            row = get_ticket(c, ticket_id)
            if not own(row, s): raise HTTPException(403, 'Technicians can only view their assigned tickets.')
            rows = c.execute('select id,event_type,actor_id,actor_name,detail,created_at from office_dashboard.service_ticket_events where ticket_id=%s order by created_at desc, id desc', (ticket_id,)).fetchall()
        return {'items': rows}

    @r.get('/{ticket_id}/comments')
    def comments(ticket_id: str, s=Depends(read)):
        with db() as c:
            row = get_ticket(c, ticket_id)
            if not own(row, s): raise HTTPException(403, 'Technicians can only view their assigned tickets.')
            rows = c.execute('select id,ticket_id,comment,created_by,created_at from office_dashboard.service_ticket_comments where ticket_id=%s order by created_at', (ticket_id,)).fetchall()
        return {'items': rows}

    @r.post('/{ticket_id}/comments', status_code=201)
    def add_comment(ticket_id: str, b: CommentIn, s=Depends(write)):
        if not b.comment.strip(): raise HTTPException(422, 'Comment cannot be empty.')
        with db() as c:
            ex = get_ticket(c, ticket_id)
            if not own(ex, s): raise HTTPException(403, 'Technicians can only comment on their assigned tickets.')
            row = c.execute('insert into office_dashboard.service_ticket_comments(ticket_id,comment,created_by) values(%s,%s,%s) returning *', (ticket_id, b.comment.strip(), s['id'])).fetchone()
            event(c, ticket_id, 'comment', s, comment_id=row['id'])
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='comment', entity_type='service_ticket', entity_id=ticket_id, after={'comment_id': row['id']})
        audit.write('service_ticket_comment_added', s['id'], None, ticket_id=ticket_id)
        return row
    return r