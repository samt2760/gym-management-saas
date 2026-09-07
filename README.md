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
- Set `ENVIRONMENT=production`, `ALLOWED_HOSTS`, `SESSION_COOKIE_SECURE=true`, and a production `DATABASE_URL`.
- Keep credentials out of Git, logs, images, and command output.
- Terminate HTTPS in front of the application and use secure operational logging, backups, monitoring, and restore drills.
- Run migrations as a reviewed deployment step, separately from application startup.
- Use an immutable image tag for a release instead of the local `dev` default: `$env:IMAGE_TAG = "<release-tag>"; docker compose up -d`.
- This repository provides deployment structure and checks; it does not deploy to a production server.
