# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

# 1. Importujemy silniki bazy danych
# identity_engine — dane tożsamości (User, auth)
# operations_engine — dane operacyjne (Transaction, TransactionLine, Budget)
# Przy przyszłym splicie: zmienić URL w database.py i dodać migration script.
from sqlmodel import Session, select
from .database import identity_engine, operations_engine

# 2. ### WAŻNE ### Importujemy modele.
# Wymagane żeby SQLModel.metadata było wypełnione przed migracjami Alembica.
from .models import User, Category, Transaction, TransactionLine  # noqa: F401

# 3. ### WAŻNE ### Importujemy router z api.py
from .api import router as api_router

TEST_USER_EMAIL = "test@local.dev"
TEST_USER_PASSWORD = "test123"


def seed_dev_user():
    """Create a test user on first start in development mode."""
    from .auth import hash_password
    with Session(identity_engine) as session:
        existing = session.exec(select(User).where(User.email == TEST_USER_EMAIL)).first()
        if not existing:
            user = User(email=TEST_USER_EMAIL, hashed_password=hash_password(TEST_USER_PASSWORD))
            session.add(user)
            session.commit()
            print(f"🧪 Dev seed: created test user [{TEST_USER_EMAIL} / {TEST_USER_PASSWORD}]")
        else:
            print(f"🧪 Dev seed: test user already exists [{TEST_USER_EMAIL}]")

def seed_default_categories():
    """Seed system default categories if they don't exist."""
    with Session(operations_engine) as session:
        existing = session.exec(select(Category).where(Category.is_system)).first()
        if not existing:
            defaults = [
                {"name": "Food", "icon": "🍔", "color": "#f87171"},
                {"name": "Transport", "icon": "🚗", "color": "#60a5fa"},
                {"name": "Utilities", "icon": "💡", "color": "#facc15"},
                {"name": "Entertainment", "icon": "🎬", "color": "#c084fc"},
                {"name": "Health", "icon": "⚕️", "color": "#4ade80"},
                {"name": "Other", "icon": "📦", "color": "#9ca3af"},
            ]
            for cat_data in defaults:
                cat = Category(
                    name=cat_data["name"],
                    icon=cat_data["icon"],
                    color=cat_data["color"],
                    is_system=True
                )
                session.add(cat)
            session.commit()
            print("🌱 System default categories seeded.")


def _run_migrations() -> None:
    """Apply all pending Alembic migrations at application startup.

    If the database already has tables but no alembic_version (i.e. it was
    created by the old create_all() approach), stamp it to head first so that
    Alembic does not try to recreate existing tables.
    """
    from sqlalchemy import create_engine, inspect

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini_path = os.path.join(base_dir, "alembic.ini")
    alembic_cfg = AlembicConfig(alembic_ini_path)

    # Use the same DATABASE_URL that Alembic env.py reads — keeps legacy-check
    # and Alembic migrations on the exact same connection.
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/database.db")
    check_engine = create_engine(database_url)
    try:
        with check_engine.connect() as conn:
            inspector = inspect(conn)
            existing_tables = inspector.get_table_names()
            has_alembic_version = "alembic_version" in existing_tables
            has_app_tables = any(t for t in existing_tables if t != "alembic_version")
    finally:
        check_engine.dispose()

    if has_app_tables and not has_alembic_version:
        # Legacy database created by SQLModel.metadata.create_all() — stamp it
        # to head so Alembic knows the schema is already up to date.
        print("⚠️  Legacy database detected (no alembic_version). Stamping to head...")
        alembic_command.stamp(alembic_cfg, "head")
        print("✅ Database stamped to head. Future migrations will apply incrementally.")

    alembic_command.upgrade(alembic_cfg, "head")
    
    # After migrations, fix any data issues from the multi-tenant migration
    # This handles cases where the 6687268e50ab migration was empty when first run
    _fix_migration_data_issues()


