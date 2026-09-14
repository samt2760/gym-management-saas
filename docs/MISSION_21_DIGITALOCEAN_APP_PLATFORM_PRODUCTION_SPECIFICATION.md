# Mission 21 — DigitalOcean App Platform Production Specification

Status: **BLOCKED.** Mission 22 must not begin until the mandatory secret-boundary fix and recorded human approvals in this document are complete.

This is a pre-provisioning design artifact only. It creates no provider resource, credentials, DNS change, TLS certificate, or production database connection.

## Repository facts

| Subject | Verified current state |
|---|---|
| Image | Root `Dockerfile`, Python 3.13 slim, non-root `appuser`; copies app, templates, static assets, Alembic configuration, and migrations. |
| Port and web command | Exposes/binds `8000`; `uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --timeout-keep-alive 5 --timeout-graceful-shutdown 30`. |
| Dependencies | Runtime dependencies are pinned in `requirements.txt`. `requirements-dev.txt`, tests, scripts, and `.env` are not in the runtime image. |
| Health | Unauthenticated `GET /health` performs `SELECT 1`; returns 200 `{"status":"ok","database":"ok"}` or generic 503. |
| Production config | Requires `ENVIRONMENT=production`, PostgreSQL `DATABASE_URL`, non-placeholder `SESSION_SECRET`, `SESSION_COOKIE_SECURE=true`, and explicit, non-wildcard `ALLOWED_HOSTS`. |
| Migration | `python -m alembic upgrade head`; Alembic gets `DATABASE_URL`; current head is `0009_postgresql_tenant_rls`. |
| Bootstrap | `python scripts/bootstrap_first_owner.py --confirm INITIALIZE_EMPTY_DATABASE ...`; password comes from `BOOTSTRAP_OWNER_PASSWORD` or prompt. |
| Backup | `python scripts/postgres_archive.py backup --output <archive.dump>` uses `BACKUP_DATABASE_URL`, custom format, checksum, and JSON metadata. `verify` and `restore-validate` are separate safe operations. |
| Filesystem | Web has no persistent writable-file requirement. Backup runner needs only temporary dump/metadata storage before encrypted off-provider upload. |
| Startup | No automatic migrations, bootstrap, backups, or GET writes. PostgreSQL uses pre-ping and configured connect timeout. |
| Logging | Standard process logs; never allow URLs/passwords/tokens in logs. Health reports failures server-side. |
| CI today | GitHub Actions installs dependencies, checks them, runs pytest/compileall, and Docker-builds. It does not run Ruff, a disposable PostgreSQL/RLS rehearsal, image publication, or deployment. |

`.dockerignore` excludes VCS, `.env`, local databases, tests, and environments. `.gitignore` excludes `*.dump` and `backups/`.

## DigitalOcean findings verified on 2026-09-13

App Platform supports Dockerfiles, container-registry images, fixed image digests, component-level encrypted runtime variables, `PRE_DEPLOY` jobs, readiness/liveness checks, logs, alerts, and rollback to any of the ten previous successful deployments. Digest pinning is required: a digest cannot deploy-on-push, which is appropriate for human-approved production releases. A rollback changes application code/configuration but **never database data**.

App Platform supports VPC networking. An app connects directly only to the VPC datacenter mapped to its App Platform region; cross-region/private paths require VPC peering. VPC networking cannot coexist with dedicated egress IPs. When a managed database uses trusted sources, the App VPC egress private IP must be allowed.

Managed PostgreSQL has private and public connection details; only same-VPC resources can use its private hostname. Require TLS `verify-full` and provider CA validation, not merely `sslmode=require`. Trusted sources are the database firewall. DigitalOcean administrative roles include capabilities such as `BYPASSRLS`; no provider-admin URL may reach an application component.

App Platform creates/manages a custom-domain certificate after domain attachment. With external DNS, use its displayed `ondigitalocean.app` CNAME alias (or provider-issued A records where CNAME is impossible). DNS may take up to 72 hours. Do not use a wildcard domain.

