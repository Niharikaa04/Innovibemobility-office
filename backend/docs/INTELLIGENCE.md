# InnoVibe Business Intelligence: Stage 1 backend foundation

Status: **implemented and unit-tested on SQLite; NOT yet run against PostgreSQL or through FastAPI** (see "Test results"). No external AI provider is connected. No migration, dependency or permission was added.

## 1. Architecture

All code is in `backend/intelligence/`. Layers only depend on the ones above them.

| Module | Responsibility |
|---|---|
| `results.py` | Result states, `Evidence`, `MetricResult`. `to_dict()` asserts an unusable state never carries a value. |
| `periods.py` | `Period`, `resolve("last_7d" / "last_30d" / "wow" / "mom")`, custom ranges (max 366 days). |
| `analytics.py` | Pure statistics: ageing buckets, workload facts, % change, anomaly screen. |
| `reader.py` | The ONLY database access: read-only transaction, `set local statement_timeout` (5 s), 5000-row cap, errors mapped to `ReaderError(kind)` so driver text never leaks. |
| `registry.py` | Authoritative metric registry, permission gate, per-request memoisation. |
| `metrics.py` | The 33 metric implementations. |
| `context.py` | Company context engine. |
| `alerts.py` | Alerts, ranked issues, insights, executive overview, missing-data gaps. Built only from registry results. |
| `guard.py` | Rate limiter and TTL cache. |
| `ai_interface.py` | Provider protocol (only `UnavailableProvider`), allow-listed read-only tools, redaction. |
| `api.py` | `IntelligenceService` (all logic) + thin FastAPI router. Wired in `main.py` with two lines. |

**One calculation per number.** Cards, alerts, insights, trends and AI tools call `compute(metric_id, ctx)`. Results are memoised per request, so two consumers cannot disagree. Composite metrics (`approvals.pending`) reuse the module metrics instead of re-querying.

**Definitions reused from existing code:** finished ticket statuses and the overdue-ticket rule (ticketapi/opscommon), receivable/payment-status rule (`finance.inv_base`), revenue/expense actuals for budgets (`finance.py`), money handling (`financelogic`), IoT offline rule (`iotapi.CONN_SQL`), location-data policy (`locationpolicy`).

## 2. Result states

| State | Meaning |
|---|---|
| `available` | Computed from real rows. |
| `partial` | Computed, but a source was missing, truncated or not permitted (listed in `limitations`). |
| `no_data` | The source exists but holds no records. `value` is `null`, never 0. |
| `not_enough_history` | A comparison/trend/anomaly needs more history than exists ("Not enough history"). |
| `no_threshold_configured` | Cannot be judged: nobody entered a limit ("No threshold configured"). |
| `no_permission` | The session's role may not read this source. |
| `not_configured` | A prerequisite setting is missing (e.g. attendance policy). |
| `unavailable` | Table missing (migration not applied), query failed, or timed out. |

A previous-period `comparison` block has its **own** state, so a current value can be available while its comparison says "Not enough history".

## 3. Metric catalogue (generated from the registry)

