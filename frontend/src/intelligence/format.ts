import type { Card, MetricResult, MetricState } from './types'
import { USABLE } from './types'

export const STATE_LABEL: Record<MetricState, string> = {
  available: 'Available', partial: 'Partial data', no_data: 'No data recorded', not_enough_history: 'Not enough history', no_threshold_configured: 'No threshold configured',
  no_permission: 'No permission', not_configured: 'Not configured', unavailable: 'Unavailable',
}
export const KIND_LABEL: Record<string, string> = {
  verified_fact: 'Verified fact', calculated_metric: 'Calculated', possible_explanation: 'Possible explanation', recommendation: 'Recommendation', unavailable: 'Not available',
}
export const RELIABILITY_LABEL: Record<string, string> = {
  system_recorded: 'System-recorded', user_entered: 'User-entered', derived: 'Derived', statistical: 'Statistical screen',
}
export const SEVERITY_LABEL: Record<string, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', attention: 'Needs attention' }
export const usable = (r: { state: MetricState }) => USABLE.includes(r.state)

const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })
/** A value is only ever rendered for usable states. Everything else returns null so the caller shows the state text, never "0". */
export function fmtValue(r: Pick<Card, 'state' | 'value' | 'unit'>): string | null {
  if (!usable(r) || r.value === null || r.value === undefined) return null
  return nf.format(r.value)
}
export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? '—' : nf.format(n))

export function fmtTime(iso?: string | null): string {
  if (!iso) return 'unknown'
  const d = new Date(iso); if (isNaN(d.getTime())) return 'unknown'
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
export function fmtAge(h?: number | null): string {
  if (h === null || h === undefined) return 'Last update unknown'
  if (h < 1) return 'Updated under an hour ago'
  if (h < 48) return `Updated ${Math.round(h)} h ago`
  return `Updated ${Math.round(h / 24)} days ago`
}
export function deltaText(c: MetricResult['comparison'] | Card['comparison']): { text: string; tone: 'up' | 'down' | 'flat' | 'na' } {
  if (!c) return { text: '', tone: 'na' }
  if (c.state === 'not_enough_history') return { text: 'Not enough history to compare', tone: 'na' }
  if (c.state !== 'available' && c.state !== 'partial') return { text: 'Comparison unavailable', tone: 'na' }
  const d = c.delta ?? 0, p = c.pct_change
  const tone = d > 0 ? 'up' : d < 0 ? 'down' : 'flat'
  return { text: `${d > 0 ? '+' : ''}${nf.format(d)} vs previous period${p !== null && p !== undefined ? ` (${p > 0 ? '+' : ''}${p.toFixed(1)}%)` : ''}`, tone }
}
export const PERIODS: { id: 'wow' | 'mom' | 'last_7d' | 'last_30d'; label: string; hint: string }[] = [
  { id: 'wow', label: 'Week on week', hint: 'This week vs the week before' },
  { id: 'mom', label: 'Month on month', hint: 'This month vs the month before' },
  { id: 'last_7d', label: 'Last 7 days', hint: 'Rolling 7 days' },
  { id: 'last_30d', label: 'Last 30 days', hint: 'Rolling 30 days' },
]
