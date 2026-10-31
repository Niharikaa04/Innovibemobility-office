import sys, types, os
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
for m in ('auditdb', 'permissions'): sys.modules.setdefault(m, types.ModuleType(m))   # project modules, stubbed for unit tests
import pytest, fleet_gps as g

NOW = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
def row(**k):
    b = dict(id='v1', registration_number='AP 31 AB 1234', vehicle_type='CAR', make='M', model='X', status='ACTIVE', customer_name=None, has_device=True,
             latitude=17.7, longitude=83.3, gps_time=NOW - timedelta(seconds=30), received_at=NOW, speed_kmh=None, heading_deg=None, accuracy_m=None,
             battery_pct=None, charging=None, source='device', prev_lat=None, prev_lon=None, prev_time=None)
    b.update(k); return b
C = g.cfg()
def iso(dt): return dt.isoformat()

# --- validation
def fx(**k):
    b = dict(lat=17.7, lon=83.3, time=iso(datetime.now(timezone.utc) - timedelta(seconds=5))); b.update(k); return b
@pytest.mark.parametrize('bad', [dict(lat=91), dict(lat=-90.1), dict(lon=181), dict(lat='nan'), dict(speed_kmh=-1), dict(speed_kmh=401), dict(battery_pct=101),
    dict(heading_deg=360), dict(time='2026-10-30T08:00:00'), dict(time=iso(datetime.now(timezone.utc) + timedelta(hours=1))),
    dict(time=iso(datetime.now(timezone.utc) - timedelta(days=30))), dict(lat=0, lon=0), dict(source='BAD SOURCE!'), dict(lat='abc')])
def test_rejects_invalid(bad):
    ok, rej = g.parse_fixes([fx(**bad)]); assert not ok and len(rej) == 1
def test_accepts_valid_and_partial_batch():
    ok, rej = g.parse_fixes([fx(), fx(lat=200), fx(speed_kmh=40, battery_pct=55, charging=False)]); assert len(ok) == 2 and rej[0]['index'] == 1
def test_epoch_timestamp_is_utc():
    ok, _ = g.parse_fixes([fx(time=int(datetime.now(timezone.utc).timestamp()))]); assert ok and ok[0].time.tzinfo is not None

# --- auth helpers
def test_signature():
    import hmac, hashlib
    body = b'{"a":1}'; sig = hmac.new(b'k', body, hashlib.sha256).hexdigest()
    assert g.verify_signature('k', body, 'sha256=' + sig) and g.verify_signature('k', body, sig.upper())
    assert not g.verify_signature('k', body, 'sha256=' + '0' * 64) and not g.verify_signature('', body, sig) and not g.verify_signature('k', body, None)
def test_token_hash_stable_not_plain():
    assert g.hash_token('ivd_x') == g.hash_token('ivd_x') and 'ivd_x' not in g.hash_token('ivd_x') and len(g.hash_token('a')) == 64

# --- status derivation
def test_no_gps():
    d = g.derive(row(gps_time=None, latitude=None, longitude=None), NOW, C); assert d['state'] == 'no_gps' and d['position'] is None and d['freshness'] == 'none'
def test_never_invents_driver_or_values():
    d = g.derive(row(), NOW, C); assert d['driver_name'] is None and d['speed_kmh'] is None and d['battery_pct'] is None and d['state'] == 'unknown'
def test_moving_idle_from_device_speed():
    assert g.derive(row(speed_kmh=25), NOW, C)['state'] == 'moving'
    assert g.derive(row(speed_kmh=0.5), NOW, C)['state'] == 'idle'
def test_calculated_speed():
    # ~1.11 km north in 60 s = ~66.7 km/h
    d = g.derive(row(prev_lat=17.69, prev_lon=83.3, prev_time=NOW - timedelta(seconds=90), gps_time=NOW - timedelta(seconds=30), latitude=17.7), NOW, C)
    assert d['state'] == 'moving' and d['speed_source'] == 'calculated' and 60 < d['speed_kmh'] < 72
