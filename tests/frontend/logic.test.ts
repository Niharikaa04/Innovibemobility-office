import { describe, it, expect } from 'vitest'
import { DemoFleet, mergeLive, matches, search, validPos, demoSummary, ago } from '../fleetGps'
import type { LiveVehicle } from '../fleetGps'
import { markerHtml, GLYPHS } from '../vehicleIcons'
const V = (id: string, o: Partial<LiveVehicle> = {}): LiveVehicle => ({ id, registration_number: 'AP 31 ' + id, vehicle_type: 'CAR', make: 'Tata', model: 'Nexon EV', status: 'ACTIVE', customer_name: 'Acme Logistics', vin: 'VIN123', driver_name: null, has_device: true,
  position: { lat: 17.7, lon: 83.3, gps_time: '2026-10-30T08:00:00Z', received_at: '2026-10-30T08:00:01Z', heading_deg: null, accuracy_m: null, source: 'device' }, freshness: 'live', state: 'idle', age_s: 5, speed_kmh: 0, speed_source: 'device', battery_pct: null, alerts: [], critical: false, ...o })
describe('merge', () => {
  it('keeps newer position when response is older', () => { const p = [V('a')], n = [V('a', { position: { ...p[0].position!, gps_time: '2026-10-30T07:00:00Z', lat: 1 } })]; expect(mergeLive(p, n)[0].position!.lat).toBe(17.7) })
  it('takes newer position', () => { const p = [V('a')], n = [V('a', { position: { ...p[0].position!, gps_time: '2026-10-30T08:00:09Z', lat: 18 } })]; expect(mergeLive(p, n)[0].position!.lat).toBe(18) })
  it('drops vehicles absent from response, accepts position-less', () => { expect(mergeLive([V('a'), V('b')], [V('b', { position: null })]).map(v => v.id)).toEqual(['b']) })
})
describe('filters/search', () => {
  it('filters', () => { expect(matches(V('a', { state: 'moving' }), 'moving')).toBe(true); expect(matches(V('a', { critical: true }), 'critical')).toBe(true); expect(matches(V('a'), 'offline')).toBe(false); expect(matches(V('a', { state: 'no_gps' }), 'all')).toBe(true) })
  it('searches id/reg/customer/vin/make', () => { const v = V('xyz'); for (const t of ['xyz', 'ap 31', 'acme', 'vin123', 'nexon', 'car']) expect(search(v, t)).toBe(true); expect(search(v, 'nomatch')).toBe(false); expect(search(v, '  ')).toBe(true) })
  it('validPos rejects missing/NaN/out of range', () => { expect(validPos(V('a', { position: null }))).toBe(false); expect(validPos(V('a', { position: { ...V('a').position!, lat: NaN } }))).toBe(false); expect(validPos(V('a', { position: { ...V('a').position!, lon: 200 } }))).toBe(false); expect(validPos(V('a'))).toBe(true) })
})
describe('demo', () => {
  const base = Array.from({ length: 14 }, (_, i) => V(String(i), { position: null, state: 'no_gps', freshness: 'none' }))
  it('flags every item as demo, keeps real ids, valid coords near Visakhapatnam', () => {
    const f = new DemoFleet(base); let items = f.step(0); for (let i = 0; i < 20; i++) items = f.step(2)
    expect(items.map(v => v.id)).toEqual(base.map(v => v.id)); expect(new Set(items.map(v => v.id)).size).toBe(14)
    for (const v of items) { expect(v.demo).toBe(true); expect(v.position!.source).toBe('demo'); expect(validPos(v)).toBe(true); expect(Math.abs(v.position!.lat - 17.69)).toBeLessThan(0.2); expect(v.driver_name).toBeNull() }
    const s = demoSummary(items); expect(s.moving + s.idle + s.charging + s.offline).toBe(14)
  })
})
describe('icons', () => {
  it('every vehicle type has a distinct glyph and the marker is well-formed', () => {
    const types = ['TWO_WHEELER', 'CAR', 'THREE_WHEELER', 'VAN', 'BUS', 'TRUCK', 'OTHER']; expect(new Set(types.map(t => GLYPHS[t])).size).toBe(7)
    for (const t of types) { const h = markerHtml(t, 'moving', { selected: true, critical: true, demo: true }); expect(h.startsWith('<svg') && h.endsWith('</svg>')).toBe(true); expect(h.match(/<svg/g)!.length).toBe(1) }
    expect(markerHtml('TWO_WHEELER', 'idle')).not.toEqual(markerHtml('CAR', 'idle'))
  })
  it('ago', () => { const n = Date.parse('2026-10-30T08:10:00Z'); expect(ago('2026-10-30T08:09:58Z', n)).toBe('just now'); expect(ago('2026-10-30T08:05:00Z', n)).toBe('5m ago'); expect(ago(null)).toBe('Never') })
})
