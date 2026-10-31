import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from 'recharts'
import type { Alert, Card, Context, Evidence, Gap, InsightCard, MetricResult, Statement } from './types'
import { KIND_LABEL, RELIABILITY_LABEL, SEVERITY_LABEL, STATE_LABEL, deltaText, fmtAge, fmtNum, fmtTime, fmtValue, usable } from './format'
import { filterHint, pageTitle, routeFor } from './links'
import type { Link as L } from './types'

/* ---------- small shared pieces ---------- */
export const StateBadge = ({ state }: { state: keyof typeof STATE_LABEL }) => <span className={'iv-state s-' + state}>{STATE_LABEL[state]}</span>
export const Sev = ({ s }: { s: Alert['severity'] }) => <span className={'iv-sev sev-' + s}>{SEVERITY_LABEL[s]}</span>
export function Kind({ k }: { k: Statement['kind'] }) { return <span className={'iv-kind k-' + k}>{KIND_LABEL[k]}</span> }
export function GoLink({ link, label }: { link?: L; label?: string }) {
  const to = routeFor(link), page = pageTitle(link), hint = filterHint(link)
  if (!to) return null
  return <span className="iv-go"><Link to={to}>{label ?? `Open ${page}`} →</Link>{hint && <small> Suggested filter: {hint}</small>}</span>
}
export function Fresh({ f, asOf }: { f?: { age_hours?: number | null; latest_source_update_at?: string | null }; asOf?: string }) {
  return <span className="iv-fresh" title={f?.latest_source_update_at ? `Latest source record: ${fmtTime(f.latest_source_update_at)}` : 'No source timestamp'}>{f ? fmtAge(f.age_hours) : ''}{asOf ? ` · as of ${fmtTime(asOf)}` : ''}</span>
}

/* ---------- metric cards ---------- */
export function MetricCard({ c }: { c: Card }) {
  const v = fmtValue(c), d = deltaText(c.comparison), to = routeFor(c.link)
  const body = (<>
    <span className="iv-card-label">{c.label}</span>
    {v !== null ? <strong className="iv-card-val">{v}<small>{c.unit && c.unit !== 'count' ? ' ' + c.unit : ''}</small></strong> : <strong className="iv-card-na">{STATE_LABEL[c.state]}</strong>}
    {v === null && c.message && <span className="iv-card-msg">{c.message}</span>}
    {v !== null && c.state === 'partial' && <span className="iv-card-msg warn">Partial data: {c.limitations[0] ?? 'some sources were unavailable'}</span>}
    {v !== null && d.text && <span className={'iv-delta d-' + d.tone}>{d.tone === 'up' && '▲ '}{d.tone === 'down' && '▼ '}{d.text}</span>}
    <span className="iv-card-foot"><span className={'iv-rel r-' + c.reliability}>{RELIABILITY_LABEL[c.reliability] ?? c.reliability}</span><Fresh f={c.freshness} /></span>
  </>)
  return to ? <Link className="iv-card clickable" to={to} aria-label={`${c.label}: ${v ?? STATE_LABEL[c.state]}. Open ${pageTitle(c.link)}`}>{body}</Link> : <div className="iv-card" role="group" aria-label={c.label}>{body}</div>
}

