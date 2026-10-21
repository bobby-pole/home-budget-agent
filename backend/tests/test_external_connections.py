"""Security and lifecycle tests for external receipt connections."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from sqlalchemy import text

from app.auth import get_current_user
from app.connection_service import ConnectionService
from app.core.encryption import EncryptionKeyError, TokenEncryptionService, get_encryption_service
from app.main import app
from app.models import (
    Budget,
    BudgetMember,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    ExternalReceiptConnectionCreate,
    User,
)


def _add_member(session: Session, budget: Budget, user: User, role: str) -> None:
    session.add(BudgetMember(budget_id=budget.id, user_id=user.id, role=role))
    session.commit()


def _set_client_user(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def _complete_authorization(
    session: Session, budget: Budget, user: User, provider: str = "lidl"
) -> ExternalReceiptConnection:
    placeholder = ConnectionService.create_connection(
        session, budget.id or 0, user, ExternalReceiptConnectionCreate(provider=provider)
    )
    connection = session.get(ExternalReceiptConnection, placeholder.id)
    assert connection is not None
    ConnectionService.complete_authorization(
        session,
        connection,
        refresh_token="server-only-refresh-token",
        consented_scopes="openid,tickets",
    )
    return connection


@pytest.fixture(autouse=True)
def setup_test_encryption_env(monkeypatch: pytest.MonkeyPatch):
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    get_encryption_service(reload_env=True)


def test_token_encryption_and_decryption():
    key = Fernet.generate_key().decode("utf-8")
    service = TokenEncryptionService(keys={"v1": key}, primary_key_id="v1")
    ciphertext, key_id = service.encrypt("server-only-refresh-token")
    assert key_id == "v1"
    assert service.decrypt(ciphertext, key_id="v1") == "server-only-refresh-token"


def test_encryption_fails_closed_for_missing_or_unknown_primary_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("TOKEN_PRIMARY_KEY_ID", raising=False)
    with pytest.raises(EncryptionKeyError):
        TokenEncryptionService().encrypt("sensitive-token")

    key = Fernet.generate_key().decode("utf-8")
    with pytest.raises(EncryptionKeyError):
        TokenEncryptionService(keys={"v1": key}, primary_key_id="missing")


def test_key_rotation_reencrypts_under_primary_key():
    key_v1 = Fernet.generate_key().decode("utf-8")
    key_v2 = Fernet.generate_key().decode("utf-8")
    old_service = TokenEncryptionService(keys={"v1": key_v1}, primary_key_id="v1")
    old_ciphertext, _ = old_service.encrypt("historic-token")
    rotated = TokenEncryptionService(keys={"v1": key_v1, "v2": key_v2}, primary_key_id="v2")
    ciphertext, key_id, changed = rotated.reencrypt_if_needed(old_ciphertext, "v1")
    assert changed is True
    assert key_id == "v2"
    assert rotated.decrypt(ciphertext, key_id=key_id) == "historic-token"


def test_sqlite_dump_never_contains_plaintext_token(session: Session):
    user = User(email="security@test.local", hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)
    budget = Budget(name="Secure Budget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    _add_member(session, budget, user, "owner")

    connection = _complete_authorization(session, budget, user)
    assert connection.encrypted_refresh_token is not None
    assert "server-only-refresh-token" not in connection.encrypted_refresh_token
    dump = "\n".join(session.connection().connection.iterdump())
    assert "server-only-refresh-token" not in dump
    assert connection.encrypted_refresh_token in dump


def test_public_api_rejects_credential_and_creates_reauth_placeholder(client: TestClient):
    rejected = client.post("/api/connections", json={"provider": "lidl", "refresh_token": "secret"})
    assert rejected.status_code == 422

    response = client.post("/api/connections", json={"provider": "lidl"})
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "lidl"
    assert data["status"] == ConnectionStatus.REAUTH_REQUIRED.value
    assert data["has_token"] is False
    assert data["consented_at"] is None
    assert "refresh_token" not in data
    assert "encrypted_refresh_token" not in data
    assert "account_identifier" not in data


def test_same_budget_member_cannot_read_or_mutate_another_users_connection(
    client: TestClient, session: Session
):
    created = client.post("/api/connections", json={"provider": "lidl"})
    connection_id = created.json()["id"]

    other_user = User(email="other@example.com", hashed_password="hash")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    budget = next(iter(session.exec(select(Budget))))
    _add_member(session, budget, other_user, "editor")
    _set_client_user(other_user)

    assert client.get("/api/connections").json() == []
    for request in (
        lambda: client.get(f"/api/connections/{connection_id}"),
        lambda: client.post(f"/api/connections/{connection_id}/sync-now"),
        lambda: client.post(f"/api/connections/{connection_id}/reconnect"),
        lambda: client.post(f"/api/connections/{connection_id}/disconnect"),
    ):
        assert request().status_code == 404


def test_viewer_cannot_create_or_manage_connection(client: TestClient, session: Session):
    viewer = User(email="viewer@example.com", hashed_password="hash")
    session.add(viewer)
    session.commit()
    session.refresh(viewer)
    budget = next(iter(session.exec(select(Budget))))
    _add_member(session, budget, viewer, "viewer")
    _set_client_user(viewer)

    response = client.post("/api/connections", json={"provider": "lidl"})
    assert response.status_code == 403


def test_two_household_members_can_create_separate_provider_connections(
    client: TestClient, session: Session
):
    first = client.post("/api/connections", json={"provider": "lidl"})
    assert first.status_code == 200

    other_user = User(email="second@example.com", hashed_password="hash")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    budget = next(iter(session.exec(select(Budget))))
    _add_member(session, budget, other_user, "editor")
    _set_client_user(other_user)

    second = client.post("/api/connections", json={"provider": "lidl"})
    assert second.status_code == 200
    assert first.json()["owner_user_id"] != second.json()["owner_user_id"]
    assert len(session.exec(select(ExternalReceiptConnection)).all()) == 2


def test_sync_requires_completed_authorization(client: TestClient):
    created = client.post("/api/connections", json={"provider": "lidl"})
    connection_id = created.json()["id"]
    sync = client.post(f"/api/connections/{connection_id}/sync-now")
    assert sync.status_code == 409
    assert "authorization" in sync.json()["detail"].lower()


def test_completed_authorization_allows_sync_and_keeps_identifier_private(
    client: TestClient, session: Session
):
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    connection = _complete_authorization(session, budget, owner)

    sync = client.post(f"/api/connections/{connection.id}/sync-now")
    assert sync.status_code == 200
    assert sync.json()["status"] == ConnectionStatus.ACTIVE.value
    detail = client.get(f"/api/connections/{connection.id}").json()
    assert detail["has_token"] is True
    assert "account_identifier" not in detail


def test_disconnect_erases_token_atomically(client: TestClient, session: Session):
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    connection = _complete_authorization(session, budget, owner)

    client.post(f"/api/connections/{connection.id}/sync-now")
    response = client.post(f"/api/connections/{connection.id}/disconnect")
    assert response.status_code == 200
    refreshed = session.get(ExternalReceiptConnection, connection.id)
    assert refreshed is not None
    assert refreshed.encrypted_refresh_token is None
    assert refreshed.encryption_key_id is None
    assert refreshed.status == ConnectionStatus.DISCONNECTED.value
    assert refreshed.sync_requested_at is None
    assert refreshed.next_sync_at is None
    assert ConnectionService.get_decrypted_token(session, refreshed) is None


def test_lost_encryption_key_marks_connection_for_reauthorization(
    session: Session, monkeypatch: pytest.MonkeyPatch
):
    user = User(email="restore@test.local", hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)
    budget = Budget(name="Restore Budget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    _add_member(session, budget, user, "owner")
    connection = _complete_authorization(session, budget, user)

    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("TOKEN_PRIMARY_KEY_ID", raising=False)
    get_encryption_service(reload_env=True)

    assert ConnectionService.get_decrypted_token(session, connection) is None
    assert connection.status == ConnectionStatus.REAUTH_REQUIRED.value
    assert connection.last_error_code == ConnectionErrorCode.ENCRYPTION_KEY_MISSING.value


def test_cross_budget_connection_is_not_accessible(client: TestClient, session: Session):
    owner = session.exec(select(User).where(User.email == "test@example.com")).one()
    other_budget = Budget(name="Other budget", owner_id=owner.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)
    _add_member(session, other_budget, owner, "owner")
    connection = _complete_authorization(session, other_budget, owner)

    assert client.get("/api/connections").json() == []
    assert client.get(f"/api/connections/{connection.id}").status_code == 404
    for action in ("sync-now", "reconnect", "disconnect"):
        assert client.post(f"/api/connections/{connection.id}/{action}").status_code == 404


def test_viewer_cannot_mutate_existing_connection(client: TestClient, session: Session):
    budget = next(iter(session.exec(select(Budget))))
    viewer = User(email="existing-viewer@example.com", hashed_password="hash")
    session.add(viewer)
    session.commit()
    session.refresh(viewer)
    _add_member(session, budget, viewer, "editor")
    connection = _complete_authorization(session, budget, viewer)
    membership = session.exec(select(BudgetMember).where(
        BudgetMember.budget_id == budget.id, BudgetMember.user_id == viewer.id
    )).one()
    membership.role = "viewer"
    session.add(membership)
    session.commit()
    _set_client_user(viewer)
    for action in ("sync-now", "reconnect", "disconnect"):
        assert client.post(f"/api/connections/{connection.id}/{action}").status_code == 403


def test_corrupted_ciphertext_marks_reauthorization(client: TestClient, session: Session):
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    connection = _complete_authorization(session, budget, owner)
    connection.encrypted_refresh_token = "invalid-ciphertext"
    session.add(connection)
    session.commit()

    assert ConnectionService.get_decrypted_token(session, connection) is None
    assert connection.status == ConnectionStatus.REAUTH_REQUIRED
    assert connection.last_error_code == ConnectionErrorCode.TOKEN_DECRYPTION_FAILED.value
    session.refresh(connection)
    assert connection.status == ConnectionStatus.REAUTH_REQUIRED


def test_worker_rotates_stored_ciphertext(client: TestClient, session: Session, monkeypatch):
    import json

    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    connection = _complete_authorization(session, budget, owner)
    old_ciphertext = connection.encrypted_refresh_token
    import os
    old_key = os.environ["TOKEN_ENCRYPTION_KEY"]
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEYS", json.dumps({"v1": old_key, "v2": new_key}))
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v2")
    get_encryption_service(reload_env=True)

    assert ConnectionService.get_decrypted_token(session, connection) == "server-only-refresh-token"
    session.refresh(connection)
    assert connection.encryption_key_id == "v2"
    assert connection.encrypted_refresh_token != old_ciphertext


def test_connection_status_storage_matches_migration_default(client: TestClient, session: Session):
    response = client.post("/api/connections", json={"provider": "lidl"})
    assert response.status_code == 200
    connection_id = response.json()["id"]
    stored = session.execute(text(
        "SELECT status FROM external_receipt_connection WHERE id = :id"
    ), {"id": connection_id}).scalar_one()
    assert stored == "reauth_required"
    # A row written using the migration's lowercase default must remain readable.
    session.execute(text(
        "UPDATE external_receipt_connection SET status = 'reauth_required' WHERE id = :id"
    ), {"id": connection_id})
    session.commit()
    session.expire_all()
    assert client.get(f"/api/connections/{connection_id}").json()["status"] == "reauth_required"
