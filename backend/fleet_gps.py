"""Fleet live GPS (db/012): authenticated telemetry ingest, provider adapter, live fleet state, route history, device management.

Two routers, mounted next to fleetapi:
  build_ingest_router(dsn)                  -> POST /api/gps/ingest            device bearer token (no browser session, no CSRF)
                                               POST /api/gps/webhook/{provider} HMAC-signed provider push
  build_router(dsn, session, csrf, audit)   -> GET  /api/fleet/live             fleet.read
                                               GET  /api/fleet/vehicles/{vid}/track  fleet.read
                                               GET/POST /api/fleet/gps/devices[...]  fleet.write (token provisioning)

Real coordinates only ever arrive through the ingest endpoints. Nothing here fabricates a position.

Status model (single source of truth, see derive()):
  freshness : live (<= GPS_LIVE_SECONDS) | delayed (<= GPS_OFFLINE_SECONDS) | offline (older) | none (never reported)
  state     : offline > charging > moving > idle > unknown; vehicles that never reported are 'no_gps'.
              States are mutually exclusive; 'critical' is an independent alert overlay driven by configured rules.
  moving/idle use the device-supplied speed when present, otherwise speed calculated from the last two recorded fixes
              (only when 5 s <= dt <= 10 min and distance >= 15 m). Otherwise the state is 'unknown' - never guessed.
  charging  only when the device/provider reported charging=true on a fix that is not offline.
  critical  = any configured alert rule fires (LOW_BATTERY, OUT_OF_SERVICE, optional OVERSPEED).
"""
import hashlib, hmac, json, logging, math, os, secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
import auditdb, permissions

log = logging.getLogger('fleet_gps')
MAX_BATCH = 100
MAX_FUTURE_SKEW = timedelta(seconds=120)
MAX_FIX_AGE = timedelta(days=7)          # buffered backlog from an offline tracker is accepted up to this age
MAX_TRACK_RANGE = timedelta(days=31)
MAX_TRACK_POINTS = 5000
MAX_LIVE_ROWS = 2000


# ---------- configuration (env, read per call so it can be tuned without code changes) ----------
def _f(name, default):
    try: return float(os.environ.get(name, default))
    except ValueError: return float(default)

def cfg():
    return {'live_s': _f('GPS_LIVE_SECONDS', 120), 'offline_s': _f('GPS_OFFLINE_SECONDS', 600), 'moving_kmh': _f('GPS_MOVING_KMH', 3),
            'critical_battery_pct': _f('FLEET_CRITICAL_BATTERY_PCT', 15), 'overspeed_kmh': _f('FLEET_OVERSPEED_KMH', 0)}   # 0 disables overspeed


# ---------- validation ----------
class Fix(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    time: datetime
    speed_kmh: float | None = Field(default=None, ge=0, le=400, allow_inf_nan=False)
    heading_deg: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000, allow_inf_nan=False)
    battery_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    charging: bool | None = None
    source: str | None = Field(default=None, pattern=r'^[a-z0-9:_-]{1,40}$')

    @field_validator('time')
    @classmethod
    def time_ok(cls, v):
        if v.tzinfo is None: raise ValueError('time must include a timezone, e.g. 2026-10-30T08:15:00Z')
        v = v.astimezone(timezone.utc); now = datetime.now(timezone.utc)
        if v > now + MAX_FUTURE_SKEW: raise ValueError('time is in the future')
        if v < now - MAX_FIX_AGE: raise ValueError('time is older than the accepted window')
        return v

    def lat_lon_ok(self):
        if self.lat == 0 and self.lon == 0: raise ValueError('coordinates (0,0) are treated as "no fix"')
        return self

class IngestBody(BaseModel):
    fixes: list[dict] = Field(min_length=1, max_length=MAX_BATCH)

def parse_fixes(raw: list[dict]):
    ok, rejected = [], []
    for i, item in enumerate(raw):
        try: ok.append(Fix.model_validate(item).lat_lon_ok())
        except ValidationError as e: rejected.append({'index': i, 'error': '; '.join(f"{'.'.join(map(str, x['loc'])) or 'fix'}: {x['msg']}" for x in e.errors())[:300]})
        except ValueError as e: rejected.append({'index': i, 'error': str(e)})
    return ok, rejected


