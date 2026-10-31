# Module status (all sidebar items, all 7 portals)

Generated from frontend/src/nav.ts on 2026-10-26. Status words: **Fully implemented**, **Partially implemented**, **UI-only**, **Blocked**, **Not implemented**.
Rule used: a page that only shows a "no backend yet" placeholder is **Not implemented**. **Blocked** = needs something only you can supply (credentials, a data source, a policy decision).

**Totals (114 sidebar entries across portals):** Partially implemented: 13 · Not implemented: 81 · Fully implemented: 2 · Blocked: 16 · UI-only: 2

**Verification caveat:** this session could not install FastAPI/psycopg/pytest or the npm packages (package registries were denied by the sandbox proxy), so no API test and no frontend test was executed. See docs/TEST_REPORT.md for exactly what was run.

## CEO portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| CEO Dashboard | Partially implemented | Layout complete; New Leads KPI and Leads Pipeline use real rows. Every other KPI/panel shows no data because no source module exists. | Render tests from earlier round; not re-run |
| Startup Metrics | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| KPI Center | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Business Overview | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Reports & Analytics | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| CRM & Contacts | Fully implemented | Contacts and leads: create/read/update/search/paginate, stage rules, notes, soft-delete, CEO dashboard feed. Quotations/orders are separate (not built). | Earlier-round tests (Postgres-backed); NOT re-run this session |
| Leads & Pipeline | Fully implemented | Contacts and leads: create/read/update/search/paginate, stage rules, notes, soft-delete, CEO dashboard feed. Quotations/orders are separate (not built). | Earlier-round tests (Postgres-backed); NOT re-run this session |
| Customers (Fleets/OEMs) | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Sales & Marketing | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| WABA (WhatsApp) | Blocked | Needs messaging provider and email service credentials; nothing is sent or received. | - |
| Email | Blocked | Needs messaging provider and email service credentials; nothing is sent or received. | - |
| Unified Inbox | Blocked | Needs messaging provider and email service credentials; nothing is sent or received. | - |
| Quotations & Orders | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Service Tickets | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Fleet Management | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Garages & Service Centers | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technicians | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| EVcare.AI Diagnostics | Blocked | Needs an external AI/telemetry source. | - |
| IoT & Telemetry | Blocked | Needs an external AI/telemetry source. | - |
| Revenue & Invoices | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Expenses | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Payments & Receivables | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Budget & Forecast | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Employees | Partially implemented | Directory, search, edit designation/phone/department, deactivate/reactivate (CEO only). No create-employee form yet (CLI tools/create_account.py exists). | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Attendance | Partially implemented | Check-in/out (server clock, duplicate-protected), daily records, monthly summary, team-today view, correction requests with approval, admin-configured shift/timezone/working days, late/early rules, DB audit. Leave and holidays are now integrated (needs 008). Missing: breaks, shift per person/roster, reports/export, notifications. Needs migration 007. | Rules: 11 tests PASS (executed). API tests (10) and UI: written, NOT executed. SQL 007 not run on any database. |
| Tasks & Approvals | Partially implemented | Core workflow works (create, assign, status, approval with no self-approval, archive, per-role scoping). Missing: comments, attachments, notifications, recurring tasks. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| HR & Leave | Partially implemented | Leave types and policies (entitlement, half days, notice, backdating, max length; all admin-entered, none seeded), apply for leave (server counts working days minus holidays), overlap and balance checks, approve/reject (never own request), cancel/correct, balances from approved leave, holiday calendar, team leave calendar, attendance integration (approved leave and holidays excluded from missing days). Missing: notifications (no notification system yet), carry-forward, manager-based approval, leave on behalf of others, reports/export, comp-off/encashment. Needs migration 008 (after 007). | Rules: 9 tests PASS (executed); attendance integration rules PASS. API tests (10) and UI: written, NOT executed. SQL 008 not run on any database. |
| Documents | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Integrations | Blocked | Same as CTO: WABA status endpoint only. Needs provider, WABA ID, Phone Number ID, token. | Earlier-round test |
| Settings | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Audit Log | Partially implemented | Viewer for the new DB audit table with filters. Only task and employee changes are written there so far; CRM and login events remain in the JSONL file. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |

## COO portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| COO Dashboard | Partially implemented | Layout only; no data source for any COO KPI. | Render tests from earlier round; not re-run |
| Service Tickets | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Fleet Management | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Garages & Service Centers | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technicians | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Spare Parts & Inventory | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Procurement | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Vehicle Inspections | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Renewals & Compliance | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Operations Analytics | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Team Management | Partially implemented | Read-only employee directory (COO has read, no write). | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Tasks & Approvals | Partially implemented | Core workflow works (create, assign, status, approval with no self-approval, archive, per-role scoping). Missing: comments, attachments, notifications, recurring tasks. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Attendance | Partially implemented | Check-in/out (server clock, duplicate-protected), daily records, monthly summary, team-today view, correction requests with approval, admin-configured shift/timezone/working days, late/early rules, DB audit. Leave and holidays are now integrated (needs 008). Missing: breaks, shift per person/roster, reports/export, notifications. Needs migration 007. | Rules: 11 tests PASS (executed). API tests (10) and UI: written, NOT executed. SQL 007 not run on any database. |
| HR & Leave | Partially implemented | Leave types and policies (entitlement, half days, notice, backdating, max length; all admin-entered, none seeded), apply for leave (server counts working days minus holidays), overlap and balance checks, approve/reject (never own request), cancel/correct, balances from approved leave, holiday calendar, team leave calendar, attendance integration (approved leave and holidays excluded from missing days). Missing: notifications (no notification system yet), carry-forward, manager-based approval, leave on behalf of others, reports/export, comp-off/encashment. Needs migration 008 (after 007). | Rules: 9 tests PASS (executed); attendance integration rules PASS. API tests (10) and UI: written, NOT executed. SQL 008 not run on any database. |
| Documents | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Customers (Fleets/OEMs) | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Vehicle Directory | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Service History | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Expenses | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Purchase Requests | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Payments & Invoices | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Reports | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Knowledge Base | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Settings | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Audit Log | Blocked | Page routes to the audit viewer but the proposed matrix gives COO no audit.read, so the server returns 403. Needs a policy decision. | Matrix test passes (plain Python) |

## CTO portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| CTO Dashboard | Partially implemented | Layout only; monitoring/billing sources not configured, shown as Not configured. | Render tests from earlier round; not re-run |
| System Monitoring | Blocked | Needs a monitoring/cloud/billing source and credentials; none supplied. | - |
| Tech Projects | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| AI & Innovation | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technical Reports | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Infrastructure | Blocked | Needs a monitoring/cloud/billing source and credentials; none supplied. | - |
| APIs & Integrations | Blocked | Only a WABA configuration-presence endpoint exists (never returns secrets, never sends). Needs provider and credentials. | Earlier-round test |
| Database | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Servers & Cloud | Blocked | Needs a monitoring/cloud/billing source and credentials; none supplied. | - |
| DevOps & Deployment | Blocked | Needs a monitoring/cloud/billing source and credentials; none supplied. | - |
| Security & Access | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Logs & Audit | Partially implemented | Same audit viewer (CTO has audit.read). Server/application logs are not connected. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Application | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Mobile App | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| IoT & Telemetry | Blocked | Needs an external AI/telemetry source. | - |
| EVcare.AI | Blocked | Needs an external AI/telemetry source. | - |
| R&D Projects | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Service Platform | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technician App | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Platform Analytics | Blocked | Needs a monitoring/cloud/billing source and credentials; none supplied. | - |
| Tech Team | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Tasks & Approvals | Partially implemented | Core workflow works (create, assign, status, approval with no self-approval, archive, per-role scoping). Missing: comments, attachments, notifications, recurring tasks. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Documents | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Knowledge Base | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Settings | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Integrations | Blocked | Only a WABA configuration-presence endpoint exists (never returns secrets, never sends). Needs provider and credentials. | Earlier-round test |
| Audit Log | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |

## Service Manager portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| Dashboard | UI-only | Routed shell with navigation; no widgets or data. | Render test (earlier round) |
| Ticket Queue | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technician Allocation | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Job Cards | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Spare-Parts Requests | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Quality Checks | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Escalations | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Reports | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |

## HR portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| Dashboard | UI-only | Routed shell with navigation; no widgets or data. | Render test (earlier round) |
| Employee Directory | Partially implemented | Directory, search, edit designation/phone/department. Deactivation is CEO-only by the proposed matrix. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Add Employee | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Technicians | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Attendance | Partially implemented | Check-in/out (server clock, duplicate-protected), daily records, monthly summary, team-today view, correction requests with approval, admin-configured shift/timezone/working days, late/early rules, DB audit. Leave and holidays are now integrated (needs 008). Missing: breaks, shift per person/roster, reports/export, notifications. Needs migration 007. | Rules: 11 tests PASS (executed). API tests (10) and UI: written, NOT executed. SQL 007 not run on any database. |
| Leave | Partially implemented | Leave types and policies (entitlement, half days, notice, backdating, max length; all admin-entered, none seeded), apply for leave (server counts working days minus holidays), overlap and balance checks, approve/reject (never own request), cancel/correct, balances from approved leave, holiday calendar, team leave calendar, attendance integration (approved leave and holidays excluded from missing days). Missing: notifications (no notification system yet), carry-forward, manager-based approval, leave on behalf of others, reports/export, comp-off/encashment. Needs migration 008 (after 007). | Rules: 9 tests PASS (executed); attendance integration rules PASS. API tests (10) and UI: written, NOT executed. SQL 008 not run on any database. |
| Documents | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Roles & Access | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Audit History | Not implemented | Placeholder page. Proposed matrix gives HR no audit.read; needs a policy decision. | - |

## Technician portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| My Jobs | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Job Cards | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Parts Requests | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Service History | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Tasks | Partially implemented | Core workflow works (create, assign, status, approval with no self-approval, archive, per-role scoping). Missing: comments, attachments, notifications, recurring tasks. Technicians see only their own tasks. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Attendance | Partially implemented | Check-in/out (server clock, duplicate-protected), daily records, monthly summary, team-today view, correction requests with approval, admin-configured shift/timezone/working days, late/early rules, DB audit. Leave and holidays are now integrated (needs 008). Missing: breaks, shift per person/roster, reports/export, notifications. Needs migration 007. | Rules: 11 tests PASS (executed). API tests (10) and UI: written, NOT executed. SQL 007 not run on any database. |
| Notifications | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |

## Employee portal

| Sidebar item | Status | What exists / what is missing | Verification |
|---|---|---|---|
| My Tasks | Partially implemented | Core workflow works (create, assign, status, approval with no self-approval, archive, per-role scoping). Missing: comments, attachments, notifications, recurring tasks. Employees see only their own tasks. | SQL run on PostgreSQL 16; rules run in plain Python; API/UI tests written, not executed |
| Attendance | Partially implemented | Check-in/out (server clock, duplicate-protected), daily records, monthly summary, team-today view, correction requests with approval, admin-configured shift/timezone/working days, late/early rules, DB audit. Leave and holidays are now integrated (needs 008). Missing: breaks, shift per person/roster, reports/export, notifications. Needs migration 007. | Rules: 11 tests PASS (executed). API tests (10) and UI: written, NOT executed. SQL 007 not run on any database. |
| Leave Requests | Partially implemented | Leave types and policies (entitlement, half days, notice, backdating, max length; all admin-entered, none seeded), apply for leave (server counts working days minus holidays), overlap and balance checks, approve/reject (never own request), cancel/correct, balances from approved leave, holiday calendar, team leave calendar, attendance integration (approved leave and holidays excluded from missing days). Missing: notifications (no notification system yet), carry-forward, manager-based approval, leave on behalf of others, reports/export, comp-off/encashment. Needs migration 008 (after 007). | Rules: 9 tests PASS (executed); attendance integration rules PASS. API tests (10) and UI: written, NOT executed. SQL 008 not run on any database. |
| Profile | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Documents | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Announcements | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |
| Team Directory | Not implemented | Placeholder page ("no backend yet"). No data, no API. | - |

## Implementation update — 2026-10-26 (workspace foundation)

A generic persisted-record workspace was added for many previously placeholder sidebar pages. It supports create, search, edit, archive, paging (API), CSV export, field validation, permission checks, and database audit records. It stores only records entered by an authorized user; it does not seed fake operational metrics. See `backend/workspaces.py`, `frontend/src/Workspace.tsx`, and `db/009_module_records.sql`.

**Important limitation:** this is a reusable CRUD foundation, not completion of all 33 domain modules. Domain-specific workflows such as invoice/payment allocation, customer-fleet relationships, quotations/orders calculations, ticket lifecycle rules, email/WABA send/receive, diagnostic inference, IoT telemetry, KPI formulas, advanced reports, onboarding/offboarding, attendance breaks, leave carry-forward, task attachments/comments/notifications, and provider monitoring remain incomplete or blocked pending dedicated implementations/data/credentials. Existing CRM, leads, people, attendance, leave, and tasks components were preserved. Migration 009 has not been applied to a real database.

## Follow-up implementation update — 2026-10-26 (structured workspace usability)

Changes in this iteration:
- Generic workspace forms now expose module-specific structured fields for KPI tracking, startup metrics, customers/fleets/OEMs, sales campaigns, quotations/orders, service tickets, fleets, garages, technicians, diagnostic/telemetry source references, invoices, expenses, payments, budgets, documents, integrations, activities, follow-ups, organizations, announcements, knowledge base, projects, and monitoring references.
- Workspace list supports search, status filtering, creation-date range filtering, pagination, status breakdown, and a summary based on persisted records only.
- CSV export now requests up to 10,000 matching persisted records and carries the active search/status/date filters; a truncation notice is shown when the cap is reached.
- Backend adds module summary and export endpoints, server-side date/status filtering, stricter custom-field validation, and export permission enforcement.
- No operational, financial, diagnostic, or telemetry data is generated automatically. Provider-dependent actions remain disabled without real credentials/source systems.

Verification status for this iteration:
- `python -m py_compile backend/*.py`: passed.
- Added unit tests for custom-field validation and provider-module registry, but the pytest suite could not be executed because `psycopg` and `bcrypt` are missing in the environment and package installation timed out.
- Frontend build/tests could not be executed because npm dependency installation timed out; TypeScript/Vitest results are therefore unknown.
- Migration 009 is still unapplied and unverified against the target database.

This iteration improves the reusable workspace foundation; it does not complete all domain-specific features in the 33-module request. Module-specific gaps and external configuration dependencies remain open.


## Service Tickets implementation update — 2026-10-26

- Added dedicated ticket and ticket-comment persistence in migration 010.
- Added protected ticket list/create, lifecycle transition and comments APIs. Every transition delegates to the existing `backend/tickets.py` role-based lifecycle rules; invalid transitions return a conflict instead of silently changing status.
- Added a ticket UI with search, status filter, pagination, creation, transition attempts and comments. Technician records are scoped to assigned/created tickets in list results.
- Status: implementation added, but not fully verified. Migration 010 is unapplied; API/UI tests and database integration tests could not run because dependencies/database are unavailable.
