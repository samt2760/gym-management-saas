# Migrations

The current application retains its legacy SQLite startup compatibility
migration so existing local databases continue to work. New schema changes
must use a reviewed, versioned migration once Alembic is introduced; do not add
new startup `ALTER TABLE` statements here or in application code.
