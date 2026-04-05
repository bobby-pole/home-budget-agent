# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 1. Importujemy silniki bazy danych
# identity_engine — dane tożsamości (User, auth)
# operations_engine — dane operacyjne (Transaction, TransactionLine, Budget)
# Przy przyszłym splicie: zmienić URL w database.py i dodać migration script.
from sqlmodel import Session, select, SQLModel
from .database import identity_engine, operations_engine

# 2. ### WAŻNE ### Importujemy modele.
# Wymagane żeby SQLModel.metadata było wypełnione.
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

def create_db_and_tables():
    """Create all tables defined in SQLModel.metadata."""
    SQLModel.metadata.create_all(identity_engine)
    SQLModel.metadata.create_all(operations_engine)
    print("✅ Database tables created (SQLModel.metadata.create_all).")

# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tworzymy tabele przy starcie (brak Alembica)
    create_db_and_tables()

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
