// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, waitFor, cleanup, act } from '@testing-library/react'
vi.mock('leaflet/dist/leaflet.css', () => ({})); vi.mock('leaflet.markercluster/dist/MarkerCluster.css', () => ({})); vi.mock('leaflet.markercluster/dist/MarkerCluster.Default.css', () => ({}))
import LiveMap from '../LiveMap'
import type { LiveVehicle } from '../fleetGps'
const V = (id: string, type: string, lat: number, lon: number, o: Partial<LiveVehicle> = {}): LiveVehicle => ({ id, registration_number: '<img src=x onerror=alert(1)>' + id, vehicle_type: type, make: 'M', model: 'X', status: 'ACTIVE', customer_name: null, vin: null, driver_name: null, has_device: true,
  position: { lat, lon, gps_time: '2026-10-30T08:00:00Z', received_at: '2026-10-30T08:00:00Z', heading_deg: null, accuracy_m: null, source: 'device' }, freshness: 'live', state: 'moving', age_s: 1, speed_kmh: 20, speed_source: 'device', battery_pct: null, alerts: [], critical: false, ...o })
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 800 }); Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 600 })
const pins = (c: HTMLElement) => c.querySelectorAll('.fl-pin')
const props = (vs: LiveVehicle[], sel: string | null = null) => ({ vehicles: vs, selectedId: sel, onSelect: () => {}, focusSignal: 0, fitSignal: 0, track: null, onError: () => {} })
describe('LiveMap (jsdom)', () => {
  it('one marker per vehicle with type-specific icon; updates in place; removes; skips invalid; popup is XSS-safe', async () => {
    const errs: string[] = []; const { container, rerender } = render(<LiveMap {...props([V('b', 'TWO_WHEELER', 17.7, 83.3), V('c', 'CAR', 17.71, 83.31), V('n', 'CAR', 0, 0, { position: null })])} onError={m => errs.push(m)}/>)
    await waitFor(() => expect(pins(container).length).toBe(2), { timeout: 5000 }); expect(errs).toEqual([])
    const html = [...pins(container)].map(p => p.innerHTML); expect(new Set(html).size).toBe(2)              // bike glyph != car glyph
    // same vehicle, new coordinates + repeated renders -> still 2 markers, no duplicates
    for (let i = 0; i < 3; i++) rerender(<LiveMap {...props([V('b', 'TWO_WHEELER', 17.7 + i * 0.001, 83.3), V('c', 'CAR', 17.71, 83.31)])}/>)
    await waitFor(() => expect(pins(container).length).toBe(2))
    // state change swaps icon, selection adds ring
    rerender(<LiveMap {...props([V('b', 'TWO_WHEELER', 17.7, 83.3, { state: 'offline' }), V('c', 'CAR', 17.71, 83.31)], 'c')}/>)
    await waitFor(() => expect(container.innerHTML).toContain('stroke="#0f2747" stroke-width="2.5"'))
    // removal
    rerender(<LiveMap {...props([V('c', 'CAR', 17.71, 83.31)])}/>); await waitFor(() => expect(pins(container).length).toBe(1))
    // popup content never parsed as HTML
    await act(async () => { (container.querySelector('.fl-pin') as HTMLElement).click() })
    await waitFor(() => expect(container.querySelector('.fl-pop')).toBeTruthy()); expect(container.querySelector('.fl-pop img')).toBeNull(); expect(container.querySelector('.fl-pop-h')!.textContent).toContain('<img')
    cleanup()
  })
})
