# Sidebar-wise implementation checklist (generated from frontend/src/nav.ts, 2026-10-26)

Structure per module: **Sidebar → Subpages → Features → Sub-features/actions → API → DB → Permissions → Integrations → Status.**
Status vocabulary: COMPLETE (implemented + tests executed and passed) / PARTIAL / BLOCKED / NOT IMPLEMENTED.
Today every status below is PARTIAL, BLOCKED or NOT IMPLEMENTED: no module is COMPLETE, because API/UI tests could not be executed in the build sandbox.
Rule for all modules: no dummy buttons, no hardcoded metrics; unavailable data is shown as "unavailable". Every write: server RBAC (`access.need`) + CSRF + DB audit row in the same transaction. Every list: server-side search/filter/pagination.

## 0. Sidebar inventory (actual) and mapping

85 unique items. Portal routes are `/<portal>/<slug>`; any item without a page renders the "no backend yet" placeholder (Dashboard.tsx).

| Portal | Group → items | Maps to module(s) below |
|---|---|---|
| CEO | Strategic: CEO Dashboard, Startup Metrics, KPI Center, Business Overview, Reports & Analytics | M1–M5 |
| CEO | Business: CRM & Contacts, Leads & Pipeline, Customers (Fleets/OEMs), Sales & Marketing, WABA, Email, Unified Inbox, Quotations & Orders | M6–M13 |
| CEO | Operations: Service Tickets, Fleet Management, Garages & Service Centers, Technicians, EVcare.AI Diagnostics, IoT & Telemetry | M14–M19 |
| CEO | Finance: Revenue & Invoices, Expenses, Payments & Receivables, Budget & Forecast | M20–M23 |
| CEO | People & Office: Employees, Attendance, Tasks & Approvals, HR & Leave, Documents | M24–M28 |
| CEO | Administration: Integrations, Settings, Audit Log | M29–M31 |
| COO | COO Dashboard | M32 |
| COO | Service Tickets, Fleet Management, Garages, Technicians | M14–M17 (read scope) |
| COO | **Spare Parts & Inventory, Procurement, Vehicle Inspections, Renewals & Compliance, Operations Analytics** | **X1, X2, X3, X4, M5/M32** |
| COO | Team Management, Tasks, Attendance, HR & Leave, Documents | M24–M28 (read scope) |
| COO | Customers (View), **Vehicle Directory**, **Service History** | M8, M15, M14 |
| COO | Finance (View): Expenses, **Purchase Requests**, **Payments & Invoices** | M21, X2, M20+M22 |
| COO | Reports, **Knowledge Base**, Settings, Audit Log | M5, X5, M30, M31 |
| CTO | CTO Dashboard, **System Monitoring**, **Technical Reports**, **Platform Analytics** | M33, M33, M5, M33 |
| CTO | **Infrastructure, Servers & Cloud, Database, DevOps & Deployment, Security & Access, Logs & Audit** | M33 subpages (+M31 for Logs & Audit) |
| CTO | **APIs & Integrations**, Integrations | M29 |
| CTO | **Tech Projects, R&D Projects, AI & Innovation** | X6 (+M18/M-AI assistant) |
| CTO | **Application, Mobile App, Service Platform, Technician App** | M33 / X7 |
| CTO | IoT & Telemetry, EVcare.AI, **Tech Team**, Tasks, Documents, Knowledge Base, Settings, Audit Log | M19, M18, M24/M26, M26, M28, X5, M30, M31 |
| Service Manager | **Dashboard, Ticket Queue, Technician Allocation, Job Cards, Spare-Parts Requests, Quality Checks, Escalations, Reports** | M14 subpages, X1, X3, X8 |
| HR | **Dashboard, Employee Directory, Add Employee, Technicians, Attendance, Leave, Documents, Roles & Access, Audit History** | M24, M17, M25, M27, M28, M30, M31 |
| Technician | **My Jobs, Job Cards, Parts Requests, Service History, Tasks, Attendance, Notifications** | M14, X8, X1, M26, M25, B |
| Employee | **My Tasks, Attendance, Leave Requests, Profile, Documents, Announcements, Team Directory** | M26, M25, M27, M24, M28, X9, M24 |