Official sources: [Dockerfile builds](https://docs.digitalocean.com/products/app-platform/reference/dockerfile/), [container-image deployment](https://docs.digitalocean.com/products/app-platform/how-to/deploy-from-container-images/), [app-spec](https://docs.digitalocean.com/products/app-platform/reference/app-spec/), [deployments and rollback](https://docs.digitalocean.com/products/app-platform/how-to/manage-deployments/), [jobs](https://docs.digitalocean.com/products/app-platform/how-to/manage-jobs/), [health checks](https://docs.digitalocean.com/products/app-platform/how-to/manage-health-checks/), [VPC](https://docs.digitalocean.com/products/app-platform/how-to/enable-vpc/), [database connections](https://docs.digitalocean.com/products/databases/postgresql/how-to/connect/), [database security](https://docs.digitalocean.com/products/databases/postgresql/how-to/secure/), [database privileges](https://docs.digitalocean.com/products/databases/postgresql/how-to/modify-user-privileges/), and [domains](https://docs.digitalocean.com/products/app-platform/how-to/manage-domains/).

## Production topology

```text
Internet browser
  -> DigitalOcean-managed TLS / App Platform ingress        [public, provider-managed]
  -> web App Platform service                                [public, operator-configured]
  -> private VPC -> Managed PostgreSQL private hostname      [non-public app path, provider-managed]

migrate PRE_DEPLOY job -> migrator PostgreSQL role           [non-routable]
temporary bootstrap job -> bootstrap PostgreSQL operator     [non-routable, one use]
backup/ops runner -> backup PostgreSQL role -> encrypted off-provider storage
                                                               [operator-controlled]
```

Only `web` is routable. `migrate` and `bootstrap` have neither a route nor a public HTTP port. DigitalOcean manages ingress/TLS, underlying App Platform infrastructure, Managed PostgreSQL availability/backups/PITR availability, deployment history, logs, and alert transport. Operators control approvals, roles/grants, secrets, migrations, bootstrap, off-provider archives, recovery, and retention.

## Web service

| Setting | Production value |
|---|---|
| Component | App Platform web service named `web` |
| Source | Private DigitalOcean Container Registry image published by approved CI |
| Release identity | Recorded immutable `sha256:` digest, never `latest` or a mutable tag |
| Region/VPC | Selected production region and mapped datacenter VPC, shared with Managed PostgreSQL |
| Network | HTTP port `8000`; one `/` route to `web`; preserve full request path |
| Command | Dockerfile command, unchanged; do not specify an overriding App Platform run command |
| Initial sizing | One `basic-xs`-or-larger instance after current provider size review; no scale-to-zero |
| Autoscaling | Disabled initially; enable only after CPU/latency/connection measurement, with a maximum that cannot exhaust DB connections |
| Readiness | `/health`: initial delay 30s, interval 10s, timeout 5s, success threshold 1, failure threshold 5 |
| Liveness | Same endpoint/configuration only after production observation confirms restarts are safe for database failures |
| Deployment | Explicit approved deployment of one digest; traffic only after readiness; retain history/logs |
| Alerts | `DEPLOYMENT_FAILED`, `DOMAIN_FAILED`, database availability/capacity alerts to on-call recipients |

Set these component-scoped runtime variables:

| Variable | Type | Required value/source |
|---|---|---|
| `ENVIRONMENT` | general | `production` |
| `DATABASE_URL` | secret | private-host TLS `verify-full` URL for `gym_runtime` only |
| `SESSION_SECRET` | secret | unique strong random session signing secret |
| `SESSION_COOKIE_SECURE` | general | `true` |
| `ALLOWED_HOSTS` | general | `app.example.com` until approved real hostname replaces it |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | general | `10` initially |
| other documented session/password/rate variables | general | retain reviewed defaults unless separately approved |
| TLS CA material | secret/file facility | provider CA only, if required by the verification URL |

Do not attach migrator, bootstrap, backup, recovery, or administrative database URLs; `BOOTSTRAP_OWNER_PASSWORD`; or DigitalOcean administration credentials to `web`.

## Pre-deploy migration job

Create App Platform job `migrate`, `kind: PRE_DEPLOY`, non-routable, from the **same approved digest** as `web`:

```text
python -m alembic upgrade head
```

Disable deploy-on-push. It runs once immediately before every explicit, human-approved production app deployment; the web deployment must fail closed if it fails. It receives only `ENVIRONMENT=production`, the TLS configuration, and scoped `gym_migrator` `DATABASE_URL` — never runtime, backup, bootstrap, or provider-admin credentials.

After every successful job, confirm: Alembic current/head is `0009_postgresql_tenant_rls`; `gyms`, `members`, `payments`, `audit_logs`, and `legacy_member_records` each report `rowsecurity=true` and `forcerowsecurity=true`; each has `tenant_gym_isolation`; runtime reports `rolsuper=false`, `rolbypassrls=false`, `rolcreatedb=false`, `rolcreaterole=false`; and runtime DDL is denied. Never auto-downgrade.

## Temporary bootstrap worker

Bootstrap is **not** part of the steady-state app spec. On a newly migrated empty database, after explicit approval:

1. Create a temporary non-routable App Platform job (or equivalently controlled VPC runner) using the release digest.
2. Scope it to `gym_bootstrap` `DATABASE_URL`, TLS material, and encrypted `BOOTSTRAP_OWNER_PASSWORD`. Supply non-secret CLI values separately.
3. Run `python scripts/bootstrap_first_owner.py --confirm INITIALIZE_EMPTY_DATABASE --gym-name ... --currency ... --registration-fee ... --monthly-fee ... --username ... --email ...`.
4. Confirm IDs only, HTTPS owner login, and dashboard access. Do not put the password in the command line, repo, shell history, logs, or long-lived app spec.
5. Delete the job/secrets and revoke/drop the bootstrap role immediately; preserve audit evidence.

The script refuses a DB containing a gym/user and rolls back on error. Because `gyms` has forced RLS and an empty database has no tenant context, the temporary bootstrap operator may have `BYPASSRLS`; it owns nothing, gets no schema grant, is never the runtime role, and is removed directly after its one use.

## Managed PostgreSQL

| Decision | Required specification |
|---|---|
| Engine | Current supported DigitalOcean Managed PostgreSQL major version, recorded at provisioning; never a deprecated version |
| Placement | Same selected App region and mapped VPC datacenter; no cross-region routing without explicitly approved VPC peering |
| Database | `gym_management_production` (confirm exact name before provisioning) |
| Network | Private hostname; trusted sources limited to App VPC egress private IP and separately approved recovery/ops source; no broad public CIDR |
| TLS | `sslmode=verify-full`, provider CA stored outside Git, tested by release rehearsal |
| Capacity | Select supported production tier from expected concurrency/storage; alerts for CPU, RAM, disk, connections, availability, and maintenance |
| Maintenance | Record low-traffic maintenance window; test reconnect/failover behavior |
| Provider backup | Managed automatic backups/PITR with plan-specific retention confirmed at provisioning; restore only to a new cluster |

| Principal | Attributes and authority |
|---|---|
| `gym_migrator` | Used by job only; schema owner; owns application tables, sequences, policies, and required schema objects |
| `gym_runtime` | `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`; owns nothing; only reviewed DML/sequence grants; no schema or role/database administration |
| `gym_backup` | Scheduled ops only; owns no application tables; `CONNECT` and narrowly reviewed dump/read access only; cannot mutate schema/data |
| `gym_bootstrap` | Temporary `LOGIN BYPASSRLS`; no ownership/schema privilege; revoke/drop after bootstrap |
| provider/provisioner administrator | Provisioning/emergency role management only; never a component credential |

Do not add a connection pool until a rehearsal proves it preserves the application’s transaction-local tenant `set_config` context without cross-tenant leakage.

## Secret separation and mandatory fix

| Credential/config | Component | Storage | Lifetime/rotation |
|---|---|---|---|
| Runtime `DATABASE_URL` | web only | component secret | rotate DB password on schedule/incident; redeploy web |
| Migrator `DATABASE_URL` | migrate only | component secret | rotate; job only |
| Backup `DATABASE_URL` | external ops runner only | operator/CI secret manager | rotate; scheduled/drill use |
| Bootstrap `DATABASE_URL` | temporary bootstrap only | temporary component secret | revoke/drop role after bootstrap |
| `SESSION_SECRET` | web only | component secret | rotate under documented session invalidation procedure |
| `BOOTSTRAP_OWNER_PASSWORD` | bootstrap only | temporary component secret or prompt | remove immediately |
| `ALLOWED_HOSTS` | web only | component general config | change only with domain approval |
| TLS CA material | relevant DB client only | secret/file facility | follow provider CA rotation |
| DO deployment credentials | CI/named operator only | CI vault/operator vault | least scope, audit, rotate |

**Resolved in Mission 21R:** database configuration (`DATABASE_URL` and connect timeout) now lives in a minimal module consumed by database/Alembic/bootstrap code, and password policy is similarly shared without importing web session configuration. Web startup remains the sole validation boundary for `SESSION_SECRET`, secure cookies, hosts, and other web-only settings. Tests prove operational imports do not load web configuration while production web startup still fails without a valid secret. Privileged operational jobs must continue to receive only their scoped credentials.

Final boundaries: **web** receives `DATABASE_URL`, `SESSION_SECRET`, and web
settings; **migration** receives `DATABASE_URL` and Alembic settings only;
**bootstrap** receives `DATABASE_URL`, explicit bootstrap inputs, and its
one-time password only; **backup/ops** receives only its backup or recovery
database URL. This prevents privileged operational jobs from inheriting secrets
owned exclusively by the web runtime.

## Network, proxy, hosts, and domain

Browser path: `Browser -> App Platform managed TLS ingress -> web:8000`. Database path: `web/migrate/temporary bootstrap or approved ops -> VPC private PostgreSQL hostname`, encrypted and identity-verified. PostgreSQL has no public application path. Recovery requires separate approval/authentication and is never web access.

Preserve `SESSION_COOKIE_SECURE=true`, CSRF, HSTS/security headers, explicit `ALLOWED_HOSTS`, and `--no-proxy-headers`. App Platform TLS termination alone is not sufficient reason to trust unverified forwarded headers/source addresses. Secure browser cookies are set at the HTTPS edge; revisit proxy headers only after a provider-specific source-address/trust-boundary review and test.

Use `app.example.com` as the canonical placeholder. Mission 22 replaces it with an approved hostname in App Platform and `ALLOWED_HOSTS`. External DNS creates a CNAME to the exact displayed `*.ondigitalocean.app` alias, or uses provider A records only if needed. App Platform owns issuance/renewal once attached. Verify DNS resolution, certificate hostname/issuer/renewal, HTTPS, and host enforcement. No wildcard domain or DNS/TLS change occurs in this mission.

## Backup and recovery

Use both provider-managed automated backups/PITR and independent daily (or approved more frequent) logical custom-format dumps via `postgres_archive.py` under `gym_backup`. Encrypt transit/storage, preserve SHA-256 metadata, upload to access-controlled off-provider object storage, and retain approved daily/monthly periods. Quarterly at minimum, run `verify` and `restore-validate` in a separately named recovery database/cluster; record revision, checksum, RPO, RTO, and duration. Never restore in place or over production. The web service has no backup/recovery credentials.

## CI/CD release pipeline

Not implemented by this mission. Mission 22 must define: checkout approved commit; pinned dependency installation; `pytest`; `ruff check .`; `ruff format --check .`; `pip check`; compile check; disposable PostgreSQL migration/RLS rehearsal; Docker build/scan/sign; private DOCR publication; digest/commit recording; human approval; fixed-digest App Platform deployment; PRE_DEPLOY migration; health check; HTTPS smoke test; release acceptance.

CI may use narrow registry-push and project/app deployment credentials plus disposable test DB credentials. It must not receive runtime, backup, bootstrap, recovery, or provider-admin DB passwords, or bootstrap owner password.

## First-deployment smoke test

1. HTTPS `GET /health` returns 200/generic healthy response.
2. Login; reject missing/invalid CSRF on a state-changing form; verify Secure, HttpOnly, intended SameSite cookie attributes.
3. Dashboard; member registration/edit; renewal; payment history; existing deliberate delete/restore flow; logout.
4. Two non-sensitive test tenants: prove A cannot read/modify B and B cannot read/modify A through application and runtime SQL attempts without trusted tenant context.
5. Confirm RLS/forced-RLS/policy flags and runtime role restrictions; runtime schema DDL must fail.

## Rollback rules

| Failure | Response |
|---|---|
| App deployment | Stop promotion; inspect safe logs; fix/rehearse; rollback to compatible known-good App Platform deployment/digest. |
| Health failure | Keep traffic stopped; validate DB connectivity/trusted sources; do not weaken TLS/RLS or expose DB. |
| Migration failure | Deployment blocked; retain backup/log evidence; investigate on disposable restore; never auto-downgrade. |
| Smoke failure | Stop acceptance/routing; rollback app only after schema compatibility review; use approved compensating migration/recovery when needed. |
| DB corruption | Stop writes; preserve evidence; restore PITR/archive to a **new** DB/cluster; validate then approved cutover. |
| Provider outage | Follow provider status/support; rely on off-provider archives and documented alternate recovery. |
| DNS/TLS failure | Validate record/domain/CAA/certificate/host; retain HTTPS, Secure cookies, and HSTS. |

Never automatically downgrade, disable RLS, grant runtime `BYPASSRLS`, expose PostgreSQL publicly, disable secure cookies, or bypass HTTPS.

## Mission 22 checklist and go/no-go

| Area | Status | Blocker | Required action |
|---|---|---:|---|
| Docker image | ready to build, unpublished | no | Build/rehearse/publish signed fixed digest. |
| DO account/project | unspecified | yes | Human-approved provisioning. |
| Region/VPC/PostgreSQL | unspecified | yes | Approve region, mapped VPC, version/plan, maintenance/PITR. |
| Roles/grants | designed only | yes | Apply/verify least privilege and ownership. |
| RLS | present in code, unverified in production | yes | Rehearse and verify after migration. |
| Web service | specified, absent | yes | Create after approvals. |
| Migration/bootstrap jobs | specified and scope-hardened | no | Provision only after normal role/grant and human-approval gates. |
| Backup/off-provider storage | runner ready, destination unspecified | yes | Approve storage, retention, encryption, drill owner. |
| Domain/TLS | hostname unspecified | yes | Approve hostname/DNS owner. |
| CI/CD/monitoring | baseline only | yes | Implement gates, alert receivers, runbooks. |
| Recovery/rollback | designed, not provider rehearsed | yes | Rehearse before go-live. |

**Final result: BLOCKED — the `SESSION_SECRET` scope fix is complete; do not start Mission 22 until human approvals record region, DB plan, hostname, off-provider storage/retention, sizing, and change authority.**

## Safety report

| Item | Result |
|---|---|
| Production/live DB contacted | NO |
| Production `DATABASE_URL` used | NO |
| Production credentials created | NO |
| DigitalOcean resources created | NO |
| DNS changed | NO |
| Repository files modified | YES — this documentation artifact only |
| Commits created | NO |
| Destructive operations | NO |
| Tests run | No new tests: documentation-only mission. Prior evidence: full pytest 119 passed; affected hardening tests 43 passed; Ruff/format passed. |
| Official docs consulted | Exact linked list in “DigitalOcean findings”. |
