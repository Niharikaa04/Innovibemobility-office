/* "Ask your business": types and the suggested-question list.
   Answers are produced ON THE SERVER (POST /api/intelligence/ask) from the registered metrics with the caller's own role, so the browser never
   recomputes, guesses or fills in a number. The question text is only sent to that one endpoint and is never executed. */
import type { Statement } from './types'

export interface AnswerEvidence { source: string; method: string; row_count: number | null }
export interface AnswerSource { metric_id: string; label: string; state: string; as_of: string; period: string | null; updated: string | null; reliability: string; evidence?: AnswerEvidence[] }
export interface Answer {
  status: 'answer' | 'limitation' | 'no_match'
  title: string
  statements: Statement[]
  sources: AnswerSource[]
  followups: string[]
  link?: { module?: string; filter?: Record<string, unknown> }
  question_id?: string
  answered_by?: string
  generated_at?: string
  ai?: { used: boolean; provider: string; message: string }
}

/** Fallback list shown before /status has loaded; the server's own list (status.ask.suggestions) replaces it. */
export const DEFAULT_SUGGESTIONS: string[] = [
  "What needs my attention today?",
  "What are the three biggest operational risks?",
  "What is delayed right now?",
  "Why has our service backlog increased?",
  "How many approvals are pending, and where?",
  "Which service centers have the highest ticket backlog?",
  "Are any technicians handling a disproportionately large workload?",
  "Which leads need follow-up?",
  "What is happening with our receivables and expenses?",
  "Which vehicles have repeated faults?",
  "Are any connected IoT devices reporting unusual readings?",
  "Compare this month's operations with last month",
  "What information is missing from my dashboard?",
  "How is performance across teams?",
]
export const MAX_QUESTION_CHARS = 300
export function suggestions(): string[] { return DEFAULT_SUGGESTIONS }