Modules not in your 33-list but present in the sidebar (must be built, no duplicates): **X1 Spare Parts & Inventory (incl. Parts Requests), X2 Procurement / Purchase Requests, X3 Vehicle Inspections & Quality Checks, X4 Renewals & Compliance, X5 Knowledge Base, X6 Tech Projects / R&D / AI & Innovation, X7 Mobile App / Technician App (field UI over M14/M26), X8 Job Cards (belongs to M14), X9 Announcements.** Cross-cutting: **A Global Search, B Notification Center, C Workflow Automation, D Activity Timeline, E Import/Export, F File Storage, G AI Assistant.**

## 1. Shared foundations (build first; every module depends on them)
| Item | Required | API | DB | Status |
|---|---|---|---|---|
| RBAC single source | CRM + dashboards + waba move to `permissions.py`/`need()`; remove env-role logic | all | none | PARTIAL (tasks/people only) |
| DB audit everywhere | login/logout/denials/CRM through `auditdb.record` | `GET /api/audit` | audit_log (005) | PARTIAL |
| Organizations | shared org table, contact↔org | `/api/organizations` CRUD | organizations, contact.org_id | NOT IMPLEMENTED |
| Notifications (B) | in-app, read/unread, prefs, links | `/api/notifications` (currently stub) | notifications, notification_prefs | NOT IMPLEMENTED |
| Timeline (D) | event feed per entity | `/api/timeline/{type}/{id}` | activity_events | NOT IMPLEMENTED |
| File storage (F) | private storage, validation, signed download | `/api/files` | files, file_links | NOT IMPLEMENTED |
| Settings backbone | departments, designations, currency, tax, timezone, working days | `/api/settings/*` | settings, departments(001), designations | NOT IMPLEMENTED |
| Money rules | totals, status, allocation, aging | (library) | — | `financelogic.py` done, 10 tests PASS; unwired |

## 2. Strategic (CEO)
### M1 CEO Dashboard — PARTIAL
- Subpages/tabs: Overview, Financial, Customers, Operations, Sales & Marketing, People, AI Insights (from LAYOUT.ceo).
- Features: KPI cards (revenue, margin, customers, tickets, new leads, cash), panels (revenue trend, customer growth, ticket status, startup metrics, pipeline, top cities, activities, approvals, messages, insights).
- Sub-features: date-range filter; KPI drill-down links; export; widget config; show "unavailable" per source; calculation period + source label.
- API: `GET /api/dashboard/ceo?from&to` (today only returns CRM snapshot). DB: reads from M6/M7/M20–M27 tables via views. Perms: `kpi.read`. Needs: M6–M27 data.
- Real today: New Leads KPI, Leads Pipeline. Everything else has no source.
### M2 Startup Metrics — NOT IMPLEMENTED
- Features: growth, acquisition, retention, conversion, sales cycle, churn, CAC, LTV, margin, burn/runway (METRICS.startup list), forecast vs actual, MoM/QoQ/YoY.
- Sub-features: metric definitions page; formula shown per metric; metrics only when inputs exist (e.g. CAC needs M9 costs).
- API: `/api/metrics/startup`, `/api/metrics/definitions`. DB: `metric_snapshots` (period, key, value, inputs jsonb). Perms: `kpi.read/export`.
### M3 KPI Center — NOT IMPLEMENTED
- Features: KPI CRUD, category, owner (employee/department), unit, frequency, target, thresholds, actual entries, progress, history, review comments, alerts, reports.
- API: `/api/kpis`, `/api/kpis/{id}/values`, `/api/kpis/{id}/reviews`. DB: kpis, kpi_values, kpi_reviews. Perms: `kpi.*`. Integrations: notifications (threshold alerts). No invented targets.
### M4 Business Overview — NOT IMPLEMENTED
- Subpages/sections: company, departments, sales, customers, finance, employees, operations, risks, pending decisions, alerts.
- API: `/api/overview/{section}` aggregating read-only views. DB: `business_risks`, `decisions` (new) + views. Perms: `reports.read`.
### M5 Reports & Analytics (also COO Reports, CTO Technical Reports) — NOT IMPLEMENTED
- Report catalogue: sales, CRM, conversion, customer, campaign, revenue, invoice, payment, expense, budget, attendance, employee, leave, task, approval, service, fleet, technician, integration health, audit.
- Sub-features: date range, filters, grouping, saved configs, CSV/XLSX/PDF export, scheduled reports (needs email), per-report permission.
- API: `/api/reports/{key}`, `/api/reports/saved`, `/api/reports/{key}/export?fmt`. DB: saved_reports, report_schedules. Perms: `reports.read/export` + module permission of the data.

