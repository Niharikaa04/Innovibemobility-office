"""Technicians API (db/001 technicians table, extended by db/012): add / view / edit / deactivate technician records, skills, specialization,
service center, availability, live workload counts from service tickets, search + filters, CSV export.
Assigning a technician to a ticket reuses the existing POST /api/service-tickets/{id}/assign endpoint (tickets.approve), which writes ticket history.
A ticket is assigned to a LOGIN ACCOUNT, so a technician without an active user account is shown but cannot be assigned tickets.
Ticket counts (from real tickets only): assigned = every non-archived ticket assigned to the technician; pending = not started or blocked (NEW, TRIAGED, DIAGNOSIS,
ASSIGNED, ACCEPTED, PARTS_REQUIRED, WAITING); in progress = IN_PROGRESS, REPAIR, QUALITY_CHECK; completed = COMPLETED, CUSTOMER_CONFIRMATION, CLOSED. No scores or ratings exist.
Availability is NULL ("not set") until a person enters it; it is never defaulted. Personal contact details (email, phone) are returned and exported only to roles holding
`technician_contact.read`; everyone else sees them withheld (the server removes them, the UI does not merely hide them).
Permissions: technicians.read / write / export (permissions.py)."""
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions
from opscommon import DONE, blank, like, make_perm, trim

AVAILABILITY = ('AVAILABLE', 'BUSY', 'ON_LEAVE', 'UNAVAILABLE')
PENDING = ['NEW', 'TRIAGED', 'DIAGNOSIS', 'ASSIGNED', 'ACCEPTED', 'PARTS_REQUIRED', 'WAITING']
IN_PROGRESS = ['IN_PROGRESS', 'REPAIR', 'QUALITY_CHECK']
AUDITED = ('skills', 'specialization', 'service_center_id', 'availability', 'is_active')


def clean_skills(v):
    if v is None: return v
    out = []
    for x in v:
        x = ' '.join(str(x).split())
        if not x: continue
        if len(x) > 40: raise ValueError('Each skill must be 40 characters or fewer.')
        if x.lower() not in {y.lower() for y in out}: out.append(x)
    if len(out) > 20: raise ValueError('At most 20 skills.')
    return out


class TechBase(BaseModel):
    @field_validator('specialization', 'service_center_id', check_fields=False, mode='before')
    @classmethod
    def _blank(cls, v): return blank(v)
    @field_validator('notes', check_fields=False, mode='before')
    @classmethod
    def _trim(cls, v): return trim(v)
    @field_validator('skills', check_fields=False)
    @classmethod
    def _skills(cls, v): return clean_skills(v)
    @field_validator('availability', check_fields=False)
    @classmethod
    def _avail(cls, v):
        if v is not None and v not in AVAILABILITY: raise ValueError('Invalid availability.')
        return v


class TechIn(TechBase):
    employee_id: str = Field(min_length=1, max_length=64)
    skills: list[str] = Field(default_factory=list)
    specialization: str | None = Field(default=None, max_length=120)
    service_center_id: str | None = None
    availability: str | None = None          # None = not set (never defaulted)
    notes: str = Field(default='', max_length=3000)


class TechUpdate(TechBase):
    skills: list[str] | None = None
    specialization: str | None = Field(default=None, max_length=120)
    service_center_id: str | None = None
    availability: str | None = None
    notes: str | None = Field(default=None, max_length=3000)
    is_active: bool | None = None


