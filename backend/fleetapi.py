"""Fleet management API (db/011): vehicles, status management, per-vehicle service history, summary and CSV export.
Permissions: fleet.read / write / export / archive (see permissions.py). Every change is written to the business audit log."""
import re
from datetime import date
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions

VEHICLE_TYPES = ('TWO_WHEELER', 'THREE_WHEELER', 'CAR', 'VAN', 'BUS', 'TRUCK', 'OTHER')
STATUSES = ('ACTIVE', 'IN_SERVICE', 'IDLE', 'OUT_OF_SERVICE', 'DECOMMISSIONED')
REG = re.compile(r'^[A-Z0-9][A-Z0-9 -]{2,18}[A-Z0-9]$')

def _trim(v): return v.strip() if isinstance(v, str) else v
def _blank_none(v):
    v = _trim(v)
    return (v or None) if isinstance(v, str) else v
def like(q: str) -> str: return '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

class VehicleBase(BaseModel):
    @field_validator('registration_number', check_fields=False, mode='before')
    @classmethod
    def reg_norm(cls, v): return re.sub(r'\s+', ' ', v.strip().upper()) if isinstance(v, str) else v
    @field_validator('registration_number', check_fields=False)
    @classmethod
    def reg_ok(cls, v):
        if v is not None and not REG.match(v): raise ValueError('Enter a valid registration number (letters, digits, spaces or hyphens).')
        return v
    @field_validator('vehicle_type', check_fields=False)
    @classmethod
    def type_ok(cls, v):
        if v is not None and v not in VEHICLE_TYPES: raise ValueError('Invalid vehicle type.')
        return v
    @field_validator('status', check_fields=False)
    @classmethod
    def status_ok(cls, v):
        if v is not None and v not in STATUSES: raise ValueError('Invalid vehicle status.')
        return v
    @field_validator('make', 'model', 'vehicle_type', 'status', 'notes', check_fields=False, mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('vin', 'customer_name', check_fields=False, mode='before')
    @classmethod
    def blank(cls, v): return _blank_none(v)

class VehicleIn(VehicleBase):
    registration_number: str = Field(min_length=4, max_length=20)
    vehicle_type: str = 'CAR'
    make: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    battery_capacity_kwh: float | None = Field(default=None, gt=0, le=2000)
    status: str = 'ACTIVE'
    vin: str | None = Field(default=None, max_length=40)
    manufacture_year: int | None = Field(default=None, ge=1990, le=2100)
    customer_name: str | None = Field(default=None, max_length=180)
    odometer_km: float | None = Field(default=None, ge=0, le=10_000_000)
    notes: str = Field(default='', max_length=5000)

class VehicleUpdate(VehicleBase):
    registration_number: str | None = Field(default=None, min_length=4, max_length=20)
    vehicle_type: str | None = None
    make: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    battery_capacity_kwh: float | None = Field(default=None, gt=0, le=2000)
    status: str | None = None
    vin: str | None = Field(default=None, max_length=40)
    manufacture_year: int | None = Field(default=None, ge=1990, le=2100)
    customer_name: str | None = Field(default=None, max_length=180)
    odometer_km: float | None = Field(default=None, ge=0, le=10_000_000)
    notes: str | None = Field(default=None, max_length=5000)

class ServiceIn(BaseModel):
    service_date: date
    service_type: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=3000)
    cost: float | None = Field(default=None, ge=0, le=1e9)
    odometer_km: float | None = Field(default=None, ge=0, le=10_000_000)
    technician_name: str | None = Field(default=None, max_length=180)
    ticket_id: str | None = Field(default=None, max_length=64)
    @field_validator('service_type', 'description', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('technician_name', 'ticket_id', mode='before')
    @classmethod
    def blank(cls, v): return _blank_none(v)
    @field_validator('service_date')
    @classmethod
    def not_future(cls, v):
        if v > date.today(): raise ValueError('Service date cannot be in the future.')
        return v

AUDITED = ('registration_number', 'vehicle_type', 'make', 'model', 'battery_capacity_kwh', 'status', 'customer_name', 'odometer_km', 'manufacture_year', 'vin')

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/fleet')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def perm(action, write=False):
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s['role'], f'fleet.{action}'):
                audit.write('permission_denied', s['id'], None, permission=f'fleet.{action}', role=s['role'])
                raise HTTPException(403, 'You do not have permission to ' + {'read': 'view fleet vehicles', 'write': 'change fleet vehicles', 'export': 'export fleet data', 'archive': 'archive vehicles'}[action] + '.')
            return s
        return dep
    def get_vehicle(c, vid, lock=False):
        try: row = c.execute('select * from office_dashboard.fleet_vehicles where id=%s and not archived' + (' for update' if lock else ''), (vid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Vehicle not found.')
        return row
    def where_for(q='', status='', vehicle_type='', customer=''):
        w = ['not archived']; a = []
        if q.strip(): w.append("(registration_number ilike %s or make ilike %s or model ilike %s or coalesce(vin,'') ilike %s or coalesce(customer_name,'') ilike %s)"); a += [like(q)] * 5
        if status.strip():
            if status not in STATUSES: raise HTTPException(422, 'Unknown vehicle status.')
            w.append('status=%s'); a.append(status)
        if vehicle_type.strip():
            if vehicle_type not in VEHICLE_TYPES: raise HTTPException(422, 'Unknown vehicle type.')
            w.append('vehicle_type=%s'); a.append(vehicle_type)
        if customer.strip(): w.append('customer_name ilike %s'); a.append(like(customer))
        return ' and '.join(w), a
    def dup(e): raise HTTPException(409, 'A vehicle with this registration number already exists.')

    @r.get('/summary')
    def summary(s=Depends(perm('read'))):
        with db() as c:
            tot = c.execute('select count(*)::int total, coalesce(sum(battery_capacity_kwh),0)::float total_kwh from office_dashboard.fleet_vehicles where not archived').fetchone()
            by_status = {x['status']: x['n'] for x in c.execute('select status, count(*)::int n from office_dashboard.fleet_vehicles where not archived group by status').fetchall()}
            by_type = {x['vehicle_type']: x['n'] for x in c.execute('select vehicle_type, count(*)::int n from office_dashboard.fleet_vehicles where not archived group by vehicle_type').fetchall()}
        return {**tot, 'by_status': by_status, 'by_type': by_type}

    @r.get('/export')
    def export(q: str = '', status: str = '', vehicle_type: str = '', customer: str = '', s=Depends(perm('export'))):
        where, a = where_for(q, status, vehicle_type, customer)
        with db() as c:
            rows = c.execute(f"select v.*, (select max(h.service_date) from office_dashboard.fleet_service_history h where h.vehicle_id=v.id) as last_service,"
                             f" (select count(*) from office_dashboard.fleet_service_history h where h.vehicle_id=v.id)::int as service_count from office_dashboard.fleet_vehicles v where {where} order by v.registration_number limit 10000", a).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='fleet_vehicle', after={'rows': len(rows)})
        head = ['Registration', 'Type', 'Make', 'Model', 'Battery (kWh)', 'Status', 'VIN', 'Year', 'Customer', 'Odometer (km)', 'Last service', 'Service records', 'Notes', 'Added', 'Updated']
        return csvutil.csv_response('fleet-vehicles.csv', head, [[x['registration_number'], x['vehicle_type'], x['make'], x['model'], x['battery_capacity_kwh'], x['status'], x['vin'], x['manufacture_year'], x['customer_name'],
                                                               x['odometer_km'], x['last_service'], x['service_count'], x['notes'], x['created_at'], x['updated_at']] for x in rows])

    @r.get('/vehicles')
    def list_vehicles(q: str = '', status: str = '', vehicle_type: str = '', customer: str = '', page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        where, a = where_for(q, status, vehicle_type, customer); role = s['role']
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.fleet_vehicles where {where}', a).fetchone()['n']
            rows = c.execute(f"select v.*, (select max(h.service_date) from office_dashboard.fleet_service_history h where h.vehicle_id=v.id) as last_service from office_dashboard.fleet_vehicles v where {where} order by v.updated_at desc limit %s offset %s", [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'vehicle_types': VEHICLE_TYPES, 'statuses': STATUSES,
                'can_write': permissions.can(role, 'fleet.write'), 'can_export': permissions.can(role, 'fleet.export'), 'can_archive': permissions.can(role, 'fleet.archive')}

    @r.post('/vehicles', status_code=201)
    def create_vehicle(b: VehicleIn, s=Depends(perm('write', True))):
        try:
            with db() as c:
                row = c.execute('insert into office_dashboard.fleet_vehicles(registration_number,vehicle_type,make,model,battery_capacity_kwh,status,vin,manufacture_year,customer_name,odometer_km,notes,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                                (b.registration_number, b.vehicle_type, b.make, b.model, b.battery_capacity_kwh, b.status, b.vin, b.manufacture_year, b.customer_name, b.odometer_km, b.notes, s['id'])).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='fleet_vehicle', entity_id=row['id'], after={k: row[k] for k in ('registration_number', 'vehicle_type', 'make', 'model', 'status')})
        except psycopg.errors.UniqueViolation as e: dup(e)
        audit.write('fleet_vehicle_created', s['id'], None, vehicle_id=str(row['id']))
        return row

    @r.get('/vehicles/{vid}')
    def detail(vid: str, s=Depends(perm('read'))):
        with db() as c:
            v = get_vehicle(c, vid)
            history = c.execute('select * from office_dashboard.fleet_service_history where vehicle_id=%s order by service_date desc, id desc', (vid,)).fetchall()
            # Tickets whose free-text vehicle reference matches this registration number (read-only link; respects technician scoping).
            tw, ta = 'not archived and upper(vehicle_reference)=upper(%s)', [v['registration_number']]
            if s['role'] == 'technician': tw += ' and (assigned_to=%s or created_by=%s)'; ta += [s['id'], s['id']]
            linked = c.execute(f'select id,ticket_number,title,status,priority,created_at from office_dashboard.service_tickets where {tw} order by created_at desc limit 50', ta).fetchall()
        return {'vehicle': v, 'service_history': history, 'tickets': linked, 'total_service_cost': float(sum((h['cost'] or 0) for h in history)), 'can_write': permissions.can(s['role'], 'fleet.write'), 'can_archive': permissions.can(s['role'], 'fleet.archive')}

    @r.patch('/vehicles/{vid}')
    def edit(vid: str, b: VehicleUpdate, s=Depends(perm('write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('registration_number', 'vehicle_type', 'make', 'model', 'status'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        if ch.get('notes', 0) is None: ch['notes'] = ''
        try:
            with db() as c:
                old = get_vehicle(c, vid, lock=True)
                diff = {k: v for k, v in ch.items() if old[k] != v and (k != 'battery_capacity_kwh' or old[k] is None or v is None or float(old[k]) != float(v)) and (k != 'odometer_km' or old[k] is None or v is None or float(old[k]) != float(v))}
                if not diff: return old
                row = c.execute('update office_dashboard.fleet_vehicles set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_at=now() where id=%s returning *', [*diff.values(), vid]).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change' if set(diff) == {'status'} else 'update', entity_type='fleet_vehicle', entity_id=vid,
                               before={k: old[k] for k in diff if k in AUDITED}, after={k: diff[k] for k in diff if k in AUDITED})
        except psycopg.errors.UniqueViolation as e: dup(e)
        audit.write('fleet_vehicle_updated', s['id'], None, vehicle_id=vid, fields=sorted(diff))
        return row

    @r.delete('/vehicles/{vid}')
    def archive(vid: str, s=Depends(perm('archive', True))):
        with db() as c:
            old = get_vehicle(c, vid, lock=True)
            c.execute('update office_dashboard.fleet_vehicles set archived=true,updated_at=now() where id=%s', (vid,))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='fleet_vehicle', entity_id=vid, before={'registration_number': old['registration_number']})
        audit.write('fleet_vehicle_archived', s['id'], None, vehicle_id=vid)
        return {'ok': True, 'archived': vid}

    @r.post('/vehicles/{vid}/service-history', status_code=201)
    def add_service(vid: str, b: ServiceIn, s=Depends(perm('write', True))):
        with db() as c:
            v = get_vehicle(c, vid, lock=True)
            if b.ticket_id:
                try: t = c.execute('select 1 from office_dashboard.service_tickets where id=%s and not archived', (b.ticket_id,)).fetchone()
                except psycopg.errors.InvalidTextRepresentation: t = None
                if not t: raise HTTPException(422, 'Linked service ticket was not found.')
            row = c.execute('insert into office_dashboard.fleet_service_history(vehicle_id,service_date,service_type,description,cost,odometer_km,technician_name,ticket_id,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                            (vid, b.service_date, b.service_type, b.description, b.cost, b.odometer_km, b.technician_name, b.ticket_id, s['id'])).fetchone()
            if b.odometer_km is not None and (v['odometer_km'] is None or float(v['odometer_km']) < b.odometer_km):   # odometer only ever moves forward
                c.execute('update office_dashboard.fleet_vehicles set odometer_km=%s,updated_at=now() where id=%s', (b.odometer_km, vid))
            else: c.execute('update office_dashboard.fleet_vehicles set updated_at=now() where id=%s', (vid,))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='service_logged', entity_type='fleet_vehicle', entity_id=vid, after={'service_type': b.service_type, 'service_date': b.service_date, 'cost': b.cost})
        audit.write('fleet_service_logged', s['id'], None, vehicle_id=vid)
        return row
    return r