## 3. Business
### M6 CRM & Contacts — PARTIAL (project marks Fully; tests not re-run)
- Exists: contacts create/read/update/search/paginate/soft-delete, notes (on leads), audit to JSONL.
- Missing: organizations (shared), tags/categories, source, ownership, archive **restore**, duplicate detection beyond email, CSV import/export, follow-ups + reminders + overdue, calls/meetings, consent & preferences, email/WhatsApp history, timeline, links to quotes/orders/invoices/tickets, record-level permissions, DB audit, move to `need("crm.*")`.
- API additions: `/api/organizations`, `/api/contacts/{id}/timeline|activities|followups|consent`, `/api/contacts/import|export`, `/api/tags`. DB: organizations, tags, contact_tags, contact_activities, followups, consents.
### M7 Leads & Pipeline — PARTIAL
- Exists: leads CRUD, stage rules, notes, search/paginate, soft-delete, CEO feed. Stages per spec require migration **004** (not applied).
- Missing: assignment/owner, source, priority, expected value/close date, org link, follow-ups, stage history, lost reason, scoring suggestion, forecast, kanban view, owner/date/source filters, restore, conversion report.
- DB: leads add owner_id, source, priority, expected_value, expected_close, lost_reason; lead_stage_history. API: `/api/leads/{id}/assign|stage-history|convert`, `/api/pipeline/summary`.
### M8 Customers (Fleets/OEMs) — NOT IMPLEMENTED
- Features: organization profile + type (OEM/fleet), decision-makers, account manager, classification, lifecycle, contracts + renewal dates, documents, vehicles, orders, invoices, payments, service history, comms, tasks, notes, health rules, reports.
- API: `/api/customers`, `/api/customers/{id}/contracts|vehicles|orders|invoices|timeline`. DB: customers (extends organizations), contracts. Depends: organizations, M13, M15, M20, M28.
### M9 Sales & Marketing — NOT IMPLEMENTED
- Features: opportunities, deal owner, targets, activities, forecast, closure; campaigns (CRUD, schedule, budget, audience segments, lists, templates, approval), attribution, performance, CPL/ROI when cost data exists, channel comparison, reports.
- DB: opportunities, sales_targets, campaigns, campaign_members, audiences, templates. Integrations: M10/M11 for sending, M7 attribution.
### M10 WABA (WhatsApp) — BLOCKED (provider choice/credentials)
- Build now (provider-independent): provider config, webhook endpoint + signature verification, idempotent event store, conversations/messages, template registry + status, consent/opt-out, status model accepted→delivered→read/failed, retry policy, logs, usage.
- Today: only `GET /api/integrations/waba` (presence of env vars). `live_sending=false`; never claim sent without provider evidence.
- DB: wa_accounts, wa_conversations, wa_messages, wa_templates, wa_events(unique event id), consents. Needs: provider, WABA ID, phone number ID, token (in `.env`, not chat).
### M11 Email — BLOCKED (SMTP/provider key)
- Build now: provider config, test connection, templates + variables, send queue with status/retry, recipient validation, attachments (M28/F), contact-linked history, transactional notifications, provider logs, search.
- DB: email_accounts, email_templates, email_messages, email_attachments, email_queue.
### M12 Unified Inbox — NOT IMPLEMENTED (needs M10/M11)
- Features: unified conversation list, identity → CRM contact link, assignment/owner, status/priority/tags, search/filters, unread, history, **internal notes separate from customer messages**, response-time, escalation rules, agent workload, timeline.
- DB: conversations(channel-agnostic), conversation_notes, assignments. API: `/api/inbox/*`.
### M13 Quotations & Orders — NOT IMPLEMENTED (+ calculation foundation exists)
- Subpages: Catalogue, Quotations, Orders.
- Features: product/service (code, unit, price, tax, active); quotation (number, dates, lines, discounts, tax, currency, terms, approval, versions, PDF, send via M10/M11, statuses draft→pending approval→sent→accepted/rejected/expired); orders (from accepted quote, idempotent creation, items, statuses, cancellation, invoice link, history).
- Totals computed server-side with `financelogic.py`. DB: products, quotations, quotation_items, quotation_versions, orders, order_items. Perms: `quotations.*`, `orders.*`.

