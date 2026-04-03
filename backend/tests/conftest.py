import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_session, get_ops_session
from app.models import User, Budget, BudgetMember
from app.auth import get_current_user
from app.api import get_current_budget

# In-memory database for testing
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session
        
    def get_ops_session_override():
        return session

    # Create a test user and their default budget to satisfy foreign keys and auth deps
    test_user = User(email="test@example.com", hashed_password="hashed_password_mock")
    session.add(test_user)
    session.commit()
    session.refresh(test_user)

    test_budget = Budget(name="Domowy", owner_id=test_user.id)
    session.add(test_budget)
    session.commit()
    session.refresh(test_budget)
    session.add(BudgetMember(budget_id=test_budget.id, user_id=test_user.id, role="owner"))
    session.commit()

    def get_current_user_override():
        return test_user

    def get_current_budget_override():
        return test_budget

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_ops_session] = get_ops_session_override
    app.dependency_overrides[get_current_user] = get_current_user_override
    app.dependency_overrides[get_current_budget] = get_current_budget_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
