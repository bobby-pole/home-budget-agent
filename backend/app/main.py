from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import asyncio
import os
from dotenv import load_dotenv

# Ensure environment variables are loaded for local execution BEFORE importing internal modules
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)

import logging  # noqa: E402
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)

from sqlmodel import Session, select, SQLModel  # noqa: E402

from .api import router  # noqa: E402
from .database import operations_engine, identity_engine  # noqa: E402
from .models import User  # noqa: E402
from .auth import hash_password  # noqa: E402

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
    with operations_engine.connect() as conn:
        try:
            conn.exec_driver_sql("ALTER TABLE receiptscan ADD COLUMN original_date VARCHAR")
            conn.commit()
        except Exception:
            pass
    print("✅ Database tables created (SQLModel.metadata.create_all).")

async def _periodic_demo_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)
            with Session(operations_engine) as session:
                from .demo_seed import cleanup_expired_demo_sessions
                cleanup_expired_demo_sessions(session, max_age_hours=24)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.getLogger(__name__).error("Periodic demo cleanup error: %s", e)

# --- LIFESPAN (Start serwera) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    # Seeding
    if os.getenv("ENVIRONMENT") == "development":
        seed_test_user()
    from .config import settings
    if settings.DEMO_MODE:
        try:
            with Session(operations_engine) as session:
                from .demo_seed import seed_demo_environment
                seed_demo_environment(session)
            logging.getLogger(__name__).info("Demo environment baseline auto-seeded on startup.")
        except Exception as e:
            logging.getLogger(__name__).error("Failed to seed baseline demo environment on startup: %s", e)
    cleanup_task = asyncio.create_task(_periodic_demo_cleanup())
    yield
    cleanup_task.cancel()

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
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        
        # Check if the path is a file that exists in the static dir (favicon, logo, etc)
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Otherwise, return index.html
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        
        return JSONResponse({"detail": "Static files not found"}, status_code=404)
else:
    # Fallback for development/API-only mode
    @app.get("/")
    def health_check():
        return {"status": "ok", "message": "Smart Budget AI API is running (No frontend files found)"}
