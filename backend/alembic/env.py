import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlmodel import SQLModel

from alembic import context

# Import all models so that SQLModel.metadata is populated for autogenerate
from app.models import (  # noqa: F401
    User,
    Budget,
    BudgetMember,
    Category,
    Tag,
    TransactionTagLink,
    Transaction,
    ReceiptScan,
    TransactionLine,
    MonthlyBudget,
    BudgetCategoryLimit,
)

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Set up Python logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use SQLModel metadata for autogenerate support
target_metadata = SQLModel.metadata

# Override sqlalchemy.url from DATABASE_URL env var if set (useful in Docker)
database_url = os.getenv("DATABASE_URL", "sqlite:///./data/database.db")
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Required for SQLite — allows ALTER TABLE via table recreation
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (applies migrations against a live DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Required for SQLite — allows ALTER TABLE via table recreation
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
