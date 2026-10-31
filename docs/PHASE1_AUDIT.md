# Phase 1 — Audit and Requirements Traceability
Evidence base: Blueprint PDF (read in full, 45 sections), the written specs in the master prompt, and the 27 source files of this project.
Status vocabulary: IT = Implemented and tested | INT = Implemented, not fully tested | P = Partial | N = Not implemented | B = Blocked.

## 1. Blueprint analysis (what the PDF actually demands)
- One central DB, one identity system, one API; portals are views, never separate systems (s.1-3, rules 1-10).
- Six domains: www, office, fleet, oem, garage, user (s.2). Only `office` is in scope of the seven internal portals; the other four are Phase 6.
- Identity -> Organization -> Department -> Role -> Permission (s.5). Isolation enforced in backend/DB, not by hiding buttons (s.41).
- Central Service Ticket engine with 13-state lifecycle, auto technician mapping, AI classification (s.23-26).
- WABA/Marketing, lead sources, Integration Hub, workflow engine, IoT/telemetry, EVcare.AI, ICC, alerts, audit, reports (s.11-40).
- Build for 10,000 vehicles (rule 10); every feature needs a documented business purpose (rule 9).

## 2. Conflicts and ambiguities that need your decision
1. **Blueprint s.22 lists 8 departments** (incl. Finance, Sales & Marketing, Procurement). Your prompt allows exactly 7 portals. Assumed: those departments become permission-controlled modules. Please confirm.
2. **Portal selector.** Prompt s.4 says the login must "display only the seven portal choices" while the earlier prompt said employees must not pick an admin portal. Proposed: show the seven as an informational list, but backend role decides. Confirm.
3. **COO content.** Blueprint s.9 lists Today's Operations/Service Network/Technicians/Customers/Fleet/Inventory; your prompt gives a table-based layout. Proposed: your layout for visuals, Blueprint lists as data requirements.
4. **CEO s.7 lists ~55 metrics**; the dashboard has 6 cards + startup grid. Proposed: surplus metrics live in KPI Center.
5. **Blueprint refers to a "WABA Integration Setup Guide.pdf" and "18 KPI framework provided"** — the WABA guide was not supplied; the 18 KPIs are available from s.8.
6. **Role storage unknown.** Whether roles are a column, a join table or a permissions model is unverified (see 4).

## 3. Audit of the existing project (what the code really does)
| Area | Finding | Status |
|---|---|---|
| Login UI | Split screen, show/hide, remember, theme toggle, errors, loading. **Forgot-password is a dead link** (no endpoint). Logo is text, not the official asset. Language selector omitted. | P |
| Auth backend | Configurable table/columns/role map, multi-scheme verify, cookie session, server-side logout, rate limit. 32 pytest pass **on a fake store only**. Never run against the real DB. | INT |
| Role routing | Pure function + guard + backend 403 check; 53 vitest pass. | IT |
| Seven-portal selector | Not built. | N |
| Shell: sidebar | Renders the specified groups for all 7 roles. **Items are buttons that do nothing** (violates spec). | P |
| Shell: search, notifications, profile menu | Search box is inert; no notifications; sign-out only. | N |
| Shell: states | Empty state exists. No error/permission-denied page, no skeleton loaders. | P |
| CEO/COO/CTO KPI cards | Correct counts and order; values come from API, which currently returns `{}`. CTO cards show "—" not a "not configured" state. | P |
| Tabs | Tab bar works; **every non-Overview tab is a placeholder** (spec forbids). | P |
| Charts | Donut, line, bar, combo render when data exists. **Funnel, startup-metric grid, India map, tables for list-type panels fall back to plain lists** (spec forbids). No chart has ever been rendered with data. | P |
| Dashboard API | Only auth + an empty `/api/dashboard/{portal}`. No business endpoints. | P |
| Service Mgr, HR, Technician, Employee | Sidebar + empty shell only. | N |
| Business modules, ticket engine, KPI Center, account mgmt, audit log, notifications, integrations | None exist. No DB write path exists at all. | N |
| Responsive | Basic breakpoint at 900px; untested on devices. | P |
| Build | `tsc` and `vite build` clean at last run. | IT |