/* ---------- alerts ---------- */
function EvidenceList({ ev }: { ev: Evidence[] }) {
  return <ul className="iv-ev">{ev.map((e, i) => <li key={i}><b>{e.source}</b><span>{e.method}</span>{e.row_count !== null && <small>{fmtNum(e.row_count)} record(s) counted</small>}{e.record_ids.length > 0 && <small>Sample record IDs: {e.record_ids.join(', ')}</small>}{e.note && <small>{e.note}</small>}</li>)}</ul>
}
export function AlertRow({ a, defaultOpen = false }: { a: Alert; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen), id = 'al-' + a.id
  return (
    <li className={'iv-alert sev-' + a.severity}>
      <button className="iv-alert-head" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span className="iv-rank" aria-label={`Rank ${a.rank}`}>{a.rank}</span>
        <span className="iv-alert-title">{a.title}</span>
        <Sev s={a.severity} />
        <span className="iv-chev" aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      <div className="iv-alert-next"><b>Next step:</b> {a.recommended_next_step}</div>
      {open && (
        <div className="iv-alert-body" id={id}>
          <dl>
            <div><dt>Severity basis</dt><dd>{a.severity_basis}</dd></div>
            <div><dt>Metric</dt><dd>{a.metric_id} · {RELIABILITY_LABEL[a.reliability] ?? a.reliability}</dd></div>
            <div><dt>Threshold</dt><dd>{a.threshold.configured ? a.threshold.label : 'No threshold configured'}</dd></div>
            <div><dt>Reported</dt><dd>{fmtTime(a.reported_at)} · <Fresh f={a.data_freshness} /></dd></div>
            <div><dt>Sources</dt><dd>{a.source.join(', ')}</dd></div>
          </dl>
          {a.facts.filter(Boolean).length > 0 && <ul className="iv-facts">{a.facts.filter(Boolean).map((f, i) => <li key={i}>{f}</li>)}</ul>}
          <h5>Evidence</h5><EvidenceList ev={a.evidence} />
          {a.limitations.length > 0 && <><h5>Limitations</h5><ul className="iv-lim">{a.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></>}
          <GoLink link={a.link} />
        </div>)}
    </li>)
}

/* ---------- insights ---------- */
export function InsightCardView({ c }: { c: InsightCard }) {
  return (
    <article className="iv-insight" aria-label={c.title}>
      <header><h4>{c.title}</h4>{c.state !== 'available' && <StateBadge state={c.state} />}</header>
      <ul>{c.statements.map((s, i) => <li key={i}><Kind k={s.kind} /><span>{s.text}</span></li>)}</ul>
      <footer><span className="iv-src">Based on: {c.metric_ids.join(', ')}</span><GoLink link={c.link} /></footer>
    </article>)
}

/* ---------- trends ---------- */
const COLORS = ['#2563eb', '#16a34a', '#f59e0b']
const SERIES: Record<string, { title: string; keys: [string, string][]; }> = {
  'tickets.trend': { title: 'Service tickets: created vs resolved', keys: [['created', 'Created'], ['resolved', 'Resolved']] },
  'tasks.trend': { title: 'Tasks: created vs completed', keys: [['created', 'Created'], ['completed', 'Completed']] },
  'leads.trend': { title: 'Leads created', keys: [['created', 'Created']] },
}
const wk = (iso: string) => { const d = new Date(iso + 'T00:00:00'); return isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) }