| id | label | kind | reliability | permissions | sources | definition |
|---|---|---|---|---|---|---|
| `approvals.pending` | Pending approvals (all modules) | composite | derived | ` + any of tasks.read, expenses.read, leave.read, attendance.read` | (composite) | Sum of the per-module pending decisions. Each module is a different table, so nothing is double-counted. Service tickets have no approval state in the schema. |
| `attendance.pending_corrections` | Attendance corrections awaiting decision | snapshot | system_recorded | `attendance.read` | attendance_corrections | Attendance correction requests in status pending. |
| `attendance.today` | Checked in today | snapshot | system_recorded | `attendance.read` | attendance_config, attendance_records | Attendance records for today's work date in the configured timezone. Aggregate counts only. |
| `budget.variance` | Budget versus actual (month) | snapshot | user_entered | `budget.read, invoices.read, expenses.read` | budgets, invoices, expenses | For the month containing the period end: budget lines vs actuals. Actual revenue = sent invoices by issue date; actual expense = approved expenses by expense date (finance.py). Variance = actual - budget. |
| `diagnostics.active_unlinked` | Active faults without a linked ticket | snapshot | system_recorded | `diagnostics.read, fleet.read` | diagnostic_faults, fleet_vehicles | ACTIVE diagnostic faults on non-archived vehicles whose ticket_id is empty. The link is the explicit ticket_id column only; it is never inferred from free-text vehicle references. |
| `diagnostics.repeated` | Vehicles with repeated faults | flow | system_recorded | `diagnostics.read, fleet.read` | diagnostic_faults, fleet_vehicles | Vehicle + fault code pairs recorded 2 or more times with detected_at in the period (two occurrences is the definition of 'repeated'). |
| `expenses.pending_review` | Expenses awaiting review | snapshot | system_recorded | `expenses.read` | expenses | Non-archived expenses in status PENDING. |
| `expenses.summary` | Approved expenses | flow | user_entered | `expenses.read` | expenses | Approved, non-archived expenses by expense_date in the period, by category, with a previous-period comparison. |
| `fleet.status` | Fleet by status | snapshot | system_recorded | `fleet.read` | fleet_vehicles | Non-archived vehicles grouped by status. |
| `invoices.receivables` | Receivables | snapshot | user_entered | `invoices.read, payments.read` | invoices, invoice_payments | Sent, non-archived invoices: total billed, non-voided payments received, outstanding balance, overdue balance (due_date < today and balance > 0) and ageing. Same rule as finance.inv_base. |
| `iot.anomalies` | Unusual telemetry readings | snapshot | statistical | `iot.read` | iot_readings, iot_devices | Latest reading (last 24h) per device+metric compared with up to 100 earlier readings (last 30 days) using the modified z-score on median/MAD; /z/ > 3.5 is flagged. Needs at least 30 baseline readings. This is a statistical screen, not a company threshold. |
| `iot.connectivity` | Devices beyond offline limit | snapshot | system_recorded | `iot.read` | iot_devices | ACTIVE, non-archived devices whose last contact is older than the device's own offline_after_minutes (iotapi rule). Devices that never reported are counted separately. |
| `iot.threshold_alerts` | Telemetry readings outside configured limits | snapshot | derived | `iot.read` | iot_readings, iot_devices, iot_thresholds | Latest reading per device and metric (last 7 days) that breaks an alert limit entered in iot_thresholds. CRITICAL wins over WARNING (iotapi.pick_alerts). |
| `kpi.user_entered` | KPI Center and Startup Metrics records | snapshot | user_entered | `kpi.read` | module_records | Records users entered in the KPI Center and Startup Metrics workspaces. Counts only; the values are not validated against any system of record. |
| `leads.flow` | Leads created and converted | flow | system_recorded | `leads.read` | leads | Leads created in the period and leads converted (converted_at) in the period. |
| `leads.followups_overdue` | Leads with overdue follow-up | snapshot | user_entered | `leads.read` | leads | Open leads whose next_follow_up date is before today. |
| `leads.pipeline` | Open leads in pipeline | snapshot | user_entered | `leads.read` | leads | Non-archived leads not yet won or lost, by stage. Value is the sum of user-entered lead values. |
| `leads.trend` | Leads created by week | flow | system_recorded | `leads.read` | leads | Weekly new lead counts (last 8 weeks ending at the period end). |
| `leave.on_leave_today` | On approved leave today | snapshot | system_recorded | `leave.read` | leave_requests | Approved leave requests whose date range includes today. Aggregate count only. |
| `leave.pending` | Leave requests awaiting decision | snapshot | system_recorded | `leave.read` | leave_requests | Leave requests in status pending. |
| `tasks.by_status` | Tasks by status | snapshot | system_recorded | `tasks.read` | tasks | Non-archived tasks grouped by their recorded status. |
| `tasks.flow` | Tasks created and completed | flow | system_recorded | `tasks.read` | tasks | Tasks created and tasks completed (completed_at) in the period, with a previous-period comparison. |
| `tasks.overdue` | Overdue tasks | snapshot | user_entered | `tasks.read` | tasks | Non-archived tasks that are open or in progress and whose due_date is before today. Tasks waiting for approval are counted under approvals, not here. |
| `tasks.pending_approval` | Tasks awaiting approval | snapshot | system_recorded | `tasks.read` | tasks | Non-archived tasks in status pending_approval. |
| `tasks.trend` | Tasks created vs completed by week | flow | system_recorded | `tasks.read` | tasks | Weekly created and completed task counts (last 8 weeks ending at the period end). |
| `tickets.ageing` | Open ticket ageing | snapshot | system_recorded | `tickets.read` | service_tickets | Open tickets bucketed by days since created_at. Descriptive buckets only: no SLA is assumed. |
| `tickets.by_service_center` | Open tickets by service center | snapshot | system_recorded | `tickets.read, garages.read` | service_tickets, service_centers | Open tickets grouped by the service_center_id foreign key. Tickets with no service center are reported as unlinked, never merged by name. |
| `tickets.flow` | Tickets created and resolved | flow | system_recorded | `tickets.read` | service_tickets | Tickets created and tickets resolved (resolved_at) in the period. Created minus resolved is the net change in open work caused by new activity. |
| `tickets.open_backlog` | Open service tickets | snapshot | system_recorded | `tickets.read` | service_tickets | Non-archived tickets whose status is not COMPLETED, CUSTOMER_CONFIRMATION or CLOSED. |
| `tickets.overdue` | Overdue service tickets | snapshot | user_entered | `tickets.read` | service_tickets | Open tickets whose due_date is before today (same rule as the Service Tickets screen). |
| `tickets.technician_workload` | Open tickets per technician | snapshot | system_recorded | `tickets.read, technicians.read` | service_tickets | Open tickets grouped by assigned_to. Reports the distribution as facts; no 'too much work' limit is configured. |
| `tickets.trend` | Tickets created vs resolved by week | flow | system_recorded | `tickets.read` | service_tickets | Weekly created and resolved ticket counts (last 8 weeks ending at the period end). |
| `tickets.unassigned` | Open tickets with no technician | snapshot | system_recorded | `tickets.read` | service_tickets | Open tickets whose assigned_to is empty. |

