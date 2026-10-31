import { useRef, useState } from 'react'
import { answer, suggestions } from './ask'
import type { Answer } from './ask'
import type { MetricResult, Overview, PeriodKind } from './types'
import { RELIABILITY_LABEL, STATE_LABEL, fmtTime } from './format'
import { GoLink, Kind } from './parts'
import { IntelError } from './client'

interface Turn { id: number; q: string; a: Answer | null; error?: string }

export default function Ask({ overview, period, metric, aiMessage }: { overview: Overview | null; period: PeriodKind; metric: (id: string, p: PeriodKind) => Promise<MetricResult>; aiMessage: string }) {
  const [text, setText] = useState(''), [turns, setTurns] = useState<Turn[]>([]), [busy, setBusy] = useState(false), seq = useRef(0)
  const ask = async (q: string) => {
    const t = q.trim(); if (!t || busy) return
    const id = ++seq.current; setBusy(true); setText(''); setTurns(x => [{ id, q: t, a: null }, ...x].slice(0, 6))
    try { const a = await answer(t, { overview, period, metric }); setTurns(x => x.map(r => r.id === id ? { ...r, a } : r)) }
    catch (e) {
      const m = e instanceof IntelError ? (e.status === 403 ? 'You do not have permission to read the data needed for this question.' : e.status === 429 ? 'Too many requests. Please wait a minute and ask again.' : e.message) : 'This question could not be answered right now.'
      setTurns(x => x.map(r => r.id === id ? { ...r, error: m } : r))
    } finally { setBusy(false) }
  }
  return (
    <section className="ch-card iv-section iv-ask" aria-labelledby="iv-ask-h">
      <header className="ch-head"><span className="ch-ic" aria-hidden>💬</span><h3 id="iv-ask-h">Ask your business</h3></header>
      <p className="iv-note">{aiMessage} Answers are built from your registered business metrics only; each one shows how it was obtained.</p>
      <form className="iv-askform" onSubmit={e => { e.preventDefault(); void ask(text) }}>
        <label htmlFor="iv-q" className="sr-only">Ask a question about the business</label>
        <input id="iv-q" type="text" maxLength={300} value={text} onChange={e => setText(e.target.value)} placeholder="For example: What is delayed right now?" autoComplete="off" />
        <button className="primary" type="submit" disabled={busy || !text.trim()}>{busy ? 'Working…' : 'Ask'}</button>
      </form>
      <div className="iv-chips" role="group" aria-label="Suggested questions">{suggestions().map(s => <button key={s} className="iv-chip" disabled={busy} onClick={() => void ask(s)}>{s}</button>)}</div>
      <div aria-live="polite" className="iv-thread">
        {turns.map(t => (
          <article className="iv-turn" key={t.id} aria-label={'Answer to: ' + t.q}>
            <p className="iv-q"><span aria-hidden>🙋</span> {t.q}</p>
            {!t.a && !t.error && <p className="iv-note" role="status">Reading the registered metrics…</p>}
            {t.error && <p className="iv-err" role="alert">{t.error}</p>}
            {t.a && (<>
              <h4>{t.a.title}</h4>
              <ul className="iv-statements">{t.a.statements.map((s, i) => <li key={i}><Kind k={s.kind} /><span>{s.text}</span></li>)}</ul>
              {t.a.sources.length > 0 && <details className="iv-how"><summary>How this was obtained</summary>
                <ul>{t.a.sources.map((s, i) => <li key={i}><b>{s.label}</b> <code>{s.metric_id}</code> · {STATE_LABEL[s.state as keyof typeof STATE_LABEL] ?? s.state}{s.period ? ` · period ${s.period}` : ''} · calculated {fmtTime(s.as_of)}{s.updated ? ` · latest record ${fmtTime(s.updated)}` : ''}{s.reliability ? ` · ${RELIABILITY_LABEL[s.reliability] ?? s.reliability}` : ''}</li>)}</ul>
                <p className="iv-note">Numbers come from the backend metric registry, not from a language model.</p></details>}
              <GoLink link={t.a.link} />
              {t.a.followups.length > 0 && <div className="iv-chips" role="group" aria-label="Follow-up questions">{t.a.followups.map(f => <button key={f} className="iv-chip" disabled={busy} onClick={() => void ask(f)}>{f}</button>)}</div>}
            </>)}
          </article>))}
      </div>
    </section>)
}
