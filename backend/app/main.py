import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.database import (
    identity_engine,
    operations_engine,
)
from app.models import User, Budget
from app.auth import hash_password
from app.api import router

# Pre-defined test account for development
TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "test@example.com")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "password123")

def seed_test_user():
    """Seed a test user if it doesn't exist."""
    with Session(identity_engine) as session:
        user = session.exec(select(User).where(User.email == TEST_USER_EMAIL)).first()
        if not user:
            user = User(
                email=TEST_USER_EMAIL,
                hashed_password=hash_password(TEST_USER_PASSWORD)
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
            # Create default budget
            budget = Budget(name="Domowy", owner_id=user.id)
            session.add(budget)
            session.commit()
            print(f"🧪 Dev seed: created test user [{TEST_USER_EMAIL} / {TEST_USER_PASSWORD}]")
        else:
            print(f"🧪 Dev seed: test user already exists [{TEST_USER_EMAIL}]")

def seed_default_categories():
    """Deprecated: categories are now seeded per budget during registration."""
    pass

def create_db_and_tables():
    """Create all tables defined in SQLModel.metadata."""
    import app.models # noqa: F401
    from sqlmodel import SQLModel
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

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Smart Budget AI API is running"}