## 4. Authentication and database (blocked)
Not received: Phase 2 source, schema (`public`, `office_dashboard`), hashing code, session behaviour.
Smallest next action: run `python tools\inspect_schema.py` (read-only) and send the output, or send the Phase 2 backend ZIP.
Until then: Phases 3 onward that touch the DB (account management, tickets, KPIs, audit) are **B**.

## 5. Traceability checklist (Blueprint section -> status)
| § | Requirement | Status |
|---|---|---|
| 1-3 | Single backend/DB, portals as views | P (auth only) |
| 4 | Central DB entities (~45) | B (schema unknown) |
| 5 | Identity/Org/Dept/Role/Permission | B |
| 6 | Role-based dashboard routing | IT (frontend/guard); backend part INT |
| 7 | CEO must-see metrics | N (no data layer) |
| 8 | 18 KPIs, formulas, missing-data rules | N (to be specified in Phase 3/4) |
| 9 | COO dashboard | P (layout slots only) |
| 10 | CTO dashboard + KPIs | P (layout slots; no monitoring source configured) |
| 11-16 | Marketing, WABA inbox/automation, lead sources | N |
| 17, 38 | Integrations Center / Hub | N (no credentials supplied; planned) |
| 18-21 | Fleet, OEM, Garage, Customer portals | N (Phase 6) |
| 22 | Employee portal departments | N |
| 23-26 | Ticket engine, lifecycle, technician mapping, AI classification | N |
| 27-28 | IoT/Telemetry, EVcare.AI | N (external dependency) |
| 29-30 | ICC, single-dashboard concept | N |
| 31-32 | Public site entry, cross-portal access | N |
| 33 | Automated alerts | N |
| 34-36 | Automation/workflow engine, funnel | N |
| 37 | WABA plan requirements | B (guide not supplied) |
| 39 | Reports daily..annual, PDF/Excel, schedules | N (Download Report = browser print) |
| 40 | Audit & security | P (login events not yet persisted; no audit table touched) |
| 41 | Data isolation at API/DB layer | P (portal-level only; no object-level checks yet) |
| 42 | Architecture (gateway, central API) | P |
| 43 | Phases 1-8 | Phase 1 in progress |
| 44 | Intern rules 1-10 | Rules 1-4, 7, 8 respected so far |

## 6. Risks
- Auth mapping is unverified; wrong guesses lock everyone out (mitigation: env-config, fail-closed, read-only).
- In-memory logout revocation resets on restart and fails across multiple workers.
- India map needs a geographic data asset; none supplied and none can be fetched from this environment's allowed hosts — use an npm package or a file you provide.
- Real logo and banner art not supplied.
- Telemetry, WABA, payment, email integrations need credentials; all stay "planned / not configured".

## 7. Proposed Phase 2-4 order once unblocked
1. Verify auth against real DB (blocked on schema).
2. Replace inert shell: working routes per sidebar item, search, notifications, 403/error pages, forgot-password.
3. Shared account management + audit logging (only additive migrations, reviewed first).
4. Ticket engine -> CEO/COO/Service Manager data; CTO "not configured" states.

---
# Update — implementation round (verified results)
| Check | Result |
|---|---|
| Backend pytest (fake user store, temp SQLite, no real DB) | 53 passed |
| Frontend vitest (routing guard only; no component render tests) | 103 passed |
| `tsc --noEmit` | clean |
| `vite build` | succeeded |
| `npm audit` | 0 vulnerabilities (react-router-dom 7.18.4, vite 8.3.5, vitest 5.0.5; I exceeded the 6.30.6 target because 6.30.6 still carried 2 moderate advisories) |
| Real database / real CEO account | NOT verified (schema still unavailable) |

