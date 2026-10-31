import { useEffect, useRef, useState } from 'react'
import { MAX_QUESTION_CHARS, suggestions } from './askTypes'
import type { Answer } from './askTypes'
import type { PeriodKind } from './types'
import { RELIABILITY_LABEL, STATE_LABEL, fmtTime } from './format'
import { GoLink, Kind } from './parts'
import { IntelError, intel } from './client'

interface Turn { id: number; q: string; a: Answer | null; error?: string; retry?: boolean }

/** One safe, specific sentence per failure kind. Server text is shown only for 422 (it is a validation message we wrote). */
export function askErrorMessage(e: unknown): { text: string; retry: boolean } {
  if (!(e instanceof IntelError)) return { text: 'This question could not be answered right now.', retry: true }
  switch (e.status) {
    case 401: return { text: 'Your session has expired. Please sign in again.', retry: false }
    case 403: return { text: 'You do not have permission to read the data needed for this question.', retry: false }
    case 422: return { text: e.message, retry: false }
    case 429: return { text: 'Too many requests. Please wait a minute and ask again.', retry: true }
    case 503: return { text: 'Business data is temporarily unavailable. Try again shortly.', retry: true }
    case 0: return { text: 'The server could not be reached. Check your connection and try again.', retry: true }
    default: return { text: 'This question could not be answered right now.', retry: true }
  }
}

export default function Ask({ period, aiMessage, suggested }: { period: PeriodKind; aiMessage: string; suggested?: string[] }) {
  const [text, setText] = useState(''), [turns, setTurns] = useState<Turn[]>([]), [busy, setBusy] = useState(false), seq = useRef(0), ac = useRef<AbortController | null>(null)
  useEffect(() => () => ac.current?.abort(), [])
  const ask = async (q: string) => {
    const t = q.trim(); if (!t || busy) return
    if (t.length > MAX_QUESTION_CHARS) { setTurns(x => [{ id: ++seq.current, q: t.slice(0, 60) + '…', a: null, error: `Questions may be at most ${MAX_QUESTION_CHARS} characters.` }, ...x].slice(0, 6)); return }
    const id = ++seq.current, ctl = new AbortController(); ac.current = ctl; setBusy(true); setText(''); setTurns(x => [{ id, q: t, a: null }, ...x].slice(0, 6))
    try { const a = await intel.ask(t, period, ctl.signal); setTurns(x => x.map(r => r.id === id ? { ...r, a } : r)) }
    catch (e) {
      if ((e as Error).name === 'AbortError') return
      const m = askErrorMessage(e); setTurns(x => x.map(r => r.id === id ? { ...r, error: m.text, retry: m.retry } : r))
    } finally { setBusy(false) }
  }
  const chips = suggested && suggested.length ? suggested : suggestions()
  return (
    <section className="ch-card iv-section iv-ask" aria-labelledby="iv-ask-h">
      <header className="ch-head"><span className="ch-ic" aria-hidden>💬</span><h3 id="iv-ask-h">Ask your business</h3></header>
      <p className="iv-note">{aiMessage} Answers are built from your registered business metrics only; each one shows how it was obtained.</p>
      <form className="iv-askform" onSubmit={e => { e.preventDefault(); void ask(text) }}>
        <label htmlFor="iv-q" className="sr-only">Ask a question about the business</label>
        <input id="iv-q" type="text" maxLength={300} value={text} onChange={e => setText(e.target.value)} placeholder="For example: What is delayed right now?" autoComplete="off" />
        <button className="primary" type="submit" disabled={busy || !text.trim()}>{busy ? 'Working…' : 'Ask'}</button>
      </form>
      <div className="iv-chips" role="group" aria-label="Suggested questions">{chips.map(s => <button key={s} className="iv-chip" disabled={busy} onClick={() => void ask(s)}>{s}</button>)}</div>
      <div aria-live="polite" className="iv-thread">
        {turns.map(t => (
          <article className="iv-turn" key={t.id} aria-label={'Answer to: ' + t.q}>
            <p className="iv-q"><span aria-hidden>🙋</span> {t.q}</p>
            {!t.a && !t.error && <p className="iv-note" role="status">Reading the registered metrics…</p>}
            {t.error && <div className="iv-err" role="alert"><p>{t.error}</p>{t.retry && <button className="iv-chip" disabled={busy} onClick={() => void ask(t.q)}>Try again</button>}</div>}
            {t.a && (<>
              <h4>{t.a.title}</h4>
              <ul className="iv-statements">{t.a.statements.map((s, i) => <li key={i}><Kind k={s.kind} /><span>{s.text}</span></li>)}</ul>
              {t.a.sources.length > 0 && <details className="iv-how"><summary>How this was obtained</summary>
                <ul>{t.a.sources.map((s, i) => <li key={i}><b>{s.label}</b> <code>{s.metric_id}</code> · {STATE_LABEL[s.state as keyof typeof STATE_LABEL] ?? s.state}{s.period ? ` · period ${s.period}` : ''} · calculated {fmtTime(s.as_of)}{s.updated ? ` · latest record ${fmtTime(s.updated)}` : ''}{s.reliability ? ` · ${RELIABILITY_LABEL[s.reliability] ?? s.reliability}` : ''}{s.evidence && s.evidence.length > 0 ? ` · evidence: ${s.evidence.map(e => `${e.source} (${e.method}${e.row_count != null ? `, ${e.row_count} rows` : ''})`).join('; ')}` : ''}</li>)}</ul>
                <p className="iv-note">Numbers come from the backend metric registry, not from a language model.{t.a.ai && !t.a.ai.used ? ' No AI provider was used and no business data was shared outside this system.' : ''}</p></details>}
              <GoLink link={t.a.link} />
              {t.a.followups.length > 0 && <div className="iv-chips" role="group" aria-label="Follow-up questions">{t.a.followups.map(f => <button key={f} className="iv-chip" disabled={busy} onClick={() => void ask(f)}>{f}</button>)}</div>}
            </>)}
          </article>))}
      </div>
    </section>)
}
