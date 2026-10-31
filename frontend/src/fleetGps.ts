// Shared types and pure helpers for the live fleet view. No React, no DOM - unit-testable.
export type State = 'moving' | 'idle' | 'charging' | 'offline' | 'unknown' | 'no_gps'
export type Freshness = 'live' | 'delayed' | 'offline' | 'none'
export type Filter = 'all' | 'moving' | 'idle' | 'charging' | 'offline' | 'critical'
export type Position = { lat: number; lon: number; gps_time: string; received_at: string; heading_deg: number | null; accuracy_m: number | null; source: string }
export type LiveVehicle = {
  id: string; registration_number: string; vehicle_type: string; make: string; model: string; status: string; customer_name: string | null; vin: string | null
  driver_name: string | null; has_device: boolean; position: Position | null; freshness: Freshness; state: State; age_s: number | null
  speed_kmh: number | null; speed_source: 'device' | 'calculated' | null; battery_pct: number | null; charging?: boolean | null
  alerts: { code: string; message: string }[]; critical: boolean; demo?: boolean
}
export type LiveSummary = { total: number; moving: number; idle: number; charging: number; offline: number; unknown: number; no_gps: number; critical: number; data_status: 'current' | 'stale' | 'unavailable'; gps_configured: boolean }
export type LiveResponse = { server_time: string; latest_gps_time: string | null; summary: LiveSummary; items: LiveVehicle[]; truncated: boolean; thresholds: { live_s: number; offline_s: number; moving_kmh: number; critical_battery_pct: number; overspeed_kmh: number } }
export type TrackPoint = { lat: number; lon: number; time: string; speed_kmh: number | null; source: string }
export type TrackResponse = { vehicle_id: string; start: string; end: string; truncated: boolean; recorded: boolean; points: TrackPoint[] }

export const VISAKHAPATNAM: [number, number] = [17.6868, 83.2185]
export const STATE_COLOR: Record<State, string> = { moving: '#16a34a', idle: '#d97706', charging: '#0d9488', offline: '#94a3b8', unknown: '#64748b', no_gps: '#94a3b8' }
export const STATE_LABEL: Record<State, string> = { moving: 'Moving', idle: 'Idle', charging: 'Charging', offline: 'Offline', unknown: 'Moving state unknown', no_gps: 'No GPS data' }
export const FRESH_LABEL: Record<Freshness, string> = { live: 'Live', delayed: 'Delayed', offline: 'Offline', none: 'Never reported' }

export const validPos = (v: LiveVehicle) => !!v.position && Number.isFinite(v.position.lat) && Number.isFinite(v.position.lon) && Math.abs(v.position.lat) <= 90 && Math.abs(v.position.lon) <= 180

export function matches(v: LiveVehicle, f: Filter) { return f === 'all' ? true : f === 'critical' ? v.critical : v.state === f }
export function search(v: LiveVehicle, q: string) {
  const t = q.trim().toLowerCase(); if (!t) return true
  return [v.id, v.registration_number, v.make, v.model, `${v.make} ${v.model}`, v.vin, v.customer_name, v.driver_name, v.vehicle_type.replace(/_/g, ' ')].some(x => (x ?? '').toLowerCase().includes(t))
}

/** Keep the newest known position per vehicle. A response carrying an OLDER fix than we already show is ignored for that vehicle
 *  (covers reordered responses). Vehicles missing from the response (archived) are dropped. */
export function mergeLive(prev: LiveVehicle[], next: LiveVehicle[]): LiveVehicle[] {
  const old = new Map(prev.map(v => [v.id, v]))
  return next.map(n => {
    const o = old.get(n.id)
    if (o?.position && n.position && Date.parse(n.position.gps_time) < Date.parse(o.position.gps_time)) return o
    return n
  })
}

export function ago(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return 'Never'
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  return s < 10 ? 'just now' : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`
}

export function demoSummary(items: LiveVehicle[]): LiveSummary {
  const s = { total: items.length, moving: 0, idle: 0, charging: 0, offline: 0, unknown: 0, no_gps: 0, critical: 0, data_status: 'current' as const, gps_configured: false }
  for (const v of items) { s[v.state]++; if (v.critical) s.critical++ }
  return s
}

/** DEMO ONLY. Simulates movement for REAL vehicle records so the UI can be exercised without hardware.
 *  Runs entirely in the browser, never touches the database, every item is flagged demo:true and source 'demo'. */
export class DemoFleet {
  private s: { id: string; lat: number; lon: number; head: number; spd: number; mode: 'drive' | 'park' | 'charge' | 'off'; batt: number }[]
  constructor(private base: LiveVehicle[], seed = 7) {
    let r = seed; const rnd = () => ((r = (r * 1664525 + 1013904223) >>> 0) / 4294967296)
    this.rnd = rnd
    this.s = base.map((v, i) => ({ id: v.id, lat: VISAKHAPATNAM[0] + (rnd() - 0.5) * 0.09, lon: VISAKHAPATNAM[1] + (rnd() - 0.5) * 0.11, head: rnd() * 360, spd: 0,
      mode: i % 7 === 5 ? 'charge' : i % 7 === 6 ? 'off' : i % 4 === 3 ? 'park' : 'drive', batt: 20 + rnd() * 75 }))
  }
  private rnd: () => number
  step(dtS: number): LiveVehicle[] {
    const now = new Date().toISOString()
    return this.base.map((v, i) => {
      const s = this.s[i]
      if (s.mode === 'drive') {
        s.spd = Math.max(8, Math.min(55, (s.spd || 25) + (this.rnd() - 0.5) * 10)); s.head = (s.head + (this.rnd() - 0.5) * 30 + 360) % 360
        const km = (s.spd * dtS) / 3600, rad = (s.head * Math.PI) / 180
        s.lat += (km * Math.cos(rad)) / 111; s.lon += (km * Math.sin(rad)) / (111 * Math.cos((s.lat * Math.PI) / 180))
        s.lat = Math.max(17.55, Math.min(17.85, s.lat)); s.lon = Math.max(83.1, Math.min(83.45, s.lon)); s.batt = Math.max(3, s.batt - dtS * 0.01)
      } else { s.spd = 0; if (s.mode === 'charge') s.batt = Math.min(100, s.batt + dtS * 0.05) }
      const off = s.mode === 'off', crit = s.batt <= 15 || v.status === 'OUT_OF_SERVICE'
      const state: State = off ? 'offline' : s.mode === 'charge' ? 'charging' : s.spd >= 3 ? 'moving' : 'idle'
      return { ...v, demo: true, driver_name: null, has_device: false, freshness: off ? 'offline' : 'live', state, age_s: off ? 3600 : 0, speed_kmh: off ? null : Math.round(s.spd * 10) / 10, speed_source: off ? null : 'device',
        battery_pct: Math.round(s.batt), charging: s.mode === 'charge', critical: crit, alerts: crit ? [{ code: s.batt <= 15 ? 'LOW_BATTERY' : 'OUT_OF_SERVICE', message: 'Simulated alert' }] : [],
        position: { lat: s.lat, lon: s.lon, gps_time: off ? new Date(Date.now() - 3600_000).toISOString() : now, received_at: now, heading_deg: s.head, accuracy_m: null, source: 'demo' } }
    })
  }
}