## Status by area
**Implemented and tested (against fakes):** session re-validation on every request (deactivation and role change end the session), Remember Me off by default, CSRF token on state-changing requests, Origin allow-list, validated request models, generic 500s, proxy header trusted only with TRUSTED_PROXY=true, throttling per IP+username, restart-safe logout (SQLite revocation file), JSONL security audit log without secrets, CEO read-only access to COO/CTO (COO/CTO not cross-allowed), ticket lifecycle rules (13 states, role-gated), WABA status endpoint that never returns values.
**Implemented, not render-tested:** real routes for every sidebar item, active states, tabs with content, page search, notifications panel, profile menu, forgot-password page, CSV export, persistent theme, seven-portal list on login, donut/line/bar/combo charts, CSS funnel, startup/health metric grids, India state-shaded map, tables with fixed columns. No browser or screenshot check was run.
**Partial:** non-Overview tabs reuse the Overview panels; Reports tab exports CSV only (no PDF/scheduled). Sidebar pages for modules show an honest "no backend yet" state.
**Not implemented:** employee/technician management, roles admin, attendance/leave/tasks, ticket persistence and API (rules only), fleet/inventory/CRM/finance/KPI Center data, integrations hub UI, WABA sending, Unified Inbox, EVcare.AI, IoT, ICC, external portals, Service Manager/HR/Technician/Employee dashboards (shell + navigation only), forgot-password email.
**Blocked:** real login compatibility (schema/hash/role source), WABA live use (provider, WABA ID, Phone Number ID, token, setup guide, country-code confirmation for 9014336878), monitoring/billing sources for CTO KPIs.

## Known limitations
- Revocation store is a local SQLite file: correct for one host / multiple workers, not for multiple servers.
- Session lifetime is checked against the token; cookies are Secure only when COOKIE_SECURE=true (set it behind HTTPS).
- Ticket lifecycle assumptions beyond the Blueprint chain are listed in backend/tickets.py.

---
# Verification round (clean-room re-check)
Method: extracted the ZIP into a fresh folder, new venv, `npm ci`. No newer ZIP or original Phase 2 source was supplied; nothing could be diffed against a newer version.

## Results actually run
| Check | Result |
|---|---|
| Backend pytest (all) | 60 passed (53 logic tests + 7 against a disposable local Postgres) |
| Frontend vitest | 131 passed (103 routing + 28 component render tests) |
| `tsc --noEmit` | clean (after adding DOM.Iterable lib) |
| `vite build` | succeeded |
| `npm audit` | 0 vulnerabilities; react-router-dom 7.18.4 |
| Startup with no auth mapping | API answers 503 "Auth is not configured" (no crash) |

## Defects found and fixed this round
1. Sidebar was an `<aside>` labelled "Main navigation" (wrong landmark); now a real `<nav>`.
2. tsconfig lacked DOM.Iterable (type error in new tests).

## Status against the master prompt
| Area | Status |
|---|---|
| Seven portals exist, URL-guarded, backend 403s, CEO read-only COO/CTO only | Implemented and tested |
| Session security (live active/role re-check, CSRF, origin list, restart-safe logout, remember off) | Implemented and tested (fake store + disposable Postgres) |
| SQL adapter (SELECT-only) | Implemented and tested on a test schema I defined; **not** on your schema |
| Existing CEO/employee account compatibility | Blocked (schema, hash format, role source unknown) |
| Navigation: every sidebar item routes; active states; page search; notifications; profile; forgot-password; theme; CSV export | Implemented and tested (render tests) |
| CEO/COO/CTO: KPI order, tab counts, every specified panel, chart components | Partially implemented: layout and rendering tested; **no real data exists**, so charts with data are only tested for funnel/map/metrics/tables, not donut/line/bar/combo (jsdom has no layout) |
| Tabs | Partially implemented: each shows content from the Overview panels; Reports exports CSV only |
| Service Manager, HR, Technician, Employee portals | Partially implemented: routed shells with navigation; modules show "no backend yet" |
| Ticket lifecycle | Partially implemented: rules tested, no API or persistence |
| Employee/technician management, roles admin, attendance, leave, tasks, approvals, fleet, inventory, CRM, finance, KPI Center, reports, automation | Not implemented |
| Integration Hub UI, WABA sending, Unified Inbox, Email | Not implemented; WABA status endpoint only (Blocked on provider, WABA ID, Phone Number ID, token) |
| EVcare.AI, IoT, ICC, fleet/OEM/garage/customer portals | Not implemented |
| CTO monitoring/billing KPIs | Blocked (no source configured; UI shows "Not configured") |
| Notifications, email reset | Blocked (no backend source/email service) |

WhatsApp: 9014336878 appears only as `WABA_BUSINESS_PHONE` (a phone number; no +91 added). It is never used as a WABA ID or Phone Number ID and nothing is sent.

