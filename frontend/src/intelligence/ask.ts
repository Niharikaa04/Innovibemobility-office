/* "Ask your business": deterministic question answering over the registered metrics.
   No AI provider is connected (Stage 3 needs an approved provider), so nothing here calls a model and nothing the user types leaves the browser
   except as a metric id that is chosen from the fixed catalogue below. Every answer is composed from backend MetricResult / Overview objects,
   so it can never disagree with the cards and alerts. Questions we cannot answer reliably say so and name what is missing. */
import type { InsightCard, MetricResult, Overview, PeriodKind, Statement } from './types'
import { USABLE } from './types'
import { STATE_LABEL, fmtNum } from './format'

export interface AnswerSource { metric_id: string; label: string; state: string; as_of: string; period: string | null; updated: string | null; reliability: string }
export interface Answer {
  status: 'answer' | 'limitation' | 'no_match'
  title: string
  statements: Statement[]
  sources: AnswerSource[]
  followups: string[]
  link?: { module?: string; filter?: Record<string, unknown> }
}
export interface AskDeps { overview: Overview | null; period: PeriodKind; metric: (id: string, p: PeriodKind) => Promise<MetricResult> }

const st = (kind: Statement['kind'], text: string, metric_id: string | null = null): Statement => ({ kind, text, metric_id })
const plural = (n: number, a: string, b = a + 's') => `${fmtNum(n)} ${n === 1 ? a : b}`
const usable = (r: MetricResult) => USABLE.includes(r.state)
const src = (r: MetricResult): AnswerSource => ({ metric_id: r.metric_id, label: r.label, state: r.state, as_of: r.as_of, period: r.period ? `${r.period.start} to ${r.period.end}` : null, updated: r.freshness?.latest_source_update_at ?? null, reliability: r.reliability })
/** A metric that cannot be used is reported as such: never as zero. */
const gap = (r: MetricResult): Statement => st('unavailable', `${r.label}: ${STATE_LABEL[r.state]}${r.message ? ` (${r.message})` : ''}.`, r.metric_id)

interface Q { id: string; label: string; match: RegExp[]; run: (d: AskDeps) => Promise<Answer> }

const from = (title: string, statements: Statement[], rs: MetricResult[], followups: string[], link?: Answer['link']): Answer => ({ status: 'answer', title, statements, sources: rs.map(src), followups, link })

function fromInsight(d: AskDeps, id: string, title: string, followups: string[]): Answer {
  const card: InsightCard | undefined = d.overview?.insights.find(i => i.id === id)
  if (!card) return { status: 'answer', title, statements: [st('unavailable', 'This analysis could not be built from the data currently available to your role.')], sources: [], followups }
  const srcs = card.metric_ids.map(m => d.overview!.cards.find(c => c.metric_id === m)).filter(Boolean).map(c => ({ metric_id: c!.metric_id, label: c!.label, state: c!.state, as_of: c!.as_of, period: c!.period ? `${c!.period.start} to ${c!.period.end}` : null, updated: c!.freshness?.latest_source_update_at ?? null, reliability: c!.reliability }))
  return { status: 'answer', title, statements: card.statements, sources: srcs.length ? srcs : card.metric_ids.map(m => ({ metric_id: m, label: m, state: card.state, as_of: d.overview!.as_of, period: null, updated: null, reliability: '' })), followups, link: card.link }
}

