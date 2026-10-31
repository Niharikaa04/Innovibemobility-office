import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import { Badge, Loading, Notices, PageHead, Stat, fmtTime, pretty } from './opsui'
import LiveMap from './LiveMap'
import FleetGpsDevices from './FleetGpsDevices'
import { DemoFleet, FRESH_LABEL, STATE_COLOR, STATE_LABEL, ago, demoSummary, matches, mergeLive, search, validPos } from './fleetGps'
import type { Filter, LiveResponse, LiveVehicle, TrackPoint, TrackResponse } from './fleetGps'
import { listIconHtml } from './vehicleIcons'

const POLL_MS = 5000, POLL_SLOW_MS = 15000
const FILTERS: { key: Filter; label: string }[] = [{ key: 'all', label: 'All' }, { key: 'moving', label: 'Moving' }, { key: 'idle', label: 'Idle' }, { key: 'charging', label: 'Charging' }, { key: 'offline', label: 'Offline' }, { key: 'critical', label: 'Critical' }]
const RANGES = { '1h': 3600e3, '6h': 6 * 3600e3, '24h': 24 * 3600e3, '7d': 7 * 24 * 3600e3 } as const
const NA = 'Not available'

export default function FleetLive() {
  const [live, setLive] = useState<LiveResponse | null>(null), [error, setError] = useState(''), [mapError, setMapError] = useState(''), [fails, setFails] = useState(0)
  const [filter, setFilter] = useState<Filter>('all'), [q, setQ] = useState(''), [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState(0), [fitSig, setFitSig] = useState(0), [showDevices, setShowDevices] = useState(false)
  const [demo, setDemo] = useState(false), [demoItems, setDemoItems] = useState<LiveVehicle[]>([])
  const [route, setRoute] = useState(false), [range, setRange] = useState<keyof typeof RANGES>('6h'), [track, setTrack] = useState<TrackResponse | null>(null), [trackErr, setTrackErr] = useState(''), [trackBusy, setTrackBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const inflight = useRef(false), seq = useRef(0), applied = useRef(0), liveRef = useRef<LiveResponse | null>(null); liveRef.current = live

  // ---- real data: poll /fleet/live (paused while the tab is hidden or demo is on; slower after repeated failures) ----
  const poll = useCallback(async () => {
    if (inflight.current) return
    inflight.current = true; const my = ++seq.current
    try {
      const r = await api.call<LiveResponse>('/fleet/live', 'GET')
      if (my < applied.current) return            // a newer response was already applied
      applied.current = my; setLive(prev => ({ ...r, items: mergeLive(prev?.items ?? [], r.items) })); setError(''); setFails(0)
    } catch (e) { setError((e as Error).message); setFails(f => f + 1) } finally { inflight.current = false }
  }, [])
  useEffect(() => {
    if (demo) return
    void poll()
    const t = setInterval(() => { if (!document.hidden) void poll() }, fails > 2 ? POLL_SLOW_MS : POLL_MS)
    const vis = () => { if (!document.hidden) void poll() }
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis) }
  }, [poll, demo, fails > 2])                     // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(t) }, [])

  // ---- demo mode: browser-only simulation over the real vehicle records; never persisted, always labelled ----
  // Falls back to the existing /fleet/vehicles list so demo works even before the GPS backend is mounted.
  useEffect(() => {
    if (!demo) return
    let dead = false, timer: ReturnType<typeof setInterval> | undefined
    ;(async () => {
      let base: LiveVehicle[] = liveRef.current?.items ?? []
      if (!base.length) {
        try {
          const l = await api.call<{ items: Record<string, any>[] }>('/fleet/vehicles?limit=100', 'GET')
          base = l.items.map(v => ({ id: v.id, registration_number: v.registration_number, vehicle_type: v.vehicle_type, make: v.make, model: v.model, status: v.status,
            customer_name: v.customer_name ?? null, vin: v.vin ?? null, driver_name: null, has_device: false, position: null, freshness: 'none' as const, state: 'no_gps' as const,
            age_s: null, speed_kmh: null, speed_source: null, battery_pct: null, alerts: [], critical: false }))
        } catch { /* leave empty: banner explains */ }
      }
      if (dead) return
      const sim = new DemoFleet(base); setDemoItems(sim.step(0))
      timer = setInterval(() => setDemoItems(sim.step(2)), 2000)
    })()
    return () => { dead = true; if (timer) clearInterval(timer) }
  }, [demo])

  // Anything pushed with source "simulator" (scripts/simulate_device.py) is labelled simulated everywhere in the UI.
  const items = useMemo(() => demo ? demoItems : (live?.items ?? []).map(v => v.position?.source === 'simulator' ? { ...v, demo: true } : v), [demo, demoItems, live])
  const hasSimulated = !demo && items.some(v => v.demo)
  const summary = demo ? demoSummary(demoItems) : live?.summary
  const shown = useMemo(() => items.filter(v => matches(v, filter) && search(v, q)), [items, filter, q])
  const onMap = useMemo(() => shown.filter(validPos), [shown])
  const selected = items.find(v => v.id === selectedId) ?? null
  const select = (id: string | null, recenter = false) => { setSelectedId(id); setRoute(false); setTrack(null); if (recenter) setFocus(f => f + 1) }
  const setF = (f: Filter) => { setFilter(f); setFitSig(s => s + 1) }
  const rowRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => { rowRef.current?.scrollIntoView({ block: 'nearest' }) }, [selectedId])

  // ---- recorded route for the selected vehicle ----
  useEffect(() => {
    if (!route || !selectedId || demo) { setTrack(null); setTrackErr(''); return }
    let dead = false; setTrackBusy(true); setTrackErr('')
    const end = new Date(), start = new Date(end.getTime() - RANGES[range])
    api.call<TrackResponse>(`/fleet/vehicles/${selectedId}/track?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`, 'GET')
      .then(r => { if (!dead) setTrack(r) }).catch(e => { if (!dead) { setTrack(null); setTrackErr((e as Error).message) } }).finally(() => { if (!dead) setTrackBusy(false) })
    return () => { dead = true }
  }, [route, range, selectedId, demo])
  const trackPts: TrackPoint[] | null = track && track.points.length ? track.points : null

  // ---- connection / freshness indicator ----
  const conn = demo ? { cls: 'demo', text: 'Demo — simulated' } : !live && error ? { cls: 'bad', text: 'Unavailable' } : !live ? { cls: 'wait', text: 'Connecting…' }
    : error ? { cls: 'bad', text: 'Connection lost — showing last data' } : live.summary.data_status === 'current' ? { cls: 'ok', text: 'Live GPS' } : live.summary.data_status === 'stale' ? { cls: 'warn', text: 'GPS data stale' } : { cls: 'off', text: 'No GPS data' }
  const lastUpdate = demo ? null : live?.latest_gps_time ?? null
  const baseIds = (live?.items ?? []).map(v => ({ id: v.id, registration_number: v.registration_number }))

  return <div className="fl"><style>{CSS}</style>
    <PageHead title="Fleet Intelligence" subtitle="Latest known GPS position of every vehicle. Locations come from connected trackers or provider feeds.">
      <span className={`fl-pill fl-${conn.cls}`} role="status"><i/>{conn.text}</span>
      <button className="ghost" onClick={() => setShowDevices(true)}>GPS devices</button>
      <button className={demo ? 'btn' : 'ghost'} aria-pressed={demo} onClick={() => { setDemo(d => !d); select(null) }}>{demo ? 'Exit demo mode' : 'Demo mode'}</button>
    </PageHead>
    {demo && <div className="fl-banner fl-b-demo" role="alert"><strong>DEMO MODE</strong> — positions are simulated in your browser for testing. They are <strong>not real GPS data</strong> and are not saved.{!items.length && ' No vehicles exist to simulate yet.'}</div>}
    {!demo && live && !live.summary.gps_configured && <div className="fl-banner fl-b-info">No GPS device or provider is connected yet, so no vehicle locations are available. Use <strong>GPS devices</strong> to create credentials, or try <strong>Demo mode</strong>.</div>}
    {!demo && live?.summary.gps_configured && live.summary.data_status === 'unavailable' && <div className="fl-banner fl-b-info">GPS devices are configured but no vehicle has reported a position yet.</div>}
    {hasSimulated && <div className="fl-banner fl-b-demo" role="alert"><strong>TEST DATA</strong> — some positions were sent by the GPS simulator script (source “simulator”). They are shown with dashed markers and are <strong>not real GPS data</strong>.</div>}
    {!demo && live?.truncated && <div className="fl-banner fl-b-warn">Fleet is larger than the live view limit; only the first vehicles are shown.</div>}
    <Notices error={demo ? mapError : error || mapError} notice="" onRetry={() => { setMapError(''); void poll() }}/>
    {!summary ? (error ? null : <Loading/>) : <>
      <div className="cards" aria-label="Fleet summary">
        <Stat name="Total vehicles" value={summary.total} on={filter === 'all'} onClick={() => setF('all')}/>
        <Stat name="Moving" value={summary.moving} on={filter === 'moving'} onClick={() => setF('moving')}/>
        <Stat name="Idle" value={summary.idle} on={filter === 'idle'} onClick={() => setF('idle')}/>
        <Stat name="Charging" value={summary.charging} on={filter === 'charging'} onClick={() => setF('charging')}/>
        <Stat name="Offline" value={summary.offline} on={filter === 'offline'} onClick={() => setF('offline')}/>
        <Stat name="Critical alerts" value={summary.critical} on={filter === 'critical'} alert={summary.critical > 0} onClick={() => setF('critical')}/>
      </div>
      <p className="fl-meta">{demo ? 'Simulated data' : <>Latest GPS update: <strong>{lastUpdate ? `${fmtTime(lastUpdate)} (${ago(lastUpdate, now)})` : 'none received'}</strong></>}
        {summary.no_gps + summary.unknown > 0 && <> · {summary.no_gps} without GPS data{summary.unknown ? `, ${summary.unknown} with unknown motion` : ''}</>}</p>
    </>}
    <div className="fl-bar"><label className="fl-search"><span className="fl-sr">Search vehicles</span><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search vehicle ID, registration, customer, make, VIN…" aria-label="Search vehicles"/></label>
      <div className="fl-chips" role="group" aria-label="Status filter">{FILTERS.map(f => <button key={f.key} className={`fl-chip${filter === f.key ? ' on' : ''}`} aria-pressed={filter === f.key} onClick={() => setF(f.key)}>{f.label}{summary && <b>{f.key === 'all' ? summary.total : summary[f.key]}</b>}</button>)}</div>
      <button className="ghost" onClick={() => setFitSig(s => s + 1)}>Fit all</button></div>
    <div className="fl-grid">
      <div><LiveMap vehicles={onMap} selectedId={selectedId} onSelect={id => select(id)} focusSignal={focus} fitSignal={fitSig} track={trackPts} onError={setMapError}/>
        <p className="fl-meta">{onMap.length} of {shown.length} shown vehicle(s) have a GPS position on the map.{trackPts && ' Dashed navy line = recorded route history; vehicle icons = latest position.'}</p></div>
      <aside className="fl-side" aria-label="Vehicle details and list">
        {selected ? <section className="fl-card" aria-live="polite">
          <div className="fl-card-h"><span dangerouslySetInnerHTML={{ __html: listIconHtml(selected.vehicle_type, selected.state) }}/><div><h3>{selected.registration_number}</h3><small>{selected.make} {selected.model}</small></div><button className="ghost" onClick={() => select(null)} aria-label="Close details">✕</button></div>
          {selected.demo && <p className="fl-demo-tag">Simulated data — not real GPS</p>}
          {selected.alerts.map(a => <p key={a.code} className="fl-alert">⚠ {a.message}</p>)}
          <dl className="fl-dl">
            <Row k="Vehicle ID" v={<code title={selected.id}>{selected.id.slice(0, 8)}</code>}/><Row k="Type" v={pretty(selected.vehicle_type)}/>
            <Row k="Assigned driver" v={selected.driver_name || NA}/><Row k="Customer" v={selected.customer_name || NA}/>
            <Row k="Vehicle status" v={<Badge v={selected.status}/>}/>
            <Row k="Movement" v={<span className="fl-dot" style={{ ['--c' as string]: STATE_COLOR[selected.state] }}>{STATE_LABEL[selected.state]}</span>}/>
            <Row k="Latitude / longitude" v={selected.position ? `${selected.position.lat.toFixed(5)}, ${selected.position.lon.toFixed(5)}` : NA}/>
            <Row k="Location" v="Not available (reverse geocoding not configured)"/>
            <Row k="Speed" v={selected.speed_kmh == null ? NA : `${Math.round(selected.speed_kmh)} km/h${selected.speed_source === 'calculated' ? ' (calculated)' : ''}`}/>
            <Row k="Battery" v={selected.battery_pct == null ? NA : `${Math.round(selected.battery_pct)}%${selected.charging ? ' · charging' : ''}`}/>
            <Row k="Last GPS update" v={selected.position ? `${fmtTime(selected.position.gps_time)} (${ago(selected.position.gps_time, now)})` : NA}/>
            <Row k="GPS data" v={<>{FRESH_LABEL[selected.freshness]}{selected.position && <small> · source: {selected.position.source}</small>}</>}/>
            {selected.position?.accuracy_m != null && <Row k="Accuracy" v={`± ${Math.round(selected.position.accuracy_m)} m`}/>}
          </dl>
          {!validPos(selected) && <p className="note">This vehicle has no GPS position, so it is not shown on the map.</p>}
          <div className="fl-actions"><button className="btn" disabled={!validPos(selected)} onClick={() => setFocus(f => f + 1)}>Recenter on vehicle</button>
            <button className="ghost" disabled={demo} aria-pressed={route} onClick={() => setRoute(r => !r)}>{route ? 'Hide route' : 'Route history'}</button></div>
          {demo && <p className="note">Route history is not available in demo mode.</p>}
          {route && !demo && <div className="fl-route"><label>Range <select value={range} onChange={e => setRange(e.target.value as keyof typeof RANGES)}>{Object.keys(RANGES).map(k => <option key={k} value={k}>Last {k}</option>)}</select></label>
            <span className="note">{trackBusy ? 'Loading…' : trackErr ? trackErr : track && !track.points.length ? 'No recorded GPS points in this range — route history unavailable.' : track ? `${track.points.length} recorded point(s)${track.truncated ? ' (most recent shown)' : ''}, ${fmtTime(track.points[0].time)} → ${fmtTime(track.points[track.points.length - 1].time)}` : ''}</span></div>}
        </section> : <section className="fl-card fl-hint">Select a vehicle on the map or in the list to see its details.</section>}
        <section className="fl-card fl-listcard"><div className="fl-card-h"><h3>Vehicles ({shown.length})</h3></div>
          {!summary ? <Loading/> : !shown.length ? <p className="note" style={{ padding: 12 }}>{items.length ? 'No vehicles match the current search and filter.' : 'No vehicles yet. Add vehicles in the fleet list first.'}</p> :
            <ul className="fl-list">{shown.map(v => <li key={v.id}><button ref={v.id === selectedId ? rowRef : undefined} className={`fl-row${v.id === selectedId ? ' on' : ''}`} onClick={() => select(v.id, true)}>
              <span dangerouslySetInnerHTML={{ __html: listIconHtml(v.vehicle_type, v.state) }}/><span className="fl-row-t"><b>{v.registration_number}{v.critical && <em title={v.alerts.map(a => a.message).join('; ')}> ⚠</em>}</b><small>{v.make} {v.model} · {pretty(v.vehicle_type)}</small></span>
              <span className="fl-row-s"><span style={{ color: STATE_COLOR[v.state] }}>{STATE_LABEL[v.state]}</span><small>{v.position ? ago(v.position.gps_time, now) : 'No GPS'}</small></span></button></li>)}</ul>}
        </section>
      </aside></div>
    {showDevices && <FleetGpsDevices vehicles={baseIds} onClose={() => setShowDevices(false)}/>}
  </div>
}
const Row = ({ k, v }: { k: string; v: ReactNode }) => <div><dt>{k}</dt><dd>{v}</dd></div>