`reliability`: `system_recorded` (written by the system), `user_entered` (typed in by people: due dates, lead values, budgets), `derived`, `statistical` (screening method, not a company rule). There is **no numeric confidence score**: none can be justified from the data, so the labels above plus `state`, `limitations` and `freshness` are the confidence methodology.

## 4. Endpoints (all require a valid session; `Cache-Control: no-store`; the only `POST` is `/ask`, which also requires CSRF)

Gate: `EXECUTIVE_ROLES = ("ceo","coo","cto")` in `intelligence/api.py` (proposed default, change the tuple to change it). Other roles get **403** and a `permission_denied` audit entry before any database connection is opened. Per-metric permissions then apply again; the rest returns `no_permission`.

Common query parameters: `period` = `wow` (default) | `mom` | `last_7d` | `last_30d`, or both `date_from` and `date_to` (max 366 days). Errors: 401 (no session), 403, 404 (unknown metric), 422 (bad period), 429 (60 requests/minute/user).

| Endpoint | Returns |
|---|---|
| `/api/intelligence/status` | `{roles, role, ai:{ai_available, provider, degraded_mode, message, data_shared_with_provider}, metrics, periods, max_range_days}` |
| `/api/intelligence/catalog` | `{metrics:[{id,label,module,description,unit,reliability,kind,sources,permitted}]}` for the caller's role |
| `/api/intelligence/overview` | `{as_of, period, previous_period, cards[], top_risks[3], alerts[], insights[], gaps[], summary{alerts_total, by_severity, metrics_available, metrics_total}, generated_at, cached}` |
| `/api/intelligence/context` | `{modules[], metric_state_counts, gaps[], unlinked[], data_quality[], thresholds[], history[], notes[]}` |
| `/api/intelligence/alerts` | `{alerts[], gaps[]}` |
| `/api/intelligence/insights` | `{insights[]}` |
| `/api/intelligence/trends` | `{trends:{tickets.trend, tasks.trend, leads.trend, tickets.flow, tasks.flow, leads.flow, expenses.summary}}` (full metric results) |
| `/api/intelligence/metrics/{metric_id}` | `{metric: MetricResult}` (403 if the role lacks permission) |

