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
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
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


def test_lidl_oauth_start_callback_and_live_sync_e2e(client: TestClient, session: Session):
    from typing import Any
    from app.adapters.lidl_poc_client import LidlPoCClient, MOCK_LIDL_V3_TICKET, get_lidl_live_config
    from app.models import ReceiptScan, Transaction

    created = client.post("/api/connections", json={"provider": "lidl"})
    assert created.status_code == 200
    conn_id = created.json()["id"]

    start_res = client.post(f"/api/connections/{conn_id}/oauth/start")
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert "https://accounts.lidl.com/connect/authorize" in start_data["authorize_url"]
    state = start_data["state"]

    class _FakeResp:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return self._payload

    class _FakeHttpSession:
        def post(self, url: str, **kwargs: Any) -> _FakeResp:
            data = kwargs.get("data", {})
            if data.get("grant_type") == "authorization_code":
                return _FakeResp(
                    200,
                    {
                        "access_token": "initial-access-token",
                        "refresh_token": "initial-refresh-token",
                        "scope": "openid profile offline_access lpprofile lpapis",
                    },
                )
            return _FakeResp(
                200,
                {
                    "access_token": "refreshed-access-token",
                    "refresh_token": "rotated-refresh-token",
                },
            )

        def get(self, url: str, **kwargs: Any) -> _FakeResp:
            if "/api/v2/" in url:
                return _FakeResp(200, {"tickets": [{"id": "live-ticket-001"}]})
            return _FakeResp(200, MOCK_LIDL_V3_TICKET)

    fake_lidl = LidlPoCClient(get_lidl_live_config(), session=_FakeHttpSession())
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    from app.models import ConnectionOAuthCallbackRequest

    cb_res = ConnectionService.complete_oauth_callback(
        session,
        budget.id or 0,
        conn_id,
        owner,
        ConnectionOAuthCallbackRequest(
            callback_url_or_code=f"com.lidlplus.app://callback?code=auth-code-999&state={state}"
        ),
        client_override=fake_lidl,
    )
    assert cb_res.status == ConnectionStatus.ACTIVE
    assert cb_res.has_token is True

    sync_res = ConnectionService.trigger_sync_now(
        session,
        budget.id or 0,
        conn_id,
        owner,
        execute_live=True,
        client_override=fake_lidl,
    )
    assert sync_res.imported_count == 1
    assert sync_res.skipped_count == 0
    assert sync_res.failed_count == 0

    # Second run is deduplicated by ticket_id
    sync_res_2 = ConnectionService.trigger_sync_now(
        session,
        budget.id or 0,
        conn_id,
        owner,
        execute_live=True,
        client_override=fake_lidl,
    )
    assert sync_res_2.imported_count == 0
    assert sync_res_2.skipped_count == 1

    scans = session.exec(select(ReceiptScan)).all()
    assert len(scans) == 1
    tx = session.get(Transaction, scans[0].transaction_id)
    assert tx is not None
    assert tx.merchant_name == "Lidl PL0422"


def test_failed_live_sync_does_not_report_success(client: TestClient, session: Session):
    from unittest.mock import Mock
    from app.adapters.lidl_poc_client import TicketMappingError

    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    connection = _complete_authorization(session, budget, owner)
    provider = Mock()
    provider.refresh_access_token.return_value = {"access_token": "test-access"}
    provider.get_tickets_list.return_value = {"tickets": [{"id": "bad-ticket"}]}
    provider.get_ticket_detail.side_effect = TicketMappingError("invalid payload")
    result = ConnectionService.trigger_sync_now(
        session, budget.id or 0, connection.id or 0, owner,
        execute_live=True, client_override=provider,
    )
    assert result.failed_count == 1
    assert result.status == ConnectionStatus.SYNC_ERROR
    session.refresh(connection)
    assert connection.last_success_at is None
    assert connection.next_sync_at is None
    assert connection.last_error_code == ConnectionErrorCode.SYNC_FAILED.value


def test_receipt_and_lines_are_atomic(client: TestClient, session: Session, monkeypatch):
    from app.adapters.lidl_poc_client import MOCK_LIDL_V3_TICKET
    from app.models import Transaction, TransactionLine
    from app.services import AIService

    budget = next(iter(session.exec(select(Budget))))
    add = session.add

    def fail_on_line(obj, *args, **kwargs):
        if isinstance(obj, TransactionLine):
            raise RuntimeError("Simulated line storage failure")
        return add(obj, *args, **kwargs)

    monkeypatch.setattr(session, "add", fail_on_line)
    monkeypatch.setattr(AIService, "_categorize_parsed_items", lambda receipt, *args: receipt)
    with pytest.raises(RuntimeError, match="Simulated line"):
        ConnectionService._ingest_lidl_canonical_receipt(
            session, budget.id or 0, budget.owner_id or 0, "atomic-ticket", MOCK_LIDL_V3_TICKET,
        )
    session.rollback()
    assert session.exec(select(Transaction)).all() == []


def test_oauth_cannot_start_without_server_encryption_key(client: TestClient, monkeypatch):
    created = client.post("/api/connections", json={"provider": "lidl"})
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    get_encryption_service(reload_env=True)
    response = client.post(f"/api/connections/{created.json()['id']}/oauth/start")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
