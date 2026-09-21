"""
backend/tests/test_external_connections.py

Comprehensive tests for ExternalReceiptConnection lifecycle, token encryption at rest,
key rotation, authorization security (cross-user / cross-budget), and failure modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.encryption import (
    EncryptionKeyError,
    TokenEncryptionService,
    get_encryption_service,
)
from app.models import (
    Budget,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    User,
)
from app.connection_service import ConnectionService


# ─── UNIT TESTS: TOKEN ENCRYPTION & KEY ROTATION ─────────────────────────────

def test_token_encryption_and_decryption():
    """Verify encryption and decryption round-trip with active primary key."""
    key = Fernet.generate_key().decode("utf-8")
    service = TokenEncryptionService(keys={"v1": key}, primary_key_id="v1")

    plaintext = "lidl-oauth-refresh-token-secret-xyz"
    ciphertext, key_id = service.encrypt(plaintext)

    assert key_id == "v1"
    assert ciphertext != plaintext
    assert plaintext not in ciphertext

    decrypted = service.decrypt(ciphertext, key_id="v1")
    assert decrypted == plaintext


def test_encryption_fail_closed_when_key_missing(monkeypatch: pytest.MonkeyPatch):
    """Ensure missing key fails closed with EncryptionKeyError."""
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("TOKEN_PRIMARY_KEY_ID", raising=False)

    service = TokenEncryptionService()
    assert not service.is_configured

    with pytest.raises(EncryptionKeyError):
        service.encrypt("sensitive-token")

    with pytest.raises(EncryptionKeyError):
        service.decrypt("some-ciphertext")


def test_encryption_fail_closed_when_key_invalid():
    """Ensure invalid key format triggers fail-closed error."""
    with pytest.raises(EncryptionKeyError):
        TokenEncryptionService(keys={"v1": "not-a-valid-base64-fernet-key"})


def test_key_rotation_decryption_with_previous_key():
    """Verify that an older key can decrypt historic records after rotation."""
    key_old = Fernet.generate_key().decode("utf-8")
    key_new = Fernet.generate_key().decode("utf-8")

    # Encrypted with old service
    service_old = TokenEncryptionService(keys={"v1": key_old}, primary_key_id="v1")
    plaintext = "super-secret-historic-token"
    ciphertext_v1, kid_v1 = service_old.encrypt(plaintext)
    assert kid_v1 == "v1"

    # Rotated service with v2 as primary and v1 as legacy
    service_rotated = TokenEncryptionService(
        keys={"v2": key_new, "v1": key_old},
        primary_key_id="v2"
    )

    decrypted = service_rotated.decrypt(ciphertext_v1, key_id="v1")
    assert decrypted == plaintext

    # Fallback decryption even when key_id is not provided
    decrypted_fallback = service_rotated.decrypt(ciphertext_v1)
    assert decrypted_fallback == plaintext


def test_key_rotation_reencryption_under_primary_key():
    """Verify automatic re-encryption from old key ID to active primary key ID."""
    key_v1 = Fernet.generate_key().decode("utf-8")
    key_v2 = Fernet.generate_key().decode("utf-8")

    service_v1 = TokenEncryptionService(keys={"v1": key_v1}, primary_key_id="v1")
    plaintext = "token-requiring-reencryption"
    ciphertext_v1, _ = service_v1.encrypt(plaintext)

    service_v2 = TokenEncryptionService(
        keys={"v2": key_v2, "v1": key_v1},
        primary_key_id="v2"
    )

    new_ciphertext, new_kid, did_reencrypt = service_v2.reencrypt_if_needed(
        ciphertext_v1, current_key_id="v1"
    )
    assert did_reencrypt is True
    assert new_kid == "v2"
    assert new_ciphertext != ciphertext_v1
    assert service_v2.decrypt(new_ciphertext, key_id="v2") == plaintext

    # If already encrypted with v2, no re-encryption occurs
    _, _, did_reencrypt_again = service_v2.reencrypt_if_needed(
        new_ciphertext, current_key_id="v2"
    )
    assert did_reencrypt_again is False


# ─── DATABASE DUMP SECURITY TEST ─────────────────────────────────────────────

def test_sqlite_dump_never_contains_plaintext_token(session: Session, monkeypatch: pytest.MonkeyPatch):
    """
    SECURITY TEST: Prove that dumping the SQLite database does NOT reveal
    the plaintext token in raw tables, queries, or serialization dumps.
    """
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", test_key)
    get_encryption_service(reload_env=True)

    secret_raw_token = "TOPSECRET_REFRESH_TOKEN_PLAINTEXT_12345"

    user = User(email="security@test.local", hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)

    budget = Budget(name="Secure Budget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)

    assert budget.id is not None
    assert user.id is not None

    # Use service to create connection
    from app.models import ExternalReceiptConnectionCreate
    data = ExternalReceiptConnectionCreate(
        provider="lidl",
        account_identifier="user@example.com",
        consented_scopes="openid,tickets",
        refresh_token=secret_raw_token,
    )
    conn_dto = ConnectionService.create_or_update_connection(session, budget.id, user, data)
    assert conn_dto.has_token is True

    # 1. Fetch raw row from database
    db_conn = session.get(ExternalReceiptConnection, conn_dto.id)
    assert db_conn is not None
    assert db_conn.encrypted_refresh_token is not None
    assert secret_raw_token not in db_conn.encrypted_refresh_token

    # 2. Extract SQLite dump across all tables and rows
    raw_connection = session.connection().connection
    dump_lines = list(raw_connection.iterdump())
    full_database_dump = "\n".join(dump_lines)

    # Invariant: Plaintext token MUST NOT exist in database dump
    assert secret_raw_token not in full_database_dump
    assert "TOPSECRET_REFRESH_TOKEN" not in full_database_dump

    # Invariant: Encrypted ciphertext IS present in the dump
    assert db_conn.encrypted_refresh_token in full_database_dump


# ─── API ENDPOINT & LIFECYCLE TESTS ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_test_encryption_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure a valid test Fernet key is always available for API tests."""
    test_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    get_encryption_service(reload_env=True)