**MetricResult:** `metric_id, label, state, value, unit, message, breakdown[], detail{}, period, comparison, as_of, freshness{latest_source_update_at, age_hours}, evidence[{source, method, row_count, record_ids(<=10), note}], limitations[], threshold{configured,label}, reliability, link{module, filter?}`.

**Alert:** `id, rule_id, rank, title, severity, severity_basis, metric_id, value, facts[], evidence[], source[], reported_at, data_freshness, threshold, reliability, limitations[], recommended_next_step, link`.

**Insight card:** `id, title, state, statements[{kind, text, metric_id}], metric_ids[], link`, where `kind` is `verified_fact | calculated_metric | possible_explanation | recommendation | unavailable`.

`link.module` is a module key (tasks, tickets, leads, payments, expenses, budget, leave, attendance, diagnostics, iot, technicians, kpi, approvals). `link.filter` uses the existing list endpoints' own query parameters (e.g. tickets `overdue=true`, `group=open`; invoices `payment_status=OVERDUE`). **Mapping module keys to frontend routes is Stage 2 work** (the frontend was not supplied; no route was guessed).

## 5. Severity and ranking (no invented policy)

* `critical/high/medium/low` come only from a field already stored on the records: ticket `priority`, task `priority`, fault `severity`, `iot_thresholds.severity`. Each alert states its `severity_basis`.
* `attention` is used when a limit someone entered is broken, or a decision is pending, but the system holds no severity (approvals, unassigned tickets, overdue leads/invoices, offline devices, budget overruns, anomalies). It is not a risk rating.
* Ranking: severity desc, then age of the oldest item (days) desc, then affected count desc, then rule id. Deterministic and reproducible.
* No SLA, workload limit or performance target exists in the schema, so none is applied. The context endpoint lists them as `configured: false`.

## 6. Anomaly method (`iot.anomalies`)

Latest reading (within 24 h) per device+metric vs up to 100 earlier readings (30 days). Modified z-score (Iglewicz and Hoaglin): `0.6745*(x-median)/MAD`; when MAD is 0 (coarse-step sensors) the documented fallback `(x-median)/(1.253314*MeanAD)`; a perfectly constant baseline gives no score. Requires at least 30 baseline readings, else `not_enough_history`. `|z| > 3.5` is the conventional cut-off for that statistic. It is a statistical screen, not a company threshold, and is labelled so. Location metrics are excluded unless the role holds `location.read`.

## 7. Security model

* Existing session cookie, revocation, per-request role re-check; role comes only from the verified session. The only POST (`/ask`) uses the `csrf` dependency already passed to `build_router`.
* Server-side gates on every endpoint and metric (`registry.permitted`, one function shared by the gate, catalogue and AI tool list, tested for all 7 roles). Own-records-only roles never receive company-wide aggregates.
* Read-only: every query is a `SELECT` in a read-only transaction with a 5 s timeout and a 5000-row cap; a test scans the package for write SQL.
* Cache and rate limiter are in-process; cache keys contain user id **and** role, period and metric. TTL 30 s.
* Audit: `intelligence_view` records `{action, user, ip, endpoint}` only; denials and rate-limit hits are logged. No questions, answers or data are logged.
* AI: no provider is connected; `UnavailableProvider` makes callers handle degraded mode. Tools are one-per-metric, read-only, take only a `period` enum; unknown tools/arguments are rejected. `redact_for_ai` allow-lists result keys, drops vehicle registrations, device identifiers and contact fields, aliases technician/customer names, strips control characters and caps text. Evidence record ids are not sent.
* Unavailable data is never zero (asserted for every metric on an empty database).

