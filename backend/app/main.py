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

# Mount API routes
app.include_router(router, prefix="/api")

# --- STATIC FILES (Frontend) ---

# Check if we are running in production (single container)
# In Docker, files are copied to /app/static
STATIC_DIR = "/app/static"

if os.path.exists(STATIC_DIR):
    # Route for the main entry point
    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    # Mount static assets (JS, CSS, etc.)
    # Important: this must be mounted AFTER API routes
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    # Catch-all route for SPA (React Router)
    @app.get("/{full_path:path}")
    async def catch_all(request: Request, full_path: str):
        # Allow API routes to be handled by the router
        if full_path.startswith("api"):
            return None
        
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
else:
    @app.get("/")
    def health_check():
        return {"status": "ok", "message": "Smart Budget AI API is running (Dev Mode)"}
