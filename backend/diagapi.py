"""EVcare.AI Diagnostics API (db/012).

Honesty rules (by design):
  * A fault exists in the database ONLY if (a) an authorised person recorded it, or (b) a real call to the configured EVcare.AI service returned it.
    Nothing is generated, simulated or inferred here.
  * If EVCARE_AI_URL / EVCARE_AI_API_KEY are not set, /status says configured=false, the run endpoint refuses, and the UI shows "Not configured".
  * Every call to the AI service (success or failure) is stored in diagnostic_runs so the history shows what really happened.

!! ASSUMED AI CONTRACT !!  I was not given EVcare.AI's real API, so `call_ai` / `parse_ai_faults` implement this assumption (edit those two functions only):
      POST {EVCARE_AI_URL}   Authorization: Bearer {EVCARE_AI_API_KEY}   JSON body: {"vehicle": {registration_number, vin, make, model, battery_capacity_kwh, odometer_km},
                                                                                       "telemetry": [{metric, value, unit, recorded_at}]}   <- "telemetry" only when the user ticks "include recent telemetry"
      200 JSON reply:        {"faults": [{"id"?: str, "code": str, "description"?: str, "severity": INFO|LOW|MEDIUM|HIGH|CRITICAL, "detected_at": ISO-8601}]}
Customer names, notes and ALL location/GPS metrics are NEVER sent to the service (telemetry = real readings received in the last 24 h, nothing else). The API key is never returned to the browser or written to logs.
Permissions: diagnostics.read / write / export; creating a ticket from a fault also needs tickets.write."""
import json, os, re, uuid
from datetime import date, datetime, timedelta, timezone
from urllib import error as urlerror, request as urlrequest
from urllib.parse import urlparse
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, locationpolicy as LP, permissions
from opscommon import blank, like, make_perm, trim

SEVERITIES = ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
SEV_ALIASES = {'INFORMATIONAL': 'INFO', 'MINOR': 'LOW', 'MODERATE': 'MEDIUM', 'MAJOR': 'HIGH', 'SEVERE': 'CRITICAL', **{s: s for s in SEVERITIES}}
TICKET_PRIORITY = {'CRITICAL': 'URGENT', 'HIGH': 'HIGH', 'MEDIUM': 'MEDIUM', 'LOW': 'LOW', 'INFO': 'LOW'}
CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,39}$')
MAX_REPLY_BYTES = 1_000_000


def ai_settings():
    url, key = (os.getenv('EVCARE_AI_URL') or '').strip(), (os.getenv('EVCARE_AI_API_KEY') or '').strip()
    return url, key
def ai_configured() -> bool:
    url, key = ai_settings(); return bool(url and key)
def _utc(d: datetime) -> datetime: return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_ai_faults(data):
    """Pure function: validate the AI reply. Returns (faults, skipped). An item missing a code, a known severity or a real timestamp is skipped, never guessed."""
    faults, skipped = [], 0
    items = data.get('faults') if isinstance(data, dict) else None
    if not isinstance(items, list): raise ValueError('Unexpected response format from the AI service.')
    for it in items[:500]:
        try:
            code = ' '.join(str(it['code']).split()).upper(); sev = SEV_ALIASES.get(str(it['severity']).strip().upper())
            at = _utc(datetime.fromisoformat(str(it['detected_at']).replace('Z', '+00:00')))
            if not CODE.match(code) or not sev or at > datetime.now(timezone.utc) + timedelta(minutes=5): raise ValueError
        except (KeyError, ValueError, TypeError): skipped += 1; continue
        desc = str(it.get('description') or '').strip()[:2000]
        ref = str(it['id']).strip()[:120] if it.get('id') not in (None, '') else f'{code}@{at.isoformat()}'
        faults.append({'code': code, 'description': desc, 'severity': sev, 'detected_at': at, 'external_ref': ref})
    return faults, skipped + max(0, len(items) - 500)