## 8. Configuration

No new environment variables are required. Optional: `IOT_EXTRA_LOCATION_METRICS` (already used by `iotapi`) is honoured so extra location-metric names are also excluded. Constants (`EXECUTIVE_ROLES`, `CACHE_TTL_SECONDS`, `RATE_LIMIT_PER_MINUTE`, `STATEMENT_TIMEOUT_MS`) are at the top of their modules.

## 9. Known limitations

1. **Not verified on PostgreSQL / FastAPI** in the build environment (no network, no Postgres, no FastAPI/psycopg). The SQL is deliberately portable and ran on SQLite; PostgreSQL behaviour (types, `numeric` as Decimal, window functions) must be confirmed by running the tests on your machine.
2. **No point-in-time backlog history.** Nothing stores "open tickets on date X". Change is reported as created-minus-resolved flows (`tickets.flow`, weekly `*.trend`). True backlog history would need a snapshot table = a new migration (needs your approval).
3. Period boundaries for timestamp metrics are UTC days; due-date metrics use the server's local date, like the existing modules.
4. Attendance has no attendance-rate: attendance `user_id` cannot be reliably linked to employee records, so only counts are shown.
5. A fault may have a ticket without `ticket_id` being set; it is then counted as unlinked (the link is never inferred from free-text `vehicle_reference`).
6. Offline limits use each device's `offline_after_minutes`; its database default (30) is a system default, not a company decision.
7. Rate limit and cache are per worker process (multiple workers each keep their own).
8. Telemetry anomaly screening examines roughly 50 device/metric series per request (row cap) and says so when truncated.
9. Gross margin, profitability, churn, employee rankings and revenue forecasts are intentionally absent (no approved definition/evidence).
10. KPI Center / Startup Metrics are counted only; their free-form values are not interpreted.
11. Notifications and background monitoring are **not** implemented; nothing claims otherwise.

## 10. Needs your approval / decision

* `EXECUTIVE_ROLES`: ceo, coo, cto proposed. Confirm or restrict (e.g. CEO only).
* Snapshot table + migration, only if you want historical backlog charts.
* Shared cache/rate-limit store (Redis/Postgres) if you run several workers.
* Stage 3: choice of AI provider and written approval of what data may be shared with it.

## 11. Test results (exact, from the build environment)

Environment: Python 3.12, **no network**; `fastapi`, `pydantic`, `psycopg`, `pytest`, `httpx` and PostgreSQL were **not installed and could not be installed**. Therefore:

| Check | Command | Result |
|---|---|---|
| Whole backend byte-compiles (incl. edited `main.py`) | `python3 -m compileall -q backend` | OK |
| New intelligence tests (58) | pytest-free runner that imports each `tests/test_intel_*.py` and calls every `test_*` function | **58 passed, 0 failed** |
| Existing test suite (`tests/test_*.py` other than `test_intel_*`) | needs pytest + fastapi + psycopg (+ Postgres for `test_pg_integration.py`) | **NOT RUN: environment blocker** |
| FastAPI router (`build_router`) | needs fastapi | **NOT RUN** (compiles; all logic it delegates to is tested through `IntelligenceService`) |
| SQL on PostgreSQL | needs Postgres | **NOT RUN** (SQL executed on SQLite via `tests/intel_fixtures.py`) |

