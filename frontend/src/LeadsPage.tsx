import {FormEvent, useCallback, useEffect, useState} from 'react'
import {ResponsiveContainer, PieChart, Pie, Cell, Tooltip, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid} from 'recharts'
import {api, download} from './api'
import {Card, DateRange, EmptyState, ErrorBanner, Field, Icon, KpiCard, Modal, PageHeader, fmtDate} from './ui'
import './leads.css'

// Display stages. key/label/db_value mirror crm.py UI_STAGES (the API maps stored values to these; stored values are never rewritten).
const STAGES = [
  {key: 'new', label: 'New', db: 'new', color: '#2563eb'},
  {key: 'contacted', label: 'Contacted', db: 'contacted', color: '#60a5fa'},
  {key: 'in_discussion', label: 'In Discussion', db: 'negotiation', color: '#f59e0b'},
  {key: 'proposal', label: 'Proposal', db: 'proposal', color: '#7c3aed'},
  {key: 'converted', label: 'Converted', db: 'won', color: '#10b981'},
  {key: 'lost', label: 'Lost / Closed', db: 'lost', color: '#ef4444'},
]
const SBY = Object.fromEntries(STAGES.map(s => [s.key, s])) as Record<string, (typeof STAGES)[number]>
const SOURCES = ['Website', 'Referral', 'LinkedIn', 'Direct', 'Campaign', 'Other']
const COLS: [string, string][] = [['title', 'Lead Title'], ['contact', 'Contact'], ['organization', 'Organization'], ['', 'Email / Phone'], ['source', 'Source'], ['value', 'Estimated Value (₹)'], ['stage', 'Stage'], ['expected_closure', 'Expected Closure'], ['created_at', 'Created Date']]
const SIZE = 10
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/, PHONE = /^\+?[0-9 ()-]{7,20}$/
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const dmy = (d?: string | null) => { const m = d && /^(\d{4})-(\d{2})-(\d{2})/.exec(d); return m ? `${m[3]}-${m[2]}-${m[1]}` : '—' }   // date-only strings: no timezone shifting
const dmon = (d: string) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d); return m ? `${m[3]}-${MON[+m[2] - 1]}-${m[1]}` : d }
const inr = (v: any) => v === null || v === undefined || v === '' ? '—' : '₹ ' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2})
const inrShort = (v: number) => v >= 1e7 ? `${+(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${+(v / 1e5).toFixed(1)}L` : v >= 1e3 ? `${+(v / 1e3).toFixed(1)}K` : String(v)
const initials = (s: string) => (s || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('')
const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const dueTone = (d: string) => { const t = todayIso(); if (d < t) return 'late'; const days = (Date.parse(d) - Date.parse(t)) / 864e5; return days <= 7 ? 'soon' : 'ok' }
const pageList = (p: number, n: number) => { const a = Array.from(new Set([1, n, p - 1, p, p + 1].filter(x => x >= 1 && x <= n))).sort((x, y) => x - y); const o: (number | string)[] = []; a.forEach((x, i) => { if (i && x - a[i - 1] > 1) o.push('…'); o.push(x) }); return o }

const blank = {title: '', contact_id: '', contact_name: '', email: '', phone: '', organization: '', source: '', value: '', stage: 'new', expected_closure: '', next_follow_up: '', notes: '', lost_reason: ''}
type Form = typeof blank & {id?: string; orig_stage?: string; orig_source?: string}
interface Stats {total: {count: number; value: number}; by_stage: Record<string, {count: number; value: number}>; trend: {granularity: string; points: {period: string; count: number}[]}; growth: Record<string, {this_month: number; last_month: number; pct: number | null}>}

export default function LeadsPage() {
  const [from, setFrom] = useState(''), [to, setTo] = useState('')
  const [q, setQ] = useState(''), [dq, setDq] = useState(''), [stage, setStage] = useState(''), [source, setSource] = useState('')
  const [sort, setSort] = useState('created_at'), [dir, setDir] = useState<'asc' | 'desc'>('desc'), [page, setPage] = useState(1), [tick, setTick] = useState(0)
  const [rows, setRows] = useState<any[]>([]), [total, setTotal] = useState(0), [loading, setLoading] = useState(true), [err, setErr] = useState('')
  const [can, setCan] = useState({write: false, archive: false, exp: false}), [sources, setSources] = useState<string[]>(SOURCES)
  const [stats, setStats] = useState<Stats | null>(null), [statsErr, setStatsErr] = useState('')
  const [fups, setFups] = useState<any[] | null>(null)
  const [f, setF] = useState<Form>(blank), [fe, setFe] = useState<Record<string, string>>({}), [saving, setSaving] = useState(false), [formErr, setFormErr] = useState('')
  const [opts, setOpts] = useState<any[]>([]), [ok, setOk] = useState(''), [exporting, setExporting] = useState(false), [busyId, setBusyId] = useState('')
  const [view, setView] = useState<any | null>(null), [detail, setDetail] = useState<any | null>(null)
  const [conv, setConv] = useState<{lead: any; mark: boolean; name: string; email: string; phone: string; org: string} | null>(null), [convErr, setConvErr] = useState(''), [converting, setConverting] = useState(false)

  useEffect(() => { const t = setTimeout(() => { setDq(q.trim()); setPage(1) }, 250); return () => clearTimeout(t) }, [q])
  const range = useCallback(() => { const p = new URLSearchParams(); if (from) p.set('date_from', from); if (to) p.set('date_to', to); return p }, [from, to])
  const filters = useCallback(() => { const p = range(); if (dq) p.set('q', dq); if (stage) p.set('stage', stage); if (source) p.set('source', source); p.set('sort', sort); p.set('dir', dir); return p }, [range, dq, stage, source, sort, dir])

  useEffect(() => {   // table
    let live = true; setLoading(true)
    const p = filters(); p.set('page', String(page)); p.set('page_size', String(SIZE))
    api.call('/crm/leads?' + p, 'GET').then(r => {
      if (!live) return
      if (!r.items.length && r.total > 0 && page > 1) { setPage(page - 1); return }
      setRows(r.items); setTotal(r.total); setCan({write: !!r.can_write, archive: !!r.can_archive, exp: !!r.can_export}); if (r.sources) setSources(r.sources); setErr('')
    }).catch(e => live && setErr(e.message)).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [filters, page, tick])
  useEffect(() => {   // KPIs + charts: date range only
    let live = true
    api.call<Stats>('/crm/leads/stats?' + range(), 'GET').then(r => { if (live) { setStats(r); setStatsErr('') } }).catch(e => live && setStatsErr(e.message))
    return () => { live = false }
  }, [range, tick])
  useEffect(() => { let live = true; api.call('/crm/leads/followups?limit=5', 'GET').then(r => live && setFups(r.items)).catch(() => live && setFups([])); return () => { live = false } }, [tick])
  useEffect(() => {   // contact suggestions while typing a name (existing CRM contacts only)
    const n = f.contact_name.trim(); if (!n || f.contact_id) { setOpts([]); return }
    let live = true; const t = setTimeout(() => { api.call('/crm/contacts?page_size=6&q=' + encodeURIComponent(n), 'GET').then(r => live && setOpts(r.items)).catch(() => live && setOpts([])) }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [f.contact_name, f.contact_id])
  useEffect(() => {   // lead details + stage history
    if (!view) { setDetail(null); return }
    let live = true; api.call('/crm/leads/' + view.id, 'GET').then(r => live && setDetail(r)).catch(() => live && setDetail({activities: [], failed: true}))
    return () => { live = false }
  }, [view])

  const pages = Math.max(1, Math.ceil(total / SIZE))
  const set = (k: keyof Form, v: string) => { setF(x => ({...x, [k]: v})); setFe(x => ({...x, [k]: ''})) }
  const reset = () => { setF(blank); setFe({}); setFormErr(''); setOpts([]) }
  const toggleSort = (k: string) => { if (sort === k) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(k); setDir('asc') }; setPage(1) }
  const anyFilter = !!(q || stage || source)
  const clearFilters = () => { setQ(''); setDq(''); setStage(''); setSource(''); setPage(1) }
  const pick = (c: any) => { setF(x => ({...x, contact_id: c.id, contact_name: c.full_name, email: c.email || '', phone: c.phone || '', organization: c.organization || ''})); setOpts([]) }
  const unlink = (name: string) => setF(x => ({...x, contact_id: '', contact_name: name, email: '', phone: '', organization: ''}))
  const linked = !!f.contact_id

  async function save(e: FormEvent) {
    e.preventDefault(); if (saving) return
    const v: Record<string, string> = {}, editing = !!f.id
    if (!f.title.trim()) v.title = 'Lead title is required.'
    if (!linked && f.email.trim() && !EMAIL.test(f.email.trim())) v.email = 'Enter a valid email address.'
    if (!linked && f.phone.trim() && !PHONE.test(f.phone.trim())) v.phone = 'Enter a valid phone number (7–20 digits; +, spaces, () and - allowed).'
    if (f.value !== '' && !(Number(f.value) >= 0)) v.value = 'Enter an amount of 0 or more.'
    if (f.stage === 'lost' && (editing ? f.orig_stage !== 'lost' : true) && !f.lost_reason.trim()) v.lost_reason = 'A reason is required for a lost lead.'
    if (!linked && !editing && (f.phone.trim() || f.organization.trim()) && !f.contact_name.trim() && !f.email.trim()) v.contact_name = 'Add a contact name or email, or pick an existing contact.'
    if (!linked && editing && f.contact_name.trim()) v.contact_name = 'Pick an existing contact from the suggestions (add new contacts in CRM & Contacts), or clear this field.'
    setFe(v); if (Object.keys(v).length) return
    const b: Record<string, any> = {title: f.title.trim(), value: f.value === '' ? (editing ? null : undefined) : Number(f.value), notes: f.notes.trim() || (editing ? null : undefined),
      expected_closure: f.expected_closure || (editing ? null : undefined), next_follow_up: f.next_follow_up || (editing ? null : undefined)}
    if (f.source && (!editing || f.source !== f.orig_source)) b.source = f.source; else if (editing && !f.source && f.orig_source) b.source = null
    if (!editing || f.stage !== f.orig_stage) { b.stage = SBY[f.stage].db; if (f.stage === 'lost') b.lost_reason = f.lost_reason.trim() }
    if (linked) b.contact_id = f.contact_id; else if (editing) b.contact_id = null
    else { if (f.contact_name.trim()) b.contact_name = f.contact_name.trim(); if (f.email.trim()) b.email = f.email.trim(); if (f.phone.trim()) b.phone = f.phone.trim(); if (f.organization.trim()) b.organization = f.organization.trim() }
    setSaving(true); setFormErr(''); setOk('')
    try {
      const r = await api.call('/crm/leads' + (editing ? '/' + f.id : ''), editing ? 'PATCH' : 'POST', b)
      setOk(editing ? 'Lead updated.' : r?.contact_created ? 'Lead added. A new contact was created in CRM & Contacts.' : r?.contact_reused ? 'Lead added and linked to the existing contact with that email.' : 'Lead added.')
      reset(); setTick(t => t + 1)
    } catch (x: any) { setFormErr(x.message) } finally { setSaving(false) }
  }
  async function archive(r: any) {
    if (busyId) return
    if (!window.confirm(`Archive "${r.title}"? It is hidden from lists, with its data and history kept. Permanent deletion is not available.`)) return
    setBusyId(r.id); setOk(''); setErr('')
    try { await api.call('/crm/leads/' + r.id, 'DELETE'); setOk('Lead archived.'); if (f.id === r.id) reset(); setTick(t => t + 1) }
    catch (x: any) { setErr(x.message) } finally { setBusyId('') }
  }
  async function exportCsv() {
    setExporting(true); setErr('')
    try { await download('/crm/leads/export?' + filters(), `leads-${new Date().toISOString().slice(0, 10)}.csv`) }
    catch (x: any) { setErr(x.message) } finally { setExporting(false) }
  }
  const edit = (r: any) => {
    setF({id: r.id, orig_stage: r.stage_ui, orig_source: r.source || '', title: r.title || '', contact_id: r.contact_id || '', contact_name: r.contact_name || '', email: r.contact_email || '', phone: r.contact_phone || '', organization: r.organization || '',
      source: r.source || '', value: r.value === null || r.value === undefined ? '' : String(r.value), stage: r.stage_ui, expected_closure: r.expected_closure || '', next_follow_up: r.next_follow_up || '', notes: r.notes || '', lost_reason: ''})
    setFe({}); setFormErr(''); setOk(''); document.getElementById('l_title')?.focus()
  }
  async function convert() {
    if (!conv || converting) return
    const n = conv.name.trim(), em = conv.email.trim(), ph = conv.phone.trim()
    if (!conv.lead.contact_id && (n || em || ph || conv.org.trim())) {
      if (!n && !em) return setConvErr('Add a contact name or email, or leave the contact fields empty.')
      if (em && !EMAIL.test(em)) return setConvErr('Enter a valid email address.')
      if (ph && !PHONE.test(ph)) return setConvErr('Enter a valid phone number.')
    }
    if (conv.mark && !conv.lead.contact_id && !n && !em) return setConvErr('Link or create a contact before marking it as a customer.')
    const b: Record<string, any> = {mark_customer: conv.mark}
    if (!conv.lead.contact_id && (n || em)) b.new_contact = {contact_name: n || undefined, email: em || undefined, phone: ph || undefined, organization: conv.org.trim() || undefined}
    setConverting(true); setConvErr('')
    try { const r = await api.call('/crm/leads/' + conv.lead.id + '/convert', 'POST', b); setOk('Lead converted.' + (r.contact_created ? ' A new contact was created.' : '') + (r.contact_marked_customer ? ' Contact marked as a customer.' : '')); setConv(null); setView(null); setTick(t => t + 1) }
    catch (x: any) { setConvErr(x.message) } finally { setConverting(false) }
  }

  const bs = stats?.by_stage, donut = STAGES.map(s => ({key: s.key, name: s.label, value: bs?.[s.key]?.count ?? 0})).filter(d => d.value > 0)
  const bars = STAGES.map(s => ({key: s.key, name: s.label, value: bs?.[s.key]?.value ?? 0})), anyValue = bars.some(b => b.value > 0)
  const growth = (k: string) => { const p = stats?.growth?.[k]?.pct; return p === null || p === undefined ? undefined : `${p > 0 ? '↑ +' : p < 0 ? '↓ ' : ''}${p}% vs last month` }
  const kpi = (k: string) => bs ? bs[k]?.count ?? 0 : null
  const trend = stats?.trend.points ?? []
  const allowed = (key: string) => !f.id || STAGES.findIndex(s => s.key === key) >= STAGES.findIndex(s => s.key === f.orig_stage) || key === 'lost'
  const closed = (r: any) => r.stage_ui === 'converted' || r.stage_ui === 'lost'

  return <div className="iv-page iv-leads">
    <PageHeader title="Leads & Pipeline" sub="Track, manage, and convert sales opportunities for InnoVibe Mobility.">
      <DateRange from={from} to={to} onChange={(a, b) => { setFrom(a); setTo(b); setPage(1) }}/>
      {can.exp && <button className="iv-btn" onClick={exportCsv} disabled={exporting || !total} title={!total ? 'No leads to export' : undefined}><Icon n="download"/>{exporting ? 'Exporting…' : 'Export CSV'}</button>}
    </PageHeader>

    {statsErr && <ErrorBanner msg={'Metrics unavailable: ' + statsErr} onRetry={() => setTick(t => t + 1)}/>}
    <div className="iv-kpis iv-kpis6">
      <KpiCard label="Total Leads" value={stats?.total.count ?? null} icon="users" tone="green" note={growth('total')}/>
      <KpiCard label="New Leads" value={kpi('new')} icon="box" tone="blue" note={growth('new')}/>
      <KpiCard label="Contacted" value={kpi('contacted')} icon="user" tone="purple" note={growth('contacted')}/>
      <KpiCard label="In Discussion" value={kpi('in_discussion')} icon="briefcase" tone="orange" note={growth('in_discussion')}/>
      <KpiCard label="Converted" value={kpi('converted')} icon="home" tone="red" note={growth('converted')}/>
      <KpiCard label="Lost / Closed" value={kpi('lost')} icon="trash" tone="red" note={growth('lost')}/>
    </div>

    <div className="iv-split" style={can.write ? undefined : {gridTemplateColumns: '1fr'}}>
      {can.write && <Card title={f.id ? 'Edit Lead' : 'Add New Lead'} icon="user">
        <form className="iv-form" onSubmit={save} noValidate aria-label={f.id ? 'Edit lead' : 'Add lead'}>
          <Field id="l_title" label="Lead Title" required error={fe.title}><input id="l_title" value={f.title} maxLength={160} placeholder="Enter lead title" onChange={e => set('title', e.target.value)}/></Field>
          <Field id="l_contact" label="Contact Name" error={fe.contact_name}>
            <div className="iv-suggest-wrap">
              <input id="l_contact" value={f.contact_name} maxLength={120} autoComplete="off" placeholder="Search or type a contact name" onChange={e => linked ? unlink(e.target.value) : set('contact_name', e.target.value)}/>
              {opts.length > 0 && <ul className="iv-suggest" role="listbox" aria-label="Matching contacts">{opts.map(c => <li key={c.id}><button type="button" role="option" aria-selected={false} onClick={() => pick(c)}>{c.full_name}<small>{[c.organization, c.email].filter(Boolean).join(' · ')}</small></button></li>)}</ul>}
            </div>
            <div className="iv-hint">{linked ? 'Linked to an existing contact. Edit its details in CRM & Contacts.' : f.contact_name.trim() && !f.id ? 'No contact selected: a contact is matched by email or created.' : ' '}</div>
          </Field>
          <Field id="l_email" label="Email" error={fe.email}><input id="l_email" type="email" value={f.email} maxLength={254} readOnly={linked} placeholder="Enter email address" onChange={e => set('email', e.target.value)}/></Field>
          <Field id="l_phone" label="Phone" error={fe.phone}><input id="l_phone" type="tel" value={f.phone} readOnly={linked} placeholder="Enter phone number" onChange={e => set('phone', e.target.value)}/></Field>
          <Field id="l_org" label="Organization"><input id="l_org" value={f.organization} maxLength={160} readOnly={linked} placeholder="Enter organization" onChange={e => set('organization', e.target.value)}/></Field>
          <Field id="l_source" label="Lead Source"><select id="l_source" value={f.source} onChange={e => set('source', e.target.value)}><option value="">Select source</option>{[...sources, ...(f.source && !sources.includes(f.source) ? [f.source] : [])].map(s => <option key={s} value={s}>{s}</option>)}</select></Field>
          <Field id="l_value" label="Estimated Value (₹)" error={fe.value}><input id="l_value" type="number" min="0" step="any" value={f.value} placeholder="Enter value" onChange={e => set('value', e.target.value)}/></Field>
          <Field id="l_stage" label="Stage"><select id="l_stage" value={f.stage} disabled={!!f.id && closed({stage_ui: f.orig_stage})} onChange={e => set('stage', e.target.value)}>{STAGES.filter(s => allowed(s.key)).map(s => <option key={s.key} value={s.key}>{s.label}</option>)}</select></Field>
          {f.stage === 'lost' && f.orig_stage !== 'lost' && <Field id="l_lost" label="Reason for losing" required error={fe.lost_reason} wide><input id="l_lost" value={f.lost_reason} maxLength={500} placeholder="Why was this lead lost?" onChange={e => set('lost_reason', e.target.value)}/></Field>}
          <Field id="l_close" label="Expected Closure Date"><input id="l_close" type="date" value={f.expected_closure} onChange={e => set('expected_closure', e.target.value)}/></Field>
          <Field id="l_fup" label="Next Follow-up (optional)"><input id="l_fup" type="date" value={f.next_follow_up} onChange={e => set('next_follow_up', e.target.value)}/></Field>
          <Field id="l_notes" label="Notes" wide><textarea id="l_notes" value={f.notes} maxLength={2000} placeholder="Enter notes…" onChange={e => set('notes', e.target.value)}/><div className="iv-count">{f.notes.length}/2000</div></Field>
          {formErr && <div className="err" role="alert" style={{gridColumn: '1/-1', margin: 0}}>{formErr}</div>}
          <div className="iv-form-actions">
            <button className="iv-btn" disabled={saving}><Icon n="plus"/>{saving ? 'Saving…' : f.id ? 'Save changes' : 'Add Lead'}</button>
            <button type="button" className="iv-btn secondary" onClick={reset} disabled={saving}>{f.id ? 'Cancel edit' : 'Clear'}</button>
          </div>
        </form>
      </Card>}

      <div className="iv-charts">
        <Card title="Leads by Stage">{!stats ? <EmptyState msg="Loading…"/> : !donut.length ? <EmptyState msg="No leads in this period yet."/> :
          <div className="iv-donut">
            <div style={{height: 150, position: 'relative'}}><ResponsiveContainer><PieChart><Pie data={donut} dataKey="value" nameKey="name" innerRadius={42} outerRadius={68} stroke="none">{donut.map(d => <Cell key={d.key} fill={SBY[d.key].color}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer>
              <div style={{position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none', textAlign: 'center', fontSize: 11}}><div><b style={{fontSize: 20, display: 'block'}}>{stats.total.count}</b>Total Leads</div></div></div>
            <ul className="iv-legend">{STAGES.map(s => <li key={s.key}><span className="iv-dot" style={{background: s.color}}/>{s.label}<b>{bs?.[s.key]?.count ?? 0}</b></li>)}</ul></div>}</Card>
        <Card title="Pipeline Value by Stage (₹)">{!stats ? <EmptyState msg="Loading…"/> : !anyValue ? <EmptyState msg="No estimated values recorded yet. Add a value to a lead to see the pipeline."/> :
          <div style={{height: 180}}><ResponsiveContainer><BarChart data={bars}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name" fontSize={10} interval={0} tickFormatter={(n: string) => n.split(' ')[0]}/><YAxis fontSize={11} tickFormatter={inrShort} width={44}/><Tooltip formatter={(v: any) => [inr(v), 'Pipeline value']}/><Bar dataKey="value" radius={[3, 3, 0, 0]}>{bars.map(b => <Cell key={b.key} fill={SBY[b.key].color}/>)}</Bar></BarChart></ResponsiveContainer></div>}</Card>
        <Card title="Leads Trend">{!stats ? <EmptyState msg="Loading…"/> : trend.length < 2 ? <EmptyState msg="The trend appears once leads have been created in more than one period."/> :
          <div style={{height: 180}}><ResponsiveContainer><LineChart data={trend}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="period" fontSize={11} tickFormatter={(p: string) => stats.trend.granularity === 'month' ? MON[+p.slice(5, 7) - 1] : p.slice(5)}/><YAxis allowDecimals={false} fontSize={11}/><Tooltip formatter={(v: any) => [v, 'Leads created']}/><Line dataKey="count" stroke="#2563eb" strokeWidth={2} dot={{r: 3}}/></LineChart></ResponsiveContainer></div>}</Card>
        <Card title="Upcoming Follow-ups">{fups === null ? <EmptyState msg="Loading…"/> : !fups.length ? <EmptyState msg="No follow-ups scheduled. Set a next follow-up date on a lead."/> :
          <ul className="iv-fups">{fups.map(r => <li key={r.id}><span className="iv-av">{initials(r.contact_name || r.title)}</span><div><b>{r.title}</b><small>{[r.contact_name, r.organization].filter(Boolean).join(' · ') || 'No contact'}</small></div><time className={'due ' + dueTone(r.next_follow_up)}>{dmon(r.next_follow_up)}</time></li>)}</ul>}</Card>
      </div>
    </div>

    <Card title="All Leads" icon="users">
      <div className="iv-filters">
        <input aria-label="Search leads" placeholder="Search leads by title, contact, organization, email, or phone…" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { setDq(q.trim()); setPage(1) } }}/>
        <select aria-label="Filter by stage" value={stage} onChange={e => { setStage(e.target.value); setPage(1) }}><option value="">All stages</option>{STAGES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
        <select aria-label="Filter by source" value={source} onChange={e => { setSource(e.target.value); setPage(1) }}><option value="">All sources</option>{sources.map(s => <option key={s} value={s}>{s}</option>)}</select>
        <button className="iv-btn" onClick={() => { setDq(q.trim()); setPage(1) }}><Icon n="search"/>Search</button>
        <button className="iv-btn secondary" onClick={clearFilters} disabled={!anyFilter} title={!anyFilter ? 'No filters applied' : undefined}>Clear filters</button>
        <span className="iv-reccount">{total} record(s)</span>
      </div>
      {ok && <div className="iv-ok" role="status" style={{marginBottom: 10}}>{ok}</div>}
      {err && <ErrorBanner msg={err} onRetry={() => setTick(t => t + 1)}/>}
      <div className="iv-table-wrap"><table className="iv-table">
        <thead><tr><th>#</th>{COLS.map(([k, l]) => <th key={l} aria-sort={k && sort === k ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>{k ? <button onClick={() => toggleSort(k)}>{l}{sort === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</button> : l}</th>)}<th>Actions</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.id}>
          <td>{(page - 1) * SIZE + i + 1}</td><td>{r.title}</td><td>{r.contact_name}</td><td>{r.organization}</td>
          <td>{r.contact_email}{r.contact_email && r.contact_phone && <br/>}{r.contact_phone}</td><td>{r.source}</td><td>{inr(r.value)}</td>
          <td><span className={'iv-spill s-' + r.stage_ui}>{r.stage_label}</span></td><td>{dmy(r.expected_closure)}</td><td>{fmtDate(r.created_at)}</td>
          <td><div className="iv-rowact">
            <button className="iv-icon" aria-label={`View ${r.title}`} title="View" onClick={() => setView(r)}><Icon n="eye"/></button>
            {can.write && <button className="iv-icon" aria-label={`Edit ${r.title}`} title="Edit" onClick={() => edit(r)}><Icon n="edit"/></button>}
            {can.archive && <button className="iv-icon danger" aria-label={`Archive ${r.title}`} title="Archive" disabled={busyId === r.id} onClick={() => archive(r)}><Icon n="trash"/></button>}
          </div></td></tr>)}</tbody></table></div>
      {loading && <p className="note">Loading…</p>}
      {!loading && !rows.length && !err && <EmptyState msg={anyFilter || from || to ? 'No leads match these filters.' : can.write ? 'No leads yet. Use the form to add your first lead.' : 'No leads yet.'}/>}
      <div className="iv-pager"><span>{total ? `Showing ${(page - 1) * SIZE + 1}–${(page - 1) * SIZE + rows.length} of ${total}` : 'No results'}</span>
        <div style={{display: 'flex', gap: 8, alignItems: 'center'}}><button className="ghost" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>Previous</button>{pageList(page, pages).map((x, i) => typeof x === 'number' ? <button key={i} className={'iv-pg' + (x === page ? ' on' : '')} aria-current={x === page ? 'page' : undefined} disabled={loading} onClick={() => setPage(x)}>{x}</button> : <span key={i}>{x}</span>)}<button className="ghost" disabled={page >= pages || loading} onClick={() => setPage(page + 1)}>Next</button></div></div>
    </Card>

    {view && <Modal title="Lead details" onClose={() => setView(null)}>
      <dl className="iv-dl">
        <dt>Title</dt><dd>{view.title}</dd><dt>Stage</dt><dd><span className={'iv-spill s-' + view.stage_ui}>{view.stage_label}</span></dd>
        <dt>Contact</dt><dd>{view.contact_name || '—'}</dd><dt>Organization</dt><dd>{view.organization || '—'}</dd><dt>Email</dt><dd>{view.contact_email || '—'}</dd><dt>Phone</dt><dd>{view.contact_phone || '—'}</dd>
        <dt>Source</dt><dd>{view.source || '—'}</dd><dt>Estimated value</dt><dd>{inr(view.value)}</dd><dt>Expected closure</dt><dd>{dmy(view.expected_closure)}</dd><dt>Next follow-up</dt><dd>{dmy(view.next_follow_up)}</dd>
        {view.lost_reason && <><dt>Lost reason</dt><dd>{view.lost_reason}</dd></>}<dt>Created</dt><dd>{fmtDate(view.created_at)}</dd><dt>Notes</dt><dd>{view.notes || '—'}</dd>
      </dl>
      <h4 className="iv-sub">History</h4>
      {!detail ? <p className="note">Loading…</p> : !detail.activities.length ? <p className="note">{detail.failed ? 'History could not be loaded.' : 'No history yet.'}</p> :
        <ul className="iv-hist">{detail.activities.map((a: any) => <li key={a.id}><span>{fmtDate(a.created_at)}</span>{a.note}</li>)}</ul>}
      {can.write && !closed(view) && <div className="iv-form-actions" style={{marginTop: 12}}><button className="iv-btn" onClick={() => { setConv({lead: view, mark: false, name: '', email: '', phone: '', org: ''}); setConvErr('') }}>Convert lead</button></div>}
    </Modal>}
    {conv && <Modal title="Convert lead" onClose={() => setConv(null)}>
      <p className="note" style={{marginTop: 0}}>Marks “{conv.lead.title}” as Converted. This cannot be undone.</p>
      {conv.lead.contact_id ? <p>Linked contact: <b>{conv.lead.contact_name}</b></p> : <div className="iv-form">
        <p className="note" style={{gridColumn: '1/-1', margin: 0}}>This lead has no contact. Optionally add one (an existing contact with the same email is reused, never duplicated).</p>
        <Field id="c_name" label="Contact Name"><input id="c_name" value={conv.name} onChange={e => setConv({...conv, name: e.target.value})}/></Field>
        <Field id="c_email" label="Email"><input id="c_email" type="email" value={conv.email} onChange={e => setConv({...conv, email: e.target.value})}/></Field>
        <Field id="c_phone" label="Phone"><input id="c_phone" type="tel" value={conv.phone} onChange={e => setConv({...conv, phone: e.target.value})}/></Field>
        <Field id="c_org" label="Organization"><input id="c_org" value={conv.org} onChange={e => setConv({...conv, org: e.target.value})}/></Field></div>}
      <label className="iv-check"><input type="checkbox" checked={conv.mark} onChange={e => setConv({...conv, mark: e.target.checked})}/> Mark the contact as a customer</label>
      {convErr && <div className="err" role="alert">{convErr}</div>}
      <div className="iv-form-actions" style={{marginTop: 12}}><button className="iv-btn" disabled={converting} onClick={convert}>{converting ? 'Converting…' : 'Confirm conversion'}</button><button className="iv-btn secondary" disabled={converting} onClick={() => setConv(null)}>Cancel</button></div>
    </Modal>}
  </div>
}