export const QUESTIONS: Q[] = [
  { id: 'attention', label: 'What needs my attention today?', match: [/attention/, /review first/, /this morning/, /prioriti[sz]e/, /what should i (do|review)/],
    run: async d => {
      const a = d.overview?.alerts ?? []
      if (!d.overview) return { status: 'answer', title: 'What needs attention', statements: [st('unavailable', 'The overview has not loaded yet.')], sources: [], followups: [] }
      const s: Statement[] = a.length ? a.slice(0, 5).map(x => st('verified_fact', `#${x.rank} ${x.title} (${x.severity}). ${x.recommended_next_step}`, x.metric_id)) : [st('verified_fact', 'No alert rule is currently triggered for the metrics your role can read.')]
      s.push(st('unavailable', 'Ranking uses recorded severity fields only; no SLA or company policy is applied.'))
      return { status: 'answer', title: 'What needs attention first', statements: s, sources: a.slice(0, 5).map(x => ({ metric_id: x.metric_id, label: x.title, state: 'available', as_of: x.reported_at, period: null, updated: x.data_freshness?.latest_source_update_at ?? null, reliability: x.reliability })), followups: ['What is delayed right now?', 'What are the three biggest operational risks?'], link: a[0]?.link }
    } },
  { id: 'risks', label: 'What are the three biggest operational risks?', match: [/biggest.*risk/, /top.*risk/, /three.*risk/, /main risk/],
    run: async d => {
      const t = d.overview?.top_risks ?? []
      const s: Statement[] = t.length ? t.map(x => st('verified_fact', `#${x.rank} ${x.title}. Severity basis: ${x.severity_basis}`, x.metric_id)) : [st('verified_fact', 'No alert rule is currently triggered.')]
      return { status: 'answer', title: 'Top operational risks', statements: s, sources: t.map(x => ({ metric_id: x.metric_id, label: x.title, state: 'available', as_of: x.reported_at, period: null, updated: x.data_freshness?.latest_source_update_at ?? null, reliability: x.reliability })), followups: ['What needs my attention today?', 'What information is missing from my dashboard?'], link: t[0]?.link }
    } },
  { id: 'delayed', label: 'What is delayed right now?', match: [/delay/, /overdue/, /late\b/, /behind schedule/, /past (their )?due/],
    run: async d => {
      const rs = await Promise.all(['tasks.overdue', 'tickets.overdue', 'leads.followups_overdue', 'invoices.receivables'].map(m => d.metric(m, d.period)))
      const [t, k, l, i] = rs, s: Statement[] = []
      if (usable(t)) s.push(st('verified_fact', `${plural(t.value ?? 0, 'task')} past their due date${t.detail.oldest_due_date ? `; the oldest was due ${t.detail.oldest_due_date}` : ''}.`, t.metric_id)); else s.push(gap(t))
      if (usable(k)) s.push(st('verified_fact', `${plural(k.value ?? 0, 'open service ticket')} past their due date${k.detail.oldest_due_date ? `; the oldest was due ${k.detail.oldest_due_date}` : ''}.`, k.metric_id)); else s.push(gap(k))
      if (usable(l)) s.push(st('verified_fact', `${plural(l.value ?? 0, 'lead')} past their follow-up date.`, l.metric_id)); else s.push(gap(l))
      if (usable(i)) s.push(st('calculated_metric', `${plural(i.detail.overdue_count ?? 0, 'invoice')} overdue, balance ${fmtNum(i.detail.overdue_amount)} (currency as recorded on the invoices).`, i.metric_id)); else s.push(gap(i))
      return from('What is delayed', s, rs, ['Why has our service backlog increased?', 'Which leads need follow-up?'], { module: 'tickets', filter: { overdue: true } })
    } },
  { id: 'backlog', label: 'Why has our service backlog increased?', match: [/backlog/, /why.*ticket/, /service.*(increase|grow|rise)/, /overdue.*ticket/],
    run: async d => fromInsight(d, 'service_backlog', 'Service backlog', ['Which service centers have the highest ticket backlog?', 'Are any technicians handling a disproportionately large workload?']) },
  { id: 'approvals', label: 'How many approvals are pending, and where?', match: [/approval/, /pending decision/, /awaiting/],
    run: async d => {
      const r = await d.metric('approvals.pending', d.period)
      if (!usable(r)) return from('Pending approvals', [gap(r)], [r], [])
      const rows = (r.breakdown || []).filter(b => b.count)
      const s = [st('calculated_metric', `${plural(r.value ?? 0, 'decision')} waiting across modules.`, r.metric_id), ...rows.map(b => st('verified_fact', `${b.module}: ${b.count}`, r.metric_id))]
      if (r.state === 'partial') s.push(st('unavailable', `Some modules were not readable for your role or are not set up: ${r.limitations.join(' ')}`, r.metric_id))
      return from('Pending approvals', s, [r], ['What needs my attention today?', 'What is delayed right now?'], { module: 'approvals' })
    } },
  { id: 'centers', label: 'Which service centers have the highest ticket backlog?', match: [/service cent/, /garage/, /highest.*backlog/],
    run: async d => {
      const r = await d.metric('tickets.by_service_center', d.period)
      if (!usable(r)) return from('Backlog by service center', [gap(r)], [r], [])
      const s = (r.breakdown || []).slice(0, 5).map(b => st('calculated_metric', `${b.service_center ?? 'Unnamed center'}: ${b.open} open (${b.share_pct}% of open tickets), ${b.overdue} overdue.`, r.metric_id))
      if (!s.length) s.push(st('unavailable', 'No open ticket is linked to a service center.', r.metric_id))
      if (r.detail.unlinked_open) s.push(st('verified_fact', `${plural(r.detail.unlinked_open, 'open ticket')} have no service center recorded, so they cannot be attributed to any center.`, r.metric_id))
      return from('Backlog by service center', s, [r], ['Why has our service backlog increased?', 'Are any technicians handling a disproportionately large workload?'], { module: 'tickets' })
    } },
  { id: 'workload', label: 'Are any technicians handling a disproportionately large workload?', match: [/technician/, /workload/, /work ?load/, /disproportion/],
    run: async d => {
      const r = await d.metric('tickets.technician_workload', d.period)
      if (!usable(r)) return from('Technician workload', [gap(r)], [r], [])
      const x = r.detail.distribution || {}, s: Statement[] = []
      if (x.owners) s.push(st('calculated_metric', `${x.owners} technicians hold ${x.total} open tickets (average ${x.mean}); the busiest holds ${x.max} (${x.max_share_pct}%)${x.max_owner_name ? `: ${x.max_owner_name}` : ''}.`, r.metric_id))
      else s.push(st('unavailable', 'No open ticket is assigned to a technician.', r.metric_id))
      if (r.detail.unassigned_open) s.push(st('verified_fact', `${plural(r.detail.unassigned_open, 'open ticket')} are not assigned to anyone.`, r.metric_id))
      s.push(st('unavailable', 'No workload limit is configured, so the system does not label any load as disproportionate. Counts are not weighted by job size.', r.metric_id))
      return from('Technician workload', s, [r], ['Which service centers have the highest ticket backlog?'], { module: 'technicians' })
    } },
  { id: 'leads', label: 'Which leads need follow-up?', match: [/lead/, /follow.?up/, /pipeline/],
    run: async d => {
      const [f, p] = await Promise.all([d.metric('leads.followups_overdue', d.period), d.metric('leads.pipeline', d.period)])
      const s: Statement[] = []
      if (usable(f)) s.push(st('verified_fact', `${plural(f.value ?? 0, 'open lead')} past their follow-up date${f.detail.oldest_follow_up ? `; oldest follow-up date ${f.detail.oldest_follow_up}` : ''}.`, f.metric_id)); else s.push(gap(f))
      if (usable(p)) s.push(st('calculated_metric', `${plural(p.value ?? 0, 'open lead')} in the pipeline (stage values are user-entered).`, p.metric_id)); else s.push(gap(p))
      return from('Lead follow-ups', s, [f, p], ['What is delayed right now?'], { module: 'leads' })
    } },
  { id: 'finance', label: 'What is happening with our receivables and expenses?', match: [/receivable/, /expense/, /invoice/, /budget/, /spend/],
    run: async d => fromInsight(d, 'receivables_expenses', 'Receivables and expenses', ['What is delayed right now?', 'What information is missing from my dashboard?']) },
  { id: 'faults', label: 'Which vehicles have repeated faults?', match: [/repeat/, /fault/, /diagnos/, /vehicle/, /recurr/],
    run: async d => {
      const [rp, un] = await Promise.all([d.metric('diagnostics.repeated', d.period), d.metric('diagnostics.active_unlinked', d.period)])
      const s: Statement[] = []
      if (usable(rp)) s.push(st('calculated_metric', `${plural(rp.value ?? 0, 'vehicle and fault-code pair')} recorded 2 or more times in the period.`, rp.metric_id)); else s.push(gap(rp))
      if (usable(un)) s.push(st('verified_fact', `${plural(un.value ?? 0, 'active fault')} have no ticket linked.`, un.metric_id)); else s.push(gap(un))
      s.push(st('recommendation', 'Open EVcare.AI Diagnostics to see the vehicles; individual vehicle identifiers are not repeated here.'))
      return from('Repeated faults', s, [rp, un], ['Are any connected IoT devices reporting unusual readings?'], { module: 'diagnostics' })
    } },
  { id: 'iot', label: 'Are any connected IoT devices reporting unusual readings?', match: [/iot/, /telemetry/, /device/, /unusual/, /anomal/, /sensor/],
    run: async d => {
      const rs = await Promise.all(['iot.threshold_alerts', 'iot.anomalies', 'iot.connectivity'].map(m => d.metric(m, d.period))), [t, a, c] = rs, s: Statement[] = []
      if (usable(t)) s.push(st('verified_fact', `${plural(t.value ?? 0, 'reading')} outside limits someone configured (${t.detail.critical ?? 0} critical, ${t.detail.warning ?? 0} warning).`, t.metric_id)); else s.push(gap(t))
      if (usable(a)) s.push(st('calculated_metric', `${plural(a.value ?? 0, 'reading')} flagged by the statistical screen. This is not a company threshold.`, a.metric_id)); else s.push(gap(a))
      if (usable(c)) s.push(st('verified_fact', `${plural(c.value ?? 0, 'device')} beyond their own offline limit; ${c.detail.never_reported ?? 0} never reported.`, c.metric_id)); else s.push(gap(c))
      return from('IoT and telemetry', s, rs, ['Which vehicles have repeated faults?'], { module: 'iot' })
    } },
  { id: 'compare', label: "Compare this month's operations with last month", match: [/compare/, /last month/, /previous (month|week|period)/, /month.?on.?month/, /versus|vs\.?\b/],
    run: async d => {
      const p: PeriodKind = 'mom', rs = await Promise.all(['tickets.flow', 'tasks.flow', 'leads.flow', 'expenses.summary'].map(m => d.metric(m, p))), s: Statement[] = [st('calculated_metric', 'Comparison uses the current month so far against the previous month (month on month).')]
      const [tk, ts, ld, ex] = rs
      const cmp = (r: MetricResult) => r.comparison?.state === 'available' ? `Previous period ${fmtNum(r.comparison.previous_value)}${r.comparison.pct_change != null ? ` (${r.comparison.pct_change > 0 ? '+' : ''}${r.comparison.pct_change.toFixed(1)}%)` : ''}.` : 'Not enough history to compare.'
      if (usable(tk)) s.push(st('calculated_metric', `Tickets: ${tk.detail.created} created, ${tk.detail.resolved} resolved, net ${tk.detail.net_inflow >= 0 ? '+' : ''}${tk.detail.net_inflow}. ${cmp(tk)}`, tk.metric_id)); else s.push(gap(tk))
      if (usable(ts)) s.push(st('calculated_metric', `Tasks: ${ts.detail.created ?? '—'} created, ${ts.detail.completed ?? '—'} completed. ${cmp(ts)}`, ts.metric_id)); else s.push(gap(ts))
      if (usable(ld)) s.push(st('calculated_metric', `Leads: ${ld.detail.created ?? '—'} created, ${ld.detail.converted ?? '—'} converted. ${cmp(ld)}`, ld.metric_id)); else s.push(gap(ld))
      if (usable(ex)) s.push(st('calculated_metric', `Approved expenses: ${fmtNum(ex.value)}. ${cmp(ex)}`, ex.metric_id)); else s.push(gap(ex))
      s.push(st('unavailable', 'Open-backlog size at an earlier date is not stored, so only flows (created and resolved) can be compared.'))
      return from('This month vs last month', s, rs, ['Why has our service backlog increased?'])
    } },
  { id: 'missing', label: 'What information is missing from my dashboard?', match: [/missing/, /not available/, /what data/, /coverage/, /gap/],
    run: async d => {
      const g = d.overview?.gaps ?? []
      const s: Statement[] = g.length ? g.map(x => st('unavailable', `${x.label}: ${STATE_LABEL[x.state]}${x.message && x.message !== STATE_LABEL[x.state] ? ` (${x.message})` : ''}.`, x.metric_id)) : [st('verified_fact', 'Every metric your role can read returned data.')]
      return { status: 'answer', title: 'Missing or unavailable information', statements: s, sources: [], followups: ['What needs my attention today?'] }
    } },
  { id: 'teams', label: 'How is performance across teams?', match: [/team/, /performance/, /department/],
    run: async () => limitation('Team performance', 'No performance target, scoring rule or department mapping exists in the system, so teams cannot be ranked or scored reliably.', 'To answer this, someone must define the performance measures (for example on-time completion targets) and map employees to departments. What exists today: technician ticket distribution, and overdue tasks and tickets.', ['Are any technicians handling a disproportionately large workload?', 'What is delayed right now?']) },
]

