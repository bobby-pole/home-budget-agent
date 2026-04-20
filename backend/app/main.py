from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
from sqlmodel import Session, select, SQLModel

from .api import router
from .database import operations_engine, identity_engine
from .models import User
from .auth import hash_password

TEST_USER_EMAIL = "test@example.com"
TEST_USER_PASSWORD = "password123"

def seed_test_user():
    """Create a default test user if it doesn't exist (dev only)."""
    with Session(operations_engine) as session:
        user = session.exec(select(User).where(User.email == TEST_USER_EMAIL)).first()
        if not user:
            user = User(
                email=TEST_USER_EMAIL,
                hashed_password=hash_password(TEST_USER_PASSWORD)
            )
            session.add(user)
            session.commit()
            print(f"🧪 Dev seed: created test user [{TEST_USER_EMAIL} / {TEST_USER_PASSWORD}]")
        else:
            print(f"🧪 Dev seed: test user already exists [{TEST_USER_EMAIL}]")

def create_db_and_tables():
    """Create all tables defined in SQLModel.metadata."""
    import app.models  # noqa: F401
    SQLModel.metadata.create_all(identity_engine)
    SQLModel.metadata.create_all(operations_engine)
    print("✅ Database tables created (SQLModel.metadata.create_all).")

# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seeding
    if os.getenv("ENVIRONMENT") == "development":
        seed_test_user()
    yield

app = FastAPI(
    title="Smart Budget AI API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Mount API routes FIRST
app.include_router(router, prefix="/api")

# 2. STATIC FILES (Frontend)
STATIC_DIR = "/app/static"

if os.path.exists(STATIC_DIR):
    # Serve assets folder specifically
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Catch-all for SPA: serve index.html for all other routes
    @app.get("/{full_path:path}")
    async def serve_react_app(request: Request, full_path: str):
        # Skip if it looks like an API call (to return proper 404 instead of index.html)
        if full_path.startswith("api"):
            return {"detail": "Not Found"}
        
        # Check if the path is a file that exists in the static dir (favicon, logo, etc)
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Otherwise, always return index.html
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        
        return {"detail": "Static files not found"}
else:
    # Fallback for development/API-only mode
    @app.get("/")
    def health_check():
        return {"status": "ok", "message": "Smart Budget AI API is running (No frontend files found)"}
