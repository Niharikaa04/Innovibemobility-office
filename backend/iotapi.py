"""IoT & Telemetry API (db/012).

NO FAKE DATA: this module never generates, simulates or back-fills readings. Rows in iot_readings arrive ONLY through POST /api/iot/ingest from a
registered device holding that device's token. "Online/Offline" is computed from the device's real last contact; alerts are computed only when a real
reading breaks a limit that a person entered under Alert limits. With no devices / no readings the UI says so.

Device ingest contract (what a real device or gateway must send):
    POST /api/iot/ingest
    Headers: X-Device-Id: <device identifier>      X-Device-Token: <token shown once when the device was registered>
    Body:    {"readings": [{"metric": "battery_voltage", "value": 51.3, "unit": "V", "recorded_at": "2026-10-27T09:15:00Z"}, ...]}   (1-200 readings; recorded_at optional = server time)
    Metric names: lower_snake_case (battery_voltage, temperature, state_of_charge, current, ...). Re-sending the same (device, metric, recorded_at) is ignored (safe retries).
Permissions: iot.read (view) / iot.write (devices, alert limits) / iot.export / iot.archive (retire a device).

LOCATION DATA (GPS etc.) is governed by locationpolicy.py and enforced HERE on every read path (latest, history, records, alerts, metrics, device detail, export):
  full = `location.read` grant (CEO + authorised Operations roles); assigned_only = technicians, limited to vehicles with an open ticket assigned to them (their entire
  IoT view is limited to those vehicles); none = location metrics are removed from responses and asking for one by name returns 403. Location views are audit-logged.
"Latest" values are the last values RECEIVED from a device, not live telemetry; each carries its own timestamp and a stale flag."""
import hashlib, hmac, os, re, secrets
from datetime import date, datetime, timedelta, timezone
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
import auditdb, csvutil, locationpolicy as LP, permissions
from opscommon import blank, like, make_perm, trim

DEVICE_TYPES = ('BMS', 'TELEMATICS', 'CHARGER', 'GPS', 'OTHER')
DEVICE_STATUSES = ('ACTIVE', 'INACTIVE')
CONNECTIONS = ('ONLINE', 'OFFLINE', 'NEVER')
SEVERITIES = ('WARNING', 'CRITICAL')
METRIC = re.compile(r'^[a-z][a-z0-9_]{1,39}$')
IDENT = re.compile(r'^[A-Za-z0-9._:-]{3,64}$')
PLAUSIBLE = {'state_of_charge': (0.0, 100.0)}    # only physically impossible values are refused; nothing else is judged here
MAX_FUTURE, MAX_AGE = timedelta(minutes=5), timedelta(days=30)
CONN_SQL = "(case when d.last_seen_at is null then 'NEVER' when d.last_seen_at < now() - make_interval(mins => d.offline_after_minutes) then 'OFFLINE' else 'ONLINE' end)"
DEVICE_COLS = ("d.id, d.device_identifier, d.name, d.device_type, d.vehicle_id, v.registration_number, d.status, d.offline_after_minutes, d.token_hint, d.last_seen_at, d.notes, d.created_at, d.updated_at, "
               + CONN_SQL + " as connection")


def hash_token(t: str) -> str: return hashlib.sha256(t.encode()).hexdigest()
def new_token() -> str: return secrets.token_urlsafe(32)
def _utc(d: datetime) -> datetime: return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
def check_metric(m: str) -> str:
    m = (m or '').strip().lower()
    if not METRIC.match(m): raise ValueError('Metric names use lowercase letters, digits and underscores (e.g. battery_voltage).')
    return m
def pick_alerts(rows):
    """Keep the most severe breach per (device, metric)."""
    best = {}
    for x in rows:
        k = (x['device_id'], x['metric'])
        if k not in best or (x['severity'] == 'CRITICAL' and best[k]['severity'] != 'CRITICAL'): best[k] = x
    return sorted(best.values(), key=lambda x: (x['severity'] != 'CRITICAL', str(x['recorded_at'])))


