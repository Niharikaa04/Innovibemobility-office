import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './intelligence.css'
import { IntelError, intel } from './client'
import type { Context, MetricResult, Overview, PeriodKind, Status, Trends } from './types'
import { PERIODS, fmtTime } from './format'
import { AlertRow, Coverage, FlowRow, InsightCardView, MetricCard, Sev, TrendChart } from './parts'
import Ask from './Ask'

type Load<T> = { s: 'loading' } | { s: 'ok'; d: T } | { s: 'err'; status: number; msg: string }
const fail = (e: unknown): { s: 'err'; status: number; msg: string } => e instanceof IntelError ? { s: 'err', status: e.status, msg: e.message } : { s: 'err', status: 0, msg: 'Something went wrong while loading business intelligence.' }

function Problem({ status, msg, onRetry }: { status: number; msg: string; onRetry: () => void }) {
  const denied = status === 403 || status === 401, slow = status === 429
  return (
    <div className={'iv-problem' + (denied ? ' denied' : '')} role={denied ? 'status' : 'alert'}>
      <strong>{denied ? 'You do not have access to business intelligence' : slow ? 'Please slow down' : 'Business intelligence is unavailable right now'}</strong>
      <p>{msg}{denied ? ' Ask an administrator if you believe you should have access.' : ''}</p>
      {!denied && <button className="primary" onClick={onRetry}>Try again</button>}
    </div>)
}