def test_calculated_speed_rejected_when_gap_large_or_jitter():
    big = g.derive(row(prev_lat=17.69, prev_lon=83.3, prev_time=NOW - timedelta(hours=2)), NOW, C); assert big['state'] == 'unknown'
    jit = g.derive(row(prev_lat=17.7, prev_lon=83.30002, prev_time=NOW - timedelta(seconds=40)), NOW, C); assert jit['state'] == 'idle' and jit['speed_kmh'] == 0
def test_freshness_thresholds():
    assert g.derive(row(speed_kmh=30, gps_time=NOW - timedelta(seconds=100)), NOW, C)['freshness'] == 'live'
    assert g.derive(row(speed_kmh=30, gps_time=NOW - timedelta(seconds=300)), NOW, C)['freshness'] == 'delayed'
    off = g.derive(row(speed_kmh=30, gps_time=NOW - timedelta(seconds=700)), NOW, C)
    assert off['freshness'] == 'offline' and off['state'] == 'offline' and off['speed_kmh'] is None and off['position'] is not None   # last known position kept
def test_charging_only_when_reported_and_not_offline():
    assert g.derive(row(charging=True, speed_kmh=0), NOW, C)['state'] == 'charging'
    assert g.derive(row(charging=None, speed_kmh=0), NOW, C)['state'] == 'idle'
    assert g.derive(row(charging=True, gps_time=NOW - timedelta(hours=1)), NOW, C)['state'] == 'offline'
def test_critical_rules():
    assert g.derive(row(battery_pct=10), NOW, C)['critical'] and g.derive(row(battery_pct=10), NOW, C)['alerts'][0]['code'] == 'LOW_BATTERY'
    assert not g.derive(row(battery_pct=80), NOW, C)['critical']
    assert g.derive(row(status='OUT_OF_SERVICE'), NOW, C)['critical']
    assert g.derive(row(status='OUT_OF_SERVICE', gps_time=None, latitude=None, longitude=None), NOW, C)['critical']
    assert not g.derive(row(battery_pct=5, gps_time=NOW - timedelta(hours=1)), NOW, C)['critical']   # stale battery reading is not trusted
    assert g.derive(row(speed_kmh=90), NOW, {**C, 'overspeed_kmh': 60})['alerts'][0]['code'] == 'OVERSPEED' and not g.derive(row(speed_kmh=90), NOW, C)['critical']
def test_future_gps_time_clamped():
    assert g.derive(row(gps_time=NOW + timedelta(seconds=60), speed_kmh=10), NOW, C)['age_s'] == 0

def test_summary_consistency():
    items = [g.derive(row(id=str(i), **k), NOW, C) for i, k in enumerate([dict(speed_kmh=30), dict(speed_kmh=0), dict(charging=True), dict(gps_time=NOW - timedelta(hours=1)),
             dict(gps_time=None, latitude=None, longitude=None), dict(speed_kmh=20, battery_pct=5)])]
    s = g.summarize(items, True)
    assert (s['moving'], s['idle'], s['charging'], s['offline'], s['no_gps'], s['critical'], s['total']) == (2, 1, 1, 1, 1, 1, 6)
    assert s['moving'] + s['idle'] + s['charging'] + s['offline'] + s['unknown'] + s['no_gps'] == s['total'] and s['data_status'] == 'current'
def test_data_status():
    assert g.summarize([g.derive(row(gps_time=None, latitude=None, longitude=None), NOW, C)], False)['data_status'] == 'unavailable'
    assert g.summarize([g.derive(row(gps_time=NOW - timedelta(hours=1)), NOW, C)], True)['data_status'] == 'stale'

# --- apply_fixes ordering semantics (fake connection mimicking the SQL contract)
class FakeConn:
    def __init__(self): self.hist = set(); self.pos = None
    def execute(self, sql, p):
        class R:
            def __init__(s, v): s.v = v
            def fetchone(s): return s.v
        if sql is g.INSERT_HIST:
            k = p[3]
            if k in self.hist: return R(None)
            self.hist.add(k); return R({'id': 1})
        if sql is g.UPSERT_POS:
            if self.pos is None or p[3] > self.pos: self.pos = p[3]; return R({'vehicle_id': 'v'})
            return R(None)
