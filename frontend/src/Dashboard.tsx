import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { api, DashData, User } from './api';
import {
  NAV,
  LAYOUT,
  TABMAP,
  slug,
  NEEDS_MONITORING,
  KPI_SOURCE,
  PORTAL_NAMES,
  Panel,
} from './nav';

import { Chart, Empty } from './Charts';
import Shell from './Shell';
import CeoHome from './CeoHome';
import { useProfile } from './useProfile';
import LeadsPage from './LeadsPage';
import ContactsPage from './ContactsPage';
import Tasks from './Tasks';
import Attendance from './Attendance';
import Leave from './Leave';
import { Employees, AuditLog } from './People';
import Workspace from './Workspace';
import Tickets from './Tickets';
import Fleet from './Fleet';
import Garages from './Garages';
import Technicians from './Technicians';
import Diagnostics from './Diagnostics';
import Iot from './Iot';
import { Invoices, Payments, Expenses, Budget } from './Finance';
import Customers from './Customers';
import SalesMarketing from './SalesMarketing';

const TASKS = ['tasks-and-approvals', 'my-tasks', 'tasks'];
const EMPLOYEES = ['employees', 'employee-directory', 'team-management'];
const AUDIT = ['audit-log', 'logs-and-audit'];
const ATTENDANCE = ['attendance'];
const LEAVE = ['hr-and-leave', 'leave', 'leave-requests'];
const TICKETS = ['service-tickets', 'ticket-queue', 'service-platform'];
const FLEET = ['fleet-management', 'vehicle-directory'];
const DIAG = ['evcare-ai-diagnostics', 'evcare-ai'];
const CUSTOMERS = ['customers-fleets-oems', 'customers', 'customers-view'];
const PAYMENTS = ['payments-and-receivables', 'payments-and-invoices'];