export default function IntelligencePanel() {
  const [period, setPeriod] = useState<PeriodKind>('wow'), [tick, setTick] = useState(0)
  const [ov, setOv] = useState<Load<Overview>>({ s: 'loading' }), [tr, setTr] = useState<Load<Trends>>({ s: 'loading' })
  const [status, setStatus] = useState<Status | null>(null)
  const [ctx, setCtx] = useState<Load<Context> | null>(null), [covOpen, setCovOpen] = useState(false)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    const ac = new AbortController()
    setOv({ s: 'loading' }); setTr({ s: 'loading' }); setCtx(null)
    intel.overview(period, ac.signal).then(d => setOv({ s: 'ok', d }), e => { if (e.name !== 'AbortError') setOv(fail(e)) })
    intel.trends(period, ac.signal).then(d => setTr({ s: 'ok', d }), e => { if (e.name !== 'AbortError') setTr(fail(e)) })
    return () => ac.abort()
  }, [period, tick])
  useEffect(() => { const ac = new AbortController(); intel.status(ac.signal).then(setStatus, () => {}); return () => ac.abort() }, [])
  useEffect(() => {
    if (!covOpen) return
    const ac = new AbortController(); setCtx({ s: 'loading' })
    intel.context(period, ac.signal).then(d => setCtx({ s: 'ok', d }), e => { if (e.name !== 'AbortError') setCtx(fail(e)) })
    return () => ac.abort()
  }, [covOpen, period, tick])

  const overview = ov.s === 'ok' ? ov.d : null
  const sum = overview?.summary
  const headline = useMemo(() => {
    if (!sum) return ''
    const urgent = sum.by_severity.critical + sum.by_severity.high
    if (!sum.alerts_total) return 'No alert rule is currently triggered for the data your role can read.'
    return `${sum.alerts_total} issue${sum.alerts_total === 1 ? '' : 's'} need${sum.alerts_total === 1 ? 's' : ''} attention${urgent ? `, ${urgent} marked critical or high from recorded priority` : ''}.`
  }, [sum])
  const retry = () => setTick(t => t + 1)
  const aiMsg = status?.ai.message || (status?.ai.ai_available ? '' : 'No AI provider is configured.')

  return (
    <div className="iv" aria-busy={ov.s === 'loading'}>
      {/* ---------- header ---------- */}
      <section className="ch-card iv-section iv-head" aria-labelledby="iv-title">
        <div>
          <h2 id="iv-title">Business Intelligence</h2>
          <p className="iv-note">{status?.ai.degraded_mode !== false ? 'Deterministic mode: every figure comes from the metric registry. ' : ''}{aiMsg}</p>
        </div>
        <div className="iv-controls">
          <div className="iv-seg" role="group" aria-label="Comparison period">{PERIODS.map(p => <button key={p.id} aria-pressed={period === p.id} title={p.hint} className={period === p.id ? 'on' : ''} onClick={() => setPeriod(p.id)}>{p.label}</button>)}</div>
          <button className="ghost" onClick={retry} disabled={ov.s === 'loading'}>↻ Refresh</button>
        </div>
        {overview && <p className="iv-meta">Period {overview.period.start} to {overview.period.end}{overview.previous_period ? ` · compared with ${overview.previous_period.start} to ${overview.previous_period.end}` : ''} · generated {fmtTime(overview.generated_at)}{overview.cached ? ' (cached up to 30 s)' : ''}</p>}
      </section>

      {ov.s === 'loading' && <div className="iv-skel" role="status" aria-label="Loading business intelligence"><i /><i /><i /><i /></div>}
      {ov.s === 'err' && <Problem status={ov.status} msg={ov.msg} onRetry={retry} />}

      {overview && (<>
        {/* ---------- executive summary ---------- */}
        <section className="ch-card iv-section" aria-labelledby="iv-sum-h">
          <header className="ch-head"><span className="ch-ic" aria-hidden>🧭</span><h3 id="iv-sum-h">Executive summary</h3></header>
          <p className="iv-headline">{headline}</p>
          <div className="iv-sevrow">{(['critical', 'high', 'medium', 'low', 'attention'] as const).map(s => sum!.by_severity[s] > 0 && <span key={s} className="iv-sevcount"><Sev s={s} /> <b>{sum!.by_severity[s]}</b></span>)}</div>
          <p className="iv-note">{sum!.metrics_available} of {sum!.metrics_total} headline metrics returned data. Severity comes from priority fields already recorded on tickets, tasks, faults and thresholds; no SLA or company policy is assumed.</p>
          <div className="iv-cards">{overview.cards.map(c => <MetricCard key={c.metric_id} c={c} />)}</div>
        </section>

        <Ask period={period} aiMessage={aiMsg} suggested={status?.ask?.suggestions} />

        {/* ---------- risks ---------- */}
        <section className="ch-card iv-section" aria-labelledby="iv-risk-h">
          <header className="ch-head"><span className="ch-ic" aria-hidden>🚨</span><h3 id="iv-risk-h">Operational risks</h3></header>
          {overview.alerts.length === 0 ? <p className="iv-ok">No alert rule is triggered right now. This covers only the metrics listed under data coverage.</p> : (<>
            <ol className="iv-alerts" aria-label="Ranked issues">{(showAll ? overview.alerts : overview.top_risks).map((a, i) => <AlertRow key={a.id} a={a} defaultOpen={i === 0 && !showAll} />)}</ol>
            {overview.alerts.length > overview.top_risks.length && <button className="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show top 3 only' : `Show all ${overview.alerts.length} issues`}</button>}
            <p className="iv-note">Ranked by severity, then age of the oldest item, then number affected. Alerts are calculated when this page loads; no notification is sent and no background monitor runs.</p></>)}
        </section>

        {/* ---------- insights ---------- */}
        <section className="ch-card iv-section" aria-labelledby="iv-ins-h">
          <header className="ch-head"><span className="ch-ic" aria-hidden>💡</span><h3 id="iv-ins-h">Evidence-backed insights</h3></header>
          {overview.insights.length ? <div className="iv-insights">{overview.insights.map(c => <InsightCardView key={c.id} c={c} />)}</div> : <p className="iv-note">No insight can be built from the data your role can read.</p>}
        </section>
      </>)}

      {/* ---------- trends ---------- */}
      <section className="ch-card iv-section" aria-labelledby="iv-tr-h">
        <header className="ch-head"><span className="ch-ic" aria-hidden>📈</span><h3 id="iv-tr-h">Trends and period comparison</h3></header>
        {tr.s === 'loading' && <p className="iv-note" role="status">Loading trends…</p>}
        {tr.s === 'err' && <Problem status={tr.status} msg={tr.msg} onRetry={retry} />}
        {tr.s === 'ok' && (<>
          <div className="iv-trends">{(['tickets.trend', 'tasks.trend', 'leads.trend'] as const).map(id => tr.d.trends[id] && <TrendChart key={id} id={id} r={tr.d.trends[id]} />)}</div>
          <h4 className="iv-sub">This period vs the previous one</h4>
          <ul className="iv-flows">{(['tickets.flow', 'tasks.flow', 'leads.flow', 'expenses.summary'] as const).map(id => tr.d.trends[id] && <FlowRow key={id} r={tr.d.trends[id]} />)}</ul>
          <p className="iv-note">The size of the open backlog on an earlier date is not stored, so change is shown as created versus resolved. Weeks before the first record show “No history”, never zero.</p>
        </>)}
      </section>

      {/* ---------- coverage ---------- */}
      <section className="ch-card iv-section" aria-labelledby="iv-cov-h">
        <header className="ch-head"><span className="ch-ic" aria-hidden>🗂️</span><h3 id="iv-cov-h">Data coverage and gaps</h3>
          <button className="ghost iv-toggle" aria-expanded={covOpen} aria-controls="iv-cov" onClick={() => setCovOpen(!covOpen)}>{covOpen ? 'Hide' : 'Show'}</button></header>
        {!covOpen && overview && <p className="iv-note">{overview.gaps.length} metric(s) cannot be shown right now. Open this section to see which modules are connected, how recent their data is, and what is missing.</p>}
        <div id="iv-cov">{covOpen && (!ctx || ctx.s === 'loading' ? <p className="iv-note" role="status">Checking data sources…</p> : ctx.s === 'err' ? <Problem status={ctx.status} msg={ctx.msg} onRetry={retry} /> : <Coverage ctx={ctx.d} gaps={ctx.d.gaps} />)}</div>
      </section>
    </div>)
}
