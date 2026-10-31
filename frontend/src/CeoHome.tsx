import { useState } from 'react';
import { Link } from 'react-router-dom';
import { NAV, slug, TABMAP, KPI_SOURCE, NEEDS_MONITORING } from './nav';
import { Chart } from './Charts';
import { lazy, Suspense } from 'react';
import { Loading } from './opsui';
import ErrorBoundary from './intelligence/ErrorBoundary';
const IntelligencePanel = lazy(() => import('./intelligence/IntelligencePanel'));     // code-split: loaded only when the AI Insights tab is opened
import './ceo-home.css';

/* Put these in frontend/public/assets/. A missing file is hidden, not shown broken. */
const HERO_BG = '/ceo-hero-bg.png';
const HERO_PERSON = '/assets/ceo-person.png';
const LOGO = '/assets/logo.png';

const KPI_ICON: Record<string, [string, string]> = {
  'Total Revenue': ['₹', 'green'],
  'Gross Margin': ['%', 'blue'],
  'Active Customers': ['👥', 'purple'],
  'Service Tickets': ['🔧', 'orange'],
  'New Leads': ['🎯', 'red'],
  'Cash Balance': ['👛', 'blue'],
};

const RANGES: [string, number][] = [['7D', 7], ['30D', 30], ['3M', 90], ['6M', 180], ['1Y', 365]];

/* ---------- Routing: find the real sidebar page by keyword so slugs always match nav.ts ---------- */
const PORTAL = 'ceo';
const ITEMS: string[] = ((NAV as any)[PORTAL] || []).flatMap(([, i]: any) => i);

function go(...words: string[]): string | null {
  for (const w of words) {
    const hit = ITEMS.find((i) => i.toLowerCase().includes(w));
    if (hit) return `/${PORTAL}/${slug(hit)}`;
  }
  return null;
}

const KPI_GO: Record<string, string[]> = {
  'Total Revenue': ['revenue'],
  'Gross Margin': ['revenue'],
  'Active Customers': ['customers'],
  'Service Tickets': ['service tickets', 'tickets'],
  'New Leads': ['leads'],
  'Cash Balance': ['payments', 'invoices'],
};

function panelGo(title: string): string | null {
  const t = title.toLowerCase();
  if (/customer/.test(t)) return go('customers');
  if (/ticket|cities/.test(t)) return go('service tickets', 'tickets');
  if (/lead|pipeline/.test(t)) return go('leads');
  if (/revenue|profit|expense/.test(t)) return go('revenue');
  if (/startup/.test(t)) return go('startup');
  if (/activity/.test(t)) return go('unified inbox', 'audit');
  if (/insight/.test(t)) return go('kpi', 'reports');
  if (/alert|upcoming/.test(t)) return go('tasks');
  return null;
}

function panelIcon(title: string): string {
  const t = title.toLowerCase();
  if (/revenue|profit|expense/.test(t)) return '📈';
  if (/customer/.test(t)) return '👥';
  if (/ticket status/.test(t)) return '🎫';
  if (/startup/.test(t)) return '🚀';
  if (/lead|pipeline/.test(t)) return '🧲';
  if (/cities/.test(t)) return '📍';
  if (/activity/.test(t)) return '🕘';
  if (/insight/.test(t)) return '💡';
  if (/alert|upcoming/.test(t)) return '🔔';
  return '📊';
}