def _fix_migration_data_issues() -> None:
    """Fix data issues from the multi-tenant migration transition.
    
    Specifically handles:
    1. Transactions with NULL budget_id (should be set based on user's budget)
    2. Users without budget membership (should create default budget)
    """
    from sqlalchemy import create_engine, text
    
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/database.db")
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as conn:
            # Check if this is SQLite (needs specific syntax for certain operations)
            is_sqlite = "sqlite" in database_url
            
            # Fix 1: Ensure all users have a budget
            # Find users without budget membership
            users_without_budget = conn.execute(text("""
                SELECT u.id, u.email 
                FROM user u
                LEFT JOIN budgetmember bm ON bm.user_id = u.id
                WHERE bm.id IS NULL
            """)).fetchall()
            
            for user_id, email in users_without_budget:
                print(f"⚠️  User {email} (id={user_id}) has no budget. Creating default budget...")
                
                # Create budget for user
                conn.execute(text("""
                    INSERT INTO budget (name, owner_id, created_at)
                    VALUES (:name, :owner_id, datetime('now'))
                """), {"name": "Domowy", "owner_id": user_id})
                
                if is_sqlite:
                    budget_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                else:
                    budget_id = conn.execute(text("SELECT LASTVAL()")).scalar()
                
                # Add user as owner of budget
                conn.execute(text("""
                    INSERT INTO budgetmember (budget_id, user_id, role)
                    VALUES (:budget_id, :user_id, 'owner')
                """), {"budget_id": budget_id, "user_id": user_id})
                conn.commit()
                print(f"✅ Created budget {budget_id} for user {user_id}")
            
            # Fix 2: Update transactions with NULL budget_id
            result = conn.execute(text("""
                UPDATE "transaction" 
                SET budget_id = (
                    SELECT bm.budget_id 
                    FROM budgetmember bm 
                    WHERE bm.user_id = "transaction".uploaded_by
                    LIMIT 1
                )
                WHERE budget_id IS NULL AND uploaded_by IS NOT NULL
            """))
            
            if result.rowcount > 0:
                print(f"✅ Fixed {result.rowcount} transactions with NULL budget_id")
            
            conn.commit()
            
    finally:
        engine.dispose()


# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run Alembic migrations on startup (applies any pending migrations automatically)
    _run_migrations()
    print("✅ Database migrations applied (alembic upgrade head).")

    seed_default_categories()

    if os.getenv("ENVIRONMENT") == "development":
        seed_dev_user()

    yield

app = FastAPI(title="Smart Budget AI", lifespan=lifespan)

# 4. ### WAŻNE ### Rejestrujemy router
# Dzięki temu endpointy z api.py (np. /upload) będą widoczne pod prefiksem /api
app.include_router(api_router, prefix="/api")

# --- Reszta: Healthcheck i Frontend ---
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Backend is running!"}

# Serwowanie Reacta (SPA)
if os.path.exists("static"):
    # Sprawdzamy czy assets istnieją (w dev mode mogą nie istnieć, bo pomijamy build frontu)
    if os.path.exists("static/assets"):
        app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    else:
        print("⚠️  static/assets folder not found. Skipping assets mount (Dev mode?).")

    # Obsługa uploadów (żebyś mógł zobaczyć wgrane zdjęcie w przeglądarce)
    # Tworzymy folder, jeśli nie istnieje, żeby nie było błędu przy starcie
    os.makedirs("static/uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="static/uploads"), name="uploads")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        file_path = f"static/{full_path}"
        if os.path.exists(file_path) and os.path.isfile(file_path):
             return FileResponse(file_path)
        
        # Jeśli nie znaleziono pliku, serwujemy index.html (SPA)
        # Ale tylko jeśli istnieje!
        index_path = "static/index.html"
        if os.path.exists(index_path):
            return FileResponse(index_path)
        
        return {"status": 404, "message": "Frontend static files not found (running in Dev/API mode)"}
else:
    print("⚠️  Static folder not found. Running in API-only mode.")