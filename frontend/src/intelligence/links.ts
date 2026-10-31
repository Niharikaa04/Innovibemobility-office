import { NAV, slug } from '../nav'
import type { Link } from './types'

/* Backend module keys -> the existing CEO sidebar page title. The route is built from nav.ts so it can never drift from the sidebar.
   A key with no CEO page is simply not linked (no guessing). */
const PAGE: Record<string, string> = {
  tasks: 'Tasks & Approvals', approvals: 'Tasks & Approvals', tickets: 'Service Tickets', leads: 'Leads & Pipeline', payments: 'Payments & Receivables',
  invoices: 'Revenue & Invoices', expenses: 'Expenses', budget: 'Budget & Forecast', leave: 'HR & Leave', attendance: 'Attendance', diagnostics: 'EVcare.AI Diagnostics',
  iot: 'IoT & Telemetry', technicians: 'Technicians', fleet: 'Fleet Management', garages: 'Garages & Service Centers', kpi: 'KPI Center',
}
const PAGES = new Set(((NAV as any).ceo as [string, string[]][]).flatMap(([, i]) => i))

export function routeFor(link?: Link | null): string | null {
  const t = link?.module ? PAGE[link.module] : undefined
  return t && PAGES.has(t) ? `/ceo/${slug(t)}` : null
}
export function pageTitle(link?: Link | null): string | null { const t = link?.module ? PAGE[link.module] : undefined; return t && PAGES.has(t) ? t : null }
/** The existing list screens do not read URL filters, so the filter is shown as a hint rather than silently dropped or faked. */
export function filterHint(link?: Link | null): string {
  const f = link?.filter; if (!f) return ''
  return Object.entries(f).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`).join(', ')
}