function csv(L: any, d: DashData | null) {
  const q = (v: any) => '"' + String(v ?? '').replace(/"/g, '""') + '"';

  const rows: any[][] = [['Section', 'Item', 'Value']];

  L.kpis.forEach((k: string) =>
    rows.push(['KPI', k, d?.kpis?.[k]?.value ?? 'Not available'])
  );

  Object.entries(d?.panels || {}).forEach(([k, a]) =>
    (a as any[]).forEach((r) =>
      rows.push([k, r.name ?? r.title ?? '', JSON.stringify(r)])
    )
  );

  const b = new Blob([rows.map((r) => r.map(q).join(',')).join('\n')], {
    type: 'text/csv',
  });

  const a = document.createElement('a');
  const url = URL.createObjectURL(b);

  a.href = url;
  a.download = `${L.title.replace(/\s+/g, '-')}-${new Date()
    .toISOString()
    .slice(0, 10)}.csv`;
  a.click();

  URL.revokeObjectURL(url);
}

export function PanelCard({
  p,
  data,
  nc,
}: {
  p: Panel;
  data: DashData | null;
  nc: boolean;
}) {
  return (
    <section className="panel">
      <h3>{p.t}</h3>
      <Chart
        p={p}
        d={data?.panels?.[p.k] || []}
        nc={nc && NEEDS_MONITORING.includes(p.k)}
      />
    </section>
  );
}

export default function Dashboard({
  user,
  portal,
  onLogout,
}: {
  user: User;
  portal: string;
  onLogout: () => void;
}) {
  const L = LAYOUT[portal];
  const { slug: sl } = useParams();
  const profile = useProfile(user);

  const [tab, setTab] = useState(0);
  const [data, setData] = useState<DashData | null>(null);
  const [err, setErr] = useState('');
  const [tries, setTries] = useState(0);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  useEffect(() => {
    setData(null);
    setErr('');
    setTab(0);

    if (L && !sl) {
      api
        .dashboard(portal, dateFrom || undefined, dateTo || undefined)
        .then(setData)
        .catch((e) => setErr(e.message));
    }
  }, [portal, sl, tries, dateFrom, dateTo]);

  const nc = !!data?.not_configured?.includes('monitoring');

  const mod = sl
    ? NAV[portal].flatMap(([, i]) => i).find((i) => slug(i) === sl)
    : null;

  /* ---------- CEO home: new design ---------- */
  if (portal === 'ceo' && !sl && L) {
    return (
      <Shell user={user} portal={portal} onLogout={onLogout}>
        <CeoHome
          profile={profile}
          data={data}
          err={err}
          layout={L}
          onRetry={() => setTries(tries + 1)}
          from={dateFrom}
          to={dateTo}
          setFrom={setDateFrom}
          setTo={setDateTo}
          onDownload={() => csv(L, data)}
        />
      </Shell>
    );
  }

  /* ---------- Every other page ---------- */
  let body;

  if (sl === 'crm-and-contacts') body = <ContactsPage key={sl} />;
  else if (sl === 'leads-and-pipeline') body = <LeadsPage key={sl} />;
  else if (sl && TASKS.includes(sl)) body = <Tasks key={sl} />;
  else if (sl && EMPLOYEES.includes(sl)) body = <Employees key={sl} />;
  else if (sl && AUDIT.includes(sl)) body = <AuditLog key={sl} />;
  else if (sl && ATTENDANCE.includes(sl)) body = <Attendance key={sl} />;
  else if (sl && LEAVE.includes(sl)) body = <Leave key={sl} />;
  else if (sl && TICKETS.includes(sl)) body = <Tickets key={sl} />;
  else if (sl && FLEET.includes(sl)) body = <Fleet key={sl} />;
  else if (sl === 'garages-and-service-centers') body = <Garages key={sl} />;
  else if (sl === 'technicians') body = <Technicians key={sl} />;
  else if (sl && DIAG.includes(sl)) body = <Diagnostics key={sl} />;
  else if (sl === 'iot-and-telemetry') body = <Iot key={sl} />;
  else if (sl && CUSTOMERS.includes(sl)) body = <Customers key={sl} />;
  else if (sl === 'sales-and-marketing') body = <SalesMarketing key={sl} />;
  else if (sl === 'revenue-and-invoices') body = <Invoices key={sl} />;
  else if (sl && PAYMENTS.includes(sl)) body = <Payments key={sl} />;
  else if (sl === 'expenses') body = <Expenses key={sl} />;
  else if (sl === 'budget-and-forecast') body = <Budget key={sl} />;
  else if (
    !sl &&
    !L &&
    NAV[portal] &&
    TASKS.includes(slug(NAV[portal][0][1][0]))
  ) {
    body = <Tasks key="home" />;
  } else if (sl) {
    body = mod ? (
      <Workspace key={sl} title={mod} />
    ) : (
      <div className="panel">
        <h3>Page not found</h3>
        <Empty msg="That page does not exist in this portal." />
      </div>
    );
  } else if (!L) {
    body = (
      <div className="panel">
        <h3>{PORTAL_NAMES[portal]} workspace</h3>
        <Empty msg="Pick a page from the menu. Its data modules are not implemented yet." />
      </div>
    );
  } else {
    const all = L.rows.flat();
    const t = L.tabs[tab];

    body = (
      <>
        {err && (
          <div className="err" role="alert">
            {err}
            <button className="ghost" onClick={() => setTries(tries + 1)}>
              Retry
            </button>
          </div>
        )}

        <div className="kpis">
          {L.kpis.map((k) => {
            const v = data?.kpis?.[k];
            const src = KPI_SOURCE[k];
            const off = src && data?.not_configured?.includes(src);

            return (
              <div className="kpi" key={k}>
                <div className="ic" aria-hidden>
                  {k[0]}
                </div>
                <div>
                  <span>{k}</span>
                  <strong>{v?.value ?? '—'}</strong>
                  <em className={off ? 'warn' : ''}>
                    {v?.trend ??
                      (off
                        ? 'Not configured'
                        : data
                          ? 'No data yet'
                          : 'Loading…')}
                  </em>
                </div>
              </div>
            );
          })}
        </div>

        <div className="tabs" role="tablist">
          {L.tabs.map((x, i) => (
            <button
              key={x}
              role="tab"
              aria-selected={i === tab}
              className={'tab' + (i === tab ? ' on' : '')}
              onClick={() => setTab(i)}
            >
              {x}
            </button>
          ))}
        </div>

        {tab === 0 ? (
          L.rows.map((r, i) => (
            <div className="row" key={i}>
              {r.map((p) => (
                <PanelCard key={p.k} p={p} data={data} nc={nc} />
              ))}
            </div>
          ))
        ) : t === 'Reports' ? (
          <div className="panel">
            <h3>Reports</h3>
            <p className="note">
              Exports the KPIs and panel data currently loaded for this portal
              as a CSV file. Scheduled and PDF reports are not implemented.
            </p>
            <button className="btn" onClick={() => csv(L, data)}>
              Download CSV
            </button>
          </div>
        ) : (
          <div className="row">
            {(TABMAP[portal]?.[t] || [])
              .map((k) => all.find((p) => p.k === k))
              .filter(Boolean)
              .map((p) => (
                <PanelCard key={p!.k} p={p!} data={data} nc={nc} />
              ))}
          </div>
        )}
      </>
    );
  }

  const hideBanner = sl === 'crm-and-contacts' || sl === 'leads-and-pipeline';

  return (
    <Shell user={user} portal={portal} onLogout={onLogout}>
      {!hideBanner && (
        <div className="banner">
          <div>
            <h1>{mod || (L ? L.title : PORTAL_NAMES[portal] + ' Portal')}</h1>
            <p>{L && !sl ? L.sub : 'InnoVibe Mobility Office'}</p>
          </div>

          {L && !sl && (
            <div
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'end',
                flexWrap: 'wrap',
              }}
            >
              <button className="btn" onClick={() => csv(L, data)}>
                Download Report (CSV)
              </button>
            </div>
          )}
        </div>
      )}

      <main className="main">{body}</main>
    </Shell>
  );
}