def test_api_create_and_read_connection(client: TestClient, session: Session):
    """Verify creating a connection and reading it back without exposing ciphertexts."""
    create_payload = {
        "provider": "lidl",
        "account_identifier": "+48 500 600 700",
        "consented_scopes": "openid,tickets,profile",
        "refresh_token": "client-test-token-value",
    }
    response = client.post("/api/connections", json=create_payload)
    assert response.status_code == 200
    data = response.json()

    assert data["provider"] == "lidl"
    assert data["account_identifier"] == "+48 500 600 700"
    assert data["consented_scopes"] == "openid,tickets,profile"
    assert data["status"] == "active"
    assert data["has_token"] is True

    # Strict privacy invariant: token and ciphertext are NEVER returned in response
    assert "refresh_token" not in data
    assert "encrypted_refresh_token" not in data
    assert "encryption_key_id" not in data

    connection_id = data["id"]

    # Read back via GET /connections
    list_resp = client.get("/api/connections")
    assert list_resp.status_code == 200
    connections = list_resp.json()
    assert len(connections) == 1
    assert connections[0]["id"] == connection_id
    assert connections[0]["has_token"] is True

    # Read back via GET /connections/{id}
    detail_resp = client.get(f"/api/connections/{connection_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == connection_id


def test_api_cross_budget_cross_user_forbidden(client: TestClient, session: Session):
    """
    Ensure user in Budget A cannot access, sync, reconnect, or disconnect
    a connection belonging to Budget B (cross-budget isolation).
    """
    # Create another user and budget (Budget B)
    other_user = User(email="other@example.com", hashed_password="hash")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)

    other_budget = Budget(name="Other Budget", owner_id=other_user.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)

    assert other_budget.id is not None
    assert other_user.id is not None

    # Insert a connection in Budget B
    other_conn = ExternalReceiptConnection(
        budget_id=other_budget.id,
        owner_user_id=other_user.id,
        provider="biedronka",
        status=ConnectionStatus.ACTIVE.value,
        consented_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(other_conn)
    session.commit()
    session.refresh(other_conn)

    # Current client is authenticated as default test_user in test_budget (Budget A)
    # Attempt to read Budget B's connection -> MUST return 404
    resp_get = client.get(f"/api/connections/{other_conn.id}")
    assert resp_get.status_code == 404

    # Attempt to trigger sync -> MUST return 404
    resp_sync = client.post(f"/api/connections/{other_conn.id}/sync-now")
    assert resp_sync.status_code == 404

    # Attempt to reconnect -> MUST return 404
    resp_reconnect = client.post(f"/api/connections/{other_conn.id}/reconnect")
    assert resp_reconnect.status_code == 404

    # Attempt to disconnect -> MUST return 404
    resp_disconnect = client.post(f"/api/connections/{other_conn.id}/disconnect")
    assert resp_disconnect.status_code == 404


def test_api_sync_now_records_request_without_false_success(client: TestClient):
    """
    'Sync now' registers sync_requested_at in queue.
    Invariant: Does NOT falsely report completed synchronization without worker #257.
    """
    create_payload = {"provider": "lidl", "refresh_token": "token-1"}
    create_resp = client.post("/api/connections", json=create_payload)
    conn_id = create_resp.json()["id"]

    sync_resp = client.post(f"/api/connections/{conn_id}/sync-now")
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()

    assert sync_data["connection_id"] == conn_id
    assert sync_data["status"] == "active"
    assert "sync_requested_at" in sync_data
    assert sync_data["sync_requested_at"] is not None
    # Message makes clear it is queued, not completed
    assert "queued" in sync_data["message"].lower()

    # Verify detail shows sync_requested_at
    detail_resp = client.get(f"/api/connections/{conn_id}")
    assert detail_resp.json()["sync_requested_at"] is not None


def test_api_reconnect_sets_reauth_required(client: TestClient):
    """Reconnect transitions connection status to reauth_required."""
    create_payload = {"provider": "lidl"}
    create_resp = client.post("/api/connections", json=create_payload)
    conn_id = create_resp.json()["id"]

    reconnect_resp = client.post(f"/api/connections/{conn_id}/reconnect")
    assert reconnect_resp.status_code == 200
    data = reconnect_resp.json()
    assert data["status"] == ConnectionStatus.REAUTH_REQUIRED.value
    assert data["last_error_code"] == ConnectionErrorCode.REAUTH_REQUIRED.value


def test_api_disconnect_deletes_token_atomically(client: TestClient, session: Session):
    """
    Disconnect deletes tokens at rest atomically and reports neutral revocation status.
    """
    create_payload = {
        "provider": "lidl",
        "refresh_token": "token-to-delete",
    }
    create_resp = client.post("/api/connections", json=create_payload)
    conn_id = create_resp.json()["id"]
    assert create_resp.json()["has_token"] is True

    # Disconnect
    disc_resp = client.post(f"/api/connections/{conn_id}/disconnect")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()
    assert disc_data["status"] == ConnectionStatus.DISCONNECTED.value
    assert disc_data["revocation_status"] == "provider_revocation_unavailable"

    # Verify in DB: tokens must be None
    db_conn = session.get(ExternalReceiptConnection, conn_id)
    assert db_conn is not None
    assert db_conn.encrypted_refresh_token is None
    assert db_conn.encryption_key_id is None
    assert db_conn.status == ConnectionStatus.DISCONNECTED.value
    assert db_conn.last_error_code == ConnectionErrorCode.PROVIDER_REVOCATION_UNAVAILABLE.value

    # Verify via API detail: has_token is False
    detail_resp = client.get(f"/api/connections/{conn_id}")
    assert detail_resp.json()["has_token"] is False
    assert detail_resp.json()["status"] == ConnectionStatus.DISCONNECTED.value


def test_sync_now_rejected_on_disconnected(client: TestClient):
    """Cannot trigger sync on a disconnected connection."""
    create_payload = {"provider": "lidl"}
    create_resp = client.post("/api/connections", json=create_payload)
    conn_id = create_resp.json()["id"]

    client.post(f"/api/connections/{conn_id}/disconnect")

    sync_resp = client.post(f"/api/connections/{conn_id}/sync-now")
    assert sync_resp.status_code == 400
    assert "disconnected" in sync_resp.json()["detail"].lower()
