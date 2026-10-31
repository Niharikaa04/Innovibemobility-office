import type { Answer } from './askTypes'
import type { Context, MetricResult, Overview, PeriodKind, Status, Trends } from './types'

/** Error that keeps the HTTP status so the UI can tell "no permission" from "unavailable" from "slow down". */
export class IntelError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let r: Response
  try { r = await fetch('/api/intelligence' + path, { credentials: 'include', signal, headers: { Accept: 'application/json' } }) }
  catch (e) { if ((e as Error).name === 'AbortError') throw e; throw new IntelError(0, 'The server could not be reached.') }
  if (!r.ok) {
    const b = await r.json().catch(() => ({}))
    throw new IntelError(r.status, typeof b.detail === 'string' ? b.detail : r.status === 422 ? 'That period is not valid.' : `Request failed (${r.status}).`)
  }
  return r.json()
}

const csrfToken = () => decodeURIComponent((document.cookie.split('; ').find(c => c.startsWith('csrf=')) || '').slice(5))
async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let r: Response
  try { r = await fetch('/api/intelligence' + path, { method: 'POST', credentials: 'include', signal, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(body) }) }
  catch (e) { if ((e as Error).name === 'AbortError') throw e; throw new IntelError(0, 'The server could not be reached.') }
  if (!r.ok) {
    const b = await r.json().catch(() => ({}))
    throw new IntelError(r.status, typeof b.detail === 'string' ? b.detail : r.status === 422 ? 'That question is not valid.' : `Request failed (${r.status}).`)
  }
  return r.json()
}

const q = (period: PeriodKind) => `?period=${encodeURIComponent(period)}`
export const intel = {
  status: (s?: AbortSignal) => get<Status>('/status', s),
  overview: (p: PeriodKind, s?: AbortSignal) => get<Overview>('/overview' + q(p), s),
  trends: (p: PeriodKind, s?: AbortSignal) => get<Trends>('/trends' + q(p), s),
  context: (p: PeriodKind, s?: AbortSignal) => get<Context>('/context' + q(p), s),
  ask: (question: string, period: PeriodKind, s?: AbortSignal) => post<Answer>('/ask', { question, period }, s),
  metric: (id: string, p: PeriodKind, s?: AbortSignal) => get<{ metric: MetricResult }>(`/metrics/${encodeURIComponent(id)}` + q(p), s).then(r => r.metric),
}
