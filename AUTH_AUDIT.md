# Authentication & database compatibility audit

## Verdict: NOT YET VERIFIED against your real database
The Phase 2 backend source, schema dump, COO and CCO images were never received. Nothing about your actual
users table, role values, hash format or session behaviour has been inspected. Tests below use an in-memory fake.

## Received vs missing
Received: Blueprint PDF, CEO image, CTO image, login image, my own earlier starter.
Missing: Phase 2 project ZIP/source, DB schema (public / office_dashboard), COO image, CCO image.

## Incompatibilities in the earlier starter (all fixed in code)
| Earlier assumption (a guess) | Now |
|---|---|
| Table office_dashboard.users | USERS_TABLE env, required, no default |
| Columns id, full_name, username, email, password_hash, role, is_active | COL_* env, required, no defaults |
| Roles equal the 7 portal names | ROLE_MAP env translates your values; unmapped roles are denied |
| Hashes are bcrypt | Scheme detected: bcrypt, argon2*, werkzeug pbkdf2/scrypt, passlib pbkdf2*. Unknown fails closed. (*needs optional package) |
| Wrote to office_dashboard.audit_log | All DB writes removed. The auth layer is SELECT-only in a read-only transaction. db/ migration deleted. |
| Cookie signed for 30 days even without "remember" | Without remember: session cookie, 12 h server expiry. Remember: 30 days. |
| Logout only deleted cookie | Server-side revocation of the session id (in memory, lost on restart) |
| Ambiguous matches possible | More than one matching row refuses login |
| Rate limit per IP | Per IP + username |

## Still unknown (needs your input)
1. Users table name, schema and column names. 2. Hash scheme(s) actually stored. 3. Role values and
whether role lives in the users table or a roles/permissions table. 4. Active-flag column and values.
5. Whether users link to employees (FK), and how technicians map. 6. How Phase 2 issues sessions (JWT,
cookie, server sessions) and whether the new frontend must share them. 7. Whether login is username, email or both.

## Safe compatibility plan
1. Run tools/inspect_schema.py (read-only; prints structure and hash prefixes only). Send me the output.
2. Fill the COL_* / ROLE_MAP values in .env from that output.
3. Test login with ONE existing account. No account creation, no password reset, no hash rewrite.
4. Known limit: revocation is in memory. Persistent revocation would need a new table; not created without your approval.

## Tests actually run (sandbox, fake repo)
Backend pytest: 32 passed. Frontend vitest: 53 passed. tsc --noEmit: OK. vite build: OK.
These prove my code's logic. They do not prove compatibility with your database.
