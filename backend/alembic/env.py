from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
import sys  # noqa: E402
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlmodel import SQLModel  # noqa: E402
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    from app.database import DATABASE_URL
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    from app.database import DATABASE_URL
    from sqlalchemy import create_engine, inspect

    config_section = config.get_section(config.config_ini_section, {})
    config_section["sqlalchemy.url"] = DATABASE_URL
    
    # Self-healing logic for old MVP schema
    repair_engine = create_engine(DATABASE_URL)
    needs_delete = False
    with repair_engine.begin():
        try:
            insp = inspect(repair_engine)
            tables = insp.get_table_names()
            if "monthly_budget" in tables:
                needs_delete = True
        except Exception as e:
            print(f"Schema check skipped: {e}")
    repair_engine.dispose()
    
    if needs_delete:
        print("DETECTED OLD SCHEMA. STARTING FRESH AND DELETING OLD DB FILE...")
        db_path = DATABASE_URL.replace("sqlite:///", "")
        import os
        if os.path.exists(db_path):
            os.remove(db_path)
            
    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
