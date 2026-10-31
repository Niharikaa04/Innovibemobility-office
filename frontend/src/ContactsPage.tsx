import {FormEvent, useCallback, useEffect, useState} from 'react'
import {ResponsiveContainer, PieChart, Pie, Cell, Tooltip, LineChart, Line, XAxis, YAxis, CartesianGrid} from 'recharts'
import {api, download} from './api'
import {Card, DateRange, EmptyState, ErrorBanner, Field, Icon, KpiCard, Modal, PageHeader, fmtDate} from './ui'

const TYPES: [string, string][] = [['customer', 'Customer'], ['partner', 'Partner'], ['vendor', 'Vendor'], ['internal', 'Internal'], ['other', 'Other']]
const TLABEL = Object.fromEntries(TYPES) as Record<string, string>
const TCOLOR: Record<string, string> = {customer: '#2563eb', partner: '#7c3aed', vendor: '#f59e0b', internal: '#ef4444', other: '#94a3b8'}   // same hues as the KPI cards and type pills
const ORGCOL = ['#2563eb', '#10b981', '#7c3aed', '#f59e0b', '#ef4444']
const pageList = (p: number, n: number) => { const a = Array.from(new Set([1, n, p - 1, p, p + 1].filter(x => x >= 1 && x <= n))).sort((x, y) => x - y); const o: (number | string)[] = []; a.forEach((x, i) => { if (i && x - a[i - 1] > 1) o.push('…'); o.push(x) }); return o }
const COLS: [string, string][] = [['full_name', 'Name'], ['email', 'Email'], ['phone', 'Phone'], ['organization', 'Organization'], ['contact_type', 'Contact Type'], ['created_at', 'Date Added']]
const SIZE = 10
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/, PHONE = /^\+?[0-9 ()-]{7,20}$/
const blank = {full_name: '', email: '', phone: '', contact_type: 'customer', organization: '', notes: ''}
type Form = typeof blank & {id?: string}
interface Stats {this_month: Record<string, number>; total: number; by_type: Record<string, number>; growth: {month: string; new: number; total: number}[]; top_organizations: {name: string; value: number}[]}