function limitation(title: string, why: string, needed: string, followups: string[]): Answer {
  return { status: 'limitation', title, statements: [st('unavailable', why), st('recommendation', needed)], sources: [], followups }
}

const UNSUPPORTED: { re: RegExp; title: string; why: string; needed: string }[] = [
  { re: /gross margin|margin|profit/, title: 'Profit and margin', why: 'Profit and gross margin are not reported: the system has no approved definition or cost ledger for them.', needed: 'An agreed definition (which revenue, which costs) and a source of cost-of-service records are needed. Invoices, receivables, expenses and budgets are available.' },
  { re: /churn|retention/, title: 'Customer churn', why: 'Customer churn is not calculated: there is no approved churn definition and no recorded customer activity history to base it on.', needed: 'A definition of an active customer and dated customer activity are needed.' },
  { re: /forecast|predict|future revenue|next (quarter|year|month) revenue|projection/, title: 'Forecasts', why: 'Forecasts are not produced. Only recorded history is analysed; nothing is projected.', needed: 'A forecasting method approved by management and enough revenue history. Budget lines you entered are available.' },
  { re: /(rank|best|worst|top|bottom).*(employee|staff|people|person)|employee.*(rank|performance)/, title: 'Employee ranking', why: 'Employees are not ranked or scored: no performance measure has been defined, and doing so from activity counts would be misleading.', needed: 'An approved performance framework is required. Aggregate workload counts are available.' },
  { re: /cash (balance|flow|position)|runway|burn/, title: 'Cash position', why: 'Cash balance, burn and runway are not reported: no bank or ledger data is connected.', needed: 'A bank or accounting connection or an approved manual cash register is required.' },
]

