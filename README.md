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

## Stopping services safely

Stop containers without removing the PostgreSQL volume:

```powershell
docker compose stop
```

Do not use `docker compose down -v`; removing the volume would delete the local PostgreSQL data.

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
