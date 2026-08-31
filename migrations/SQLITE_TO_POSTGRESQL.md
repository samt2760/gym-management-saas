# Future SQLite-to-PostgreSQL migration path

This project remains on SQLite for now. Do not point a production application
at PostgreSQL until the following controlled migration has been rehearsed.

1. Upgrade the SQLite database to the latest Alembic revision and verify
   `alembic current`, foreign-key checks, row counts, and payment totals.
2. Provision a managed PostgreSQL instance with TLS, encrypted backups,
   point-in-time recovery, least-privilege credentials, and a tested restore.
3. Configure `DATABASE_URL` for PostgreSQL and run `alembic upgrade head` on
   the empty target database. Do not use SQLite files as a production source
   after the cutover begins.
4. Export source data in dependency order: gyms, members (including archived
   members), then payments. Import into PostgreSQL inside transactions while
   preserving primary keys, UTC timestamps, currency snapshots, and payment
   amounts exactly.
5. Reconcile source and target by table counts, per-gym member counts, payment
   totals by currency/date/type, orphan checks, and sampled member histories.
6. Put SQLite writes into maintenance mode, repeat a final delta export, run
   reconciliation again, then switch `DATABASE_URL` and deploy the application.
7. Keep the encrypted SQLite snapshot read-only until the agreed retention
   period ends. Document rollback as a new controlled cutover, never by
   silently overwriting PostgreSQL data.

PostgreSQL-specific enhancements—connection pooling, row-level security,
native UUIDs, full-text search, and tenant partitioning—should be introduced
in separately reviewed migrations after this data move is complete.
