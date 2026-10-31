// Shared building blocks for the business modules (CRM, Leads, Customers, Sales, WABA).
// Inline SVG icons (Feather-style paths) are used because no icon library was confirmed in package.json.
import {ReactNode} from 'react'

const P: Record<string, ReactNode> = {
  user: <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>,
  users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>,
  briefcase: <><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></>,
  box: <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>,
  home: <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>,
  download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></>,
  edit: <><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>,
  trash: <><path d="M3 6h18"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></>,
  eye: <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>,
  plus: <><path d="M12 5v14"/><path d="M5 12h14"/></>,
  search: <><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></>,
  x: <><path d="M18 6L6 18"/><path d="M6 6l12 12"/></>,
}
export type IconName = keyof typeof P
export const Icon = ({n, size = 16}: {n: IconName; size?: number}) =>
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{P[n]}</svg>

export type Tone = 'green' | 'blue' | 'purple' | 'orange' | 'red' | 'slate'

export const fmtDate = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString('en-GB').replace(/\//g, '-') : ''

/** Page title + module-specific subtitle + right-aligned actions (export, date range). */
export function PageHeader({title, sub, children}: {title: string; sub: string; children?: ReactNode}) {
  return <div className="iv-head"><div><h1>{title}</h1><p>{sub}</p></div><div className="iv-actions">{children}</div></div>
}

/** KPI card. `value` is null while loading or unavailable (shows an em dash, never a fake zero). */
export function KpiCard({label, value, icon, tone, note}: {label: string; value: number | string | null; icon: IconName; tone: Tone; note?: string}) {
  return <div className={'iv-kpi ' + tone}><span className="iv-kpi-ic"><Icon n={icon} size={22}/></span>
    <div><small>{label}</small><strong>{value ?? '—'}</strong>{note && <em>{note}</em>}</div></div>
}

export function Card({title, icon, children, className = ''}: {title: string; icon?: IconName; children: ReactNode; className?: string}) {
  return <section className={'iv-card ' + className}><h3>{icon && <Icon n={icon}/>}{title}</h3>{children}</section>
}

/** Neutral empty state: explains what is missing and what to do. Deliberately not styled as an error. */
export const EmptyState = ({msg}: {msg: string}) => <div className="iv-empty">{msg}</div>

export function ErrorBanner({msg, onRetry}: {msg: string; onRetry?: () => void}) {
  return <div className="err" role="alert">{msg} {onRetry && <button className="ghost" onClick={onRetry}>Retry</button>}</div>
}

/** Date-range filter. Empty = all time. */
export function DateRange({from, to, onChange}: {from: string; to: string; onChange: (from: string, to: string) => void}) {
  return <div className="iv-range" role="group" aria-label="Date range">
    <label>From<input type="date" value={from} max={to || undefined} onChange={e => onChange(e.target.value, to)}/></label>
    <label>To<input type="date" value={to} min={from || undefined} onChange={e => onChange(from, e.target.value)}/></label>
    {(from || to) ? <button className="ghost" onClick={() => onChange('', '')}>All time</button> : <span className="iv-alltime">All time</span>}
  </div>
}

/** Labelled form field: label above control, control fills its grid cell. */
export function Field({id, label, required, error, wide, children}: {id: string; label: string; required?: boolean; error?: string; wide?: boolean; children: ReactNode}) {
  return <div className={'iv-field' + (wide ? ' wide' : '')}><label htmlFor={id}>{label}{required && <span className="req"> *</span>}</label>{children}{error && <p className="iv-ferr" role="alert">{error}</p>}</div>
}

export function Modal({title, onClose, children}: {title: string; onClose: () => void; children: ReactNode}) {
  return <div className="iv-modal" role="dialog" aria-modal="true" aria-label={title} onClick={e => { if (e.target === e.currentTarget) onClose() }}
    onKeyDown={e => { if (e.key === 'Escape') onClose() }}>
    <div className="iv-modal-box"><div className="iv-modal-h"><h3>{title}</h3><button className="ghost" aria-label="Close" onClick={onClose}><Icon n="x"/></button></div>{children}</div></div>
}
