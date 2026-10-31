import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'
import { Drawer, Loading, Notices, fmtTime } from './opsui'

type Device = { id: string; vehicle_id: string; registration_number: string; label: string; external_id: string | null; active: boolean; last_seen_at: string | null; created_at: string }
type Listing = { items: Device[]; webhook_configured: boolean; providers: string[] }
type Created = Device & { token: string; token_notice: string }

/** Provision / revoke GPS device credentials. The token is shown exactly once; only its SHA-256 hash is stored. */
export default function FleetGpsDevices({ vehicles, onClose }: { vehicles: { id: string; registration_number: string }[]; onClose: () => void }) {
  const [data, setData] = useState<Listing | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ vehicle_id: '', label: '', external_id: '' }), [created, setCreated] = useState<Created | null>(null)
  const load = useCallback(async () => { setError(''); try { setData(await api.call<Listing>('/fleet/gps/devices', 'GET')) } catch (e) { setError((e as Error).message) } }, [])
  useEffect(() => { void load() }, [load])
  const ingest = `${typeof location === 'undefined' ? '' : location.origin}/api/gps/ingest`
  const add = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try { setCreated(await api.call<Created>('/fleet/gps/devices', 'POST', { vehicle_id: form.vehicle_id, label: form.label, external_id: form.external_id || null })); setForm({ vehicle_id: '', label: '', external_id: '' }); await load() }
    catch (x) { setError((x as Error).message) } finally { setBusy(false) }
  }
  const revoke = async (d: Device) => {
    if (!confirm(`Revoke "${d.label}" for ${d.registration_number}? The device will stop being accepted immediately.`)) return
    setBusy(true); setError('')
    try { await api.call(`/fleet/gps/devices/${d.id}/revoke`, 'POST', {}); setNotice('Device revoked.'); await load() } catch (x) { setError((x as Error).message) } finally { setBusy(false) }
  }
  const copy = (t: string) => { void navigator.clipboard?.writeText(t).then(() => setNotice('Copied.'), () => setError('Copy failed - select the text manually.')) }
  return <Drawer label="GPS devices" wide onClose={onClose}><h3 style={{ margin: 0 }}>GPS devices &amp; providers</h3>
    <p className="note">Each device is bound to one vehicle and authenticates with its own secret token. Positions are only accepted from active devices.</p>
    <Notices error={error} notice={notice} onRetry={() => void load()}/>
    {created && <div className="fl-token" role="status"><strong>Token for {created.label}</strong> — {created.token_notice}<code>{created.token}</code>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}><button className="ghost" onClick={() => copy(created.token)}>Copy token</button><button className="ghost" onClick={() => setCreated(null)}>I have stored it</button></div></div>}
    <form className="formgrid" onSubmit={add} aria-label="Add GPS device">
      <label>Vehicle *<select required value={form.vehicle_id} onChange={e => setForm({ ...form, vehicle_id: e.target.value })}><option value="">Select vehicle…</option>{vehicles.map(v => <option key={v.id} value={v.id}>{v.registration_number}</option>)}</select></label>
      <label>Device label *<input required maxLength={120} value={form.label} placeholder="e.g. Tracker unit 12" onChange={e => setForm({ ...form, label: e.target.value })}/></label>
      <label>Provider device ID / IMEI<input maxLength={120} value={form.external_id} placeholder="Only for provider webhooks" onChange={e => setForm({ ...form, external_id: e.target.value })}/></label>
      <div><button className="btn" disabled={busy}>{busy ? 'Working…' : 'Create device & token'}</button></div></form>
    {!data ? <Loading/> : <div className="ops-tablewrap"><table><thead><tr><th>Vehicle</th><th>Label</th><th>Provider ID</th><th>Last seen</th><th>Status</th><th/></tr></thead><tbody>
      {data.items.map(d => <tr key={d.id}><td>{d.registration_number}</td><td>{d.label}</td><td>{d.external_id || '—'}</td><td>{d.last_seen_at ? fmtTime(d.last_seen_at) : 'Never'}</td><td>{d.active ? 'Active' : 'Revoked'}</td>
        <td>{d.active && <button className="ghost" disabled={busy} onClick={() => void revoke(d)}>Revoke</button>}</td></tr>)}
      {!data.items.length && <tr><td colSpan={6}>No GPS devices yet.</td></tr>}</tbody></table></div>}
    <h3>Connection details</h3>
    <p className="note">Direct device / app push — <code>POST {ingest}</code> with <code>Authorization: Bearer &lt;token&gt;</code>:</p>
    <pre className="fl-code">{`{"fixes":[{"lat":17.7231,"lon":83.3012,"time":"2026-10-30T08:15:00Z","speed_kmh":32.5,"battery_pct":71,"charging":false}]}`}</pre>
    <p className="note">Provider webhook — <code>POST /api/gps/webhook/{'{provider}'}</code>, signed with <code>X-Signature: sha256=&lt;HMAC-SHA256 of body&gt;</code>. Status: {data?.webhook_configured ? 'GPS_WEBHOOK_SECRET is set.' : 'GPS_WEBHOOK_SECRET is not set (webhook disabled).'} Providers: {data?.providers.join(', ') || '—'}.</p>
  </Drawer>
}
