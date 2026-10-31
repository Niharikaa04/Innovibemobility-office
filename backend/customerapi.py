"""Customers (Fleets / OEMs) API (db/017). Permissions: customers.read / write / export / archive (permissions.py). Every change is audit-logged.
Single source of truth: the contact person is the existing CRM contact (primary_contact_id) and is read live, never copied; vehicle counts are derived from
fleet_vehicles.customer_name (no stored totals). Fleet Management and CRM are only read, never modified."""
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions

TYPES = ('FLEET', 'OEM')
STATUSES = ('NEW', 'ACTIVE', 'INACTIVE')
SORTS = {'name': 'lower(c.name)', 'city': 'lower(c.city)', 'status': 'c.status', 'customer_type': 'c.customer_type', 'created_at': 'c.created_at', 'vehicle_count': 'vehicle_count'}
NORM = r"lower(regexp_replace(btrim({}),'\s+',' ','g'))"   # same expression as the unique index; also used to match vehicles to customers
AUDITED = ('name', 'customer_type', 'status', 'primary_contact_id', 'city', 'description')

def _trim(v): return v.strip() if isinstance(v, str) else v
def _blank(v):
    v = _trim(v)
    return (v or None) if isinstance(v, str) else v
def like(q: str) -> str: return '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

class Base(BaseModel):
    @field_validator('name', 'description', check_fields=False, mode='before')
    @classmethod
    def trim(cls, v): return _trim(v) if isinstance(v, str) else v
    @field_validator('city', 'primary_contact_id', check_fields=False, mode='before')
    @classmethod
    def blank(cls, v): return _blank(v)
    @field_validator('customer_type', check_fields=False)
    @classmethod
    def type_ok(cls, v):
        if v is not None and v not in TYPES: raise ValueError('Customer type must be Fleet or OEM.')
        return v
    @field_validator('status', check_fields=False)
    @classmethod
    def status_ok(cls, v):
        if v is not None and v not in STATUSES: raise ValueError('Invalid status.')
        return v

class CustomerIn(Base):
    name: str = Field(min_length=1, max_length=180)
    customer_type: str = 'FLEET'
    status: str = 'NEW'
    primary_contact_id: str | None = None
    city: str | None = Field(default=None, max_length=80)
    description: str = Field(default='', max_length=3000)

