# backend/app/database.py
import os
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import create_engine, Session

SQLITE_FILE_NAME = "database.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///./data/{SQLITE_FILE_NAME}")

# Ensure local data directory exists if SQLite database is placed in a subfolder
if "sqlite:///./data" in DATABASE_URL:
    os.makedirs("./data", exist_ok=True)

# check_same_thread=False jest wymagane dla SQLite w FastAPI, timeout zapobiega database is locked
connect_args = {"check_same_thread": False, "timeout": 30.0}

# Identity engine: User authentication and identity data.
# Future split: point this to a separate auth DB.
identity_engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Operations engine: Business data (transactions, items, budgets).
# Future split: point this to a separate ops DB and add a migration script.
operations_engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Alias kept for backward compatibility (used in background tasks in api.py)
engine = identity_engine


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode and busy timeout for concurrent SQLite reads/writes."""
    if "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()


def get_session():
    """Session for identity data (User, auth)."""
    with Session(identity_engine) as session:
        yield session


def get_ops_session():
    """Session for operational data (Transaction, TransactionLine, Budget)."""
    with Session(operations_engine) as session:
        yield session


def get_ai_session():
    """Read-only session for AI layer (stub — enforcement added when DBs split)."""
    with Session(operations_engine) as session:
        yield session