# ---------- provider adapter interface ----------
class ProviderAdapter(Protocol):
    """Translate one provider webhook payload into [(external_device_id, Fix-dict), ...].
    Register an implementation in ADAPTERS['<name>']; the device must exist in fleet_gps_devices with external_id = that id."""
    def parse(self, payload: dict) -> list[tuple[str, dict]]: ...

class GenericAdapter:
    """Payload: {"positions":[{"device_id":"IMEI/ID","lat":..,"lon":..,"time":"ISO-8601","speed_kmh":..,"battery_pct":..,"charging":..}]}"""
    def parse(self, payload):
        out = []
        for p in payload.get('positions', []) if isinstance(payload, dict) else []:
            if isinstance(p, dict) and isinstance(p.get('device_id'), (str, int)):
                out.append((str(p['device_id']), {k: v for k, v in p.items() if k != 'device_id'}))
        return out

ADAPTERS: dict[str, ProviderAdapter] = {'generic': GenericAdapter()}


# ---------- pure helpers (unit-tested) ----------
def hash_token(t: str) -> str: return hashlib.sha256(t.encode()).hexdigest()

def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header: return False
    given = header.split('=', 1)[1] if header.startswith('sha256=') else header
    return hmac.compare_digest(hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), given.strip().lower())

def haversine_km(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))

def calc_speed(row):
    """km/h from the last two recorded fixes, or None when that cannot be done reliably."""
    if row.get('prev_time') is None or row.get('gps_time') is None: return None
    dt = (row['gps_time'] - row['prev_time']).total_seconds()
    if dt < 5 or dt > 600: return None
    d = haversine_km(row['prev_lat'], row['prev_lon'], row['latitude'], row['longitude'])
    if d * 1000 < 15: return 0.0
    v = d / (dt / 3600)
    return round(v, 1) if v <= 250 else None

def derive(row: dict, now: datetime, c: dict | None = None) -> dict:
    """Turn one joined vehicle+position row into the public live item. Deterministic given (row, now, config)."""
    c = c or cfg(); gt = row.get('gps_time')
    base = {'id': str(row['id']), 'registration_number': row['registration_number'], 'vehicle_type': row['vehicle_type'], 'make': row['make'], 'model': row['model'],
            'status': row['status'], 'customer_name': row['customer_name'], 'vin': row.get('vin'), 'has_device': bool(row.get('has_device')), 'driver_name': None}   # no driver in schema
    alerts = [{'code': 'OUT_OF_SERVICE', 'message': 'Vehicle is marked out of service'}] if row['status'] == 'OUT_OF_SERVICE' else []
    if gt is None:
        return {**base, 'position': None, 'freshness': 'none', 'state': 'no_gps', 'age_s': None, 'speed_kmh': None, 'speed_source': None, 'battery_pct': None, 'alerts': alerts, 'critical': bool(alerts)}
    age = max(0.0, (now - gt).total_seconds())
    fresh = 'live' if age <= c['live_s'] else 'delayed' if age <= c['offline_s'] else 'offline'
    usable = fresh != 'offline'
    speed, src = (row['speed_kmh'], 'device') if row.get('speed_kmh') is not None else (calc_speed(row), 'calculated')
    if speed is None: src = None
    if usable and row.get('battery_pct') is not None and row['battery_pct'] <= c['critical_battery_pct']:
        alerts.append({'code': 'LOW_BATTERY', 'message': f"Battery at {row['battery_pct']:.0f}% (threshold {c['critical_battery_pct']:.0f}%)"})
    if usable and c['overspeed_kmh'] > 0 and speed is not None and speed > c['overspeed_kmh']:
        alerts.append({'code': 'OVERSPEED', 'message': f"Speed {speed:.0f} km/h exceeds {c['overspeed_kmh']:.0f} km/h"})
    state = 'offline' if not usable else 'charging' if row.get('charging') is True else 'unknown' if speed is None else 'moving' if speed >= c['moving_kmh'] else 'idle'
    pos = {'lat': row['latitude'], 'lon': row['longitude'], 'gps_time': gt.isoformat(), 'received_at': row['received_at'].isoformat(), 'heading_deg': row.get('heading_deg'), 'accuracy_m': row.get('accuracy_m'), 'source': row['source']}
    return {**base, 'position': pos, 'freshness': fresh, 'state': state, 'age_s': round(age), 'speed_kmh': speed if usable else None, 'speed_source': src if usable else None,
            'battery_pct': row.get('battery_pct'), 'charging': row.get('charging'), 'alerts': alerts, 'critical': bool(alerts)}