export default function ContactsPage() {
  const [from, setFrom] = useState(''), [to, setTo] = useState('')
  const [q, setQ] = useState(''), [dq, setDq] = useState(''), [type, setType] = useState(''), [org, setOrg] = useState('')
  const [sort, setSort] = useState('created_at'), [dir, setDir] = useState<'asc' | 'desc'>('desc'), [page, setPage] = useState(1), [tick, setTick] = useState(0)
  const [rows, setRows] = useState<any[]>([]), [total, setTotal] = useState(0), [loading, setLoading] = useState(true), [err, setErr] = useState('')
  const [can, setCan] = useState({write: false, archive: false, exp: false})
  const [stats, setStats] = useState<Stats | null>(null), [statsErr, setStatsErr] = useState('')
  const [orgs, setOrgs] = useState<string[]>([])
  const [f, setF] = useState<Form>(blank), [fe, setFe] = useState<Record<string, string>>({}), [saving, setSaving] = useState(false), [formErr, setFormErr] = useState('')
  const [ok, setOk] = useState(''), [view, setView] = useState<any | null>(null), [exporting, setExporting] = useState(false), [busyId, setBusyId] = useState('')

  useEffect(() => { const t = setTimeout(() => { setDq(q.trim()); setPage(1) }, 250); return () => clearTimeout(t) }, [q])
  const range = useCallback(() => { const p = new URLSearchParams(); if (from) p.set('date_from', from); if (to) p.set('date_to', to); return p }, [from, to])
  const filters = useCallback(() => { const p = range(); if (dq) p.set('q', dq); if (type) p.set('contact_type', type); if (org) p.set('organization', org); p.set('sort', sort); p.set('dir', dir); return p }, [range, dq, type, org, sort, dir])

  useEffect(() => {   // table
    let live = true; setLoading(true)
    const p = filters(); p.set('page', String(page)); p.set('page_size', String(SIZE))
    api.call('/crm/contacts?' + p, 'GET').then(r => {
      if (!live) return
      if (!r.items.length && r.total > 0 && page > 1) { setPage(page - 1); return }
      setRows(r.items); setTotal(r.total); setCan({write: !!r.can_write, archive: !!r.can_archive, exp: !!r.can_export}); setErr('')
    }).catch(e => live && setErr(e.message)).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [filters, page, tick])
  useEffect(() => {   // metrics + charts: date range only
    let live = true
    api.call<Stats>('/crm/contacts/stats?' + range(), 'GET').then(r => { if (live) { setStats(r); setStatsErr('') } }).catch(e => live && setStatsErr(e.message))
    return () => { live = false }
  }, [range, tick])
  useEffect(() => { api.call('/crm/contacts/organizations', 'GET').then(r => setOrgs(r.items)).catch(() => {}) }, [tick])

  const pages = Math.max(1, Math.ceil(total / SIZE))
  const set = (k: keyof Form, v: string) => { setF(x => ({...x, [k]: v})); setFe(x => ({...x, [k]: ''})) }
  const reset = () => { setF(blank); setFe({}); setFormErr('') }
  const toggleSort = (k: string) => { if (sort === k) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(k); setDir('asc') }; setPage(1) }
  const anyFilter = !!(q || type || org)
  const clearFilters = () => { setQ(''); setDq(''); setType(''); setOrg(''); setPage(1) }

  async function save(e: FormEvent) {
    e.preventDefault(); if (saving) return
    const v: Record<string, string> = {}
    if (!f.full_name.trim()) v.full_name = 'Full name is required.'
    if (f.email.trim() && !EMAIL.test(f.email.trim())) v.email = 'Enter a valid email address.'
    if (f.phone.trim() && !PHONE.test(f.phone.trim())) v.phone = 'Enter a valid phone number (7–20 digits; +, spaces, () and - allowed).'
    setFe(v); if (Object.keys(v).length) return
    const body = {full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone.trim(), organization: f.organization.trim(), notes: f.notes.trim(), contact_type: f.contact_type}
    setSaving(true); setFormErr(''); setOk('')
    try {
      await api.call('/crm/contacts' + (f.id ? '/' + f.id : ''), f.id ? 'PATCH' : 'POST', body)
      setOk(f.id ? 'Contact updated.' : 'Contact added.'); reset(); setTick(t => t + 1)
    } catch (x: any) { setFormErr(x.message) } finally { setSaving(false) }
  }
  async function remove(r: any) {
    if (busyId) return
    if (!window.confirm(`Delete ${r.full_name}? The contact is archived: hidden from lists, with its data kept. Permanent deletion is not available.`)) return
    setBusyId(r.id); setOk(''); setErr('')
    try { await api.call('/crm/contacts/' + r.id, 'DELETE'); setOk('Contact deleted (archived).'); if (f.id === r.id) reset(); setTick(t => t + 1) }
    catch (x: any) { setErr(x.message) } finally { setBusyId('') }
  }
  async function exportCsv() {
    setExporting(true); setErr('')
    try { await download('/crm/contacts/export?' + filters(), `contacts-${new Date().toISOString().slice(0, 10)}.csv`) }
    catch (x: any) { setErr(x.message) } finally { setExporting(false) }
  }
  const edit = (r: any) => { setF({id: r.id, full_name: r.full_name || '', email: r.email || '', phone: r.phone || '', contact_type: r.contact_type || 'other', organization: r.organization || '', notes: r.notes || ''}); setFe({}); setFormErr(''); setOk(''); document.getElementById('f_name')?.focus() }

  const by = stats?.by_type, donut = TYPES.map(([k, l]) => ({key: k, name: l, value: by?.[k] ?? 0})).filter(d => d.value > 0)
  const tm = (k: string) => stats ? `+${stats.this_month?.[k] ?? 0} added this month` : undefined
  const maxOrg = Math.max(1, ...(stats?.top_organizations.map(o => o.value) || [1]))

  return <div className="iv-page">
    <PageHeader title="CRM & Contacts" sub="Manage your customers, partners, vendors and business contacts for InnoVibe Mobility.">
      <DateRange from={from} to={to} onChange={(a, b) => { setFrom(a); setTo(b); setPage(1) }}/>
      {can.exp && <button className="iv-btn" onClick={exportCsv} disabled={exporting || !total} title={!total ? 'No contacts to export' : undefined}><Icon n="download"/>{exporting ? 'Exporting…' : 'Export CSV'}</button>}
    </PageHeader>

    {statsErr && <ErrorBanner msg={'Metrics unavailable: ' + statsErr} onRetry={() => setTick(t => t + 1)}/>}
    <div className="iv-kpis">
      <KpiCard label="Total Contacts" value={stats?.total ?? null} icon="users" tone="green" note={tm('total')}/>
      <KpiCard label="Customers" value={by?.customer ?? null} icon="user" tone="blue" note={tm('customer')}/>
      <KpiCard label="Partners" value={by?.partner ?? null} icon="briefcase" tone="purple" note={tm('partner')}/>
      <KpiCard label="Vendors" value={by?.vendor ?? null} icon="box" tone="orange" note={tm('vendor')}/>
      <KpiCard label="Internal Contacts" value={by?.internal ?? null} icon="home" tone="red" note={tm('internal')}/>
    </div>

    <div className="iv-split" style={can.write ? undefined : {gridTemplateColumns: '1fr'}}>
      {can.write && <Card title={f.id ? 'Edit Contact' : 'Add New Contact'} icon="user">
        <form className="iv-form" onSubmit={save} noValidate aria-label={f.id ? 'Edit contact' : 'Add contact'}>
          <Field id="f_name" label="Full Name" required error={fe.full_name} wide><input id="f_name" value={f.full_name} maxLength={120} placeholder="Enter full name" onChange={e => set('full_name', e.target.value)}/></Field>
          <Field id="f_email" label="Email" error={fe.email}><input id="f_email" type="email" value={f.email} maxLength={254} placeholder="Enter email address" onChange={e => set('email', e.target.value)}/></Field>
          <Field id="f_phone" label="Phone" error={fe.phone}><input id="f_phone" type="tel" value={f.phone} placeholder="Enter phone number" onChange={e => set('phone', e.target.value)}/></Field>
          <Field id="f_type" label="Contact Type" required><select id="f_type" value={f.contact_type} onChange={e => set('contact_type', e.target.value)}>{TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field id="f_org" label="Organization"><input id="f_org" value={f.organization} maxLength={160} placeholder="Enter organization" onChange={e => set('organization', e.target.value)}/></Field>
          <Field id="f_notes" label="Notes" wide><textarea id="f_notes" value={f.notes} maxLength={2000} placeholder="Enter notes…" onChange={e => set('notes', e.target.value)}/><div className="iv-count">{f.notes.length}/2000</div></Field>
          {formErr && <div className="err" role="alert" style={{gridColumn: '1/-1', margin: 0}}>{formErr}</div>}
          <div className="iv-form-actions">
            <button className="iv-btn" disabled={saving}><Icon n="plus"/>{saving ? 'Saving…' : f.id ? 'Save changes' : 'Add contact'}</button>
            <button type="button" className="iv-btn secondary" onClick={reset} disabled={saving}>{f.id ? 'Cancel edit' : 'Clear'}</button>
          </div>
        </form>
      </Card>}

      <div className="iv-charts">
        <Card title="Contacts by Type">{!stats ? <EmptyState msg="Loading…"/> : !donut.length ? <EmptyState msg="No contacts yet. Add a contact to see the breakdown."/> :
          <div className="iv-donut">
            <div style={{height: 150, position: 'relative'}}><ResponsiveContainer><PieChart><Pie data={donut} dataKey="value" nameKey="name" innerRadius={42} outerRadius={68} stroke="none">{donut.map(d => <Cell key={d.key} fill={TCOLOR[d.key]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer>
              <div style={{position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none', textAlign: 'center', fontSize: 11}}><div><b style={{fontSize: 20, display: 'block'}}>{stats.total}</b>Total</div></div></div>
            <ul className="iv-legend">{TYPES.map(([k, l]) => <li key={k}><span className="iv-dot" style={{background: TCOLOR[k]}}/>{l}<b>{by?.[k] ?? 0}</b></li>)}</ul></div>}</Card>
        <Card title="Contacts Growth">{!stats ? <EmptyState msg="Loading…"/> : stats.growth.length < 2 ? <EmptyState msg="Growth appears once contacts have been added in more than one month."/> :
          <div style={{height: 180}}><ResponsiveContainer><LineChart data={stats.growth}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="month" fontSize={11}/><YAxis allowDecimals={false} fontSize={11}/><Tooltip formatter={(v: any, n: any) => [v, n === 'total' ? 'Total contacts' : 'Added']}/><Line dataKey="total" stroke="#2563eb" strokeWidth={2} dot={{r: 3}}/></LineChart></ResponsiveContainer></div>}</Card>
        <Card title="Top Organizations" className="span2">{!stats ? <EmptyState msg="Loading…"/> : !stats.top_organizations.length ? <EmptyState msg="No organizations recorded yet. Add an organization to a contact."/> :
          <ul className="iv-bars">{stats.top_organizations.map((o, i) => <li key={o.name}><span title={o.name}>{o.name}</span><div className="iv-bar"><i style={{width: o.value / maxOrg * 100 + '%', background: ORGCOL[i % 5]}}/></div><b>{o.value}</b></li>)}</ul>}</Card>
      </div>
    </div>

    <Card title="All Contacts" icon="users">
      <div className="iv-filters">
        <input aria-label="Search contacts" placeholder="Search name, email, phone, organization…" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { setDq(q.trim()); setPage(1) } }}/>
        <select aria-label="Filter by contact type" value={type} onChange={e => { setType(e.target.value); setPage(1) }}><option value="">All types</option>{TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <select aria-label="Filter by organization" value={org} onChange={e => { setOrg(e.target.value); setPage(1) }}><option value="">All organizations</option>{orgs.map(o => <option key={o} value={o}>{o}</option>)}</select>
        <button className="iv-btn" onClick={() => { setDq(q.trim()); setPage(1) }}><Icon n="search"/>Search</button>
        <button className="iv-btn secondary" onClick={clearFilters} disabled={!anyFilter} title={!anyFilter ? 'No filters applied' : undefined}>Clear filters</button>
        <span className="iv-reccount">{total} record(s)</span>
      </div>
      {ok && <div className="iv-ok" role="status" style={{marginBottom: 10}}>{ok}</div>}
      {err && <ErrorBanner msg={err} onRetry={() => setTick(t => t + 1)}/>}
      <div className="iv-table-wrap"><table className="iv-table">
        <thead><tr><th>#</th>{COLS.map(([k, l]) => <th key={k} aria-sort={sort === k ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}><button onClick={() => toggleSort(k)}>{l}{sort === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</button></th>)}<th>Actions</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.id}>
          <td>{(page - 1) * SIZE + i + 1}</td><td>{r.full_name}</td><td>{r.email}</td><td>{r.phone}</td><td>{r.organization}</td>
          <td><span className={'iv-pill ' + r.contact_type}>{TLABEL[r.contact_type] ?? r.contact_type}</span></td><td>{fmtDate(r.created_at)}</td>
          <td><div className="iv-rowact">
            <button className="iv-icon" aria-label={`View ${r.full_name}`} title="View" onClick={() => setView(r)}><Icon n="eye"/></button>
            {can.write && <button className="iv-icon" aria-label={`Edit ${r.full_name}`} title="Edit" onClick={() => edit(r)}><Icon n="edit"/></button>}
            {can.archive && <button className="iv-icon danger" aria-label={`Delete ${r.full_name}`} title="Delete" disabled={busyId === r.id} onClick={() => remove(r)}><Icon n="trash"/></button>}
          </div></td></tr>)}</tbody></table></div>
      {loading && <p className="note">Loading…</p>}
      {!loading && !rows.length && !err && <EmptyState msg={anyFilter || from || to ? 'No contacts match these filters.' : can.write ? 'No contacts yet. Use the form to add your first contact.' : 'No contacts yet.'}/>}
      <div className="iv-pager"><span>{total ? `Showing ${(page - 1) * SIZE + 1}–${(page - 1) * SIZE + rows.length} of ${total}` : 'No results'}</span>
        <div style={{display: 'flex', gap: 8, alignItems: 'center'}}><button className="ghost" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>Previous</button>{pageList(page, pages).map((x, i) => typeof x === 'number' ? <button key={i} className={'iv-pg' + (x === page ? ' on' : '')} aria-current={x === page ? 'page' : undefined} disabled={loading} onClick={() => setPage(x)}>{x}</button> : <span key={i}>{x}</span>)}<button className="ghost" disabled={page >= pages || loading} onClick={() => setPage(page + 1)}>Next</button></div></div>
    </Card>

    {view && <Modal title="Contact details" onClose={() => setView(null)}><dl className="iv-dl">
      <dt>Name</dt><dd>{view.full_name}</dd><dt>Email</dt><dd>{view.email || '—'}</dd><dt>Phone</dt><dd>{view.phone || '—'}</dd><dt>Organization</dt><dd>{view.organization || '—'}</dd>
      <dt>Type</dt><dd>{TLABEL[view.contact_type] ?? view.contact_type}</dd><dt>Date added</dt><dd>{fmtDate(view.created_at)}</dd><dt>Notes</dt><dd>{view.notes || '—'}</dd></dl></Modal>}
  </div>
}
