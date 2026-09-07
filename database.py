from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = "sqlite:///./gym.db"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# ============================================================
# SQLITE FOREIGN KEY ENFORCEMENT
# ============================================================
#
# SQLite does not enable foreign-key enforcement by default.
# Enable it for every connection created by SQLAlchemy so
# database-level ON DELETE RESTRICT protections are actually
# enforced.
#
# This protects:
#   payments.member_id -> members.id
#   payments.gym_id    -> gyms.id
#   members.gym_id     -> gyms.id
#
# Payment history therefore cannot be accidentally orphaned
# through a physical member/gym deletion.
# ============================================================

@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