def summarize(items: list[dict], any_device: bool) -> dict:
    s = {k: 0 for k in ('moving', 'idle', 'charging', 'offline', 'unknown', 'no_gps', 'critical')}
    for i in items:
        s[i['state']] += 1; s['critical'] += 1 if i['critical'] else 0
    live = sum(1 for i in items if i['freshness'] == 'live'); reported = sum(1 for i in items if i['freshness'] != 'none')
    s['total'] = len(items)
    s['data_status'] = 'unavailable' if not reported else 'current' if live else 'stale'   # unavailable: nothing has ever reported
    s['gps_configured'] = any_device
    return s


# ---------- ingest core ----------
UPSERT_POS = """insert into office_dashboard.fleet_vehicle_position(vehicle_id,latitude,longitude,gps_time,speed_kmh,heading_deg,accuracy_m,battery_pct,charging,source,device_id)
 values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
 on conflict (vehicle_id) do update set latitude=excluded.latitude, longitude=excluded.longitude, gps_time=excluded.gps_time, received_at=now(), speed_kmh=excluded.speed_kmh,
   heading_deg=excluded.heading_deg, accuracy_m=excluded.accuracy_m, battery_pct=excluded.battery_pct, charging=excluded.charging, source=excluded.source, device_id=excluded.device_id
 where excluded.gps_time > office_dashboard.fleet_vehicle_position.gps_time returning vehicle_id"""
INSERT_HIST = """insert into office_dashboard.fleet_gps_history(vehicle_id,latitude,longitude,gps_time,speed_kmh,battery_pct,source) values(%s,%s,%s,%s,%s,%s,%s)
 on conflict (vehicle_id,gps_time) do nothing returning id"""

def apply_fixes(c, vehicle_id, device_id, fixes: list[Fix], default_source: str):
    """Oldest-first. A fix only replaces the current position if it is strictly newer (enforced in SQL, so concurrent requests cannot regress it)."""
    r = {'accepted': 0, 'historical': 0, 'duplicate': 0}
    for f in sorted(fixes, key=lambda x: x.time):
        src = f.source or default_source
        if not c.execute(INSERT_HIST, (vehicle_id, f.lat, f.lon, f.time, f.speed_kmh, f.battery_pct, src)).fetchone(): r['duplicate'] += 1; continue
        if c.execute(UPSERT_POS, (vehicle_id, f.lat, f.lon, f.time, f.speed_kmh, f.heading_deg, f.accuracy_m, f.battery_pct, f.charging, src, device_id)).fetchone(): r['accepted'] += 1
        else: r['historical'] += 1   # older than the current position: kept as route history only
    return r


