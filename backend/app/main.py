# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import SQLModel

# 1. Importujemy silniki bazy danych
# identity_engine — dane tożsamości (User, auth)
# operations_engine — dane operacyjne (Receipt, Item, Budget)
# Przy przyszłym splicie: zmienić URL w database.py i dodać migration script.
from sqlmodel import Session, select
from .database import identity_engine, operations_engine

# 2. ### WAŻNE ### Importujemy modele.
# Jeśli tego nie zrobisz, SQLModel nie będzie wiedział, że ma utworzyć tabele 'Receipt' i 'Item'!
from .models import User, Budget, BudgetMember, Receipt, Item, MonthlyBudget

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
        "ALTER TABLE receipt ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT 0",
    ]
    with operations_engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"✅ Migration applied: {sql}")
            except Exception:
                pass  # Column already exists — safe to ignore

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