## 4. Operations
### M14 Service Tickets (+ Ticket Queue, Technician Allocation, Job Cards, Escalations, Quality Checks, Service History, Reports, My Jobs) — NOT IMPLEMENTED
- Preserve lifecycle rules in `backend/tickets.py` (only rule file exists).
- Features: create/numbering, customer + vehicle link, category, description, priority/severity, assign technician/team, status transitions, SLA policies + due dates, escalation rules, internal notes vs customer updates, attachments, history, resolution codes, reopen/close, job cards (parts used, labour, checklist, sign-off), reports, KPIs (open, overdue, resolution time, workload).
- DB: tickets, ticket_events, sla_policies, job_cards, job_card_parts. API: `/api/tickets`, `/api/job-cards`. Perms: `tickets.*` (technician: assigned only).
### M15 Fleet Management (+ Vehicle Directory) — NOT IMPLEMENTED
- Vehicle registry (VIN/reg), specs, customer link, status, assignment, maintenance schedule/history, mileage, registration + insurance expiry alerts, documents, ticket/diagnostic history, utilization report. DB: vehicles, maintenance_schedules, maintenance_records.
### M16 Garages & Service Centers — NOT IMPLEMENTED
- Profiles, contacts, location, hours, capabilities, capacity, technician assignment, appointments, repairs, history, performance. DB: service_centers, appointments.
### M17 Technicians (+ HR "Technicians") — NOT IMPLEMENTED (table `technicians` exists in 001)
- Profile ↔ employee, skills, certifications + expiry alerts, center assignment, ticket/task assignment, availability, workload, history, performance. DB: technician_skills, certifications.
### M18 EVcare.AI Diagnostics — BLOCKED (model/service endpoint)
- Fault-code ingestion, diagnostic records, severity, recommendation (labelled AI recommendation, never confirmed fault), technician review, model version/inference metadata, history, failures. DB: diagnostics, diagnostic_reviews.
### M19 IoT & Telemetry — BLOCKED (telemetry source)
- Device registry, vehicle link, authenticated ingestion, validation, duplicate protection, connectivity status (only after verified data), thresholds, anomaly alerts, health, retention, reports. DB: devices, telemetry_readings (partition/retention), alerts.
### X1 Spare Parts & Inventory (+ Parts Requests, Spare-Parts Requests) — NOT IMPLEMENTED
- Parts catalogue, stock levels per location, movements, reorder levels, requests from job cards, approval, issue/return. DB: parts, stock_movements, part_requests. Links: M14, X2.
### X2 Procurement / Purchase Requests — NOT IMPLEMENTED
- Purchase request, approval chain, vendor, PO, receipt → stock; links to Expenses/Budget. DB: vendors, purchase_requests, purchase_orders.
### X3 Vehicle Inspections & Quality Checks — NOT IMPLEMENTED
- Inspection templates, checklists, results, photos, pass/fail, linked to vehicle/ticket. DB: inspection_templates, inspections.
### X4 Renewals & Compliance — NOT IMPLEMENTED
- Registration/insurance/contract/certification renewal calendar fed by M15, M8, M17, M28; reminders via B.

## 5. Finance
### M20 Revenue & Invoices (+ COO "Payments & Invoices") — NOT IMPLEMENTED
- Invoice create/number, customer/order link, items, discount, tax, currency, dates, terms, PDF, statuses (draft/issued/partially paid/paid/overdue/cancelled), credit notes, history, revenue reports. Outstanding derived from verified allocations (`financelogic.invoice_status`). DB: invoices, invoice_items, credit_notes.
### M21 Expenses — NOT IMPLEMENTED
- Records, categories, amounts/currency, employee/department, receipt upload, approval + comments, reimbursement, budget link, duplicate check, monthly report. DB: expenses, expense_categories, expense_approvals.
### M22 Payments & Receivables — BLOCKED for gateway; foundation buildable
- Payment records, provider reference, allocations (`allocate_payment`), statuses, failed/pending, refunds, reconciliation, aging (`aging`), reminders, webhook with signature + idempotency (`idempotent_once`). No raw card data. DB: payments, payment_allocations, payment_events(unique event id).
### M23 Budget & Forecast — NOT IMPLEMENTED
- Department/month/year budgets, forecasts + assumptions, actual vs budget, variance, scenarios, approvals. DB: budgets, budget_lines, forecasts, scenarios.