const CSS = `
.fl{--navy:#0f2747;--mut:#64748b;--line:#e2e8f0;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;color:var(--navy)}
.fl-pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:13px;font-weight:600;background:#fff}
.fl-pill i{width:9px;height:9px;border-radius:50%;background:var(--mut)}.fl-ok i{background:var(--ok)}.fl-warn i{background:var(--warn)}.fl-bad i{background:var(--bad)}.fl-demo{border-color:var(--warn);color:#92400e;background:#fffbeb}.fl-demo i{background:var(--warn)}
.fl-banner{border-radius:10px;padding:10px 14px;margin:8px 0;font-size:14px;border:1px solid var(--line);background:#f8fafc}.fl-b-demo{background:#fffbeb;border-color:#f59e0b;color:#78350f}.fl-b-warn{background:#fffbeb;border-color:#fcd34d}
.fl-meta{font-size:13px;color:var(--mut);margin:8px 2px}
.fl-bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0}.fl-search{flex:1 1 260px}.fl-search input{width:100%}.fl-sr{position:absolute;left:-9999px}
.fl-chips{display:flex;gap:6px;flex-wrap:wrap}.fl-chip{border:1px solid var(--line);background:#fff;color:var(--navy);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer}.fl-chip b{margin-left:6px;color:var(--mut);font-weight:600}.fl-chip.on{background:var(--navy);border-color:var(--navy);color:#fff}.fl-chip.on b{color:#cbd5e1}
.fl-grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:16px;align-items:start}
.fl-mapbox{position:relative;isolation:isolate}.fl-map{height:clamp(380px,64vh,740px);border:1px solid var(--line);border-radius:14px;box-shadow:0 2px 8px rgba(15,39,71,.08);overflow:hidden;background:#e5e9ef}
.fl-overlay{position:absolute;z-index:500;left:12px;right:12px;bottom:12px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13px;box-shadow:0 2px 8px rgba(15,39,71,.15)}.fl-overlay-err{border-color:var(--bad);color:#991b1b}
.fl-pin{background:none;border:0}.fl-pop{min-width:150px;font-size:13px}.fl-pop-h{font-weight:700;color:var(--navy)}.fl-pop-m{color:var(--mut)}
.fl-side{display:flex;flex-direction:column;gap:12px;min-width:0}
.fl-card{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 4px rgba(15,39,71,.06);padding:14px}.fl-hint{color:var(--mut);font-size:14px}
.fl-card-h{display:flex;align-items:center;gap:10px}.fl-card-h h3{margin:0;font-size:16px}.fl-card-h small{color:var(--mut)}.fl-card-h .ghost{margin-left:auto}
.fl-dl{display:grid;gap:6px;margin:10px 0}.fl-dl>div{display:flex;justify-content:space-between;gap:12px;font-size:13px;border-bottom:1px solid #f1f5f9;padding-bottom:5px}.fl-dl dt{color:var(--mut)}.fl-dl dd{margin:0;text-align:right;overflow-wrap:anywhere}
.fl-dot::before{content:'';display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-right:6px}
.fl-alert{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:8px;padding:6px 10px;font-size:13px;margin:8px 0 0}.fl-demo-tag{background:#fffbeb;color:#92400e;border-radius:8px;padding:4px 10px;font-size:12px;font-weight:700;margin:8px 0 0}
.fl-actions{display:flex;gap:8px;flex-wrap:wrap}.fl-route{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px}
.fl-listcard{padding:0}.fl-listcard .fl-card-h{padding:12px 14px;border-bottom:1px solid var(--line)}.fl-list{list-style:none;margin:0;padding:0;max-height:340px;overflow:auto}
.fl-row{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid #f1f5f9;padding:9px 14px;cursor:pointer;color:inherit;font:inherit}.fl-row:hover{background:#f8fafc}.fl-row.on{background:#eff6ff;box-shadow:inset 3px 0 0 var(--navy)}
.fl-row-t{display:flex;flex-direction:column;min-width:0;flex:1}.fl-row-t small,.fl-row-s small{color:var(--mut);font-size:12px}.fl-row-t em{color:var(--bad);font-style:normal}.fl-row-s{display:flex;flex-direction:column;align-items:flex-end;font-size:12px;font-weight:600}
.fl-token{border:1px solid #f59e0b;background:#fffbeb;border-radius:10px;padding:10px 12px;margin:10px 0;font-size:13px}.fl-token code{display:block;margin-top:6px;word-break:break-all;background:#fff;border:1px solid var(--line);padding:6px 8px;border-radius:6px}
.fl-code{background:#0f2747;color:#e2e8f0;border-radius:8px;padding:10px;font-size:12px;overflow:auto}
@media (max-width:980px){.fl-grid{grid-template-columns:1fr}.fl-list{max-height:280px}.fl-map{height:56vh}}
`
