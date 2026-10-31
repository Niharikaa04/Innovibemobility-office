import { ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { api, Notices, User, HOME, Role } from './api';
import { NAV, slug, PORTAL_NAMES } from './nav';
import { useProfile } from './useProfile';
import ProfileModal, { Avatar } from './ProfileModal';
import './shell.css';

export const toggleTheme = () => {
  const d = document.documentElement;
  const n = d.dataset.theme === 'dark' ? 'light' : 'dark';
  d.dataset.theme = n;
  try {
    localStorage.setItem('theme', n);
  } catch {}
};

/* Sidebar icon picked from the menu label */
const ICONS: [RegExp, string][] = [
  [/dashboard/i, '🏠'], [/startup/i, '🚀'], [/kpi/i, '🎯'], [/overview/i, '📊'],
  [/report|analytics/i, '📈'], [/crm|contact/i, '📇'], [/lead|pipeline/i, '🧲'],
  [/customer/i, '👥'], [/sales|marketing/i, '📣'], [/waba|whatsapp/i, '💬'],
  [/unified/i, '📥'], [/email/i, '✉️'], [/quot|order/i, '🧾'],
  [/ticket/i, '🛠'], [/fleet/i, '🚐'], [/garage|service center/i, '🏭'],
  [/technician/i, '👷'], [/ai|diagnostic/i, '🤖'], [/iot|telemetry/i, '📡'],
  [/revenue|expense/i, '💰'], [/invoice|payment/i, '💳'], [/budget/i, '🧮'],
  [/employee|team/i, '🧑‍💼'], [/attendance/i, '🗓'], [/leave/i, '🌴'],
  [/task|project/i, '✅'], [/audit|log/i, '📜'], [/setting/i, '⚙️'],
];
const iconOf = (s: string) => ICONS.find(([r]) => r.test(s))?.[1] ?? '•';

export default function Shell({
  user,
  portal,
  onLogout,
  children,
}: {
  user: User;
  portal: string;
  onLogout: () => void;
  children: ReactNode;
}) {
  const base = HOME[portal as Role] || '/' + portal;
  const nav = NAV[portal] || [];
  const go = useNavigate();
  const profile = useProfile(user);
  const searchRef = useRef<HTMLInputElement>(null);

  const [q, setQ] = useState('');
  const [menu, setMenu] = useState<'' | 'n' | 'p'>('');
  const [nt, setNt] = useState<Notices | null>(null);
  const [editing, setEditing] = useState(false);

  const flat = useMemo(
    () =>
      nav.flatMap(([g, items]) =>
        items.map((i, ix) => ({
          g,
          i,
          to: g === nav[0]?.[0] && ix === 0 ? base : `${base}/${slug(i)}`,
        }))
      ),
    [portal]
  );

  const hits = q.trim()
    ? flat
        .filter((x) => x.i.toLowerCase().includes(q.trim().toLowerCase()))
        .slice(0, 8)
    : [];

  // Load notifications once (for the badge count)
  useEffect(() => {
    if (!nt) {
      api
        .notifications()
        .then(setNt)
        .catch(() => setNt({ configured: false, items: [] }));
    }
  }, []);

  // Ctrl+K / Cmd+K focuses search
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);

  const ro = user.role !== portal;
  const count = nt?.configured ? nt.items.length : 0;

  return (
    <div className="shell">
      <aside className="side">
        <div className="logo">
          <img
            src="/assets/logo.png"
            alt="InnoVibe Mobility India Pvt Ltd"
            className="sidebar-logo-img"
          />
        </div>

        <nav aria-label="Main navigation">
          {nav.map(([g, items], gi) => (
            <div key={g}>
              <div className="grp">{g}</div>

              {items.map((i, ii) => {
                const to = gi === 0 && ii === 0 ? base : `${base}/${slug(i)}`;
                return (
                  <NavLink
                    key={i}
                    to={to}
                    end
                    className={({ isActive }) => 'item' + (isActive ? ' on' : '')}
                  >
                    <span className="ico" aria-hidden>{iconOf(i)}</span>
                    {i}
                  </NavLink>
                );
              })}
            </div>
          ))}

          {user.role === 'ceo' && (
            <div>
              <div className="grp">Read-only views</div>

              {(['coo', 'cto'] as const).map((p) => (
                <NavLink
                  key={p}
                  to={HOME[p]}
                  className={({ isActive }) => 'item' + (isActive ? ' on' : '')}
                >
                  <span className="ico" aria-hidden>👁</span>
                  {PORTAL_NAMES[p]} Dashboard
                </NavLink>
              ))}

              {portal !== 'ceo' && (
                <NavLink to="/ceo" className="item">
                  <span className="ico" aria-hidden>↩</span>
                  Back to CEO Dashboard
                </NavLink>
              )}
            </div>
          )}
        </nav>
      </aside>

      <div className="shell-main">
        <header className="top">
          <div className="shell-search" style={{ position: 'relative', flex: 1 }}>
            <span className="search-ic" aria-hidden>🔍</span>
            <input
              ref={searchRef}
              className="search"
              style={{ width: '100%' }}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search pages, customers, tickets, vehicles..."
              aria-label="Search pages"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && hits[0]) {
                  go(hits[0].to);
                  setQ('');
                }
                if (e.key === 'Escape') setQ('');
              }}
            />
            <kbd className="kbd">Ctrl + K</kbd>

            {q.trim() && (
              <div
                className="pop"
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  zIndex: 100,
                }}
              >
                {hits.map((h) => (
                  <button
                    key={h.to}
                    className="li"
                    onClick={() => {
                      go(h.to);
                      setQ('');
                    }}
                  >
                    <span>{h.i}</span>
                    <small>{h.g}</small>
                  </button>
                ))}

                {!hits.length && <p className="note">No matching pages.</p>}

                <p className="note">
                  Searching customers, tickets and vehicles is not configured yet.
                </p>
              </div>
            )}
          </div>

          <div
            className="who"
            style={{ display: 'flex', alignItems: 'center', gap: 10 }}
          >
            {/* Bell with count badge */}
            <button
              className="bell"
              aria-label={`Notifications${count ? `, ${count} new` : ''}`}
              onClick={() => setMenu(menu === 'n' ? '' : 'n')}
            >
              🔔
              {count > 0 && <span className="badge">{count}</span>}
            </button>

            {/* Notifications */}
            <div style={{ position: 'relative' }}>
              <button
                className="ghost"
                aria-label="Notifications"
                aria-expanded={menu === 'n'}
                onClick={() => setMenu(menu === 'n' ? '' : 'n')}
              >
                Notifications
              </button>

              {menu === 'n' && (
                <div
                  className="pop"
                  role="dialog"
                  aria-label="Notifications"
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 8px)',
                    right: 0,
                    width: 300,
                    zIndex: 100,
                  }}
                >
                  {!nt ? (
                    <p className="note">Loading...</p>
                  ) : !nt.configured ? (
                    <p className="note">Notifications are not configured yet.</p>
                  ) : nt.items.length ? (
                    nt.items.map((n) => (
                      <div className="li" key={n.id}>
                        <span>{n.title}</span>
                        <small>{n.time}</small>
                      </div>
                    ))
                  ) : (
                    <p className="note">You are all caught up.</p>
                  )}
                </div>
              )}
            </div>

            {/* Profile */}
            <div style={{ position: 'relative' }}>
              <button
                className="ghost profile-btn"
                aria-expanded={menu === 'p'}
                onClick={() => setMenu(menu === 'p' ? '' : 'p')}
              >
                <Avatar p={profile} size={42} />

                <span className="pn">
                  <b>{profile.name}</b>
                  <small>{profile.title}</small>
                </span>

                <span aria-hidden="true">⌄</span>
              </button>

              {menu === 'p' && (
                <div
                  className="pop"
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 8px)',
                    right: 0,
                    width: 240,
                    zIndex: 100,
                    padding: 8,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: 10,
                      borderBottom: '1px solid #e5eaf2',
                      marginBottom: 6,
                    }}
                  >
                    <Avatar p={profile} size={48} border="none" />

                    <div style={{ minWidth: 0 }}>
                      <b style={{ display: 'block', fontSize: 13 }}>
                        {profile.name}
                      </b>
                      <small>{profile.title}</small>
                      {profile.email && (
                        <small style={{ display: 'block', opacity: 0.7 }}>
                          {profile.email}
                        </small>
                      )}
                    </div>
                  </div>

                  <button
                    className="li"
                    onClick={() => {
                      setEditing(true);
                      setMenu('');
                    }}
                  >
                    Edit profile
                  </button>

                  <button
                    className="li"
                    onClick={() => {
                      go(HOME[user.role]);
                      setMenu('');
                    }}
                  >
                    My portal
                  </button>

                  <button
                    className="li"
                    onClick={() => {
                      toggleTheme();
                      setMenu('');
                    }}
                  >
                    Switch light/dark
                  </button>

                  <button className="li" onClick={onLogout}>
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {ro && (
          <div className="ro">
            Read-only view of the {PORTAL_NAMES[portal]} portal, authorised for
            the CEO.
          </div>
        )}

        {children}
      </div>

      {editing && (
        <ProfileModal
          user={user}
          profile={profile}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}