export function TrendChart({ id, r }: { id: string; r: MetricResult }) {
  const cfg = SERIES[id], [table, setTable] = useState(false)
  if (!cfg) return null
  if (!usable(r)) return <section className="iv-trend"><h4>{cfg.title}</h4><div className="iv-na"><StateBadge state={r.state} /><p>{r.message || STATE_LABEL[r.state]}</p></div></section>
  const rows = r.breakdown.map(b => ({ name: wk(b.week_start), ...Object.fromEntries(cfg.keys.map(([k]) => [k, b[k] === null || b[k] === undefined ? null : b[k]])) }))
  return (
    <section className="iv-trend" aria-label={cfg.title}>
      <header><h4>{cfg.title}</h4><button className="iv-linkbtn" onClick={() => setTable(!table)} aria-pressed={table}>{table ? 'Show chart' : 'Show table'}</button></header>
      {table ? (
        <div className="iv-tablewrap"><table><caption className="sr-only">{cfg.title} by week</caption><thead><tr><th scope="col">Week starting</th>{cfg.keys.map(([k, l]) => <th scope="col" key={k}>{l}</th>)}</tr></thead>
          <tbody>{r.breakdown.map((b, i) => <tr key={i}><th scope="row">{wk(b.week_start)}</th>{cfg.keys.map(([k]) => <td key={k}>{b[k] === null || b[k] === undefined ? 'No history' : b[k]}</td>)}</tr>)}</tbody></table></div>
      ) : (
        <div className="iv-chart" role="img" aria-label={`${cfg.title}, last ${rows.length} weeks`}>
          <ResponsiveContainer width="100%" height={200}>
            {id === 'leads.trend'
              ? <BarChart data={rows}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="created" name="Created" fill={COLORS[0]} radius={[4, 4, 0, 0]} /></BarChart>
              : <LineChart data={rows}><CartesianGrid strokeDasharray="3 3" stroke="var(--line)" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Legend />{cfg.keys.map(([k, l], i) => <Line key={k} type="monotone" dataKey={k} name={l} stroke={COLORS[i]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />)}</LineChart>}
          </ResponsiveContainer>
        </div>)}
      {r.limitations.map((l, i) => <p className="iv-note" key={i}>{l}</p>)}
      <p className="iv-note"><Fresh f={r.freshness} asOf={r.as_of} /></p>
    </section>)
}

export function FlowRow({ r }: { r: MetricResult }) {
  if (!usable(r)) return <li><b>{r.label}</b><span><StateBadge state={r.state} /> {r.message}</span></li>
  const d = deltaText(r.comparison)
  const c = r.detail.created, x = r.detail.resolved ?? r.detail.completed ?? r.detail.converted
  return <li><b>{r.label}</b><span>{r.metric_id === 'expenses.summary' ? `Approved expenses ${fmtNum(r.value)}` : `${fmtNum(c)} created · ${fmtNum(x)} ${r.metric_id === 'tickets.flow' ? 'resolved' : r.metric_id === 'tasks.flow' ? 'completed' : 'converted'}`}</span><span className={'iv-delta d-' + d.tone}>{d.text || ''}</span></li>
}

/* ---------- coverage ---------- */
export function Coverage({ ctx, gaps }: { ctx: Context; gaps: Gap[] }) {
  const yn = (v: boolean | null) => (v === null ? 'Could not be determined' : v ? 'Yes' : 'No')
  return (
    <div className="iv-cov">
      <div className="iv-tablewrap"><table><caption className="sr-only">Data coverage by module</caption>
        <thead><tr><th scope="col">Module</th><th scope="col">Connected</th><th scope="col">Has records</th><th scope="col">Latest update</th><th scope="col">History</th></tr></thead>
        <tbody>{ctx.modules.map(m => <tr key={m.module}><th scope="row">{m.label}</th>
          {!m.permitted ? <td colSpan={4}><StateBadge state="no_permission" /></td> : <><td>{yn(m.connected)}</td><td>{m.connected ? yn(m.has_data) : '—'}</td><td>{m.latest_update_at ? fmtTime(m.latest_update_at) : '—'}</td><td>{m.history_days !== null ? `${m.history_days} days` : '—'}</td></>}</tr>)}</tbody></table></div>
      <div className="iv-cov-grid">
        <div><h5>Thresholds and rules</h5><ul>{ctx.thresholds.map(t => <li key={t.name}><b>{t.name}</b>: {t.configured ? 'configured' : 'No threshold configured'} <small>({t.source})</small></li>)}</ul></div>
        <div><h5>Records that cannot be linked</h5>{ctx.unlinked.length ? <ul>{ctx.unlinked.map(u => <li key={u.what}>{fmtNum(u.count)} {u.what}</li>)}</ul> : <p className="iv-note">None found.</p>}
          <h5>Data-quality findings</h5>{ctx.data_quality.length ? <ul>{ctx.data_quality.map(u => <li key={u.metric_id + u.issue}>{fmtNum(u.count)} × {u.issue.replace(/_/g, ' ')} ({u.metric_id})</li>)}</ul> : <p className="iv-note">None found.</p>}</div>
        <div><h5>Metrics that cannot be shown ({gaps.length})</h5>{gaps.length ? <ul>{gaps.map(g => <li key={g.metric_id}><b>{g.label}</b>: {STATE_LABEL[g.state]}{g.message && g.message !== STATE_LABEL[g.state] ? ` — ${g.message}` : ''}</li>)}</ul> : <p className="iv-note">Every readable metric returned data.</p>}</div>
      </div>
      <ul className="iv-notes">{ctx.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
    </div>)
}