def build_ingest_router(dsn):
    r = APIRouter(prefix='/api/gps')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def deny(request, why):
        log.warning('gps ingest denied: %s ip=%s', why, request.client.host if request.client else '?')
        raise HTTPException(401, 'Invalid or missing GPS credentials.', headers={'WWW-Authenticate': 'Bearer'})

    @r.post('/ingest')
    def ingest(b: IngestBody, request: Request, authorization: str | None = Header(default=None)):
        """Device/app push. Header: Authorization: Bearer <device token>. The token fixes the vehicle; the payload cannot name a different one."""
        if not authorization or not authorization.lower().startswith('bearer '): deny(request, 'no bearer')
        th = hash_token(authorization[7:].strip())
        fixes, rejected = parse_fixes(b.fixes)
        if not fixes: raise HTTPException(422, {'message': 'No valid GPS fixes in request.', 'rejected': rejected})
        with db() as c:
            d = c.execute('select d.id, d.vehicle_id from office_dashboard.fleet_gps_devices d join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id where d.token_hash=%s and d.active and not v.archived', (th,)).fetchone()
            if not d: deny(request, 'unknown/revoked token')
            res = apply_fixes(c, d['vehicle_id'], d['id'], fixes, 'device')
            c.execute('update office_dashboard.fleet_gps_devices set last_seen_at=now() where id=%s', (d['id'],))
        log.info('gps ingest device=%s %s rejected=%d', d['id'], res, len(rejected))
        return {**res, 'rejected': rejected}

    @r.post('/webhook/{provider}')
    async def webhook(provider: str, request: Request, x_signature: str | None = Header(default=None)):
        """Provider push. Header X-Signature: sha256=<hex HMAC-SHA256 of the raw body using GPS_WEBHOOK_SECRET>. Devices are matched by external_id."""
        secret = os.environ.get('GPS_WEBHOOK_SECRET', '')
        if not secret: raise HTTPException(503, 'GPS provider webhook is not configured.')
        raw = await request.body()
        if len(raw) > 1_000_000: raise HTTPException(413, 'Payload too large.')
        if not verify_signature(secret, raw, x_signature): deny(request, 'bad signature')
        adapter = ADAPTERS.get(provider)
        if not adapter: raise HTTPException(404, 'Unknown GPS provider.')
        try: pairs = adapter.parse(json.loads(raw))
        except (ValueError, TypeError): raise HTTPException(422, 'Payload is not valid JSON for this provider.')
        by_dev: dict[str, list[dict]] = {}
        for ext, fx in pairs[:MAX_BATCH * 20]: by_dev.setdefault(ext, []).append(fx)
        total = {'accepted': 0, 'historical': 0, 'duplicate': 0}; rejected = []; unknown = []
        with db() as c:
            for ext, raws in by_dev.items():
                d = c.execute('select d.id, d.vehicle_id from office_dashboard.fleet_gps_devices d join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id where d.external_id=%s and d.active and not v.archived', (ext,)).fetchone()
                if not d: unknown.append(ext); continue
                fixes, rej = parse_fixes(raws[:MAX_BATCH]); rejected += [{'device_id': ext, **x} for x in rej]
                if fixes:
                    for k, v in apply_fixes(c, d['vehicle_id'], d['id'], fixes, f'provider:{provider}').items(): total[k] += v
                    c.execute('update office_dashboard.fleet_gps_devices set last_seen_at=now() where id=%s', (d['id'],))
        return {**total, 'rejected': rejected, 'unknown_devices': unknown[:50]}
    return r


# ---------- dashboard (session-authenticated) ----------
class DeviceIn(BaseModel):
    vehicle_id: str
    label: str = Field(min_length=1, max_length=120)
    external_id: str | None = Field(default=None, max_length=120)
    @field_validator('label', 'external_id', mode='before')
    @classmethod
    def trim(cls, v): return (v.strip() or None) if isinstance(v, str) else v