What the 58 tests cover: period maths (week/month windows, month-end clamping, 366-day cap); ageing, workload and anomaly maths (including the MAD = 0 fallback); exact hand-computed results for tasks, tickets, leads, receivables (partial/voided/over-payments), expenses, budget variance, approvals, diagnostics, device connectivity, threshold alerts, anomalies and weekly trends; "no data / not enough history / unavailable are never zero"; one-calculation-per-request; permission gate for all 7 roles including catalogue = gate = AI tool list; non-executive refusal before any DB connection; cache isolation across users and roles; rate limiting; period validation (422); audit content; write-SQL scan; `PgReader` behaviour against a faked driver (read-only flag, timeout set first and re-armed after rollback, error mapping without leaking driver text, never commits); AI tool allow-list, argument rejection, redaction, prompt-injection inertness, degraded mode, database-outage behaviour.

**Please run on your machine (with your normal setup):**
```
cd backend
python -m pytest tests/test_intel_analytics.py tests/test_intel_metrics.py tests/test_intel_security.py -q
python -m pytest -q          # full existing suite, to confirm nothing regressed
```
The new tests are plain functions (no fixtures) importing `tests/intel_fixtures.py`; they need only `pytest` itself.

## 12. Files added / changed

Added: `backend/intelligence/` (11 modules), `backend/docs/INTELLIGENCE.md`, `backend/tests/intel_fixtures.py`, `backend/tests/test_intel_analytics.py`, `backend/tests/test_intel_metrics.py`, `backend/tests/test_intel_security.py`.
Changed: `backend/main.py`, 2 lines (`import intelligence.api as intelligence_api`; `app.include_router(intelligence_api.build_router(dsn, session, csrf, audit))`), CRLF line endings preserved.
Not added: migrations, dependencies, permissions, environment variables.

## 13. Stage 3/4 addendum: Ask your business, hardening

**`POST /api/intelligence/ask`** body `{question, period}` (unknown fields rejected; question 1-300 chars after trimming; period one of `wow|mom|last_7d|last_30d`).
Order of checks: session + CSRF -> executive role + rate limit -> input validation -> resolve -> only then the database.

