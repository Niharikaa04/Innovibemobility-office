"""Garages & Service Centers API (db/012): add / view / edit / archive centers, search + filters, assigned technicians, linked tickets, CSV export.
Each center has a generated human-readable ID (SC-00001, db/013). "Service history" = the center's completed/closed tickets (real records only).
Permissions: garages.read / write / export / archive (permissions.py). Every change is written to the business audit log in the same transaction."""
import re
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions
from opscommon import DONE, blank, like, make_perm, trim

SERVICES = ('GENERAL', 'BATTERY', 'MOTOR', 'CHARGER', 'BRAKES', 'ELECTRICAL', 'SOFTWARE', 'BODY', 'TYRES', 'PREVENTIVE', 'OTHER')   # same list as ticket categories
STATUSES = ('ACTIVE', 'INACTIVE', 'TEMPORARILY_CLOSED')
PHONE = re.compile(r'^\+?[0-9 ()-]{7,20}$')
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
AUDITED = ('name', 'address', 'city', 'state', 'contact_person', 'phone', 'email', 'supported_services', 'status')


class CenterBase(BaseModel):
    @field_validator('name', 'address', 'notes', check_fields=False, mode='before')
    @classmethod
    def _trim(cls, v): return trim(v)
    @field_validator('city', 'state', 'contact_person', 'phone', 'email', check_fields=False, mode='before')
    @classmethod
    def _blank(cls, v): return blank(v)
    @field_validator('phone', check_fields=False)
    @classmethod
    def _phone(cls, v):
        if v is not None and not PHONE.match(v): raise ValueError('Enter a valid phone number.')
        return v
    @field_validator('email', check_fields=False)
    @classmethod
    def _email(cls, v):
        if v is not None and not EMAIL.match(v): raise ValueError('Enter a valid email address.')
        return v.lower() if v else v
    @field_validator('status', check_fields=False)
    @classmethod
    def _status(cls, v):
        if v is not None and v not in STATUSES: raise ValueError('Invalid status.')
        return v
    @field_validator('supported_services', check_fields=False)
    @classmethod
    def _services(cls, v):
        if v is None: return v
        bad = [x for x in v if x not in SERVICES]
        if bad: raise ValueError('Unknown service: ' + ', '.join(bad))
        return list(dict.fromkeys(v))   # de-duplicate, keep order


class CenterIn(CenterBase):
    name: str = Field(min_length=1, max_length=180)
    address: str = Field(default='', max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    contact_person: str | None = Field(default=None, max_length=120)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=254)
    supported_services: list[str] = Field(default_factory=list, max_length=len(SERVICES))
    status: str = 'ACTIVE'
    notes: str = Field(default='', max_length=3000)


class CenterUpdate(CenterBase):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    contact_person: str | None = Field(default=None, max_length=120)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=254)
    supported_services: list[str] | None = Field(default=None, max_length=len(SERVICES))
    status: str | None = None
    notes: str | None = Field(default=None, max_length=3000)


class LinkIn(BaseModel): ticket_id: str = Field(min_length=1, max_length=64)


