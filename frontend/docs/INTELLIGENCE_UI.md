# InnoVibe Business Intelligence: Stage 2 frontend integration

Location: **CEO Dashboard > AI Insights tab** (the existing tab; no new route, no duplicate navigation). `CeoHome.tsx` renders `<IntelligencePanel/>` for that tab instead of the old generic "AI Insights" list. Other portals and tabs are unchanged.

## Files
| File | Purpose |
|---|---|
| `src/intelligence/types.ts` | TypeScript contracts for `GET /api/intelligence/*` (from backend `docs/INTELLIGENCE.md` s.4) |
| `src/intelligence/client.ts` | GET-only client, keeps HTTP status (`IntelError`), supports `AbortSignal` |
| `src/intelligence/links.ts` | Backend module key -> existing CEO sidebar route, built from `nav.ts` (unknown keys are not linked) |
| `src/intelligence/format.ts` | State labels, value formatting. `fmtValue` returns `null` for every unusable state, so unavailable data is never rendered as 0 |
| `src/intelligence/ask.ts` | Deterministic "Ask your business" resolver (fixed question catalogue + metric endpoints) |
| `src/intelligence/parts.tsx`, `Ask.tsx`, `IntelligencePanel.tsx`, `intelligence.css` | UI |
| `src/CeoHome.tsx` | 3-line change: import + render the panel for the AI Insights tab |
| `src/intelligence.render.test.tsx` | 22 tests |

## Endpoints used
`/status` (AI mode banner), `/overview` (summary cards, ranked alerts, insights, gaps), `/trends` (weekly series + period flows), `/context` (loaded only when "Data coverage" is opened), `/metrics/{id}` (Ask answers, memoised per period). The period selector (`wow`, `mom`, `last_7d`, `last_30d`) is passed through to the backend; the browser never sends a role, user id or scope.

## What the UI shows
Executive summary with severity counts and metric cards (state, value, previous-period delta, reliability label, freshness) · ranked operational risks with expandable evidence (severity basis, source, method, threshold, freshness, limitations, link) · evidence-backed insight cards where each sentence is tagged *Verified fact / Calculated / Possible explanation / Recommendation / Not available* · trend charts (Recharts) with a table alternative · period comparison · data coverage and gaps · Ask your business with suggested questions, follow-ups and a "How this was obtained" section.
States covered: loading skeleton, no data, not enough history, no threshold, partial, no permission, not configured, unavailable, 403, 429, network/server error with retry.

## Ask your business: what it is and is not
**No AI provider is connected** (Stage 3 requires an approved provider and data-sharing arrangement). Free text is matched in the browser to a fixed catalogue of 14 questions; answers are composed from backend `MetricResult` objects and the overview, so they cannot disagree with cards and alerts. The typed text is never sent to the server and never logged. Gross margin/profit, churn, forecasts, employee ranking and cash position are answered with an explanation of what is missing. Anything else returns "I cannot answer that yet". The conversation thread lives only in component state (no server-managed conversation until Stage 3). All typed and database text is rendered as React text nodes (no HTML injection).

## Known limitations / needs a decision
1. **Drill-down filters:** existing list screens do not read URL filters, so links open the right page and the backend's suggested filter is shown as text. Real deep-linking needs those screens to accept query parameters.
2. **Currency:** the backend returns amounts without a currency; the UI shows plain numbers.
3. The matcher is keyword-based and intentionally narrow; natural-language understanding is Stage 3.
4. Only the CEO portal has the panel. COO/CTO are allowed by the API gate but their dashboards were not changed.
5. Not visually inspected in a real browser (no browser in the build environment); layout and dark mode are CSS-only and covered by structure tests, not screenshots.
6. **Pre-existing, not caused by this work:** `LiveMap.tsx` imports `leaflet` and `leaflet.markercluster`, which are missing from `package.json`, so `npm run build` fails on the supplied project. Adding them is a dependency change that needs your approval. 28 existing tests also fail on the supplied project (identical before and after this change).

## Test results (exact)
| Check | Result |
|---|---|
| `npx vitest run src/intelligence.render.test.tsx` | 22 passed, 0 failed |
| Full suite `npx vitest run` | 259 tests: 231 passed, 28 failed. The same 28 fail on the untouched supplied project (records.test 18, app.render.test 5, tasks.render.test 4, ops2.render.test 1). No new failures. |
| `npx tsc --noEmit` | Supplied project: 3 errors, all `LiveMap.tsx` missing `leaflet`. With leaflet installed temporarily via `--no-save`: 0 errors |
| `npx vite build` | Supplied project: fails (same leaflet import). With leaflet installed `--no-save`: succeeds |
Not run: end-to-end against a real FastAPI/PostgreSQL backend (not available here); backend Stage 1 tests were not re-run.
