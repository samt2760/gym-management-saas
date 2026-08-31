import sqlite3
from pathlib import Path

DB_PATH = Path("gym.db")

conn = sqlite3.connect(DB_PATH)

try:
    conn.execute("PRAGMA foreign_keys = OFF")

    # Safety check
    version = conn.execute(
        "SELECT version_num FROM alembic_version"
    ).fetchone()

    if not version or version[0] != "0001_database_hardening":
        raise RuntimeError(
            f"Unexpected Alembic version: {version}"
        )

    # Preserve existing payment data.
    conn.execute("""
        CREATE TABLE payments_new (
            id INTEGER NOT NULL,
            member_id INTEGER,
            member_name VARCHAR NOT NULL,
            amount INTEGER NOT NULL,
            payment_date DATE NOT NULL,
            membership_type VARCHAR NOT NULL,
            payment_type VARCHAR NOT NULL,
            gym_id INTEGER NOT NULL,
            currency VARCHAR(3) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,

            PRIMARY KEY (id),

            CONSTRAINT fk_payments_gym_id_gyms
                FOREIGN KEY(gym_id)
                REFERENCES gyms(id)
                ON DELETE RESTRICT,

            CONSTRAINT fk_payments_member_id_members
                FOREIGN KEY(member_id)
                REFERENCES members(id)
                ON DELETE RESTRICT,

            CONSTRAINT ck_payments_amount_nonnegative
                CHECK (amount >= 0),

            CONSTRAINT ck_payments_monthly_membership
                CHECK (membership_type = 'Monthly'),

            CONSTRAINT ck_payments_valid_type
                CHECK (payment_type IN ('Registration', 'Renewal'))
        )
    """)

    # Copy every existing payment.
    conn.execute("""
        INSERT INTO payments_new (
            id,
            member_id,
            member_name,
            amount,
            payment_date,
            membership_type,
            payment_type,
            gym_id,
            currency,
            created_at,
            updated_at
        )
        SELECT
            id,
            member_id,
            member_name,
            amount,
            payment_date,
            membership_type,
            payment_type,
            gym_id,
            currency,
            created_at,
            updated_at
        FROM payments
    """)

    # Replace the old table.
    conn.execute("DROP TABLE payments")
    conn.execute("ALTER TABLE payments_new RENAME TO payments")

    # Recreate the indexes exactly as they existed.
    conn.execute("""
        CREATE INDEX ix_payments_id
        ON payments(id)
    """)

    conn.execute("""
        CREATE INDEX ix_payments_gym_payment_date
        ON payments(gym_id, payment_date)
    """)

    conn.execute("""
        CREATE INDEX ix_payments_member_payment_date
        ON payments(member_id, payment_date)
    """)

    conn.commit()

    print("Payment table cleanup completed successfully.")

finally:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
