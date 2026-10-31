# Configuration still needed

Do not send credentials in chat or commit them to this ZIP. Configure them through the deployment secret manager/environment.

- **Database:** `DATABASE_URL` for the office dashboard schema, with reviewed migrations applied in order. Back up first; 007, 008 and 009 are not applied by this project ZIP.
- **Authentication:** existing `USERS_TABLE`, `COL_*`, `SESSION_SECRET`, `ALLOWED_ORIGINS`, and deployment cookie settings must match the actual login database and deployment.
- **WhatsApp Business:** provider name, WABA ID, phone-number ID, access token, business phone, webhook verification token, callback URL and subscribed webhook events. Sending/receiving remains disabled until provider setup and verification are implemented and tested.
- **Email:** provider choice (e.g. Microsoft 365/Graph, Google Workspace/Gmail API, or SMTP), OAuth/app registration, sender mailbox, webhook/polling strategy and credentials.
- **Monitoring/Cloud:** approved source (cloud provider or monitoring product), read-only API credentials, service identifiers, and cost/billing source for CTO metrics.
- **EVcare.AI / IoT:** real diagnostic model/API and data contract; telemetry device/source, authentication, units, timestamps and retention requirements. No synthetic sensor or diagnostic values are generated.
- **Business rules:** approved currency, timezone, fiscal year, KPI definitions, approval hierarchy, invoice/tax rules, payment allocation policy, leave carry-forward rules, SLA targets, and role-to-permission policy.
- **Testing/deployment:** access to a disposable PostgreSQL database and ability to install frontend/backend dependencies to run the full test/build suite.

Never provide production secrets in the source ZIP. Use environment variables or a secret manager.

## Additional setup for the latest implementation
- Review and apply `db/009_module_records.sql` and `db/010_service_tickets.sql` only after backup, in order, after migrations 001–008.
- The service ticket API requires the API database connection to have the same reviewed schema/table-owner access used by existing modules.
- The ticket assignment field currently stores the internal user identifier as text. Confirm the canonical employee/user identifier mapping before production use.
- The generic workspaces are foundations only; do not enter sensitive finance or customer documents until access policy, retention, file storage, and data ownership rules are approved.