def mk(t): return g.Fix.model_validate(fx(time=iso(t)))
def test_apply_out_of_order_and_duplicates():
    n = datetime.now(timezone.utc); c = FakeConn()
    r = g.apply_fixes(c, 'v', 'd', [mk(n - timedelta(seconds=10)), mk(n - timedelta(seconds=50)), mk(n - timedelta(seconds=10))], 'device')
    assert r == {'accepted': 2, 'historical': 0, 'duplicate': 1}
    newest = g.Fix.model_validate(fx(time=iso(n - timedelta(seconds=10)))).time
    assert c.pos == newest
    r2 = g.apply_fixes(c, 'v', 'd', [mk(n - timedelta(seconds=300))], 'device')      # late arrival must not overwrite newer position
    assert r2 == {'accepted': 0, 'historical': 1, 'duplicate': 0}

    assert c.pos == newest   # position unchanged by the late fix

# --- HTTP-level auth behaviour of the ingest router (psycopg.connect faked)
from fastapi import FastAPI
from fastapi.testclient import TestClient
class Cur:
    def __init__(s, row): s.row = row
    def fetchone(s): return s.row
class FakeDB:
    def __init__(s, device): s.device = device; s.calls = []
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def execute(s, sql, p=()):
        s.calls.append(sql)
        if 'fleet_gps_devices d join' in sql: return Cur(s.device)
        if sql is g.INSERT_HIST: return Cur({'id': 1})
        if sql is g.UPSERT_POS: return Cur({'vehicle_id': 'v'})
        return Cur(None)
def client(monkeypatch, device):
    fake = FakeDB(device); monkeypatch.setattr(g.psycopg, 'connect', lambda *a, **k: fake)
    app = FastAPI(); app.include_router(g.build_ingest_router(lambda: 'x')); return TestClient(app), fake
BODY = lambda: {'fixes': [fx()]}
def test_ingest_requires_bearer(monkeypatch):
    c, _ = client(monkeypatch, {'id': 'd', 'vehicle_id': 'v'})
    assert c.post('/api/gps/ingest', json=BODY()).status_code == 401
    assert c.post('/api/gps/ingest', json=BODY(), headers={'Authorization': 'Basic abc'}).status_code == 401
def test_ingest_unknown_token_401(monkeypatch):
    c, f = client(monkeypatch, None)
    assert c.post('/api/gps/ingest', json=BODY(), headers={'Authorization': 'Bearer nope'}).status_code == 401
    assert not any(q is g.UPSERT_POS for q in f.calls)       # nothing written
def test_ingest_ok_and_all_invalid_422(monkeypatch):
    c, _ = client(monkeypatch, {'id': 'd', 'vehicle_id': 'v'}); h = {'Authorization': 'Bearer ivd_x'}
    r = c.post('/api/gps/ingest', json=BODY(), headers=h); assert r.status_code == 200 and r.json()['accepted'] == 1
    assert c.post('/api/gps/ingest', json={'fixes': [fx(lat=999)]}, headers=h).status_code == 422
    assert c.post('/api/gps/ingest', json={'fixes': []}, headers=h).status_code == 422
def test_webhook_secret_and_signature(monkeypatch):
    import hmac, hashlib, json
    c, _ = client(monkeypatch, {'id': 'd', 'vehicle_id': 'v'})
    monkeypatch.delenv('GPS_WEBHOOK_SECRET', raising=False)
    assert c.post('/api/gps/webhook/generic', content=b'{}').status_code == 503
    monkeypatch.setenv('GPS_WEBHOOK_SECRET', 'sek')
    assert c.post('/api/gps/webhook/generic', content=b'{}', headers={'X-Signature': 'sha256=bad'}).status_code == 401
    body = json.dumps({'positions': [dict(device_id='IMEI1', **fx())]}).encode()
    sig = 'sha256=' + hmac.new(b'sek', body, hashlib.sha256).hexdigest()
    r = c.post('/api/gps/webhook/generic', content=body, headers={'X-Signature': sig}); assert r.status_code == 200 and r.json()['accepted'] == 1
    assert c.post('/api/gps/webhook/nope', content=body, headers={'X-Signature': sig}).status_code == 404
