# Operations: Service Tickets and Fleet Management

Run `db/011_ops_tickets_fleet.sql` (after 001, 005, 010) before using either page. Nothing is seeded: both pages start empty.

## Service Tickets  (`/<portal>/service-tickets`, also Ticket Queue / Service Platform)
API `backend/ticketapi.py`, UI `frontend/src/Tickets.tsx`.
- Create, view, **edit** (PATCH), **assign** technician, change status (only the next states the server allows for your role).
- Fields: ticket ID (server generated `IVT-…`), title, description, priority, category, status, technician, customer, vehicle, due date, created/updated/resolved dates.
- Summary cards (All, Open, In progress, Waiting, Completed, Overdue, Unassigned, Urgent) - each card is also a filter.
- Search (ID, title, customer, vehicle, technician) + filters: status, priority, category, technician, created date range.
- **History** per ticket: created, edits (old -> new), assignments, status changes, comments; also written to the audit log.
- CSV export honours the active filters (spreadsheet-formula safe).

## Fleet Management  (`/<portal>/fleet-management`, COO "Vehicle Directory")
API `backend/fleetapi.py`, UI `frontend/src/Fleet.tsx`.
- Add, view, edit vehicles; change status (Active, In service, Idle, Out of service, Decommissioned).
- Fields: registration number (unique ignoring case/spaces/hyphens), vehicle type, make, model, battery capacity (kWh), status, VIN, year, customer, odometer, notes.
- Vehicle detail: service history (add record; odometer only moves forward), total service cost, linked service tickets (matched by registration), per-vehicle history CSV.
- Search + filters (status, type, customer), summary cards, filtered CSV export.

## Who can do what (backend-enforced, `permissions.py`)
| Role | Tickets | Fleet |
|---|---|---|
| CEO | everything | everything incl. archive |
| Service manager | read, create, edit, assign, transition, export | read, add, edit, service history, export (no archive) |
| COO | read, export | read, export |
| CTO | read, export | read, export |
| Technician | own/assigned tickets only: view, edit, comment, transition | read only |
| HR / Employee | none | none |
Archiving a vehicle is CEO-only, matching the existing rule that only the CEO archives. Change `permissions.py` if you want otherwise.

## Verified here
Backend: full suite + `tests/test_ops_pg.py` (real Postgres, real migrations, real login/CSRF). Frontend: `src/ops.render.test.tsx`, type-check, production build.
Not verified: your real database/accounts, a browser run, and your Supabase setup.