export function suggestions(): string[] { return QUESTIONS.map(q => q.label) }

/** Resolve free text to a catalogue question. The text is only used for matching and is never sent to the server or an AI model. */
export function resolve(text: string): { kind: 'q'; q: Q } | { kind: 'limit'; a: Answer } | { kind: 'none' } {
  const t = text.toLowerCase().trim().slice(0, 300)
  if (!t) return { kind: 'none' }
  const exact = QUESTIONS.find(q => q.label.toLowerCase() === t)
  if (exact) return { kind: 'q', q: exact }
  const u = UNSUPPORTED.find(x => x.re.test(t))
  if (u) return { kind: 'limit', a: limitation(u.title, u.why, u.needed, ['What information is missing from my dashboard?', 'What needs my attention today?']) }
  let best: Q | null = null, bestScore = 0
  for (const q of QUESTIONS) { const sc = q.match.reduce((n, re) => n + (re.test(t) ? 1 : 0), 0); if (sc > bestScore) { best = q; bestScore = sc } }
  return best ? { kind: 'q', q: best } : { kind: 'none' }
}

export const NO_MATCH: Answer = {
  status: 'no_match', title: 'I cannot answer that yet',
  statements: [st('unavailable', 'No AI provider is configured, so only the registered business questions can be answered, from real data. Try one of the suggested questions.')],
  sources: [], followups: [],
}

export async function answer(text: string, d: AskDeps): Promise<Answer> {
  const r = resolve(text)
  if (r.kind === 'limit') return r.a
  if (r.kind === 'none') return { ...NO_MATCH, followups: suggestions().slice(0, 3) }
  return r.q.run(d)
}