* Answers are produced on the server by `intelligence/ask.py` from the same registry as the cards, with the caller's own role. The browser no longer fetches or combines metrics.
* The question text is data: it selects one entry of a fixed catalogue (14 questions). It is never executed, interpolated into SQL, sent to a model, logged, cached or echoed. The audit log records only the catalogue id (`question_id`) and `status`.
* Unsupported (profit, churn, forecasts, employee ranking, cash) and sensitive/hostile questions (salaries, credentials, contact details, individual location, instruction override, SQL) get a `limitation` answer and read no data.
* Each answer has `sources[]` with state, period, freshness, reliability and `evidence[]` (source, method, row count). A metric that is missing, unavailable or not permitted for the role is an `unavailable` statement, never 0.
* No AI provider is called. `AI_PROVIDER` in the environment does NOT enable anything (no provider implementation exists); `/status` reports `degraded_mode` and `data_shared_with_provider: false`. Enabling a provider needs explicit approval of the provider and of exactly which fields may be shared, and must go through `ai_interface.redact_for_ai`.
* Database outage -> one safe `503`; missing `DATABASE_URL` -> `503` ("not configured") on database routes and `not_configured: ["crm"]` on the CEO dashboard. All `/api/` responses carry `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Unhandled errors log only the exception class and route.
* Cache keys include user id and role; entries are deep-copied on read and write.

Tests: `tests/test_intel_ask.py` (service, security and HTTP integration), `tests/test_stage4_hardening.py` (route allow-list, CSRF on every write, no-database behaviour), `tests/test_intel_pg_parity.py` (every metric on real PostgreSQL equals the SQLite result; needs `pgserver`, uses an inferred schema, not production DDL). Suites that build a database from `<project>/db/*.sql` skip with an explicit reason when that folder is absent.

Frontend: `intelligence/Ask.tsx` calls `intel.ask` (CSRF header, abort on unmount), shows evidence under "How this was obtained", maps 401/403/422/429/503/network errors to fixed safe messages, and offers "Try again" only for transient failures.

### 13.1 Follow-up: RBAC audit, ordering fixes, performance

* **RBAC matrix test** (`tests/test_rbac_matrix.py`, 67 tests): logs in as all 7 roles and calls every `/api` route (the database is unreachable on purpose, so 403 = blocked at the gate, anything else = reached the handler). Invariants: a role with no grant on a module is denied on every route of it; a read/export-only role is denied every state-changing route unless it holds approve/archive/admin; all 60 `/api/workspaces/{module}` slugs are checked per role. No permission violation was found in the audited modules. This verifies the permission GATE only. Row-level scoping (own records, assigned tickets) is exercised by the PostgreSQL suites that need `db/`, which could not run here.
* **Authorization before validation:** `/api/intelligence/ask` and workspace create/update used to validate the body first, so a role without access got `422` (schema hints) instead of `403`. Both now gate first.
* **Latent bug fixed:** `workspaces.py` passed `action=` as an audit field; `AuditSink.write(action, ...)` already has that parameter, so a denied workspace write crashed with `TypeError` (500) instead of returning 403.
* **Database outage anywhere in the API** (`psycopg.OperationalError`) is now one generic `503`, not a `500`; the driver message is never returned or logged.
* **Performance:** the metric memo is shared between endpoints for the same user + role + period + day (TTL = endpoint cache TTL). Measured on PostgreSQL: overview 110 queries, then alerts/insights/trends/Ask 0 extra queries (previously 110/54/48/110). Failed (unavailable) metrics are dropped from the memo so a transient error is retried, not replayed. Covered by `tests/test_intel_perf.py`, including user/role/period isolation and TTL expiry. Frontend: the AI Insights panel is code-split with `React.lazy` (about 28 kB out of the main bundle; the main chunk is still about 1.17 MB because other pages share the charting library).

### 13.2 Verified against the real migrations (db/*.sql)

With the project's `db/` folder present (at `<project>/db`, next to `backend/`), the PostgreSQL suites run against a disposable database built from those migrations: 405 backend tests pass; 17 skip because `013_ops_followup.sql` is not in the supplied `db/` folder (`test_ops2_pg.py`, which says so in its skip reason).
* `tests/test_intel_real_schema.py`: all 33 metrics run on the real migrated schema with no query errors; on an empty database they report no_data / not_configured / no_threshold, and the only numeric value is `approvals.pending = 0`, whose source tables exist and hold no pending rows.
* Row-level rules (own attendance/leave/tasks, CRM, ops) are exercised by the existing PostgreSQL suites, which now run.
* Test fixes (tests only, no product code): `test_crm` fixture now applies 013/014 (columns `crm.py` writes) and not 004 (which removes the legacy `qualified` stage a test relies on); its activity-count test now expects stage-history entries; `test_ops_pg` applies 012 (adds `service_tickets.service_center_id`).
* File-name note: the 012 forward migration is saved as `012_garages _&_ service_centers.sql` while its rollback is `012_garages_technicians_diagnostics_iot.rollback.sql`. `tests/conftest.py::migration_path` accepts either name. Consider renaming the file so the pair matches.

### 13.3 Windows case-insensitivity fix (frontend)

`frontend/src/intelligence/ask.ts` (types + suggestions) sat next to `Ask.tsx` (the component). On Windows/macOS file names ignore letter case, so `import Ask from './Ask'` resolved to `ask.ts`, which has no default export: the AI Insights tab crashed ("does not provide an export named 'default'") and blanked the page. The types file is now `askTypes.ts`. `sourceNames.test.ts` fails if two source files ever share a name ignoring case and extension, and AI Insights is wrapped in an `ErrorBoundary` so a failure in one panel shows a message instead of blanking the dashboard.

