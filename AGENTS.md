# Gym Management SaaS — Engineering Guide

## Project purpose

This project is a Gym Management System being evolved from a working
single-gym FastAPI application into a secure, production-grade, multi-tenant
SaaS product. It manages gym members, membership entitlement, registration,
renewals, payment history, attendance, reporting, and gym operations.

Preserve proven business behavior while improving correctness, security,
operability, and scale. Never rewrite working functionality without a clear
justification, migration plan, and automated regression coverage.

## Technology stack

- Python and FastAPI for the web application and API.
- Jinja2 for the current server-rendered web interface.
- SQLAlchemy for database access.
- SQLite is the current local-development/prototype database.
- PostgreSQL is the required production and multi-tenant database target.
- Alembic is the required schema-migration tool.
- Pytest is the required automated test framework.
- Ruff is the standard linter and formatter.

## Architecture rules

- Keep route handlers thin. Put membership, payments, attendance, and
  reporting decisions in domain services with explicit tests.
- Keep database access behind clearly scoped repositories or service methods;
  do not scatter business rules across templates and route handlers.
- Treat templates as presentation only. Templates must not decide eligibility,
  calculate money, or enforce permissions.
- Prefer append-only records and explicit status transitions for financial and
  operational history.
- Use structured configuration loaded from environment variables; do not
  depend on the process working directory for production paths.
- Do not introduce a new external service or payment provider without an
  adapter boundary, failure handling, and idempotency design.

## Database rules

- PostgreSQL is required for production. SQLite is permitted only for local
  development and isolated tests where behavior remains compatible.
- Enforce foreign keys, `NOT NULL`, check constraints, unique constraints, and
  indexes at the database level as well as validating in the application.
- Store money as integer minor units together with an ISO 4217 currency code;
  never use binary floating-point for money.
- Use timezone-aware timestamps for events. Store timestamps in UTC and render
  them in the tenant's configured timezone.
- Add tenant identifiers to every tenant-owned table and index them with the
  fields used in tenant-scoped queries.
- Do not rely on writes during `GET` requests to maintain state.

## Authentication rules

- All non-public pages and APIs require authentication.
- Use a vetted identity/session approach, secure password hashing where local
  passwords are supported, secure cookies, CSRF protection, and session
  expiry/revocation.
- Never log passwords, session identifiers, bearer tokens, reset links, or
  raw authentication headers.
- Authentication failure responses must not disclose whether an account,
  email address, or tenant exists.

## Authorization rules

- Authorize every request on the server; hidden UI controls are never an
  authorization mechanism.
- Implement role-based permissions at minimum for owner/admin, manager,
  front-desk, and accountant roles.
- Check both tenant scope and permission before reading or changing a record.
- Financial corrections, pricing changes, data exports, and destructive actions
  require explicit privileged permissions and audit records.

## Membership business rules

- Membership status and expiry dates must be calculated consistently from the
  authoritative entitlement/subscription record.
- Define one documented end-date convention (inclusive end-of-day or exclusive
  expiry) and use it in registration, renewal, attendance, dashboards, and
  reports.
- Membership adjustments must be explicit, permissioned, reason-coded, and
  auditable; do not silently grant entitlement by editing dates.
- A member must be successfully registered before renewal is allowed.

## Registration business rules

- Registration is separate from renewal.
- Registration consists of the registration fee plus the first month fee.
- Successful registration must atomically create the member, the initial
  membership entitlement, and its payment/ledger record.
- Validate required identity/contact fields and registration dates on the
  backend. Client-side validation is only a usability aid.
- Duplicate-member handling must follow a documented tenant-scoped policy;
  do not create accidental duplicate active memberships.

## Renewal business rules

- Renewal can cover multiple months.
- Renewal amount must be a valid positive multiple of the configured monthly
  fee for the applicable plan and price version.
- Renewals must extend the authoritative membership expiry consistently with
  the selected expiry convention; expired-member renewal behavior must be
  documented and tested.
- A renewal must be idempotent where a payment provider, retry, or submitted
  request could otherwise create duplicate charges or entitlement.

## Payment rules

- Record registration and renewal as distinct payment types.
- Payment history must never be silently deleted.
- Preserve immutable payment amounts, currency, member reference, plan/price
  snapshot, method, status, external reference, and receipt/audit metadata.
- Handle refunds, voids, chargebacks, and corrections as explicit compensating
  records; never overwrite settled financial history.
- Revenue reports must exclude failed, voided, and refunded amounts according
  to documented accounting rules.
- Payment creation and the corresponding membership entitlement change must be
  transactional or safely recoverable through an idempotent workflow.

## Data integrity rules

- Backend validation is authoritative.
- Validate data types, dates, field lengths, currency, phone/email formats,
  permitted state transitions, and tenant ownership before persistence.
- Use database transactions for multi-record operations. Roll back fully on
  failure and return safe, actionable errors.
- Use soft deletion/archival for operational records when history must remain;
  do not orphan references without a documented retention purpose.
- Record who performed sensitive actions, when, why, and the before/after
  values in an audit trail.

## Testing requirements

- Every important business rule must have automated tests.
- Add regression tests before changing existing registration, renewal, expiry,
  payment, deletion, or pricing behavior.
- Maintain unit tests for domain rules, integration tests for routes and
  database transactions, and end-to-end smoke tests for critical UI flows.
- Include authorization and tenant-isolation tests for every resource type.
- Test validation failures, concurrent/retried payment requests, migration
  upgrades, and rollback/recovery paths where applicable.
- Do not merge feature work with failing tests, lint, formatting, or type
  checks unless an explicit approved exception documents the reason.

## Security requirements

