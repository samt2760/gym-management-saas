# Gym Management System

FastAPI and Jinja2 gym management application backed by SQLAlchemy and PostgreSQL. The repository includes Docker Compose for local deployment, Alembic for explicit schema migrations, and pytest coverage for the core workflows.

## Local setup

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` to a local PostgreSQL password and use the same password in `DATABASE_URL`. Set a unique `SESSION_SECRET`; do not commit `.env`.
3. Build the web image:

   ```powershell
   docker compose build web
   ```

4. Start PostgreSQL and wait for it to become healthy:

   ```powershell
   docker compose up -d db
   docker compose ps
   ```

5. Run migrations explicitly before starting the web service:

   ```powershell
   docker compose run --rm web python -m alembic upgrade head
   ```

6. Start the web service:

   ```powershell
   docker compose up -d web
   ```

7. Verify the application and database connection:

   ```powershell
   Invoke-WebRequest http://localhost:8000/health -UseBasicParsing
   ```

The expected response is HTTP 200 with `{"status":"ok","database":"ok"}`.

## Tests and checks

Use the project virtual environment and install both dependency sets:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest
python -m compileall app
```

## Migration workflow

Migrations are not run automatically when the application starts. For a deployment, build the application image, make the database available, run `python -m alembic upgrade head` once using the deployment environment, and then start the application. Confirm the applied revision with `python -m alembic current` and check for schema drift with `python -m alembic check` where supported.

Never reset the database, downgrade migrations, or run destructive SQL as part of routine deployment. Review and test every migration before applying it to a production database.

### Controlled schema release gate

The current repository head is `0008_payment_legacy_association`. Inspect the configured database and repository before a release:

```powershell
docker compose run --rm --no-deps web python -m alembic current
python -m alembic heads
```

The currently deployed local database is intentionally still at `0004_align_authentication_token_columns`; pending migrations are `0005_payment_renewal_integrity`, `0006_audit_trail`, `0007_login_throttles`, and `0008_payment_legacy_association`. Do not run them against the live database until a rehearsal has passed.

First create and retain a pre-deployment custom-format backup, then rehearse the exact release image and migration chain against a named disposable restore:

```powershell
python scripts/schema_release_gate.py `
  --archive backups/gym-management-2026-09-10.dump `
  --recovery-database gym_migration_rehearsal_20260910 `
  --expected-start 0004_align_authentication_token_columns `
  --drop-recovery-database
```

The rehearsal refuses the configured live database, verifies the archive and starting revision, runs `alembic upgrade head` only in the configured Compose release image against the disposable target, checks the resulting schema and preserved historical payment facts, and starts the application long enough to verify `/health`. Any failure is terminal for the release: retain the pre-migration backup, investigate, and restore into a separate recovery database if needed. Do not casually downgrade a production database and never use `docker compose down -v`.

After a successful rehearsal, an authorized operator must run `python -m alembic upgrade head` exactly once as a separately reviewed migration job using the immutable release image and the confirmed live database URL. Verify `alembic current`, the required schema, and `/health` before routing new application instances. FastAPI startup never runs migrations automatically.

## Stopping services safely

Stop containers without removing the PostgreSQL volume:

```powershell
docker compose stop
```

Do not use `docker compose down -v`; removing the volume would delete the local PostgreSQL data.

## Backup and recovery

Backups contain the current operational schema: `alembic_version`, `gyms`, `members`, `payments`, `users`, `user_sessions`, and `password_reset_tokens`. Store them outside the repository with access restricted to the operators who need recovery access; do not attach them to tickets or commit them. The `backups/` directory and `*.dump` archives are ignored by Git.

With the `db` service healthy, create a PostgreSQL custom-format archive without stopping the application. The helper runs `pg_dump` inside the database container and reads its configured `POSTGRES_USER` and `POSTGRES_DB`; it never writes a password to the command line or archive name.

```powershell
python scripts/postgres_backup.py backup --output backups/gym-management-2026-09-10.dump
```

`pg_dump` success alone is not enough. Verify every backup by restoring it to an explicitly named, disposable database. The command refuses the configured live application database, validates that the archive is readable, restores it, checks counts for every current operational table, detects members without a gym and payments, sessions, or reset tokens without a corresponding parent record, and reports the restored Alembic revision.

The current historical archive contains one documented pre-linkage exception: payment `9` has no `member_id`, while its immutable ledger facts remain `member_name=saas`, `200 GHS`, `2026-08-28`, and `Registration`. Recovery verification permits only that exact row (or no unlinked rows after the approved repair); any additional or altered unlinked payment fails verification. It is not deleted, changed, counted as a normal member relationship, or treated as permission to create new unlinked payments. Migration `0008_payment_legacy_association` repairs it by creating a tenant-scoped archived legacy-member record and linking the payment to that record while preserving the ledger facts.