def call_ai(vehicle: dict, telemetry: list | None = None):
    """The ONLY place that talks to EVcare.AI. Returns the parsed JSON reply or raises RuntimeError with a safe (secret-free) message."""
    url, key = ai_settings(); u = urlparse(url)
    if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1')): raise RuntimeError('EVCARE_AI_URL must be an https URL.')
    payload = {'vehicle': {k: (float(v) if k in ('battery_capacity_kwh', 'odometer_km') and v is not None else v) for k, v in vehicle.items()}}
    if telemetry: payload['telemetry'] = telemetry
    body = json.dumps(payload).encode()
    req = urlrequest.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}', 'Accept': 'application/json'})
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            raw = resp.read(MAX_REPLY_BYTES + 1)
    except urlerror.HTTPError as e: raise RuntimeError(f'The AI service answered with HTTP {e.code}.')
    except (urlerror.URLError, TimeoutError, OSError): raise RuntimeError('Could not reach the AI service.')
    if len(raw) > MAX_REPLY_BYTES: raise RuntimeError('The AI service reply was too large.')
    try: return json.loads(raw)
    except ValueError: raise RuntimeError('The AI service did not return valid JSON.')


class FaultIn(BaseModel):
    fault_code: str = Field(min_length=1, max_length=40)
    description: str = Field(default='', max_length=2000)
    severity: str
    detected_at: datetime
    @field_validator('fault_code', 'description', mode='before')
    @classmethod
    def _t(cls, v): return ' '.join(v.split()) if isinstance(v, str) else v
    @field_validator('fault_code')
    @classmethod
    def _c(cls, v):
        if not CODE.match(v): raise ValueError('Fault code may contain letters, digits and . _ : / - only.')
        return v.upper()
    @field_validator('severity', mode='before')
    @classmethod
    def _s(cls, v):
        s = SEV_ALIASES.get(str(v).strip().upper())
        if not s: raise ValueError('Severity must be one of ' + ', '.join(SEVERITIES) + '.')
        return s
    @field_validator('detected_at')
    @classmethod
    def _d(cls, v):
        v = _utc(v)
        if v > datetime.now(timezone.utc) + timedelta(minutes=5): raise ValueError('Detection time cannot be in the future.')
        if v.year < 2000: raise ValueError('Detection time is not valid.')
        return v


class RunIn(BaseModel):
    include_telemetry: bool = False


class FaultStatusIn(BaseModel):
    status: str
    @field_validator('status')
    @classmethod
    def _s(cls, v):
        if v not in ('ACTIVE', 'RESOLVED'): raise ValueError('Status must be ACTIVE or RESOLVED.')
        return v