def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/garages')
    perm = make_perm(session, csrf, audit, 'garages')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def dup(): raise HTTPException(409, 'A service center with this name already exists in this city.')

    def get_center(c, cid, lock=False):
        try: row = c.execute('select * from office_dashboard.service_centers where id=%s and not archived' + (' for update' if lock else ''), (cid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Service center not found.')
        return row

    def where_for(q='', status='', city='', service=''):
        w = ['not sc.archived']; a = []
        if q.strip(): w.append("(sc.name ilike %s or sc.center_code ilike %s or sc.address ilike %s or coalesce(sc.city,'') ilike %s or coalesce(sc.state,'') ilike %s or coalesce(sc.contact_person,'') ilike %s or coalesce(sc.phone,'') ilike %s)"); a += [like(q)] * 7
        if status.strip():
            if status not in STATUSES: raise HTTPException(422, 'Unknown status.')
            w.append('sc.status=%s'); a.append(status)
        if city.strip(): w.append('sc.city ilike %s'); a.append(like(city))
        if service.strip():
            if service not in SERVICES: raise HTTPException(422, 'Unknown service.')
            w.append('%s = any(sc.supported_services)'); a.append(service)
        return ' and '.join(w), a

    COUNTS = ("(select count(*) from office_dashboard.technicians t where t.service_center_id=sc.id and t.is_active)::int as technician_count,"
              " (select count(*) from office_dashboard.service_tickets k where k.service_center_id=sc.id and not k.archived and k.status <> all(%s))::int as open_tickets")

    @r.get('/summary')
    def summary(s=Depends(perm('read'))):
        with db() as c:
            tot = c.execute("select count(*)::int total, count(distinct lower(city)) filter (where city is not null)::int cities from office_dashboard.service_centers where not archived").fetchone()
            by_status = {x['status']: x['n'] for x in c.execute('select status, count(*)::int n from office_dashboard.service_centers where not archived group by status').fetchall()}
            techs = c.execute('select count(*)::int n from office_dashboard.technicians t join office_dashboard.service_centers sc on sc.id=t.service_center_id where t.is_active and not sc.archived').fetchone()['n']
            open_t = c.execute('select count(*)::int n from office_dashboard.service_tickets k join office_dashboard.service_centers sc on sc.id=k.service_center_id where not k.archived and not sc.archived and k.status <> all(%s)', (list(DONE),)).fetchone()['n']
        return {**tot, 'by_status': by_status, 'assigned_technicians': techs, 'open_tickets': open_t}

    @r.get('/cities')
    def cities(s=Depends(perm('read'))):
        with db() as c: rows = c.execute("select distinct city from office_dashboard.service_centers where not archived and city is not null order by city").fetchall()
        return {'items': [x['city'] for x in rows]}

    @r.get('/export')
    def export(q: str = '', status: str = '', city: str = '', service: str = '', s=Depends(perm('export'))):
        where, a = where_for(q, status, city, service)
        with db() as c:
            rows = c.execute(f'select sc.*, {COUNTS} from office_dashboard.service_centers sc where {where} order by sc.name limit 10000', [list(DONE), *a]).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='service_center', after={'rows': len(rows)})
        head = ['Service center ID', 'Name', 'Address', 'City', 'State', 'Contact person', 'Phone', 'Email', 'Supported services', 'Status', 'Technicians', 'Open tickets', 'Notes', 'Added', 'Updated']
        return csvutil.csv_response('service-centers.csv', head, [[x['center_code'], x['name'], x['address'], x['city'], x['state'], x['contact_person'], x['phone'], x['email'], '; '.join(x['supported_services']),
                                                                    x['status'], x['technician_count'], x['open_tickets'], x['notes'], x['created_at'], x['updated_at']] for x in rows])

    @r.get('')
    def list_centers(q: str = '', status: str = '', city: str = '', service: str = '', page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        where, a = where_for(q, status, city, service); role = s['role']
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.service_centers sc where {where}', a).fetchone()['n']
            rows = c.execute(f'select sc.*, {COUNTS} from office_dashboard.service_centers sc where {where} order by sc.name limit %s offset %s', [list(DONE), *a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'statuses': STATUSES, 'services': SERVICES,
                'can_write': permissions.can(role, 'garages.write'), 'can_export': permissions.can(role, 'garages.export'), 'can_archive': permissions.can(role, 'garages.archive')}

    @r.post('', status_code=201)
    def create(b: CenterIn, s=Depends(perm('write', True))):
        try:
            with db() as c:
                row = c.execute('insert into office_dashboard.service_centers(name,address,city,state,contact_person,phone,email,supported_services,status,notes,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                                (b.name, b.address, b.city, b.state, b.contact_person, b.phone, b.email, b.supported_services, b.status, b.notes, s['id'])).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='service_center', entity_id=row['id'], after={k: row[k] for k in ('name', 'city', 'status')})
        except psycopg.errors.UniqueViolation: dup()
        audit.write('service_center_created', s['id'], None, center_id=str(row['id']))
        return row

    @r.get('/{cid}')
    def detail(cid: str, s=Depends(perm('read'))):
        with db() as c:
            center = get_center(c, cid)
            techs = c.execute("select t.id, e.full_name as name, t.specialization, t.skills, t.availability, t.is_active,"
                              " (select count(*) from office_dashboard.service_tickets k join office_dashboard.users u on u.id::text=k.assigned_to where u.employee_id=t.employee_id and not k.archived and k.status <> all(%s))::int as open_tickets"
                              " from office_dashboard.technicians t join office_dashboard.employees e on e.id=t.employee_id where t.service_center_id=%s order by e.full_name", (list(DONE), cid)).fetchall()
            cols = 'id,ticket_number,title,status,priority,assigned_name,vehicle_reference,created_at,resolved_at'
            tickets = c.execute(f'select {cols} from office_dashboard.service_tickets where service_center_id=%s and not archived and status <> all(%s) order by created_at desc limit 50', (cid, list(DONE))).fetchall()
            history = c.execute(f'select {cols} from office_dashboard.service_tickets where service_center_id=%s and not archived and status = any(%s) order by coalesce(resolved_at, updated_at) desc limit 50', (cid, list(DONE))).fetchall()
        role = s['role']
        return {'center': center, 'technicians': techs, 'tickets': tickets, 'service_history': history, 'can_write': permissions.can(role, 'garages.write'), 'can_archive': permissions.can(role, 'garages.archive'),
                'can_assign_technicians': permissions.can(role, 'technicians.write')}

    @r.patch('/{cid}')
    def edit(cid: str, b: CenterUpdate, s=Depends(perm('write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('name', 'status', 'supported_services'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        for k in ('address', 'notes'):
            if k in ch and ch[k] is None: ch[k] = ''
        try:
            with db() as c:
                old = get_center(c, cid, lock=True)
                diff = {k: v for k, v in ch.items() if old[k] != v}
                if not diff: return old
                row = c.execute('update office_dashboard.service_centers set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_at=now() where id=%s returning *', [*diff.values(), cid]).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change' if set(diff) == {'status'} else 'update', entity_type='service_center', entity_id=cid,
                               before={k: old[k] for k in diff if k in AUDITED}, after={k: diff[k] for k in diff if k in AUDITED})
        except psycopg.errors.UniqueViolation: dup()
        audit.write('service_center_updated', s['id'], None, center_id=cid, fields=sorted(diff))
        return row

    @r.delete('/{cid}')
    def archive(cid: str, s=Depends(perm('archive', True))):
        with db() as c:
            old = get_center(c, cid, lock=True)
            open_t = c.execute('select count(*)::int n from office_dashboard.service_tickets where service_center_id=%s and not archived and status <> all(%s)', (cid, list(DONE))).fetchone()['n']
            if open_t: raise HTTPException(409, f'This center has {open_t} open ticket(s). Move or finish them before archiving it.')
            techs = c.execute('select count(*)::int n from office_dashboard.technicians where service_center_id=%s and is_active', (cid,)).fetchone()['n']
            if techs: raise HTTPException(409, f'{techs} active technician(s) are assigned to this center. Reassign them before archiving it.')
            c.execute('update office_dashboard.service_centers set archived=true,updated_at=now() where id=%s', (cid,))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='service_center', entity_id=cid, before={'name': old['name']})
        audit.write('service_center_archived', s['id'], None, center_id=cid)
        return {'ok': True, 'archived': cid}

    def ticket_event(c, tid, s, **detail):
        c.execute("insert into office_dashboard.service_ticket_events(ticket_id,event_type,actor_id,actor_name,detail) values(%s,'updated',%s,%s,%s)", (tid, s['id'], s.get('name'), Jsonb(detail, dumps=auditdb._dumps)))

    @r.post('/{cid}/tickets')
    def link_ticket(cid: str, b: LinkIn, s=Depends(perm('write', True))):
        """Attach an existing service ticket to this center (moves it if it was on another center)."""
        with db() as c:
            center = get_center(c, cid, lock=True)
            try: t = c.execute('select id,status,service_center_id from office_dashboard.service_tickets where id=%s and not archived for update', (b.ticket_id,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: t = None
            if not t: raise HTTPException(404, 'Service ticket not found.')
            if t['status'] == 'CLOSED': raise HTTPException(409, 'A closed ticket cannot be moved.')
            if str(t['service_center_id'] or '') == cid: return {'ok': True, 'unchanged': True}
            prev = c.execute('select name from office_dashboard.service_centers where id=%s', (t['service_center_id'],)).fetchone() if t['service_center_id'] else None
            c.execute('update office_dashboard.service_tickets set service_center_id=%s,updated_at=now() where id=%s', (cid, b.ticket_id))
            ticket_event(c, b.ticket_id, s, changes={'service_center': {'from': prev['name'] if prev else None, 'to': center['name']}})
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='link_ticket', entity_type='service_center', entity_id=cid, after={'ticket_id': b.ticket_id})
        audit.write('service_center_ticket_linked', s['id'], None, center_id=cid, ticket_id=b.ticket_id)
        return {'ok': True}

    @r.delete('/{cid}/tickets/{ticket_id}')
    def unlink_ticket(cid: str, ticket_id: str, s=Depends(perm('write', True))):
        with db() as c:
            center = get_center(c, cid, lock=True)
            try: t = c.execute('select id,status from office_dashboard.service_tickets where id=%s and service_center_id=%s and not archived for update', (ticket_id, cid)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: t = None
            if not t: raise HTTPException(404, 'That ticket is not linked to this center.')
            if t['status'] == 'CLOSED': raise HTTPException(409, 'A closed ticket cannot be changed.')
            c.execute('update office_dashboard.service_tickets set service_center_id=null,updated_at=now() where id=%s', (ticket_id,))
            ticket_event(c, ticket_id, s, changes={'service_center': {'from': center['name'], 'to': None}})
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='unlink_ticket', entity_type='service_center', entity_id=cid, after={'ticket_id': ticket_id})
        audit.write('service_center_ticket_unlinked', s['id'], None, center_id=cid, ticket_id=ticket_id)
        return {'ok': True}
    return r
