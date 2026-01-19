# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import SQLModel

# 1. Importujemy silnik bazy danych
from .database import engine

# 2. ### WAŻNE ### Importujemy modele. 
# Jeśli tego nie zrobisz, SQLModel nie będzie wiedział, że ma utworzyć tabele 'Receipt' i 'Item'!
from .models import Receipt, Item 

# 3. ### WAŻNE ### Importujemy router z api.py
from .api import router as api_router

# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tworzy tabele w bazie danych
    SQLModel.metadata.create_all(engine)
    print("✅ Database tables created (if not existed).")
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
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    
    # Obsługa uploadów (żebyś mógł zobaczyć wgrane zdjęcie w przeglądarce)
    # Tworzymy folder, jeśli nie istnieje, żeby nie było błędu przy starcie
    os.makedirs("static/uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="static/uploads"), name="uploads")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        file_path = f"static/{full_path}"
        if os.path.exists(file_path) and os.path.isfile(file_path):
             return FileResponse(file_path)
        return FileResponse("static/index.html")
else:
    print("⚠️  Static folder not found. Running in API-only mode.")