def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/technicians')
    perm = make_perm(session, csrf, audit, 'technicians')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)

    # Three %s placeholders (pending / in-progress / completed status lists) come FIRST in every query that uses BASE: pass W3.
    BASE = ("select t.id, t.employee_id, e.employee_code, e.full_name as name, e.email, e.phone, e.designation, t.skills, t.specialization, t.availability, t.is_active, t.notes,"
            " t.service_center_id, sc.name as service_center, u.id::text as user_id,"
            " coalesce(w.assigned,0)::int as assigned_tickets, coalesce(w.pending,0)::int as pending_tickets, coalesce(w.in_progress,0)::int as in_progress_tickets, coalesce(w.completed,0)::int as completed_tickets,"
            " (coalesce(w.pending,0)+coalesce(w.in_progress,0))::int as open_tickets, t.created_at, t.updated_at"
            " from office_dashboard.technicians t join office_dashboard.employees e on e.id=t.employee_id"
            " left join office_dashboard.service_centers sc on sc.id=t.service_center_id"
            " left join office_dashboard.users u on u.employee_id=e.id and u.is_active"
            " left join lateral (select count(*) as assigned, count(*) filter (where k.status = any(%s)) as pending, count(*) filter (where k.status = any(%s)) as in_progress, count(*) filter (where k.status = any(%s)) as completed"
            "  from office_dashboard.service_tickets k where k.assigned_to=u.id::text and not k.archived) w on true")
    DONE_L = list(DONE)
    W3 = [PENDING, IN_PROGRESS, DONE_L]
    def mask(row, s):
        if not permissions.can(s['role'], 'technician_contact.read'): row = {**row, 'email': None, 'phone': None, 'contact_hidden': True}
        return row

    def where_for(q='', availability='', service_center_id='', skill='', active=None):
        w = ['true']; a = []
        if q.strip(): w.append("(e.full_name ilike %s or e.employee_code ilike %s or coalesce(t.specialization,'') ilike %s or array_to_string(t.skills,' ') ilike %s)"); a += [like(q)] * 4
        if availability.strip():
            if availability == 'NOT_SET': w.append('t.availability is null')
            elif availability not in AVAILABILITY: raise HTTPException(422, 'Unknown availability.')
            else: w.append('t.availability=%s'); a.append(availability)
        if service_center_id.strip():
            if service_center_id == 'none': w.append('t.service_center_id is null')
            else: w.append('t.service_center_id::text=%s'); a.append(service_center_id)
        if skill.strip(): w.append("exists (select 1 from unnest(t.skills) sk where sk ilike %s)"); a.append(like(skill))
        if active is not None: w.append('t.is_active=%s'); a.append(active)
        return ' and '.join(w), a

    def one(c, tid):
        try: row = c.execute(BASE + ' where t.id=%s', [*W3, tid]).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Technician not found.')
        return row
    def lock(c, tid):
        try: ok = c.execute('select 1 from office_dashboard.technicians where id=%s for update', (tid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: ok = None
        if not ok: raise HTTPException(404, 'Technician not found.')
    def check_center(c, cid):
        if not cid: return
        try: ok = c.execute('select 1 from office_dashboard.service_centers where id=%s and not archived', (cid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: ok = None
        if not ok: raise HTTPException(422, 'Choose an existing service center.')

    @r.get('/summary')
    def summary(s=Depends(perm('read'))):
        with db() as c:
            tot = c.execute('select count(*)::int total, count(*) filter (where is_active)::int active, count(*) filter (where is_active and service_center_id is null)::int without_center from office_dashboard.technicians').fetchone()
            by_av = {x['availability'] or 'NOT_SET': x['n'] for x in c.execute('select availability, count(*)::int n from office_dashboard.technicians where is_active group by availability').fetchall()}
            tk = c.execute("select count(*) filter (where k.status <> all(%s))::int open_assigned, count(*) filter (where k.status <> all(%s) and k.assigned_to is null)::int unassigned from office_dashboard.service_tickets k where not k.archived",
                           (DONE_L, DONE_L)).fetchone()
        return {**tot, 'by_availability': by_av, 'open_assigned_tickets': tk['open_assigned'] - tk['unassigned'], 'unassigned_open_tickets': tk['unassigned']}

    @r.get('/workload')
    def workload(service_center_id: str = '', s=Depends(perm('read'))):
        """Workload distribution from real ticket counts (active technicians only). No scores, no estimates."""
        w, a = ['t.is_active'], []
        if service_center_id.strip():
            if service_center_id == 'none': w.append('t.service_center_id is null')
            else: w.append('t.service_center_id::text=%s'); a.append(service_center_id)
        with db() as c:
            rows = c.execute(f'{BASE} where {" and ".join(w)} order by (coalesce(w.pending,0)+coalesce(w.in_progress,0)) desc, e.full_name limit 200', [*W3, *a]).fetchall()
            unassigned = c.execute('select count(*)::int n from office_dashboard.service_tickets where not archived and assigned_to is null and status <> all(%s)', (DONE_L,)).fetchone()['n']
        items = [{'id': x['id'], 'name': x['name'], 'service_center': x['service_center'], 'availability': x['availability'], 'has_login': bool(x['user_id']),
                  'pending': x['pending_tickets'], 'in_progress': x['in_progress_tickets'], 'completed': x['completed_tickets'], 'open': x['open_tickets']} for x in rows]
        return {'items': items, 'unassigned_open_tickets': unassigned, 'total_open': sum(i['open'] for i in items)}

    @r.get('/candidates')
    def candidates(s=Depends(perm('write'))):
        """Active employees who are not technicians yet."""
        with db() as c:
            rows = c.execute("select e.id, e.employee_code, e.full_name as name, e.designation from office_dashboard.employees e where e.is_active and not exists (select 1 from office_dashboard.technicians t where t.employee_id=e.id) order by e.full_name limit 500").fetchall()
        return {'items': rows}

    @r.get('/export')
    def export(q: str = '', availability: str = '', service_center_id: str = '', skill: str = '', active: bool | None = None, s=Depends(perm('export'))):
        where, a = where_for(q, availability, service_center_id, skill, active)
        with db() as c:
            rows = [mask(x, s) for x in c.execute(f'{BASE} where {where} order by e.full_name limit 10000', [*W3, *a]).fetchall()]
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='technician', after={'rows': len(rows), 'contact_included': permissions.can(s['role'], 'technician_contact.read')})
        contact = permissions.can(s['role'], 'technician_contact.read')
        head = ['Technician ID (employee code)', 'Name'] + (['Email', 'Phone'] if contact else []) + ['Skills', 'Specialization', 'Service center', 'Availability', 'Record', 'Assigned', 'Pending', 'In progress', 'Completed', 'Created', 'Updated']
        return csvutil.csv_response('technicians.csv', head, [[x['employee_code'], x['name']] + ([x['email'], x['phone']] if contact else []) + ['; '.join(x['skills'] or []), x['specialization'], x['service_center'], x['availability'] or 'Not set',
                                                                'active' if x['is_active'] else 'inactive', x['assigned_tickets'], x['pending_tickets'], x['in_progress_tickets'], x['completed_tickets'], x['created_at'], x['updated_at']] for x in rows])

    @r.get('')
    def list_technicians(q: str = '', availability: str = '', service_center_id: str = '', skill: str = '', active: bool | None = None,
                         page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        where, a = where_for(q, availability, service_center_id, skill, active); role = s['role']
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.technicians t join office_dashboard.employees e on e.id=t.employee_id where {where}', a).fetchone()['n']
            rows = [mask(x, s) for x in c.execute(f'{BASE} where {where} order by e.full_name limit %s offset %s', [*W3, *a, limit, (page - 1) * limit]).fetchall()]
            centers = c.execute('select id, name from office_dashboard.service_centers where not archived order by name').fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'availability': AVAILABILITY, 'centers': centers, 'can_see_contact': permissions.can(role, 'technician_contact.read'),
                'can_write': permissions.can(role, 'technicians.write'), 'can_export': permissions.can(role, 'technicians.export'), 'can_assign': permissions.can(role, 'tickets.approve')}

    @r.post('', status_code=201)
    def create(b: TechIn, s=Depends(perm('write', True))):
        try:
            with db() as c:
                try: emp = c.execute('select id, full_name, is_active from office_dashboard.employees where id=%s for update', (b.employee_id,)).fetchone()
                except psycopg.errors.InvalidTextRepresentation: emp = None
                if not emp: raise HTTPException(422, 'Choose an existing employee.')
                if not emp['is_active']: raise HTTPException(422, 'That employee is not active.')
                check_center(c, b.service_center_id)
                row = c.execute('insert into office_dashboard.technicians(employee_id,skills,specialization,service_center_id,availability,notes) values(%s,%s,%s,%s,%s,%s) returning id',
                                (b.employee_id, b.skills, b.specialization, b.service_center_id, b.availability, b.notes)).fetchone()
                out = mask(one(c, row['id']), s)
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='technician', entity_id=row['id'], after={'employee': emp['full_name'], 'availability': b.availability, 'service_center_id': b.service_center_id})
        except psycopg.errors.UniqueViolation: raise HTTPException(409, 'This employee is already a technician.')
        audit.write('technician_created', s['id'], None, technician_id=str(row['id']))
        return out

    @r.get('/{tid}')
    def detail(tid: str, s=Depends(perm('read'))):
        with db() as c:
            t = one(c, tid)
            tickets = c.execute('select k.id,k.ticket_number,k.title,k.status,k.priority,k.due_date,k.vehicle_reference,k.created_at from office_dashboard.service_tickets k'
                                ' where k.assigned_to=%s and not k.archived order by (k.status = any(%s)) asc, k.updated_at desc limit 50', (t['user_id'] or '', DONE_L)).fetchall() if t['user_id'] else []
        return {'technician': mask(t, s), 'tickets': tickets, 'can_write': permissions.can(s['role'], 'technicians.write'), 'can_assign': permissions.can(s['role'], 'tickets.approve')}

    @r.patch('/{tid}')
    def edit(tid: str, b: TechUpdate, s=Depends(perm('write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('skills', 'is_active'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        if 'notes' in ch and ch['notes'] is None: ch['notes'] = ''
        with db() as c:
            lock(c, tid); old = one(c, tid)
            if 'service_center_id' in ch: check_center(c, ch['service_center_id'])
            if ch.get('is_active') is False and old['is_active'] and old['open_tickets']:
                raise HTTPException(409, f"This technician still has {old['open_tickets']} open ticket(s). Reassign them before deactivating.")
            norm = lambda x: None if x is None else str(x) if not isinstance(x, (list, bool)) else x   # UUID vs str compares by text
            diff = {k: v for k, v in ch.items() if norm(old[k]) != norm(v)}
            if not diff: return mask(old, s)
            c.execute('update office_dashboard.technicians set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_at=now() where id=%s', [*diff.values(), tid])
            out = mask(one(c, tid), s)
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change' if set(diff) <= {'availability', 'is_active'} else 'update', entity_type='technician', entity_id=tid,
                           before={k: old[k] for k in diff if k in AUDITED}, after={k: diff[k] for k in diff if k in AUDITED})
        audit.write('technician_updated', s['id'], None, technician_id=tid, fields=sorted(diff))
        return out
    return r