```powershell
python scripts/postgres_backup.py verify-restore `
  --archive backups/gym-management-2026-09-10.dump `
  --recovery-database gym_recovery_20260910 `
  --drop-recovery-database
```

The disposable database is created in the existing PostgreSQL server but is not the application database and does not replace, reset, or remove `postgres_data`. Omit `--drop-recovery-database` to inspect a failed recovery target manually; remove only the explicitly named disposable database after investigation.

For a production recovery, first stop or otherwise prevent application writes, take and retain the failed-system backup, restore the selected archive into a clean recovery database, run the verification above, and validate representative sign-in, member, and payment flows before routing the application to it. A custom dump already includes its schema and data. Alembic remains the schema authority: verify the restored revision first; apply only the reviewed migrations needed to bring that recovered revision to the application release, rather than replaying migrations blindly. Restart the application and confirm `/health` returns `{"status":"ok","database":"ok"}`.

Operational recommendations, not repository automation: schedule at least daily backups, retain several short-term restore points and periodic longer-term copies, and regularly perform a restore drill. Backup frequency determines the recovery point objective (RPO), while backup size, infrastructure, and the tested procedure determine recovery time objective (RTO); measure both in the target environment rather than assuming fixed values.

## Production precautions

- Use PostgreSQL and a strong, externally managed `SESSION_SECRET` in production.
- Set `ENVIRONMENT=production`, a non-placeholder `SESSION_SECRET`, `SESSION_COOKIE_SECURE=true`, a PostgreSQL `DATABASE_URL`, and explicit non-wildcard `ALLOWED_HOSTS`. Startup fails fast if these requirements are not met.
- Terminate HTTPS before the application. The app sends HSTS only in production, uses secure HttpOnly session cookies, and sends CSP, anti-framing, MIME-sniffing, referrer, permissions, and no-store headers for dynamic pages. The current server-rendered templates use inline styles, so the CSP intentionally permits inline styles but does not permit inline scripts.
- The container starts Uvicorn with forwarded headers disabled. This is the safe default because no trusted-proxy network is configured; do not enable forwarded headers until the proxy IP/network policy is explicitly defined and reviewed. Login throttling therefore uses the direct peer address.
- `/health` is unauthenticated and performs a minimal database connectivity check. It is suitable for the included Docker healthcheck and returns only generic status values.
- `DATABASE_CONNECT_TIMEOUT_SECONDS` configures the PostgreSQL connect timeout. Remote PostgreSQL TLS is deployment-specific: provide a suitable `sslmode`/certificate configuration in `DATABASE_URL` or the driver environment; do not place certificates in this repository.
- Keep credentials out of Git, logs, images, and command output.
- Terminate HTTPS in front of the application and use secure operational logging, backups, monitoring, and restore drills.
- Run migrations as a reviewed deployment step, separately from application startup.
- Use an immutable image tag for a release instead of the local `dev` default: `$env:IMAGE_TAG = "<release-tag>"; docker compose up -d`.
- This repository provides deployment structure and checks; it does not deploy to a production server.

## First production owner bootstrap

After a **fresh** PostgreSQL database has been migrated to the current Alembic
head, an operator must create the initial gym and owner before the web
application can accept a login. This is a one-shot, operator-only command; it
is not an HTTP endpoint and it does not run during application startup.

Use separate database identities:

- The schema-owner/migrator role owns application tables and runs Alembic.
- A tightly held bootstrap-operator role has `BYPASSRLS` solely because an
  empty database has no tenant context with which to insert the first
  FORCE-RLS-protected `gyms` row. It must not be used by the web service.
- The web runtime role remains `LOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`,
  `NOCREATEDB`, and `NOCREATEROLE`, with only its reviewed application grants.

The bootstrap operator supplies the gym name, ISO currency, integer minor-unit
fees, owner username, owner email, and a strong password. Inject
`BOOTSTRAP_OWNER_PASSWORD` only through the operator's approved secret channel,
or enter it at the non-echoing prompt. Do not put it in a repository file,
shell history, image, or deployment environment for the web service.

```powershell
python scripts/bootstrap_first_owner.py `
  --confirm INITIALIZE_EMPTY_DATABASE `
  --gym-name "Example Gym" `
  --currency GHS `
  --registration-fee 0 `
  --monthly-fee 12000 `
  --username owner `
  --email owner@example.invalid
```

The command requires the controlled PostgreSQL bootstrap role and refuses if
*any* gym or user already exists. It hashes the supplied password with the
application's existing password hasher, commits the gym and owner atomically,
and prints only created record IDs. A failure rolls back the whole operation.
Verify success by logging in over HTTPS, opening `/dashboard`, and confirming
the initial encrypted backup has restored successfully. Remove the injected
bootstrap password immediately after use and revoke or disable the temporary
bootstrap operator according to the production access procedure; the command
will remain harmless against an initialized database because it refuses a
second invocation.