## Not verified
Browser rendering/screenshots, mobile layouts, real-DB behaviour, CSRF over real cross-site conditions, load.

---
# Implementation round: CRM vertical slice (first verified end-to-end workflow)
Audit of what existed: login/session/CSRF/audit layers, routed module pages that showed "no backend yet", CEO dashboard slots fed by an empty `/api/dashboard/ceo`. Reused all of it; no duplicate auth, API layer, or pages.

## Files
Created: db/003_crm.sql, backend/crm.py, backend/tests/test_crm.py, frontend/src/Crm.tsx, frontend/src/crm.render.test.tsx.
Modified: backend/main.py (router include + CEO KPI feed), backend/.env.example, frontend/src/api.ts (`api.call`), frontend/src/Dashboard.tsx (renders Crm for the two existing CRM routes).

## Evidence (all run)
Backend pytest: 74 passed (incl. 8 CRM end-to-end tests on a disposable Postgres). Frontend vitest: 136 passed. tsc clean. vite build OK. npm audit: 0 vulnerabilities.

## Status
| Feature | Status |
|---|---|
| Contacts: create/read/update/search/paginate/archive, validation, duplicate-email 409, persistence across relogin | Implemented and tested (disposable Postgres) |
| Leads: create/edit/stage change/filter/search/archive/notes, transition rules (no going back, terminal won/lost, lost needs reason), contact linking without duplicates | Implemented and tested (disposable Postgres) |
| CRM permissions (write: ceo; read: ceo, coo; configurable), CSRF, audit file | Implemented and tested |
| CEO dashboard "New Leads" KPI (last 30 days) and Leads Pipeline from real rows; "crm" shown unavailable when DB unreachable | Implemented and tested |
| CRM pages in the browser (list, search, add/edit form, confirm-archive, stage select, errors, no fake success) | Implemented, render-tested only. Not tried against your Supabase or in a real browser |
| Running db/003_crm.sql on your Supabase | NOT done. Needs you to run it |
| Customers, quotations/orders, employees, attendance, tasks/approvals, other KPIs, finance, reports, CSV export of CRM, integrations | Not implemented |
| Production deployment | Not done; not production-ready |

## Assumptions to confirm
Lead stages (new, contacted, qualified, proposal, negotiation, won, lost) follow the CEO reference funnel; they are not confirmed company policy. Pipeline counts are leads *currently in* each stage (not cumulative). "New Leads" = leads created in the last 30 days. No CCO role exists; CRM write access defaults to ceo only.

---
# CRM bug-fix round (code only; NO Supabase access, nothing run against any real database)
Supabase: project kfyakvllofevjgmbxtpr was NOT accessible to the connected account (permission denied). No query or change was made to any project.
Fixed + regression-tested on a disposable local Postgres: stages are now New Lead / Contacted / Proposal Sent / Negotiation / Won / Lost ("qualified" rejected by the API,
legacy rows still readable and movable forward); null/blank title or stage -> 422 (was 500); lead can be unlinked from its contact; contact picker searches on the server
(was capped at 100); lead-note creation audited; CEO snapshot failures are logged (class name only); prepare_threshold=None for Supabase pooler compatibility.
Prepared, NOT applied: db/004_pipeline_stages.sql (+ .rollback.sql). Aborts if any 'qualified' rows exist; never rewrites data.
Evidence: backend pytest 82 passed; frontend vitest 139 passed; tsc clean; vite build OK.

---
# Delete (= archive) round (code only; no live DB, no migrations applied)
Delete is a soft delete (is_archived=true); rows, notes and relationships are kept; archived records are excluded from lists, search, detail and dashboard counts.
New server-side permission CRM_ARCHIVE_ROLES (default ceo; must also have CRM read access); write access alone cannot delete; denied attempts are audited (crm_archive_denied).
Audit (existing JSONL sink) now records actor, record_type, record id and timestamp for contact_archived / lead_archived. Permanent deletion is NOT implemented (future approved phase).
Pending, not applied: db/004_pipeline_stages.sql. No new migration is needed for Delete. Note: the audit trail is a file (audit.jsonl), not a DB table.
Evidence: backend pytest 88 passed; frontend vitest 143 passed; tsc clean; vite build OK. Not tested against Supabase.