class ReadingIn(BaseModel):
    metric: str
    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=16)
    recorded_at: datetime | None = None
    @field_validator('metric')
    @classmethod
    def _m(cls, v): return check_metric(v)
    @field_validator('unit', mode='before')
    @classmethod
    def _u(cls, v): return blank(v)
    @model_validator(mode='after')
    def _ok(self):
        lo_hi = PLAUSIBLE.get(self.metric)
        if lo_hi and not (lo_hi[0] <= self.value <= lo_hi[1]): raise ValueError(f'{self.metric} must be between {lo_hi[0]:g} and {lo_hi[1]:g}.')
        if self.recorded_at is not None:
            t, now = _utc(self.recorded_at), datetime.now(timezone.utc)
            if t > now + MAX_FUTURE: raise ValueError('recorded_at is in the future.')
            if t < now - MAX_AGE: raise ValueError('recorded_at is older than 30 days.')
            self.recorded_at = t
        return self


class IngestIn(BaseModel): readings: list[ReadingIn] = Field(min_length=1, max_length=200)


class DeviceBase(BaseModel):
    @field_validator('name', 'vehicle_id', check_fields=False, mode='before')
    @classmethod
    def _b(cls, v): return blank(v)
    @field_validator('notes', check_fields=False, mode='before')
    @classmethod
    def _t(cls, v): return trim(v)
    @field_validator('device_type', check_fields=False)
    @classmethod
    def _dt(cls, v):
        if v is not None and v not in DEVICE_TYPES: raise ValueError('Invalid device type.')
        return v
    @field_validator('status', check_fields=False)
    @classmethod
    def _st(cls, v):
        if v is not None and v not in DEVICE_STATUSES: raise ValueError('Invalid status.')
        return v