def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/diagnostics')
    perm = make_perm(session, csrf, audit, 'diagnostics')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)

    def get_vehicle(c, vid):
        try: row = c.execute('select * from office_dashboard.fleet_vehicles where id=%s and not archived', (vid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Vehicle not found.')
        return row

    @r.get('/status')
    def status(s=Depends(perm('read'))):
        return {'ai_configured': ai_configured(), 'message': None if ai_configured() else 'Not configured: set EVCARE_AI_URL and EVCARE_AI_API_KEY on the server to enable AI diagnostics.',
                'can_write': permissions.can(s['role'], 'diagnostics.write'), 'can_export': permissions.can(s['role'], 'diagnostics.export'), 'can_create_ticket': permissions.can(s['role'], 'tickets.write')}

    @r.get('/vehicles')
    def vehicles(q: str = '', with_faults: bool = False, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        w, a = ['not v.archived'], []
        if q.strip(): w.append("(v.registration_number ilike %s or v.make ilike %s or v.model ilike %s or coalesce(v.vin,'') ilike %s or coalesce(v.customer_name,'') ilike %s)"); a += [like(q)] * 5
        if with_faults: w.append("exists (select 1 from office_dashboard.diagnostic_faults f where f.vehicle_id=v.id and f.status='ACTIVE')")
        where = ' and '.join(w)
        with db() as c:
            total = c.execute(f'select count(*)::int n from office_dashboard.fleet_vehicles v where {where}', a).fetchone()['n']
            rows = c.execute("select v.id, v.registration_number, v.make, v.model, v.vehicle_type, v.status, v.customer_name,"
                             " (select count(*) from office_dashboard.diagnostic_faults f where f.vehicle_id=v.id and f.status='ACTIVE')::int as active_faults,"
                             " (select max(f.detected_at) from office_dashboard.diagnostic_faults f where f.vehicle_id=v.id) as last_fault_at"
                             f" from office_dashboard.fleet_vehicles v where {where} order by active_faults desc, v.registration_number limit %s offset %s", [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit}

    @r.get('/vehicles/{vid}')
    def vehicle_history(vid: str, status: str = '', severity: str = '', date_from: date | None = None, date_to: date | None = None, s=Depends(perm('read'))):
        w, a = ['f.vehicle_id=%s'], [vid]
        if date_from and date_to and date_from > date_to: raise HTTPException(422, 'Start date must be on or before end date.')
        if date_from: w.append('f.detected_at >= %s'); a.append(date_from)
        if date_to: w.append('f.detected_at < %s'); a.append(date_to + timedelta(days=1))
        if status:
            if status not in ('ACTIVE', 'RESOLVED'): raise HTTPException(422, 'Unknown status.')
            w.append('f.status=%s'); a.append(status)
        if severity:
            if severity not in SEVERITIES: raise HTTPException(422, 'Unknown severity.')
            w.append('f.severity=%s'); a.append(severity)
        with db() as c:
            v = get_vehicle(c, vid)
            faults = c.execute(f"select f.id, f.fault_code, f.description, f.severity, f.detected_at, f.source, f.status, f.resolved_at, f.ticket_id, t.ticket_number from office_dashboard.diagnostic_faults f"
                               f" left join office_dashboard.service_tickets t on t.id=f.ticket_id where {' and '.join(w)} order by f.detected_at desc, f.id desc limit 500", a).fetchall()
            runs = c.execute('select id, outcome, message, fault_count, created_at from office_dashboard.diagnostic_runs where vehicle_id=%s order by created_at desc limit 20', (vid,)).fetchall()
        role = s['role']
        return {'vehicle': {k: v[k] for k in ('id', 'registration_number', 'make', 'model', 'vehicle_type', 'status', 'customer_name')}, 'faults': faults, 'runs': runs, 'ai_configured': ai_configured(),
                'can_write': permissions.can(role, 'diagnostics.write'), 'can_create_ticket': permissions.can(role, 'diagnostics.write') and permissions.can(role, 'tickets.write')}

    @r.get('/faults')
    def all_faults(vehicle_id: str = '', status: str = '', severity: str = '', source: str = '', date_from: date | None = None, date_to: date | None = None, q: str = '',
                   page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('read'))):
        """Diagnostic history across vehicles: filter by vehicle, date range (detected time), fault status, severity and source."""
        w, a = ['not v.archived'], []
        if vehicle_id.strip(): w.append('f.vehicle_id::text=%s'); a.append(vehicle_id.strip())
        if status:
            if status not in ('ACTIVE', 'RESOLVED'): raise HTTPException(422, 'Unknown status.')
            w.append('f.status=%s'); a.append(status)
        if severity:
            if severity not in SEVERITIES: raise HTTPException(422, 'Unknown severity.')
            w.append('f.severity=%s'); a.append(severity)
        if source:
            if source not in ('MANUAL', 'EVCARE_AI', 'IOT'): raise HTTPException(422, 'Unknown source.')
            w.append('f.source=%s'); a.append(source)
        if date_from and date_to and date_from > date_to: raise HTTPException(422, 'Start date must be on or before end date.')
        if date_from: w.append('f.detected_at >= %s'); a.append(date_from)
        if date_to: w.append('f.detected_at < %s'); a.append(date_to + timedelta(days=1))
        if q.strip(): w.append("(f.fault_code ilike %s or f.description ilike %s or v.registration_number ilike %s)"); a += [like(q)] * 3
        where = ' and '.join(w); frm = 'from office_dashboard.diagnostic_faults f join office_dashboard.fleet_vehicles v on v.id=f.vehicle_id left join office_dashboard.service_tickets t on t.id=f.ticket_id'
        with db() as c:
            total = c.execute(f'select count(*)::int n {frm} where {where}', a).fetchone()['n']
            rows = c.execute(f'select f.id, f.vehicle_id, v.registration_number, f.fault_code, f.description, f.severity, f.detected_at, f.source, f.status, f.resolved_at, f.ticket_id, t.ticket_number {frm} where {where}'
                             ' order by f.detected_at desc, f.id desc limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit}

    @r.post('/vehicles/{vid}/faults', status_code=201)
    def record_fault(vid: str, b: FaultIn, s=Depends(perm('write', True))):
        with db() as c:
            get_vehicle(c, vid)
            row = c.execute("insert into office_dashboard.diagnostic_faults(vehicle_id,fault_code,description,severity,detected_at,source,recorded_by) values(%s,%s,%s,%s,%s,'MANUAL',%s) returning *",
                            (vid, b.fault_code, b.description, b.severity, b.detected_at, s['id'])).fetchone()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='diagnostic_fault', entity_id=row['id'], after={'vehicle_id': vid, 'fault_code': b.fault_code, 'severity': b.severity, 'source': 'MANUAL'})
        audit.write('diagnostic_fault_recorded', s['id'], None, vehicle_id=vid)
        return row

    @r.patch('/faults/{fid}')
    def set_status(fid: str, b: FaultStatusIn, s=Depends(perm('write', True))):
        with db() as c:
            try: old = c.execute('select * from office_dashboard.diagnostic_faults where id=%s for update', (int(fid),)).fetchone()
            except ValueError: old = None
            if not old: raise HTTPException(404, 'Fault not found.')
            if old['status'] == b.status: return old
            row = c.execute("update office_dashboard.diagnostic_faults set status=%s, resolved_at=case when %s='RESOLVED' then now() else null end where id=%s returning *", (b.status, b.status, old['id'])).fetchone()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='status_change', entity_type='diagnostic_fault', entity_id=old['id'], before={'status': old['status']}, after={'status': b.status})
        audit.write('diagnostic_fault_status', s['id'], None, fault_id=fid, status=b.status)
        return row

    @r.post('/faults/{fid}/ticket', status_code=201)
    def make_ticket(fid: str, s=Depends(perm('write', True))):
        """Create a service ticket from a recorded fault and link them. One ticket per fault."""
        if not permissions.can(s['role'], 'tickets.write'): raise HTTPException(403, 'You do not have permission to create service tickets.')
        with db() as c:
            try: f = c.execute('select * from office_dashboard.diagnostic_faults where id=%s for update', (int(fid),)).fetchone()
            except ValueError: f = None
            if not f: raise HTTPException(404, 'Fault not found.')
            if f['ticket_id']: raise HTTPException(409, 'A service ticket was already created for this fault.')
            v = get_vehicle(c, f['vehicle_id'])
            title = f"Fault {f['fault_code']}" + (f": {f['description']}" if f['description'] else '')
            desc = (f"Created from a diagnostic fault.\nVehicle: {v['registration_number']} ({v['make']} {v['model']})\nFault code: {f['fault_code']}\nSeverity: {f['severity']}\n"
                    f"Detected: {f['detected_at'].isoformat()}\nSource: {f['source']}\n\n{f['description']}").strip()
            number = 'IVT-' + uuid.uuid4().hex[:10].upper()
            t = c.execute('insert into office_dashboard.service_tickets(ticket_number,title,description,customer_name,vehicle_reference,priority,category,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                          (number, title[:180], desc[:5000], v['customer_name'], v['registration_number'], TICKET_PRIORITY[f['severity']], 'GENERAL', s['id'])).fetchone()
            c.execute('update office_dashboard.diagnostic_faults set ticket_id=%s where id=%s', (t['id'], f['id']))
            c.execute("insert into office_dashboard.service_ticket_events(ticket_id,event_type,actor_id,actor_name,detail) values(%s,'created',%s,%s,%s)",
                      (t['id'], s['id'], s.get('name'), Jsonb({'priority': t['priority'], 'category': 'GENERAL', 'from_fault_id': f['id']}, dumps=auditdb._dumps)))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create_ticket_from_fault', entity_type='diagnostic_fault', entity_id=f['id'], after={'ticket_id': t['id'], 'ticket_number': number})
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='service_ticket', entity_id=t['id'], after={'status': t['status'], 'priority': t['priority'], 'category': t['category']})
        audit.write('service_ticket_created', s['id'], None, ticket_id=str(t['id']), from_fault=fid)
        return {'ticket_id': t['id'], 'ticket_number': t['ticket_number'], 'priority': t['priority']}

    @r.post('/vehicles/{vid}/run')
    def run_ai(vid: str, b: RunIn | None = None, s=Depends(perm('write', True))):
        if not ai_configured(): raise HTTPException(503, 'Not configured: EVcare.AI is not set up on this server (EVCARE_AI_URL / EVCARE_AI_API_KEY).')
        with db() as c: v = get_vehicle(c, vid)
        payload = {k: v[k] for k in ('registration_number', 'vin', 'make', 'model', 'battery_capacity_kwh', 'odometer_km')}
        telemetry = []
        if b and b.include_telemetry:
            if not permissions.can(s['role'], 'iot.read'): raise HTTPException(403, 'You do not have permission to include telemetry.')
            w, a = ['r.vehicle_id=%s', "r.recorded_at > now() - interval '24 hours'", 'r.metric !~ %s'], [vid, LP.location_pattern(os.getenv('IOT_EXTRA_LOCATION_METRICS', ''))]   # location is never sent to the AI service
            sc = LP.vehicle_scope(s['role'], s['id'], 'r.vehicle_id')                                                                                                   # technicians: assigned vehicles only
            if sc: w.append(sc[0]); a += sc[1]
            with db() as c:
                telemetry = [{'metric': x['metric'], 'value': x['value'], 'unit': x['unit'], 'recorded_at': x['recorded_at'].isoformat()} for x in c.execute(
                    'select distinct on (r.device_id, r.metric) r.metric, r.value, r.unit, r.recorded_at from office_dashboard.iot_readings r join office_dashboard.iot_devices d on d.id=r.device_id'
                    f" where not d.archived and {' and '.join(w)} order by r.device_id, r.metric, r.recorded_at desc", a).fetchall()]
        err, faults, skipped = None, [], 0
        try: faults, skipped = parse_ai_faults(call_ai(payload, telemetry))      # network call happens OUTSIDE any database transaction
        except RuntimeError as e: err = str(e)
        except ValueError as e: err = str(e)
        with db() as c:
            inserted = 0
            if not err:
                for f in faults:
                    cur = c.execute("insert into office_dashboard.diagnostic_faults(vehicle_id,fault_code,description,severity,detected_at,source,external_ref,recorded_by) values(%s,%s,%s,%s,%s,'EVCARE_AI',%s,%s)"
                                    " on conflict (vehicle_id, source, external_ref) where external_ref is not null do nothing", (vid, f['code'], f['description'], f['severity'], f['detected_at'], f['external_ref'], s['id']))
                    inserted += cur.rowcount
            msg = err or (f'{inserted} new fault(s), {len(faults) - inserted} already recorded' + (f', {skipped} item(s) skipped because they were incomplete' if skipped else '') + (f'; {len(telemetry)} recent telemetry reading(s) were sent' if telemetry else ''))
            c.execute('insert into office_dashboard.diagnostic_runs(vehicle_id,requested_by,outcome,message,fault_count) values(%s,%s,%s,%s,%s)', (vid, s['id'], 'FAILED' if err else 'SUCCESS', msg[:1000], inserted))
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='run_diagnostic', entity_type='fleet_vehicle', entity_id=vid, outcome='failed' if err else 'success', after={'new_faults': inserted, 'skipped': skipped, 'telemetry_sent': len(telemetry)})
        audit.write('diagnostic_run', s['id'], None, vehicle_id=vid, ok=not err)
        if err: raise HTTPException(502, err)
        return {'new_faults': inserted, 'already_recorded': len(faults) - inserted, 'skipped': skipped, 'telemetry_sent': len(telemetry), 'message': msg}

    @r.get('/export')
    def export(vehicle_id: str = '', severity: str = '', status: str = '', date_from: date | None = None, date_to: date | None = None, s=Depends(perm('export'))):
        w, a = ['true'], []
        if date_from and date_to and date_from > date_to: raise HTTPException(422, 'Start date must be on or before end date.')
        if date_from: w.append('f.detected_at >= %s'); a.append(date_from)
        if date_to: w.append('f.detected_at < %s'); a.append(date_to + timedelta(days=1))
        if vehicle_id: w.append('f.vehicle_id::text=%s'); a.append(vehicle_id)
        if severity:
            if severity not in SEVERITIES: raise HTTPException(422, 'Unknown severity.')
            w.append('f.severity=%s'); a.append(severity)
        if status:
            if status not in ('ACTIVE', 'RESOLVED'): raise HTTPException(422, 'Unknown status.')
            w.append('f.status=%s'); a.append(status)
        with db() as c:
            rows = c.execute(f"select f.*, v.registration_number, t.ticket_number from office_dashboard.diagnostic_faults f join office_dashboard.fleet_vehicles v on v.id=f.vehicle_id"
                             f" left join office_dashboard.service_tickets t on t.id=f.ticket_id where {' and '.join(w)} order by f.detected_at desc limit 10000", a).fetchall()
            auditdb.record(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='diagnostic_fault', after={'rows': len(rows)})
        return csvutil.csv_response('diagnostic-faults.csv', ['Vehicle', 'Fault code', 'Description', 'Severity', 'Detected at', 'Source', 'Status', 'Resolved at', 'Ticket'],
                                    [[x['registration_number'], x['fault_code'], x['description'], x['severity'], x['detected_at'], x['source'], x['status'], x['resolved_at'], x['ticket_number']] for x in rows])
    return r
