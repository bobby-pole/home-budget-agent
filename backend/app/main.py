# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import SQLModel

# 1. Importujemy silniki bazy danych
# identity_engine — dane tożsamości (User, auth)
# operations_engine — dane operacyjne (Transaction, TransactionLine, Budget)
# Przy przyszłym splicie: zmienić URL w database.py i dodać migration script.
from sqlmodel import Session, select
from .database import identity_engine, operations_engine

# 2. ### WAŻNE ### Importujemy modele.
# Jeśli tego nie zrobisz, SQLModel nie będzie wiedział, że ma utworzyć tabele 'Transaction' i 'TransactionLine'!
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


# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tworzy tabele na obu silnikach (bezpieczne — ta sama baza, idempotentne).
    SQLModel.metadata.create_all(identity_engine)
    SQLModel.metadata.create_all(operations_engine)
    print("✅ Database tables created (if not existed).")

    # Inline migrations for columns added after initial schema creation
    # (SQLite's create_all does not add new columns to existing tables)
    from sqlalchemy import text
    migrations = [
        # Legacy migrations for old 'receipt' table (kept for reference, safe to ignore on fresh DB)
        "ALTER TABLE receipt ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE receipt ADD COLUMN category_id INTEGER REFERENCES category(id)",
        # Schema migrations
        "ALTER TABLE category ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE monthly_budget ADD COLUMN user_id INTEGER REFERENCES user(id)",
        "ALTER TABLE tag ADD COLUMN color TEXT",
        # Data migrations
        "UPDATE category SET name = 'Food' WHERE name = 'Jedzenie' AND is_system = 1",
        "UPDATE category SET name = 'Utilities' WHERE name = 'Rachunki' AND is_system = 1",
        "UPDATE category SET name = 'Entertainment' WHERE name = 'Rozrywka' AND is_system = 1",
        "UPDATE category SET name = 'Health' WHERE name = 'Zdrowie' AND is_system = 1",
        "UPDATE category SET name = 'Other' WHERE name = 'Inne' AND is_system = 1",
        # Transaction-First refactor: add type column to transaction table (for existing DBs)
        "ALTER TABLE \"transaction\" ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'",
        # Clean up obsolete columns from transaction table (moved to ReceiptScan)
        "ALTER TABLE \"transaction\" DROP COLUMN status",
        "ALTER TABLE \"transaction\" DROP COLUMN image_path",
        "ALTER TABLE \"transaction\" DROP COLUMN content_hash",
    ]
    with operations_engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"✅ Migration applied: {sql}")
            except Exception:
                pass  # Column already exists — safe to ignore

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