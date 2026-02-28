# backend/app/database.py
from sqlmodel import create_engine, Session

SQLITE_FILE_NAME = "database.db"
DATABASE_URL = f"sqlite:///./data/{SQLITE_FILE_NAME}"

# check_same_thread=False jest wymagane dla SQLite w FastAPI
connect_args = {"check_same_thread": False}

# Identity engine: User authentication and identity data.
# Future split: point this to a separate auth DB.
identity_engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Operations engine: Business data (receipts, items, budgets).
# Future split: point this to a separate ops DB and add a migration script.
operations_engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Alias kept for backward compatibility (used in background tasks in api.py)
engine = identity_engine


def get_session():
    """Session for identity data (User, auth)."""
    with Session(identity_engine) as session:
        yield session


def get_ops_session():
    """Session for operational data (Receipt, Budget, Item)."""
    with Session(operations_engine) as session:
        yield session


def get_ai_session():
    """Read-only session for AI layer (stub — enforcement added when DBs split)."""
    with Session(operations_engine) as session:
        yield session