## 6. People & Office
### M24 Employees (+ Team Management, Employee Directory, Add Employee, Team Directory, Profile, Tech Team) — PARTIAL
- Exists: directory, search, edit designation/phone/department, deactivate/reactivate (CEO), audit.
- Missing: create employee (UI + API + account provisioning via `tools/create_account.py` logic), ID, manager/reporting tree, join date, employment type/status, documents, onboarding tasks, probation, transfers, offboarding + exit checklist + access revocation, history, task/attendance/leave summaries; confidential-field restriction.
- DB: employees (001) extended; employment_history, onboarding_templates.
### M25 Attendance — PARTIAL (built this pass; API/UI tests not yet executed; see MODULE_STATUS)
- Check-in/out (server timestamps, timezone, duplicate protection), shifts, working days, late/early, breaks, corrections + manager approval, daily/monthly summaries, reports. DB: shifts, attendance_records, attendance_corrections.
### M26 Tasks & Approvals (+ My Tasks) — PARTIAL
- Exists: create/assign/status/approval (no self-approval)/archive/per-role scoping.
- Missing: collaborators, subtasks, dependencies, comments, attachments, history, department/workload views, overdue alerts, escalations, notifications, recurring.
### M27 HR & Leave (+ Leave, Leave Requests) — PARTIAL (built this pass; API/UI tests not yet executed; see MODULE_STATUS)
- Leave types/policies (configurable, no invented entitlements), applications, approve/reject, balances, cancellation/correction, holidays, team calendar, notifications, attendance integration, reports. DB: leave_types, leave_policies, leave_balances, leave_requests, holidays.
### M28 Documents — NOT IMPLEMENTED
- Upload (type/size validation, private storage), categories, metadata, entity links (employee/customer/contract/quote/invoice/service), search, versions, expiry + reminders, permission-checked download, secure share, archive/restore, retention, audit. DB: documents, document_versions (uses F).
### X9 Announcements / Notifications (technician, employee) — NOT IMPLEMENTED
- Announcements CRUD (HR/CEO), audience, read receipts; Notifications page over B.

## 7. Administration & dashboards
### M29 Integrations (+ CTO "APIs & Integrations") — PARTIAL (WABA presence check only) / BLOCKED
- Registry, provider config (secrets from env only), connection test, enable/disable, webhook status, sync history, last success, errors, retry/safe replay, health, usage, audit. "Connected" only after real verification. DB: integrations, integration_events.
### M30 Settings (+ Roles & Access) — NOT IMPLEMENTED
- Company profile, departments, designations, users, roles, permissions (matrix now in code; moving to DB is a decision), sessions, timezone, working days, currency, tax, notification prefs, workflow, flags, security, retention; admin-only; audited.
### M31 Audit Log (+ Audit History, Logs & Audit) — PARTIAL
- Exists: viewer with filters for DB audit table; tasks + employee changes written. Missing: auth events, CRM, finance, permission, integration events; correlation id; export (permission-gated); retention config; COO/HR `audit.read` decision.
### M32 COO Dashboard (+ Operations Analytics) — PARTIAL (layout only)
- KPIs/panels from LAYOUT.coo: vehicles, active/completed tickets, technicians on field, parts stock, procurement, service-ticket trend, fleet status, renewals, workload, inventory, centers, procurement, ongoing tickets, tasks, activity. Every panel needs real source (M14–M17, X1, X2, M24–M26); read-only for COO per matrix.
### M33 CTO Dashboard (+ System Monitoring, Infrastructure, Servers & Cloud, Database, DevOps & Deployment, Security & Access, Application, Mobile App, Service Platform, Technician App, Platform Analytics) — PARTIAL / BLOCKED
- Needs real monitoring/billing source (uptime, latency, incidents, cost). Buildable now from our own system: API error counts/latency (needs request logging), DB reachability, failed jobs, auth-failure counts, integration status. Everything else shows "not configured".
### X5 Knowledge Base — NOT IMPLEMENTED: articles, categories, search, permissions (feeds G AI search).
### X6 Tech Projects / R&D / AI & Innovation — NOT IMPLEMENTED: projects, milestones, owners, status; links to Tasks.

## 8. Cross-module workflows to test end-to-end
A Lead→Revenue, B Customer communication, C Onboarding, D Leave, E Service, F Finance (see build prompt). Each needs: authz-failure, invalid-transition, retry, duplicate-event and consistency tests.

## 9. Phase order and exit criteria
1 Verify + RBAC/audit unification → 2 Organizations, settings, notifications, timeline, files → 3 Employees/Attendance/Leave/Documents → 4 Catalogue/Quotes/Orders/Invoices/Payments → 5 WABA/Email/Inbox/automation → 6 Tickets/Fleet/Garages/Technicians/Parts/Procurement/Inspections → 7 KPIs/dashboards/reports/AI → 8 Hardening.
A module becomes COMPLETE only when: migration reviewed and applied, API tests + permission tests + UI tests executed and passed, audit rows verified, docs updated.
