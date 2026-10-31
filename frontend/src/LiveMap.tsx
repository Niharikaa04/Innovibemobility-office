import { useEffect, useRef, useState } from 'react'
import type * as LT from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'
import type { LiveVehicle, TrackPoint } from './fleetGps'
import { STATE_LABEL, VISAKHAPATNAM, ago, validPos } from './fleetGps'
import { markerHtml } from './vehicleIcons'

// OpenStreetMap's public tile servers are for light use (https://operations.osmfoundation.org/policies/tiles/).
// For production traffic point `tileUrl` at a commercial/self-hosted tile provider.
export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
type Props = { vehicles: LiveVehicle[]; selectedId: string | null; onSelect: (id: string | null) => void; focusSignal: number; fitSignal: number; track: TrackPoint[] | null; onError: (m: string) => void; tileUrl?: string }

export default function LiveMap({ vehicles, selectedId, onSelect, focusSignal, fitSignal, track, onError, tileUrl = OSM_TILES }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const R = useRef<{ L: typeof LT; map: LT.Map; cluster: any; markers: Map<string, { m: LT.Marker; key: string }>; trackLayer: LT.LayerGroup; fitted: boolean } | null>(null)
  const latest = useRef({ vehicles, selectedId, onSelect }); latest.current = { vehicles, selectedId, onSelect }
  const [ready, setReady] = useState(false), [tileErr, setTileErr] = useState(false)

  // ---- init (browser only: Leaflet is imported dynamically, so SSR never touches window/document) ----
  useEffect(() => {
    let dead = false, map: LT.Map | null = null
    ;(async () => {
      try {
        const mod: any = await import('leaflet'); const L: typeof LT = mod.default ?? mod
        ;(window as any).L = L                      // markercluster is a UMD plugin that attaches to the global L
        await import('leaflet.markercluster')
        if (dead || !el.current) return
        map = L.map(el.current, { center: VISAKHAPATNAM, zoom: 11, zoomControl: true, worldCopyJump: true })
        const tiles = L.tileLayer(tileUrl, { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map)
        let fails = 0; tiles.on('tileerror', () => { if (++fails >= 3) setTileErr(true) }); tiles.on('tileload', () => { if (fails) { fails = 0; setTileErr(false) } })
        const cluster = (L as any).markerClusterGroup({ maxClusterRadius: 45, disableClusteringAtZoom: 16, showCoverageOnHover: false, spiderfyOnMaxZoom: true }); map.addLayer(cluster)
        R.current = { L, map, cluster, markers: new Map(), trackLayer: L.layerGroup().addTo(map), fitted: false }
        setReady(true)
      } catch (e) { onError(`Map failed to load: ${(e as Error).message}`) }
    })()
    return () => { dead = true; R.current = null; map?.remove(); setReady(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileUrl])

  // ---- sync markers: add/update/remove by vehicle id (one marker per vehicle, positions updated in place) ----
  useEffect(() => {
    const r = R.current; if (!ready || !r) return
    const { L, cluster, markers } = r, seen = new Set<string>()
    for (const v of vehicles) {
      if (!validPos(v)) continue          // vehicles without valid GPS never get a marker
      seen.add(v.id)
      const p = v.position!, key = `${v.vehicle_type}|${v.state}|${v.id === selectedId}|${v.critical}|${!!v.demo}`, ll: LT.LatLngExpression = [p.lat, p.lon]
      let e = markers.get(v.id)
      if (!e) {
        const m = L.marker(ll, { icon: icon(L, v, v.id === selectedId), keyboard: true, title: v.registration_number, riseOnHover: true })
        m.on('click', () => latest.current.onSelect(v.id)); m.bindPopup(() => popup(latest.current.vehicles.find(x => x.id === v.id) ?? v), { closeButton: true, autoPan: true })
        cluster.addLayer(m); e = { m, key }; markers.set(v.id, e)
      } else {
        const cur = e.m.getLatLng(); if (cur.lat !== p.lat || cur.lng !== p.lon) { e.m.setLatLng(ll); cluster.refreshClusters(e.m) }
        if (e.key !== key) { e.m.setIcon(icon(L, v, v.id === selectedId)); e.key = key }
        e.m.setZIndexOffset(v.id === selectedId ? 1000 : v.critical ? 500 : 0)
        if (e.m.isPopupOpen()) e.m.getPopup()?.setContent(popup(v))
      }
    }
    for (const [id, e] of markers) if (!seen.has(id)) { cluster.removeLayer(e.m); markers.delete(id) }
    if (!r.fitted && markers.size) { r.fitted = true; fit() }   // fit once when the first positions arrive; later fits are user-triggered
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicles, selectedId, ready])

  function fit() {
    const r = R.current; if (!r) return
    const pts = [...r.markers.values()].map(e => e.m.getLatLng())
    if (pts.length) r.map.fitBounds(r.L.latLngBounds(pts).pad(0.2), { maxZoom: 15, animate: false }); else r.map.setView(VISAKHAPATNAM, 11)
  }
  useEffect(() => { if (ready) fit() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [fitSignal])

  // ---- recenter on the selected vehicle (list click or Recenter button) ----
  useEffect(() => {
    const r = R.current, id = latest.current.selectedId; if (!ready || !r || !id) return
    const e = r.markers.get(id); if (!e) return
    r.cluster.zoomToShowLayer(e.m, () => { r.map.setView(e.m.getLatLng(), Math.max(r.map.getZoom(), 15), { animate: true }); e.m.openPopup() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSignal])

  // ---- recorded route (history) - visually distinct from live markers; nothing is drawn without recorded points ----
  useEffect(() => {
    const r = R.current; if (!ready || !r) return
    r.trackLayer.clearLayers(); if (!track || track.length === 0) return
    const { L } = r, ll = track.map(p => [p.lat, p.lon] as LT.LatLngTuple)
    L.polyline(ll, { color: '#0f2747', weight: 4, opacity: 0.75, dashArray: '8 6' }).addTo(r.trackLayer)
    const step = Math.max(1, Math.ceil(track.length / 250))
    track.forEach((p, i) => { if (i % step && i !== track.length - 1) return
      L.circleMarker([p.lat, p.lon], { radius: i === 0 || i === track.length - 1 ? 6 : 3, color: '#fff', weight: 1.5, fillColor: i === 0 ? '#16a34a' : i === track.length - 1 ? '#dc2626' : '#0f2747', fillOpacity: 1 })
        .bindTooltip(`${i === 0 ? 'Route start · ' : i === track.length - 1 ? 'Last recorded point · ' : ''}${new Date(p.time).toLocaleString()}${p.speed_kmh != null ? ` · ${Math.round(p.speed_kmh)} km/h` : ''}`).addTo(r.trackLayer) })
    r.map.fitBounds(L.latLngBounds(ll).pad(0.15), { maxZoom: 16 })
  }, [track, ready])

  return <div className="fl-mapbox"><div ref={el} className="fl-map" role="application" aria-label="Live fleet map"/>
    {!ready && <div className="fl-overlay">Loading map…</div>}
    {tileErr && <div className="fl-overlay fl-overlay-err">Map tiles could not be loaded. Check your connection or tile provider settings; vehicle positions are still updating.</div>}
  </div>
}

function icon(L: typeof LT, v: LiveVehicle, selected: boolean) {
  return L.divIcon({ className: 'fl-pin', html: markerHtml(v.vehicle_type, v.state, { selected, critical: v.critical, demo: v.demo }), iconSize: [34, 34], iconAnchor: [17, 17], popupAnchor: [0, -16] })
}
// Popup is built with DOM nodes + textContent: registration numbers/customer names are user-entered and must never be parsed as HTML.
function popup(v: LiveVehicle) {
  const d = document.createElement('div'); d.className = 'fl-pop'
  const add = (t: string, cls = '') => { const x = document.createElement('div'); if (cls) x.className = cls; x.textContent = t; d.appendChild(x) }
  add(v.registration_number, 'fl-pop-h'); add(`${v.make} ${v.model}`); add(STATE_LABEL[v.state] + (v.demo ? ' (simulated)' : ''))
  add(`Last GPS update: ${v.position ? ago(v.position.gps_time) : 'Not available'}`, 'fl-pop-m'); if (v.speed_kmh != null) add(`${Math.round(v.speed_kmh)} km/h`, 'fl-pop-m')
  return d
}
