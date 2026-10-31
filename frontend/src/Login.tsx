import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, HOME } from './api';
import type { User } from './api';
import './login.css';

/* Decorative flowing wave lines for the left panel. */
const mk = (
  n: number,
  f: (t: number) => string,
  o: (t: number) => number,
) =>
  Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    return { d: f(t), o: o(t), bright: i % 8 === 3 };
  });

const WAVES = [
  ...mk(
    54,
    (t) => `M-60 ${586 + t * 96} C 240 ${664 + t * 40} 470 ${596 - t * 44} 880 ${196 + t * 214}`,
    (t) => Math.max(0.14, Math.min(0.8, 0.8 - Math.abs(t - 0.4) * 1.05)),
  ),
  ...mk(
    26,
    (t) => `M-60 ${654 + t * 50} C 260 ${706 + t * 30} 560 ${690 - t * 12} 880 ${470 + t * 120}`,
    (t) => Math.max(0.12, 0.42 - Math.abs(t - 0.5) * 0.5),
  ),
];

function WaveScene() {
  return (
    <svg
      className="lg-scene"
      viewBox="0 0 800 700"
      preserveAspectRatio="xMaxYMax slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id="lgWave"
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="0"
          x2="800"
          y2="0"
        >
          <stop offset="0" stopColor="#2563eb" stopOpacity=".45" />
          <stop offset=".5" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#c4f6ff" />
        </linearGradient>
      </defs>
      <g className="lg-waves" fill="none" strokeLinecap="round">
        {WAVES.map((wave, i) => (
          <path
            key={i}
            d={wave.d}
            stroke={wave.bright ? '#67e8f9' : 'url(#lgWave)'}
            strokeWidth={wave.bright ? 1.5 : 1}
            opacity={wave.bright ? Math.min(0.95, wave.o + 0.25) : wave.o}
          />
        ))}
      </g>
    </svg>
  );
}

const Eye = ({ off }: { off: boolean }) => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {off ? (
      <>
        <path d="M3 3l18 18" />
        <path d="M10.6 6.2A9.8 9.8 0 0 1 12 6c5 0 8.5 4 9.5 6a14 14 0 0 1-3 3.8M6.5 7.6A14.5 14.5 0 0 0 2.5 12c1 2 4.5 6 9.5 6 1.3 0 2.5-.3 3.6-.8" />
        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      </>
    ) : (
      <>
        <path d="M2.5 12C3.5 10 7 6 12 6s8.5 4 9.5 6c-1 2-4.5 6-9.5 6s-8.5-4-9.5-6z" />
        <circle cx="12" cy="12" r="3" />
      </>
    )}
  </svg>
);

const UserIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
  </svg>
);

const LockIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="11" width="16" height="10" rx="2.5" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
);

const Arrow = () => (
  <svg className="lg-arrow" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

const iconProps = {
  width: 40,
  height: 40,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.4,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true as const,
};

const Leaf = () => (
  <svg {...iconProps}>
    <path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14" />
    <path d="M5 19c2-5 5-8 9-10" />
  </svg>
);

const People = () => (
  <svg {...iconProps}>
    <circle cx="12" cy="8" r="3" />
    <circle cx="5.5" cy="10" r="2.2" />
    <circle cx="18.5" cy="10" r="2.2" />
    <path d="M6.5 19c0-3.2 2.4-5.2 5.5-5.2s5.5 2 5.5 5.2" />
    <path d="M1.8 17c0-2.2 1.5-3.6 3.7-3.6M22.2 17c0-2.2-1.5-3.6-3.7-3.6" />
  </svg>
);

const Chart = () => (
  <svg {...iconProps}>
    <rect x="3.5" y="13" width="4" height="7" rx="1" />
    <rect x="10" y="9" width="4" height="11" rx="1" />
    <rect x="16.5" y="4" width="4" height="16" rx="1" />
  </svg>
);

export default function Login({ onUser }: { onUser: (user: User) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [capsLock, setCapsLock] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!username.trim() || !password) {
      setError('Enter your username or email and password.');
      return;
    }

    setBusy(true);
    setError('');

    try {
      const user = await api.login(username.trim(), password, rememberMe);
      onUser(user);
      navigate(HOME[user.role], { replace: true });
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Unable to sign in. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lg-page">
      <section className="lg-brand">
        <WaveScene />
        <div className="lg-dots" />

        <div className="lg-brand-inner">
          <div className="lg-logo">
            <div className="lg-logo-win">
              <img
                src="/assets/logo.png"
                alt="InnoVibe Mobility India Pvt Ltd"
                onError={(event) => {
                  const image = event.currentTarget;
                  if (!image.src.endsWith('/logo.png')) {
                    image.src = '/logo.png';
                  }
                }}
              />
            </div>
          </div>

          <div className="lg-copy">
            <p className="lg-eyebrow">
              <span>People</span><i aria-hidden="true" />
              <span>Technology</span><i aria-hidden="true" />
              <span>Sustainable Mobility</span>
            </p>
            <h1>
              <span className="lg-ln">One Platform.</span>{' '}
              <span className="lg-ln lg-cy">Smarter Mobility</span>{' '}
              <span className="lg-ln">for a Greener Tomorrow.</span>
            </h1>
            <p className="lg-lead">
              Driving clean, connected and efficient mobility through technology, people and innovation.
            </p>
          </div>

          <ul className="lg-pillars">
            <li><Leaf /><span>Clean<br />Mobility</span></li>
            <li><People /><span>Connected<br />Communities</span></li>
            <li><Chart /><span>Sustainable<br />Growth</span></li>
          </ul>
        </div>
      </section>

      <main className="lg-form-side">
        <div className="lg-card">
          <h2>Welcome back</h2>
          <p className="lg-sub">Sign in to your InnoVibe Office Dashboard</p>

          <form onSubmit={handleSubmit} noValidate aria-busy={busy}>
            <div className="lg-group">
              <label htmlFor="u">Username or Email</label>
              <div className="lg-field">
                <span className="lg-ico"><UserIcon /></span>
                <input
                  id="u"
                  name="username"
                  type="text"
                  autoComplete="username"
                  placeholder="Enter your username or email"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </div>
            </div>

            <div className="lg-group">
              <label htmlFor="p">Password</label>
              <div className="lg-field">
                <span className="lg-ico"><LockIcon /></span>
                <input
                  id="p"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  onKeyUp={(event) => setCapsLock(event.getModifierState('CapsLock'))}
                  onBlur={() => setCapsLock(false)}
                />
                <button
                  type="button"
                  className="lg-eye"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                >
                  <Eye off={showPassword} />
                </button>
              </div>
              {capsLock && <div className="lg-caps" role="status">Caps Lock is on</div>}
            </div>

            <div className="lg-row">
              <label className="lg-check">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => setRememberMe(event.target.checked)}
                />
                <span>Remember me</span>
              </label>
              <Link to="/forgot-password" className="lg-forgot">Forgot password?</Link>
            </div>

            {error && <div className="lg-err" role="alert">{error}</div>}

            <button className="lg-go" type="submit" disabled={busy}>
              {busy ? (
                <><span className="lg-spin" aria-hidden="true" />Signing in…</>
              ) : (
                <>Sign In<Arrow /></>
              )}
            </button>
          </form>
        </div>

        <p className="lg-foot">© {new Date().getFullYear()} InnoVibe Mobility India Pvt Ltd</p>
      </main>
    </div>
  );
}