class CustomerUpdate(Base):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    customer_type: str | None = None
    status: str | None = None
    primary_contact_id: str | None = None
    city: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=3000)

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/customers')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def perm(action, write=False):
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s['role'], f'customers.{action}'):
                audit.write('permission_denied', s['id'], None, permission=f'customers.{action}', role=s['role'])
                raise HTTPException(403, f'You do not have permission to {action} customers.')
            return s
        return dep
    def has_fleet(c): return bool(c.execute("select to_regclass('office_dashboard.fleet_vehicles') is not null as ok").fetchone()['ok'])
    def vcount(fleet): return (f"(select count(*)::int from office_dashboard.fleet_vehicles v where not v.archived and v.customer_name is not null and {NORM.format('v.customer_name')}={NORM.format('c.name')})" if fleet else '0')
    def select(fleet):
        return ("select c.*, ct.full_name as contact_name, ct.email as contact_email, ct.phone as contact_phone, ct.organization as contact_organization, coalesce(ct.is_archived,false) as contact_archived, "
                f"{vcount(fleet)} as vehicle_count from office_dashboard.customers c left join office_dashboard.contacts ct on ct.id=c.primary_contact_id")
    def where_for(q='', customer_type='', status='', city=''):
        w = ['not c.archived']; a = []
        if q.strip(): w.append("(c.name ilike %s or coalesce(c.city,'') ilike %s or c.description ilike %s or coalesce(ct.full_name,'') ilike %s or coalesce(ct.email,'') ilike %s or coalesce(ct.phone,'') ilike %s)"); a += [like(q)] * 6
        if customer_type.strip():
            if customer_type not in TYPES: raise HTTPException(422, 'Unknown customer type.')
            w.append('c.customer_type=%s'); a.append(customer_type)
        if status.strip():
            if status not in STATUSES: raise HTTPException(422, 'Unknown status.')
            w.append('c.status=%s'); a.append(status)
        if city.strip(): w.append('c.city ilike %s'); a.append(like(city))
        return ' and '.join(w), a
    def get_customer(c, cid, lock=False):
        try: row = c.execute('select * from office_dashboard.customers where id=%s and not archived' + (' for update' if lock else ''), (cid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Customer not found.')
        return row
    def check_unique(c, name=None, contact_id=None, exclude=None):
        """Friendly duplicate checks; the unique indexes in 017 remain the real guard against concurrent requests."""
        if name is not None:
            d = c.execute(f"select name from office_dashboard.customers where not archived and {NORM.format('name')}={NORM.format('%s')} and (%s::uuid is null or id<>%s::uuid)", (name, exclude, exclude)).fetchone()
            if d: raise HTTPException(409, f'A customer named "{d["name"]}" already exists.')
        if contact_id:
            try: ct = c.execute('select id,full_name,is_archived from office_dashboard.contacts where id=%s', (contact_id,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: ct = None
            if not ct or ct['is_archived']: raise HTTPException(422, 'The selected CRM contact was not found.')
            d = c.execute('select name from office_dashboard.customers where not archived and primary_contact_id=%s and (%s::uuid is null or id<>%s::uuid)', (contact_id, exclude, exclude)).fetchone()
            if d: raise HTTPException(409, f'{ct["full_name"]} is already the primary contact of customer "{d["name"]}".')
    def dup(): raise HTTPException(409, 'This customer or contact is already linked to another customer. Reload and try again.')

    @r.get('/summary')
    def summary(s=Depends(perm('read'))):
        with db() as c:
            fleet = has_fleet(c)
            t = c.execute('select count(*)::int total, count(*) filter (where primary_contact_id is not null)::int with_contact from office_dashboard.customers where not archived').fetchone()
            by_type = {x['k']: x['n'] for x in c.execute('select customer_type k, count(*)::int n from office_dashboard.customers where not archived group by 1').fetchall()}
            by_status = {x['k']: x['n'] for x in c.execute('select status k, count(*)::int n from office_dashboard.customers where not archived group by 1').fetchall()}
            veh = unmatched = None
            if fleet:   # each vehicle is counted once: customer names are unique, so a vehicle matches at most one customer
                m = f"exists(select 1 from office_dashboard.customers c where not c.archived and {NORM.format('c.name')}={NORM.format('v.customer_name')})"
                veh = c.execute(f'select count(*)::int n from office_dashboard.fleet_vehicles v where not v.archived and v.customer_name is not null and {m}').fetchone()['n']
                unmatched = c.execute(f"select count(*)::int n from office_dashboard.fleet_vehicles v where not v.archived and v.customer_name is not null and btrim(v.customer_name)<>'' and not {m}").fetchone()['n']
        return {**t, 'by_type': by_type, 'by_status': by_status, 'vehicles': veh, 'unmatched_vehicles': unmatched, 'fleet_available': fleet}

    @r.get('/contacts')
    def contact_picker(q: str = '', s=Depends(perm('write'))):
        w, a = 'not ct.is_archived', []
        if q.strip(): w += " and (ct.full_name ilike %s or coalesce(ct.email,'') ilike %s or coalesce(ct.organization,'') ilike %s or coalesce(ct.phone,'') ilike %s)"; a += [like(q)] * 4
        with db() as c:
            return c.execute(f"select ct.id, ct.full_name, ct.email, ct.phone, ct.organization, ct.contact_type, cu.name as linked_customer from office_dashboard.contacts ct left join office_dashboard.customers cu on cu.primary_contact_id=ct.id and not cu.archived where {w} order by lower(ct.full_name) limit 15", a).fetchall()

    @r.get('/export')
    def export(q: str = '', customer_type: str = '', status: str = '', city: str = '', s=Depends(perm('export'))):
        w, a = where_for(q, customer_type, status, city)
        with db() as c:
            rows = c.execute(f'{select(has_fleet(c))} where {w} order by lower(c.name) limit 10000', a).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='customer', after={'rows': len(rows)})
        head = ['Customer', 'Type', 'Status', 'Primary contact', 'Email', 'Phone', 'City', 'Vehicles', 'Description', 'Added', 'Updated']
        return csvutil.csv_response('customers.csv', head, [[x['name'], x['customer_type'], x['status'], x['contact_name'], x['contact_email'], x['contact_phone'], x['city'], x['vehicle_count'], x['description'], x['created_at'], x['updated_at']] for x in rows])

    @r.get('')
    def list_customers(q: str = '', customer_type: str = '', status: str = '', city: str = '', sort: str = 'name', direction: str = 'asc', page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        if sort not in SORTS: raise HTTPException(422, 'Unknown sort column.')
        w, a = where_for(q, customer_type, status, city); d = 'desc' if direction == 'desc' else 'asc'
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.customers c left join office_dashboard.contacts ct on ct.id=c.primary_contact_id where {w}', a).fetchone()['n']
            rows = c.execute(f'{select(has_fleet(c))} where {w} order by {SORTS[sort]} {d} nulls last, lower(c.name) limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'types': TYPES, 'statuses': STATUSES,
                'can_write': permissions.can(s['role'], 'customers.write'), 'can_export': permissions.can(s['role'], 'customers.export'), 'can_archive': permissions.can(s['role'], 'customers.archive')}

    @r.post('', status_code=201)
    def create(b: CustomerIn, s=Depends(perm('write', True))):
        try:
            with db() as c:
                check_unique(c, b.name, b.primary_contact_id)
                row = c.execute('insert into office_dashboard.customers(name,customer_type,status,primary_contact_id,city,description,created_by,updated_by) values(%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                                (b.name, b.customer_type, b.status, b.primary_contact_id, b.city, b.description, s['id'], s['id'])).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='customer', entity_id=row['id'], after={k: row[k] for k in AUDITED if k != 'description'})
        except psycopg.errors.UniqueViolation: dup()
        audit.write('customer_created', s['id'], None, customer_id=str(row['id']))
        return row

    @r.get('/{cid}')
    def detail(cid: str, s=Depends(perm('read'))):
        with db() as c:
            fleet = has_fleet(c)
            try: row = c.execute(f'{select(fleet)} where c.id=%s and not c.archived', (cid,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: row = None
            if not row: raise HTTPException(404, 'Customer not found.')
            can_fleet = fleet and permissions.can(s['role'], 'fleet.read'); vehicles = []
            if can_fleet:
                vehicles = c.execute(f"select id,registration_number,vehicle_type,make,model,status from office_dashboard.fleet_vehicles v where not v.archived and v.customer_name is not null and {NORM.format('v.customer_name')}={NORM.format('%s')} order by registration_number limit 100", (row['name'],)).fetchall()
        return {'customer': row, 'vehicles': vehicles, 'vehicles_visible': can_fleet, 'can_write': permissions.can(s['role'], 'customers.write'), 'can_archive': permissions.can(s['role'], 'customers.archive')}

    @r.patch('/{cid}')
    def edit(cid: str, b: CustomerUpdate, s=Depends(perm('write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('name', 'customer_type', 'status'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        if ch.get('description', 0) is None: ch['description'] = ''
        try:
            with db() as c:
                old = get_customer(c, cid, lock=True)
                diff = {k: v for k, v in ch.items() if str(old[k] if old[k] is not None else '') != str(v if v is not None else '')}
                if not diff: return old
                check_unique(c, diff.get('name'), diff.get('primary_contact_id'), exclude=cid)
                row = c.execute('update office_dashboard.customers set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_by=%s,updated_at=now() where id=%s returning *', [*diff.values(), s['id'], cid]).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change' if set(diff) == {'status'} else 'update', entity_type='customer', entity_id=cid,
                               before={k: old[k] for k in diff if k in AUDITED and k != 'description'}, after={k: diff[k] for k in diff if k in AUDITED and k != 'description'})
        except psycopg.errors.UniqueViolation: dup()
        audit.write('customer_updated', s['id'], None, customer_id=cid, fields=sorted(diff))
        return row

    @r.delete('/{cid}')
    def archive(cid: str, s=Depends(perm('archive', True))):
        with db() as c:
            old = get_customer(c, cid, lock=True)
            c.execute('update office_dashboard.customers set archived=true,updated_by=%s,updated_at=now() where id=%s', (s['id'], cid))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='customer', entity_id=cid, before={'name': old['name']})
        audit.write('customer_archived', s['id'], None, customer_id=cid)
        return {'ok': True, 'archived': cid}
    return r
