#!/usr/bin/env python3
"""Pushes SIMULATED fixes through the real ingest API to test the pipeline end to end (auth, validation, DB, polling, map).
Payloads carry source="simulator", so the dashboard labels them as test data. Never use against production vehicles you care about.

  python scripts/simulate_device.py --url https://your-host/api/gps/ingest --token ivd_xxx [--interval 5] [--count 30]
"""
import argparse, json, math, random, time, urllib.request, urllib.error
from datetime import datetime, timezone

ap = argparse.ArgumentParser(); ap.add_argument('--url', required=True); ap.add_argument('--token', required=True)
ap.add_argument('--interval', type=float, default=5); ap.add_argument('--count', type=int, default=30)
ap.add_argument('--lat', type=float, default=17.6868); ap.add_argument('--lon', type=float, default=83.2185)   # Visakhapatnam
a = ap.parse_args(); lat, lon, head, batt = a.lat, a.lon, random.uniform(0, 360), 80.0
for i in range(a.count):
    spd = random.uniform(15, 45); head = (head + random.uniform(-25, 25)) % 360; km = spd * a.interval / 3600
    lat += km * math.cos(math.radians(head)) / 111; lon += km * math.sin(math.radians(head)) / (111 * math.cos(math.radians(lat))); batt -= 0.05
    body = {'fixes': [{'lat': round(lat, 6), 'lon': round(lon, 6), 'time': datetime.now(timezone.utc).isoformat(), 'speed_kmh': round(spd, 1), 'heading_deg': round(head, 1), 'battery_pct': round(batt, 1), 'charging': False, 'source': 'simulator'}]}
    req = urllib.request.Request(a.url, json.dumps(body).encode(), {'Content-Type': 'application/json', 'Authorization': f'Bearer {a.token}'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: print(i, r.status, r.read().decode())
    except urllib.error.HTTPError as e: print(i, e.code, e.read().decode()); break
    time.sleep(a.interval)