/* trend text: colour by sign, neutral when it is only a status ("No data yet", "last 30 days") */
function tone(t?: string, off?: boolean) {
  if (off) return 'warn';
  if (!t) return 'neutral';
  const s = t.trim();
  if (/^[-−▼]/.test(s)) return 'down';
  if (/^[+▲]/.test(s)) return 'up';
  return 'neutral';
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const hide = (e: React.SyntheticEvent<HTMLImageElement>) => { e.currentTarget.style.display = 'none'; };

export default function CeoHome({
  profile, data, err, layout: L, onRetry, from, to, setFrom, setTo, onDownload,
}: {
  profile: any; data: any; err: string; layout: any; onRetry: () => void;
  from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void; onDownload: () => void;
}) {
  const [tab, setTab] = useState(0);
  const [range, setRange] = useState('');
  const [personOk, setPersonOk] = useState(true);

  const name = profile?.name || 'CEO';
  const nc = !!data?.not_configured?.includes('monitoring');
  const all = L.rows.flat();
  const t = L.tabs[tab];

  const card = (p: any) => {
    const link = panelGo(p.t);
    return (
      <section className={'ch-card t-' + p.type} key={p.k}>
        <header className="ch-head">
          <span className="ch-ic" aria-hidden>{panelIcon(p.t)}</span>
          <h3>{p.t}</h3>
          {link && <Link className="ch-link" to={link}>View all →</Link>}
        </header>
        <div className="ch-body">
          <Chart p={p} d={data?.panels?.[p.k] || []} nc={nc && NEEDS_MONITORING.includes(p.k)} />
        </div>
      </section>
    );
  };

  const pickRange = (label: string, days: number) => {
    setRange(label);
    setFrom(iso(new Date(Date.now() - days * 86400000)));
    setTo(iso(new Date()));
  };

  return (
    <div className="ceo-home">
      {/* ---------- Hero ---------- */}
      <section className={'hero' + (personOk ? '' : ' no-person')} style={{ backgroundImage: `url(${HERO_BG})` }}>
        {personOk && (
          <div className="hero-person"><img src={HERO_PERSON} alt="" onError={() => setPersonOk(false)} /></div>
        )}
        <div className="hero-text">
          <h1>Welcome back,<span>{name} 👋</span></h1>
          <p>Here’s your executive overview of InnoVibe Mobility’s business, operations and growth.</p>
          <blockquote>
            Driving cleaner, smarter and more connected mobility for a better future.
            <cite>— InnoVibe Mobility</cite>
          </blockquote>
        </div>
        <div className="hero-brand">
          <img src={LOGO} alt="InnoVibe Mobility" onError={hide} />
          <small>Sustainable Mobility<br />for a Cleaner Tomorrow</small>
        </div>
      </section>

      {err && (
        <div className="ch-err" role="alert">{err}<button onClick={onRetry}>Retry</button></div>
      )}

      {/* ---------- KPI cards (real values only) ---------- */}
      <div className="kpi-row">
        {L.kpis.map((k: string) => {
          const v = data?.kpis?.[k];
          const src = (KPI_SOURCE as any)[k];
          const off = !!(src && data?.not_configured?.includes(src));
          const [ic, ic_tone] = KPI_ICON[k] || [k[0], 'blue'];
          const link = go(...(KPI_GO[k] || []));
          const Wrap: any = link ? Link : 'div';
          const trend = v?.trend ?? (off ? 'Not configured' : data ? 'No data yet' : 'Loading…');
          return (
            <Wrap className={'kpi-card' + (link ? ' clickable' : '')} key={k} {...(link ? { to: link } : {})}>
              <div className="kpi-top">
                <span className={'kpi-ic ' + ic_tone} aria-hidden>{ic}</span>
                <div>
                  <span className="kpi-name">{k}</span>
                  <strong>{v?.value ?? '—'}</strong>
                </div>
              </div>
              <div className="kpi-mid">
                <em className={'kpi-trend ' + tone(v?.trend, off)}>
                  {tone(v?.trend, off) === 'up' && '▲ '}{tone(v?.trend, off) === 'down' && '▼ '}{trend}
                </em>
                {v?.note && <small className="kpi-note">{v.note}</small>}
              </div>
              {link && <span className="kpi-more">View Details →</span>}
            </Wrap>
          );
        })}
      </div>

      {/* ---------- Tabs + filters ---------- */}
      <div className="filter-row">
        <div className="tab-strip" role="tablist">
          {L.tabs.map((x: string, i: number) => (
            <button key={x} role="tab" aria-selected={i === tab} className={i === tab ? 'on' : ''} onClick={() => setTab(i)}>
              {x}
            </button>
          ))}
        </div>
        <div className="filters">
          <input type="date" aria-label="From date" value={from} onChange={(e) => { setRange(''); setFrom(e.target.value); }} />
          <span className="to">To</span>
          <input type="date" aria-label="To date" value={to} onChange={(e) => { setRange(''); setTo(e.target.value); }} />
          <div className="pills">
            {RANGES.map(([l, d]) => (
              <button key={l} className={range === l ? 'on' : ''} onClick={() => pickRange(l, d)}>{l}</button>
            ))}
          </div>
          <button className="ghost" onClick={() => { setRange(''); setFrom(''); setTo(''); }}>Clear</button>
          <button className="primary" onClick={onDownload}>⬇ Download Report (CSV)</button>
        </div>
      </div>

      {/* ---------- Panels ---------- */}
      {tab === 0 ? (
        L.rows.map((r: any[], i: number) => (
          <div className={'panel-row n' + r.length + ' r' + i} key={i}>{r.map(card)}</div>
        ))
      ) : t === 'Reports' ? (
        <section className="ch-card">
          <header className="ch-head"><h3>Reports</h3></header>
          <p className="muted">Exports the KPIs and panel data currently loaded as a CSV file.</p>
          <button className="primary" onClick={onDownload}>Download CSV</button>
        </section>
      ) : t === 'AI Insights' ? (
        <ErrorBoundary label="AI Insights"><Suspense fallback={<Loading />}><IntelligencePanel /></Suspense></ErrorBoundary>
      ) : (
        <div className="panel-row n3 r0">
          {((TABMAP as any)['ceo']?.[t] || []).map((k: string) => all.find((p: any) => p.k === k)).filter(Boolean).map(card)}
        </div>
      )}
    </div>
  );
}