class DeviceIn(DeviceBase):
    device_identifier: str = Field(min_length=3, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    device_type: str = 'OTHER'
    vehicle_id: str | None = None
    status: str = 'ACTIVE'
    offline_after_minutes: int = Field(default=30, ge=1, le=10080)
    notes: str = Field(default='', max_length=2000)
    @field_validator('device_identifier', mode='before')
    @classmethod
    def _id(cls, v):
        v = trim(v)
        if isinstance(v, str) and not IDENT.match(v): raise ValueError('Device ID: 3-64 letters, digits and . _ : - only.')
        return v


class DeviceUpdate(DeviceBase):
    name: str | None = Field(default=None, max_length=120)
    device_type: str | None = None
    vehicle_id: str | None = None
    status: str | None = None
    offline_after_minutes: int | None = Field(default=None, ge=1, le=10080)
    notes: str | None = Field(default=None, max_length=2000)


class ThresholdIn(BaseModel):
    metric: str
    severity: str
    min_value: float | None = Field(default=None, allow_inf_nan=False)
    max_value: float | None = Field(default=None, allow_inf_nan=False)
    @field_validator('metric')
    @classmethod
    def _m(cls, v): return check_metric(v)
    @field_validator('severity')
    @classmethod
    def _s(cls, v):
        if v not in SEVERITIES: raise ValueError('Severity must be WARNING or CRITICAL.')
        return v
    @model_validator(mode='after')
    def _b(self):
        if self.min_value is None and self.max_value is None: raise ValueError('Enter a minimum, a maximum, or both.')
        if self.min_value is not None and self.max_value is not None and not self.min_value < self.max_value: raise ValueError('Minimum must be lower than maximum.')
        return self


def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/iot')
    perm = make_perm(session, csrf, audit, 'iot')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)

    # ---------- access policy (server-side; the UI only reflects it) ----------
    def extra(): return os.getenv('IOT_EXTRA_LOCATION_METRICS', '')
    def access(s): return LP.location_access(s['role'], permissions.can(s['role'], 'location.read'))
    def deny_location(s):
        audit.write('permission_denied', s['id'], None, permission='location.read', role=s['role'])
        raise HTTPException(403, 'You do not have permission to view location data.')
    def seen_location(s, rows, endpoint):
        n = sum(1 for x in rows if LP.is_location_metric(x.get('metric', ''), extra()))
        if n: audit.write('iot_location_viewed', s['id'], None, endpoint=endpoint, rows=n, access=access(s))

    def get_device(c, did, lock=False, s=None):
        try: row = c.execute(f'select {DEVICE_COLS} from office_dashboard.iot_devices d left join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id where d.id=%s and not d.archived' + (' for update of d' if lock else ''), (did,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if row and s and s['role'] == 'technician':      # technicians only see devices on vehicles assigned to them
            ok = row['vehicle_id'] and c.execute(f'select 1 from ({LP.ASSIGNED_VEHICLES_SQL}) a where a.id=%s', [s['id'], list(LP.DONE_STATUSES), row['vehicle_id']]).fetchone()
            if not ok: row = None
        if not row: raise HTTPException(404, 'Device not found.')
        return row
    def check_vehicle(c, vid):
        if not vid: return
        try: ok = c.execute('select 1 from office_dashboard.fleet_vehicles where id=%s and not archived', (vid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: ok = None
        if not ok: raise HTTPException(422, 'Choose an existing vehicle.')

    def dev_where(s, extra_w=None, extra_a=None):
        w, a = ['not d.archived'], []
        sc = LP.vehicle_scope(s['role'], s['id'], 'd.vehicle_id')
        if sc: w.append(sc[0]); a += sc[1]
        if extra_w: w += extra_w; a += extra_a or []
        return ' and '.join(w), a

    def reading_where(s, device_id='', vehicle_id='', metric='', date_from: date | None = None, date_to: date | None = None):
        w, a = ['not d.archived'], []
        sc = LP.vehicle_scope(s['role'], s['id'], 'r.vehicle_id')
        if sc: w.append(sc[0]); a += sc[1]
        if access(s) == 'none':
            if metric.strip() and LP.is_location_metric(metric, extra()): deny_location(s)
            w.append('r.metric !~ %s'); a.append(LP.location_pattern(extra()))
        if date_from and date_to and date_from > date_to: raise HTTPException(422, 'Start date must be on or before end date.')
        if device_id.strip(): w.append('r.device_id::text=%s'); a.append(device_id.strip())
        if vehicle_id.strip(): w.append('r.vehicle_id::text=%s'); a.append(vehicle_id.strip())
        if metric.strip():
            try: m = check_metric(metric)
            except ValueError as e: raise HTTPException(422, str(e))
            w.append('r.metric=%s'); a.append(m)
        if date_from: w.append('r.recorded_at >= %s'); a.append(date_from)
        if date_to: w.append('r.recorded_at < %s'); a.append(date_to + timedelta(days=1))
        return ' and '.join(w), a

    LATEST = ("select distinct on (r.device_id, r.metric) r.device_id, r.metric, r.value, r.unit, r.recorded_at, r.received_at, r.vehicle_id, d.device_identifier, d.name as device_name, v.registration_number,"
              " d.offline_after_minutes, (r.recorded_at < now() - make_interval(mins => d.offline_after_minutes)) as stale, extract(epoch from (now() - r.recorded_at))::bigint as age_seconds"
              " from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id left join office_dashboard.fleet_vehicles v on v.id=r.vehicle_id where {where}"
              " order by r.device_id, r.metric, r.recorded_at desc")

    def alerts_for(c, s, device_id='', vehicle_id='', metric=''):
        where, a = reading_where(s, device_id, vehicle_id, metric)
        active_where = where + " and d.status='ACTIVE'"
        rows = c.execute(f"select l.*, th.severity, th.min_value, th.max_value, case when th.min_value is not null and l.value < th.min_value then 'BELOW_MIN' else 'ABOVE_MAX' end as breach"
                         f" from ({LATEST.format(where=active_where)}) l join office_dashboard.iot_thresholds th on th.metric=l.metric"
                         f" and ((th.min_value is not null and l.value < th.min_value) or (th.max_value is not null and l.value > th.max_value))", a).fetchall()
        ew, ea = ["d.status='ACTIVE'", f'{CONN_SQL}=' + "'OFFLINE'"], []
        if device_id.strip(): ew.append('d.id::text=%s'); ea.append(device_id.strip())
        if vehicle_id.strip(): ew.append('d.vehicle_id::text=%s'); ea.append(vehicle_id.strip())
        dw, da = dev_where(s, ew, ea)
        offline = c.execute(f"select {DEVICE_COLS} from office_dashboard.iot_devices d left join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id where {dw} order by d.last_seen_at", da).fetchall()
        return pick_alerts(rows), offline

    # ---------------- Device ingest (no browser session: authenticated by the per-device token) ----------------
    @r.post('/ingest')
    def ingest(b: IngestIn, x_device_id: str = Header(), x_device_token: str = Header()):
        bad = HTTPException(401, 'Invalid device credentials.')
        with db() as c:
            d = c.execute('select id, status, token_hash, vehicle_id from office_dashboard.iot_devices where lower(device_identifier)=lower(%s) and not archived for update', (x_device_id.strip(),)).fetchone()
            ok = hmac.compare_digest(hash_token(x_device_token.strip()), d['token_hash'] if d else hash_token('x'))   # same work for unknown ids: no enumeration by timing
            if not (d and ok): raise bad
            if d['status'] != 'ACTIVE': raise HTTPException(403, 'This device is deactivated.')
            now, n = datetime.now(timezone.utc), 0
            for x in b.readings:
                cur = c.execute('insert into office_dashboard.iot_readings(device_id,vehicle_id,metric,value,unit,recorded_at) values(%s,%s,%s,%s,%s,%s) on conflict (device_id, metric, recorded_at) do nothing',
                                (d['id'], d['vehicle_id'], x.metric, x.value, x.unit, x.recorded_at or now)); n += cur.rowcount
            c.execute('update office_dashboard.iot_devices set last_seen_at=now() where id=%s', (d['id'],))
        return {'accepted': n, 'duplicates': len(b.readings) - n}

    # ---------------- Overview ----------------
    @r.get('/summary')
    def summary(s=Depends(perm('read'))):
        dw, da = dev_where(s); rw, ra = reading_where(s, '', '', '')
        rw += " and r.recorded_at > now() - interval '24 hours'"
        with db() as c:
            by_status = {x['status']: x['n'] for x in c.execute(f'select d.status, count(*)::int n from office_dashboard.iot_devices d where {dw} group by d.status', da).fetchall()}
            by_conn = {x['connection']: x['n'] for x in c.execute(f"select {CONN_SQL} as connection, count(*)::int n from office_dashboard.iot_devices d where {dw} and d.status='ACTIVE' group by 1", da).fetchall()}
            readings_24h = c.execute(f'select count(*)::int n from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id where {rw}', ra).fetchone()['n']
            thr, off = alerts_for(c, s)
        acc = access(s)
        return {'devices': sum(by_status.values()), 'by_status': by_status, 'by_connection': by_conn, 'readings_24h': readings_24h, 'threshold_alerts': len(thr), 'offline_devices': len(off),
                'location_access': acc, 'scoped_to_assigned_vehicles': s['role'] == 'technician'}

    # ---------------- Devices ----------------
    @r.get('/devices')
    def list_devices(q: str = '', status: str = '', device_type: str = '', vehicle_id: str = '', connection: str = '', page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        w, a = [], []
        if q.strip(): w.append("(d.device_identifier ilike %s or coalesce(d.name,'') ilike %s or coalesce(v.registration_number,'') ilike %s)"); a += [like(q)] * 3
        if status:
            if status not in DEVICE_STATUSES: raise HTTPException(422, 'Unknown status.')
            w.append('d.status=%s'); a.append(status)
        if device_type:
            if device_type not in DEVICE_TYPES: raise HTTPException(422, 'Unknown device type.')
            w.append('d.device_type=%s'); a.append(device_type)
        if vehicle_id.strip(): w.append('d.vehicle_id::text=%s'); a.append(vehicle_id.strip())
        if connection:
            if connection not in CONNECTIONS: raise HTTPException(422, 'Unknown connection state.')
            w.append(f'{CONN_SQL}=%s'); a.append(connection)
        where, wa = dev_where(s, w, a); role = s['role']
        frm = 'from office_dashboard.iot_devices d left join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id'
        with db() as c:
            total = c.execute(f'select count(*)::int n {frm} where {where}', wa).fetchone()['n']
            rows = c.execute(f'select {DEVICE_COLS} {frm} where {where} order by d.device_identifier limit %s offset %s', [*wa, limit, (page - 1) * limit]).fetchall()
            vsc = LP.vehicle_scope(role, s['id'], 'v.id')
            vehicles = c.execute('select v.id, v.registration_number from office_dashboard.fleet_vehicles v where not v.archived' + (f' and {vsc[0]}' if vsc else '') + ' order by v.registration_number limit 1000', vsc[1] if vsc else []).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'device_types': DEVICE_TYPES, 'statuses': DEVICE_STATUSES, 'vehicles': vehicles,
                'can_write': permissions.can(role, 'iot.write'), 'can_export': permissions.can(role, 'iot.export'), 'can_archive': permissions.can(role, 'iot.archive')}

    @r.post('/devices', status_code=201)
    def create_device(b: DeviceIn, s=Depends(perm('write', True))):
        token = new_token()
        try:
            with db() as c:
                check_vehicle(c, b.vehicle_id)
                row = c.execute('insert into office_dashboard.iot_devices(device_identifier,name,device_type,vehicle_id,status,offline_after_minutes,token_hash,token_hint,notes,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id',
                                (b.device_identifier, b.name, b.device_type, b.vehicle_id, b.status, b.offline_after_minutes, hash_token(token), token[-4:], b.notes, s['id'])).fetchone()
                out = get_device(c, row['id'])
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='iot_device', entity_id=row['id'], after={'device_identifier': b.device_identifier, 'device_type': b.device_type, 'vehicle_id': b.vehicle_id})
        except psycopg.errors.UniqueViolation: raise HTTPException(409, 'A device with this ID already exists.')
        audit.write('iot_device_created', s['id'], None, device_id=str(row['id']))
        return {**out, 'device_token': token, 'token_notice': 'Copy this token now. It is shown only once and cannot be recovered; rotate the token if it is lost.'}

    @r.get('/devices/{did}')
    def device_detail(did: str, s=Depends(perm('read'))):
        """Device details: settings, connection state, latest received value per metric (with stale flag) and the 25 most recent raw records."""
        with db() as c:
            d = get_device(c, did, s=s)
            where, a = reading_where(s, device_id=did)
            latest = c.execute(f'select * from ({LATEST.format(where=where)}) l order by l.metric', a).fetchall()
            recent = c.execute(f'select r.metric, r.value, r.unit, r.recorded_at, r.received_at from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id where {where} order by r.recorded_at desc, r.id desc limit 25', a).fetchall()
        seen_location(s, latest + recent, 'device_detail')
        return {'device': d, 'latest': latest, 'recent': recent, 'location_access': access(s), 'can_write': permissions.can(s['role'], 'iot.write')}

    @r.patch('/devices/{did}')
    def edit_device(did: str, b: DeviceUpdate, s=Depends(perm('write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('device_type', 'status', 'offline_after_minutes'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        if 'notes' in ch and ch['notes'] is None: ch['notes'] = ''
        with db() as c:
            old = get_device(c, did, lock=True)
            if 'vehicle_id' in ch: check_vehicle(c, ch['vehicle_id'])
            diff = {k: v for k, v in ch.items() if (None if old[k] is None else str(old[k])) != (None if v is None else str(v))}
            if not diff: return old
            c.execute('update office_dashboard.iot_devices set ' + ','.join(f'{k}=%s' for k in diff) + ',updated_at=now() where id=%s', [*diff.values(), did])
            out = get_device(c, did)
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change' if set(diff) == {'status'} else 'update', entity_type='iot_device', entity_id=did,
                           before={k: old[k] for k in diff if k != 'notes'}, after={k: diff[k] for k in diff if k != 'notes'})
        audit.write('iot_device_updated', s['id'], None, device_id=did, fields=sorted(diff))
        return out

    @r.post('/devices/{did}/rotate-token')
    def rotate(did: str, s=Depends(perm('write', True))):
        token = new_token()
        with db() as c:
            get_device(c, did, lock=True)
            c.execute('update office_dashboard.iot_devices set token_hash=%s, token_hint=%s, updated_at=now() where id=%s', (hash_token(token), token[-4:], did))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='rotate_token', entity_type='iot_device', entity_id=did)   # the token itself is never logged
        audit.write('iot_device_token_rotated', s['id'], None, device_id=did)
        return {'device_token': token, 'token_notice': 'Copy this token now. The previous token no longer works and this one is shown only once.'}

    @r.delete('/devices/{did}')
    def archive_device(did: str, s=Depends(perm('archive', True))):
        with db() as c:
            old = get_device(c, did, lock=True)
            c.execute("update office_dashboard.iot_devices set archived=true, status='INACTIVE', updated_at=now() where id=%s", (did,))   # readings are kept
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='iot_device', entity_id=did, before={'device_identifier': old['device_identifier']})
        audit.write('iot_device_archived', s['id'], None, device_id=did)
        return {'ok': True, 'archived': did}

    # ---------------- Readings ----------------
    @r.get('/metrics')
    def metrics(s=Depends(perm('read'))):
        where, a = reading_where(s)
        with db() as c:
            rows = c.execute("select r.metric, (array_agg(r.unit order by r.recorded_at desc))[1] as unit, count(*)::int as readings, max(r.recorded_at) as last_at from office_dashboard.iot_readings r"
                             f" join office_dashboard.iot_devices d on d.id=r.device_id where {where} and r.recorded_at > now() - interval '90 days' group by r.metric order by r.metric", a).fetchall()
        return {'items': rows}

    @r.get('/latest')
    def latest(device_id: str = '', vehicle_id: str = '', metric: str = '', s=Depends(perm('read'))):
        where, a = reading_where(s, device_id, vehicle_id, metric)
        with db() as c:
            rows = c.execute(f"select * from ({LATEST.format(where=where)}) l order by l.registration_number nulls last, l.device_identifier, l.metric", a).fetchall()
        seen_location(s, rows, 'latest')
        return {'items': rows, 'location_access': access(s)}

    @r.get('/readings')
    def readings(device_id: str = '', vehicle_id: str = '', metric: str = '', date_from: date | None = None, date_to: date | None = None, limit: int = Query(1000, ge=1, le=5000), s=Depends(perm('read'))):
        if not metric.strip(): raise HTTPException(422, 'Choose a metric to chart.')
        where, a = reading_where(s, device_id, vehicle_id, metric, date_from, date_to)
        with db() as c:
            rows = c.execute(f'select r.device_id, d.device_identifier, d.name as device_name, r.metric, r.value, r.unit, r.recorded_at from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id'
                             f' where {where} order by r.recorded_at desc limit %s', [*a, limit + 1]).fetchall()
        seen_location(s, rows, 'readings')
        return {'points': list(reversed(rows[:limit])), 'truncated': len(rows) > limit, 'limit': limit}

    @r.get('/records')
    def records(device_id: str = '', vehicle_id: str = '', metric: str = '', date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), s=Depends(perm('read'))):
        """Raw received telemetry records, newest first (every record keeps its own recorded-at and received-at time)."""
        where, a = reading_where(s, device_id, vehicle_id, metric, date_from, date_to)
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id where {where}', a).fetchone()['n']
            rows = c.execute(f'select r.id, d.device_identifier, d.name as device_name, v.registration_number, r.metric, r.value, r.unit, r.recorded_at, r.received_at from office_dashboard.iot_readings r'
                             f' join office_dashboard.iot_devices d on d.id=r.device_id left join office_dashboard.fleet_vehicles v on v.id=r.vehicle_id where {where} order by r.recorded_at desc, r.id desc limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        seen_location(s, rows, 'records')
        return {'items': rows, 'total': total, 'page': page, 'limit': limit}

    @r.get('/alerts')
    def alerts(device_id: str = '', vehicle_id: str = '', metric: str = '', s=Depends(perm('read'))):
        with db() as c:
            thr, off = alerts_for(c, s, device_id, vehicle_id, metric)
            has_limits = c.execute('select count(*)::int n from office_dashboard.iot_thresholds').fetchone()['n'] > 0
        seen_location(s, thr, 'alerts')
        return {'threshold_alerts': thr, 'offline_devices': off, 'limits_configured': has_limits}

    @r.get('/export')
    def export(device_id: str = '', vehicle_id: str = '', metric: str = '', date_from: date | None = None, date_to: date | None = None, s=Depends(perm('export'))):
        where, a = reading_where(s, device_id, vehicle_id, metric, date_from, date_to)
        with db() as c:
            rows = c.execute(f'select d.device_identifier, d.name as device_name, v.registration_number, r.metric, r.value, r.unit, r.recorded_at, r.received_at from office_dashboard.iot_readings r'
                             f' join office_dashboard.iot_devices d on d.id=r.device_id left join office_dashboard.fleet_vehicles v on v.id=r.vehicle_id where {where} order by r.recorded_at desc limit 50000', a).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='iot_reading', after={'rows': len(rows), 'metric': metric or None, 'location_access': access(s)})
        seen_location(s, rows, 'export')
        return csvutil.csv_response('iot-readings.csv', ['Device ID', 'Device name', 'Vehicle', 'Metric', 'Value', 'Unit', 'Recorded at', 'Received at'],
                                    [[x['device_identifier'], x['device_name'], x['registration_number'], x['metric'], x['value'], x['unit'], x['recorded_at'], x['received_at']] for x in rows])

    # ---------------- Alert limits ----------------
    @r.get('/thresholds')
    def thresholds(s=Depends(perm('read'))):
        with db() as c: rows = c.execute('select id, metric, severity, min_value, max_value, created_at from office_dashboard.iot_thresholds order by metric, severity').fetchall()
        if access(s) != 'full': rows = [x for x in rows if not LP.is_location_metric(x['metric'], extra())]
        return {'items': rows, 'can_write': permissions.can(s['role'], 'iot.write')}

    @r.post('/thresholds', status_code=201)
    def set_threshold(b: ThresholdIn, s=Depends(perm('write', True))):
        if LP.is_location_metric(b.metric, extra()) and access(s) != 'full': deny_location(s)
        with db() as c:
            row = c.execute('insert into office_dashboard.iot_thresholds(metric,severity,min_value,max_value,created_by) values(%s,%s,%s,%s,%s)'
                            ' on conflict (metric, severity) do update set min_value=excluded.min_value, max_value=excluded.max_value returning *', (b.metric, b.severity, b.min_value, b.max_value, s['id'])).fetchone()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='set_threshold', entity_type='iot_threshold', entity_id=row['id'], after={'metric': b.metric, 'severity': b.severity, 'min': b.min_value, 'max': b.max_value})
        audit.write('iot_threshold_set', s['id'], None, metric=b.metric)
        return row

    @r.delete('/thresholds/{tid}')
    def delete_threshold(tid: int, s=Depends(perm('write', True))):
        with db() as c:
            row = c.execute('select metric, severity from office_dashboard.iot_thresholds where id=%s for update', (tid,)).fetchone()
            if not row or (LP.is_location_metric(row['metric'], extra()) and access(s) != 'full'): raise HTTPException(404, 'Alert limit not found.')
            c.execute('delete from office_dashboard.iot_thresholds where id=%s', (tid,))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='delete_threshold', entity_type='iot_threshold', entity_id=tid, before=dict(row))
        audit.write('iot_threshold_deleted', s['id'], None, threshold_id=tid)
        return {'ok': True}
    return r