- Require HTTPS in production and set appropriate secure headers, trusted
  hosts, secure cookies, CSP, CSRF protections, and rate limits.
- Minimize personally identifiable information and protect it in transit,
  at rest, in logs, exports, and backups.
- Use parameterized ORM/database queries; never interpolate user input into
  SQL, shell commands, filesystem paths, templates, or redirects.
- Validate uploads, if introduced, by content type, size, storage isolation,
  malware scanning policy, and authorization.
- Log security-relevant events without logging secrets or unnecessary PII.
- Keep dependencies pinned and scanned for known vulnerabilities.

## Coding standards

- Use type hints, clear names, small focused functions, and explicit domain
  types/enums rather than free-form status strings where practical.
- Follow PEP 8 and Ruff rules. Format code with Ruff before committing.
- Return correct HTTP status codes and consistent error shapes; browser form
  flows should receive accessible field-level feedback rather than raw JSON
  errors.
- Avoid N+1 queries and unbounded list endpoints; paginate and filter in SQL.
- Keep templates accessible: semantic HTML, labelled controls, keyboard focus,
  responsive layouts, error feedback, and UTF-8 source files.
- Do not embed new large CSS/JavaScript blocks in page templates; use shared,
  versioned static assets or components.

## Migration rules

- Database schema changes require migrations.
- Never use `create_all()` or ad-hoc startup `ALTER TABLE` statements as a
  production migration mechanism.
- Every migration must be reviewed, reversible where feasible, tenant-safe,
  tested against representative data, and deployed separately from application
  rollout when required.
- Do not drop, truncate, or rename production data without an approved backup,
  restore plan, and explicit authorization.
- Include both upgrade and downgrade considerations; document irreversible
  migrations and the compensating recovery procedure.

## API rules

- Version public APIs (for example, `/api/v1`) and maintain compatibility
  intentionally.
- Use Pydantic request/response schemas; do not expose ORM models directly.
- Authenticate, authorize, validate tenant scope, and apply rate limits to
  every protected endpoint.
- Paginate collection endpoints and use documented filters/sorts with bounds.
- Use idempotency keys for payment and other retry-sensitive mutations.
- Publish OpenAPI documentation, error contracts, and deprecation policy.

## UI/UX rules

- Keep current working user flows intact unless a product-approved change is
  explicitly required.
- Provide clear success, validation, authorization, and system-error feedback.
- Require a deliberate confirmation flow for destructive actions, but do not
  rely on client-side confirmation for security.
- Ensure mobile responsiveness, keyboard accessibility, visible focus states,
  sufficient contrast, and readable data tables.
- Display financial amounts using the tenant currency and centralized money
  formatting; never assume a fallback currency for tenant data.

## Production deployment rules

- Deploy stateless application instances behind TLS termination with health and
  readiness checks, structured logs, metrics, error tracking, and tracing.
- Run schema migrations through a controlled deployment step, never from each
  web-process startup.
- Use managed PostgreSQL with encrypted automated backups, point-in-time
  recovery, documented RPO/RTO, and regular restore drills.
- Configure worker count, connection pooling, timeouts, rate limits, and
  resource limits for the target environment.
- Use CI/CD gates for tests, formatting, linting, dependency/security scans,
  migration checks, and deployment approval.

## Multi-tenancy rules

- Never expose one gym's data to another gym.
- Resolve the tenant from an authenticated, trusted context—not a client-sent
  body field—and apply it to every query, mutation, export, background job,
  cache key, log context, and object-storage path.
- Enforce tenant isolation in both application code and PostgreSQL row-level
  security for tenant-owned records.
- Never use global `first()`/unscoped queries for tenant configuration or
  business data.
- Include tenant-isolation tests for reads, writes, identifiers, reporting,
  background jobs, and error paths.

## Rules for handling secrets

- Never hard-code secrets.
- Store secrets only in the approved secret manager or injected environment
  variables; keep local `.env` files out of version control.
- Use separate, least-privilege credentials for local, test, staging, and
  production environments.
- Rotate compromised or expired secrets promptly and support key rotation.
- Never print secrets in logs, test output, exception messages, screenshots,
  documentation, or committed fixtures.

## Rules for destructive database operations

- Never perform destructive production operations without explicit approval.
- Destructive operations include `DROP`, `TRUNCATE`, mass `DELETE`, unsafe
  updates, data overwrites, schema/data rewrites, and irreversible migrations.
- Before approved production work, identify exact targets, take a verified
  backup, document rollback/restore steps, use a dry run where possible, and
  record the approval.
- Prefer archival, soft deletion, and compensating records over deletion.
- Do not delete payment history or audit history.

## Standard development commands

Use the project virtual environment on Windows:

```powershell
# Install dependencies
.\\venv\\Scripts\\python.exe -m pip install -r requirements.txt

# Run the development server
.\\venv\\Scripts\\python.exe -m uvicorn main:app --reload

# Run automated tests (after the pytest suite is added)
.\\venv\\Scripts\\python.exe -m pytest

# Apply migrations (after Alembic is configured)
.\\venv\\Scripts\\python.exe -m alembic upgrade head

# Create a reviewed migration (after Alembic is configured)
.\\venv\\Scripts\\python.exe -m alembic revision --autogenerate -m "describe_change"

# Lint (after Ruff is added to development dependencies)
.\\venv\\Scripts\\python.exe -m ruff check .

# Format (after Ruff is added to development dependencies)
.\\venv\\Scripts\\python.exe -m ruff format .
```

The current repository does not yet include a pytest suite, Alembic, or Ruff.
Add and configure those tools before relying on their commands in CI or
production workflows.
