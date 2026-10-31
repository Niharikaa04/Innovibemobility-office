/* Contracts of GET /api/intelligence/* (see backend/docs/INTELLIGENCE.md section 4). Nothing here is invented client-side. */
export type MetricState = 'available' | 'partial' | 'no_data' | 'not_enough_history' | 'no_threshold_configured' | 'no_permission' | 'not_configured' | 'unavailable'
export const USABLE: MetricState[] = ['available', 'partial']
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'attention'
export type StatementKind = 'verified_fact' | 'calculated_metric' | 'possible_explanation' | 'recommendation' | 'unavailable'
export type PeriodKind = 'wow' | 'mom' | 'last_7d' | 'last_30d'

export interface Link { module?: string; filter?: Record<string, unknown>; api_path?: string }
export interface Freshness { latest_source_update_at?: string | null; age_hours?: number | null }
export interface Evidence { source: string; method: string; row_count: number | null; record_ids: string[]; note: string }
export interface Comparison { state: MetricState; message?: string; previous_value?: number; delta?: number; pct_change?: number | null; [k: string]: unknown }
export interface MetricResult {
  metric_id: string; label: string; state: MetricState; value: number | null; unit: string; message: string
  breakdown: Record<string, any>[]; detail: Record<string, any>; period: { start: string; end: string } | null
  comparison: Comparison | null; as_of: string; freshness: Freshness; evidence: Evidence[]; limitations: string[]
  threshold: { configured: boolean; label: string }; reliability: string; link: Link
}
export type Card = Omit<MetricResult, 'breakdown' | 'evidence'>
export interface Alert {
  id: string; rule_id: string; rank: number; title: string; severity: Severity; severity_basis: string; metric_id: string; value: number | null
  facts: string[]; evidence: Evidence[]; source: string[]; reported_at: string; data_freshness: Freshness
  threshold: { configured: boolean; label: string }; reliability: string; limitations: string[]; recommended_next_step: string; link: Link
}
export interface Statement { kind: StatementKind; text: string; metric_id: string | null }
export interface InsightCard { id: string; title: string; state: MetricState; statements: Statement[]; metric_ids: string[]; link: Link }
export interface Gap { metric_id: string; label: string; state: MetricState; message: string }
export interface Overview {
  as_of: string; period: { start: string; end: string }; previous_period: { start: string; end: string } | null
  cards: Card[]; top_risks: Alert[]; alerts: Alert[]; insights: InsightCard[]; gaps: Gap[]
  summary: { alerts_total: number; by_severity: Record<Severity, number>; metrics_available: number; metrics_total: number }
  generated_at: string; cached: boolean
}
export interface Trends { trends: Record<string, MetricResult>; generated_at: string; cached: boolean }
export interface ModuleInfo { module: string; label: string; permitted: boolean; connected: boolean | null; has_data: boolean | null; latest_update_at: string | null; oldest_record_at: string | null; history_days: number | null }
export interface Context {
  as_of: string; modules: ModuleInfo[]; metric_state_counts: Record<string, number>; metric_count: number; gaps: Gap[]
  unlinked: { what: string; count: number; metric_id: string }[]; data_quality: { metric_id: string; issue: string; count: number }[]
  thresholds: { name: string; configured: boolean; source: string }[]
  history: { module: string; oldest_record_at: string | null; history_days: number | null; supports_previous_period_comparison: boolean }[]
  notes: string[]; generated_at: string; cached: boolean
}
export interface Status { roles: string[]; role: string; ai: { ai_available: boolean; provider: string; degraded_mode: boolean; message: string; data_shared_with_provider: boolean }; metrics: number; periods: string[]; max_range_days: number }