LIVE_SQL = """select v.id, v.registration_number, v.vehicle_type, v.make, v.model, v.status, v.customer_name, v.vin,
  p.latitude, p.longitude, p.gps_time, p.received_at, p.speed_kmh, p.heading_deg, p.accuracy_m, p.battery_pct, p.charging, p.source,
  pr.latitude prev_lat, pr.longitude prev_lon, pr.gps_time prev_time,
  exists(select 1 from office_dashboard.fleet_gps_devices d where d.vehicle_id=v.id and d.active) has_device
 from office_dashboard.fleet_vehicles v
 left join office_dashboard.fleet_vehicle_position p on p.vehicle_id=v.id
 left join lateral (select h.latitude, h.longitude, h.gps_time from office_dashboard.fleet_gps_history h where h.vehicle_id=v.id and p.gps_time is not null and h.gps_time < p.gps_time order by h.gps_time desc limit 1) pr on true
 where not v.archived order by v.registration_number limit %s"""

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/fleet')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def perm(action, write=False):   # same contract as fleetapi.perm
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s['role'], f'fleet.{action}'):
                audit.write('permission_denied', s['id'], None, permission=f'fleet.{action}', role=s['role'])
                raise HTTPException(403, 'You do not have permission to ' + ('view fleet vehicles' if action == 'read' else 'manage GPS devices') + '.')
            return s
        return dep

    @r.get('/live')
    def live(s=Depends(perm('read'))):
        now = datetime.now(timezone.utc); c_ = cfg()
        with db() as c:
            rows = c.execute(LIVE_SQL, (MAX_LIVE_ROWS,)).fetchall()
            any_dev = c.execute('select exists(select 1 from office_dashboard.fleet_gps_devices where active) e').fetchone()['e']
        items = [derive(x, now, c_) for x in rows]
        latest = max((x['position']['gps_time'] for x in items if x['position']), default=None)
        return {'server_time': now.isoformat(), 'latest_gps_time': latest, 'summary': summarize(items, any_dev), 'items': items, 'truncated': len(rows) >= MAX_LIVE_ROWS,
                'thresholds': {'live_s': c_['live_s'], 'offline_s': c_['offline_s'], 'moving_kmh': c_['moving_kmh'], 'critical_battery_pct': c_['critical_battery_pct'], 'overspeed_kmh': c_['overspeed_kmh']}}

    @r.get('/vehicles/{vid}/track')
    def track(vid: str, start: datetime | None = None, end: datetime | None = None, s=Depends(perm('read'))):
        end = (end or datetime.now(timezone.utc)); start = start or end - timedelta(hours=6)
        end, start = (end if end.tzinfo else end.replace(tzinfo=timezone.utc)), (start if start.tzinfo else start.replace(tzinfo=timezone.utc))
        if start >= end: raise HTTPException(422, 'Start must be before end.')
        if end - start > MAX_TRACK_RANGE: raise HTTPException(422, 'Range is limited to 31 days.')
        try:
            with db() as c:
                if not c.execute('select 1 from office_dashboard.fleet_vehicles where id=%s and not archived', (vid,)).fetchone(): raise HTTPException(404, 'Vehicle not found.')
                rows = c.execute('select latitude lat, longitude lon, gps_time, speed_kmh, source from office_dashboard.fleet_gps_history where vehicle_id=%s and gps_time>=%s and gps_time<=%s order by gps_time desc limit %s',
                                 (vid, start, end, MAX_TRACK_POINTS + 1)).fetchall()
        except psycopg.errors.InvalidTextRepresentation: raise HTTPException(404, 'Vehicle not found.')
        trunc = len(rows) > MAX_TRACK_POINTS; rows = list(reversed(rows[:MAX_TRACK_POINTS]))
        return {'vehicle_id': vid, 'start': start.isoformat(), 'end': end.isoformat(), 'truncated': trunc, 'recorded': True,
                'points': [{'lat': x['lat'], 'lon': x['lon'], 'time': x['gps_time'].isoformat(), 'speed_kmh': x['speed_kmh'], 'source': x['source']} for x in rows]}

    @r.get('/gps/devices')
    def devices(s=Depends(perm('write'))):
        with db() as c:
            rows = c.execute('select d.id, d.vehicle_id, v.registration_number, d.label, d.external_id, d.active, d.last_seen_at, d.created_at from office_dashboard.fleet_gps_devices d join office_dashboard.fleet_vehicles v on v.id=d.vehicle_id order by d.active desc, d.created_at desc limit 500').fetchall()
        return {'items': rows, 'webhook_configured': bool(os.environ.get('GPS_WEBHOOK_SECRET')), 'providers': sorted(ADAPTERS)}

    @r.post('/gps/devices', status_code=201)
    def create_device(b: DeviceIn, s=Depends(perm('write', True))):
        token = 'ivd_' + secrets.token_urlsafe(32)
        try:
            with db() as c:
                if not c.execute('select 1 from office_dashboard.fleet_vehicles where id=%s and not archived', (b.vehicle_id,)).fetchone(): raise HTTPException(404, 'Vehicle not found.')
                row = c.execute('insert into office_dashboard.fleet_gps_devices(vehicle_id,label,external_id,token_hash,created_by) values(%s,%s,%s,%s,%s) returning id, vehicle_id, label, external_id, active, created_at',
                                (b.vehicle_id, b.label, b.external_id, hash_token(token), s['id'])).fetchone()
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='fleet_gps_device', entity_id=row['id'], after={'vehicle_id': b.vehicle_id, 'label': b.label})
        except psycopg.errors.InvalidTextRepresentation: raise HTTPException(404, 'Vehicle not found.')
        except psycopg.errors.UniqueViolation: raise HTTPException(409, 'A device with this provider device ID is already active.')
        audit.write('fleet_gps_device_created', s['id'], None, device_id=str(row['id']))
        return {**row, 'token': token, 'token_notice': 'Store this token now. It is not shown again.'}

    @r.post('/gps/devices/{did}/revoke')
    def revoke_device(did: str, s=Depends(perm('write', True))):
        try:
            with db() as c:
                row = c.execute('update office_dashboard.fleet_gps_devices set active=false, revoked_at=now() where id=%s and active returning id, vehicle_id', (did,)).fetchone()
                if not row: raise HTTPException(404, 'Active device not found.')
                auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='update', entity_type='fleet_gps_device', entity_id=did, after={'active': False})
        except psycopg.errors.InvalidTextRepresentation: raise HTTPException(404, 'Active device not found.')
        audit.write('fleet_gps_device_revoked', s['id'], None, device_id=did)
        return {'ok': True}
    return r
