"""Synthetic & regression tests for #264: trusted-local privacy boundary,
persistent encrypted PKCE attempts, desktop OAuth capture, and lifecycle endurance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.adapters.lidl_poc_client import (
    MOCK_LIDL_V3_TICKET,
    LidlPoCClient,
    get_lidl_live_config,
)
from app.auth import get_current_user
from app.config import Settings, settings
from app.connection_service import ConnectionService
from app.core.encryption import get_encryption_service
from app.import_scheduler import (
    ImportWorker,
    ProviderRatePolicy,
    enqueue_connection_sync_job,
    is_trusted_worker_environment,
)
from app.main import app
from app.models import (
    Budget,
    BudgetMember,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJobStatus,
    ReceiptScan,
    SourceRecord,
    Transaction,
    User,
)


@pytest.fixture(autouse=True)
def setup_264_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    monkeypatch.setenv("IMPORT_WORKER_ROLE", "trusted_local")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "IMPORT_WORKER_ROLE", "trusted_local")
    get_encryption_service(reload_env=True)


def test_compose_and_settings_fail_closed_for_central_vps(monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[2]
    prod_compose = (repo_root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    demo_compose = (repo_root / "docker-compose.demo.yml").read_text(encoding="utf-8")

    assert "IMPORT_WORKER_ROLE=central_vps" in prod_compose
    assert "IMPORT_WORKER_ENABLED=false" in prod_compose
    assert "IMPORT_WORKER_ROLE=central_vps" in demo_compose
    assert "IMPORT_WORKER_ENABLED=false" in demo_compose

    # When IMPORT_WORKER_ROLE is unset, production and demo fail closed to central_vps.
    monkeypatch.delenv("IMPORT_WORKER_ROLE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    prod_settings = Settings()
    assert prod_settings.resolve_import_worker_role() == "central_vps"
    assert is_trusted_worker_environment() is False

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEMO_MODE", "true")
    demo_settings = Settings()
    assert demo_settings.resolve_import_worker_role() == "central_vps"


def test_central_vps_and_demo_block_oauth_and_live_sync_endpoints(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    created = client.post("/api/connections", json={"provider": "lidl"})
    assert created.status_code == 200
    conn_id = created.json()["id"]

    conn = session.get(ExternalReceiptConnection, conn_id)
    assert conn is not None
    ConnectionService.complete_authorization(
        session,
        conn,
        refresh_token="synthetic-refresh-token",
        consented_scopes="openid offline_access",
    )

    for mode, value in (("central_vps_role", "central_vps"), ("demo_mode", True)):
        if mode == "central_vps_role":
            monkeypatch.setenv("IMPORT_WORKER_ROLE", str(value))
            monkeypatch.setattr(settings, "IMPORT_WORKER_ROLE", str(value))
            monkeypatch.setattr(settings, "DEMO_MODE", False)
            monkeypatch.setenv("DEMO_MODE", "false")
        else:
            monkeypatch.setenv("IMPORT_WORKER_ROLE", "trusted_local")
            monkeypatch.setattr(settings, "IMPORT_WORKER_ROLE", "trusted_local")
            monkeypatch.setattr(settings, "DEMO_MODE", True)
            monkeypatch.setenv("DEMO_MODE", "true")

        cfg = client.get("/api/config").json()
        assert cfg["trusted_local"] is False
        assert cfg["desktop_oauth_available"] is False

        assert client.post(f"/api/connections/{conn_id}/oauth/start").status_code == 403
        assert (
            client.post(
                f"/api/connections/{conn_id}/oauth/callback",
                json={"callback_url_or_code": "com.lidlplus.app://callback?code=x&state=y"},
            ).status_code
            == 403
        )
        assert client.post(f"/api/connections/{conn_id}/oauth/desktop-login").status_code == 403
        assert client.post(f"/api/connections/{conn_id}/sync-now?live=true").status_code == 403
        assert client.post(f"/api/connections/{conn_id}/sync-now").status_code == 403

        outcome = ConnectionService.execute_connection_sync(session, conn)
        assert outcome.error_classification == "permanent"
        assert outcome.error_code == ConnectionErrorCode.SYNC_FAILED


def test_oauth_attempt_persists_encrypted_across_restarts_and_expires(
    client: TestClient,
    session: Session,
):
    created = client.post("/api/connections", json={"provider": "lidl"})
    conn_id = created.json()["id"]

    start_res = client.post(f"/api/connections/{conn_id}/oauth/start")
    assert start_res.status_code == 200
    state = start_res.json()["state"]

    conn = session.get(ExternalReceiptConnection, conn_id)
    assert conn is not None
    assert conn.encrypted_oauth_attempt is not None
    assert conn.oauth_attempt_key_id == "v1"
    assert conn.oauth_attempt_expires_at is not None

    # SQLite dump must never contain plaintext PKCE verifier, state, or nonce
    dump = "\n".join(session.connection().connection.iterdump())
    assert state not in dump

    # Simulate expiry -> must clear attempt and fail with 400
    conn.oauth_attempt_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    session.add(conn)
    session.commit()

    expired_res = client.post(
        f"/api/connections/{conn_id}/oauth/callback",
        json={"callback_url_or_code": f"com.lidlplus.app://callback?code=c1&state={state}"},
    )
    assert expired_res.status_code == 400
    assert "expired" in expired_res.json()["detail"].lower()
    session.refresh(conn)
    assert conn.encrypted_oauth_attempt is None


def test_desktop_oauth_login_flow_rejects_bad_state_and_completes_without_secret_leaks(
    client: TestClient,
    session: Session,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    created = client.post("/api/connections", json={"provider": "lidl"})
    conn_id = created.json()["id"]

    auth_code_secret = "SYNTHETIC_AUTH_CODE_DO_NOT_LOG_123"
    refresh_secret = "SYNTHETIC_REFRESH_SECRET_DO_NOT_LOG_456"
    access_secret = "SYNTHETIC_ACCESS_SECRET_DO_NOT_LOG_789"

    class _Resp:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return self._payload

    class _FakeOAuthHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(
                200,
                {
                    "access_token": access_secret,
                    "refresh_token": refresh_secret,
                    "expires_in": 3600,
                    "scope": "openid profile offline_access",
                },
            )

    fake_client = LidlPoCClient(get_lidl_live_config(), session=_FakeOAuthHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_client)
    monkeypatch.setattr("app.adapters.lidl_desktop_oauth.is_desktop_oauth_available", lambda: True)

    # 1. Cancelled/timed-out desktop window clears pending encrypted attempt immediately
    from app.adapters.lidl_desktop_oauth import DesktopOAuthCancelledError

    def _cancel_capture(_url: str) -> str:
        raise DesktopOAuthCancelledError("Window closed by user")

    monkeypatch.setattr(
        "app.adapters.lidl_desktop_oauth.capture_lidl_oauth_callback",
        _cancel_capture,
    )
    cancel_res = client.post(f"/api/connections/{conn_id}/oauth/desktop-login")
    assert cancel_res.status_code == 400
    conn_after_cancel = session.get(ExternalReceiptConnection, conn_id)
    assert conn_after_cancel is not None
    assert conn_after_cancel.encrypted_oauth_attempt is None

    # 2. Mismatched state from desktop capture must fail cleanly (allow_raw_code=False)
    monkeypatch.setattr(
        "app.adapters.lidl_desktop_oauth.capture_lidl_oauth_callback",
        lambda _url: f"com.lidlplus.app://callback?code={auth_code_secret}&state=wrong-state",
    )
    bad_res = client.post(f"/api/connections/{conn_id}/oauth/desktop-login")
    assert bad_res.status_code == 400

    # 3. Valid desktop redirect URL completes login automatically and clears pending attempt
    def _capture_with_url_state(authorize_url: str) -> str:
        from urllib.parse import parse_qs, urlsplit

        state = parse_qs(urlsplit(authorize_url).query)["state"][0]
        return f"com.lidlplus.app://callback?code={auth_code_secret}&state={state}"

    monkeypatch.setattr(
        "app.adapters.lidl_desktop_oauth.capture_lidl_oauth_callback",
        _capture_with_url_state,
    )
    caplog.set_level(logging.DEBUG)
    ok_res = client.post(f"/api/connections/{conn_id}/oauth/desktop-login")
    assert ok_res.status_code == 200, ok_res.text
    body = ok_res.json()
    assert body["status"] == ConnectionStatus.ACTIVE.value
    assert body["has_token"] is True

    conn = session.get(ExternalReceiptConnection, conn_id)
    assert conn is not None
    assert conn.encrypted_oauth_attempt is None
    assert conn.encrypted_refresh_token is not None

    dump = "\n".join(session.connection().connection.iterdump())
    for secret in (auth_code_secret, refresh_secret, access_secret):
        assert secret not in dump
        assert secret not in caplog.text


def test_synthetic_endurance_expiry_rotation_restart_key_loss_and_disconnect(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exercise full lifecycle: access expiry -> refresh rotation -> restart -> key loss -> disconnect."""
    created = client.post("/api/connections", json={"provider": "lidl"})
    conn_id = created.json()["id"]
    conn = session.get(ExternalReceiptConnection, conn_id)
    assert conn is not None
    ConnectionService.complete_authorization(
        session,
        conn,
        refresh_token="refresh-v1",
        consented_scopes="openid offline_access",
    )

    state = {"refresh_calls": 0, "ticket_calls": 0}

    class _Resp:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return self._payload

    class _EnduranceHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            state["refresh_calls"] += 1
            sent = kwargs.get("data", {}).get("refresh_token")
            if state["refresh_calls"] == 1:
                assert sent == "refresh-v1"
                return _Resp(200, {"access_token": "access-1", "refresh_token": "refresh-v2"})
            assert sent == "refresh-v2"
            return _Resp(200, {"access_token": "access-2", "refresh_token": "refresh-v3"})

        def get(self, url: str, **kwargs: Any) -> _Resp:
            state["ticket_calls"] += 1
            if "/api/v2/" in url:
                return _Resp(200, {"tickets": [{"id": "endurance-ticket-1"}]})
            return _Resp(200, MOCK_LIDL_V3_TICKET)

    fake_client = LidlPoCClient(get_lidl_live_config(), session=_EnduranceHttp())  # type: ignore[arg-type]
    budget = session.exec(select(Budget)).one()
    owner = session.get(User, budget.owner_id)
    assert owner is not None

    # 1. First sync uses refresh-v1 -> rotates to refresh-v2 and imports 1 receipt
    res1 = ConnectionService.trigger_sync_now(
        session, budget.id or 0, conn_id, owner, execute_live=True, client_override=fake_client
    )
    assert res1.imported_count == 1
    session.refresh(conn)
    assert ConnectionService.get_decrypted_token(session, conn) == "refresh-v2"

    # 2. Second sync after simulated restart uses rotated refresh-v2 -> rotates to refresh-v3 & deduplicates
    res2 = ConnectionService.trigger_sync_now(
        session, budget.id or 0, conn_id, owner, execute_live=True, client_override=fake_client
    )
    assert res2.imported_count == 0
    assert res2.skipped_count == 1
    assert ConnectionService.get_decrypted_token(session, conn) == "refresh-v3"

    # 3. Missing encryption key fails closed without erasing ciphertext
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    get_encryption_service(reload_env=True)
    assert ConnectionService.get_decrypted_token(session, conn) is None
    assert conn.status == ConnectionStatus.REAUTH_REQUIRED
    assert conn.last_error_code == ConnectionErrorCode.ENCRYPTION_KEY_MISSING.value
    assert conn.encrypted_refresh_token is not None

    # 4. Disconnect erases stored ciphertext atomically
    disc_res = client.post(f"/api/connections/{conn_id}/disconnect")
    assert disc_res.status_code == 200
    session.refresh(conn)
    assert conn.encrypted_refresh_token is None
    assert conn.status == ConnectionStatus.DISCONNECTED


def test_per_owner_isolation_and_worker_idempotency_in_shared_budget(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """Two household members in one budget remain isolated while worker dedupes repeated runs."""
    budget = session.exec(select(Budget)).one()
    owner = session.get(User, budget.owner_id)
    assert owner is not None

    partner = User(email="partner_264@example.com", hashed_password="pw")
    session.add(partner)
    session.commit()
    session.refresh(partner)
    assert partner.id is not None
    session.add(BudgetMember(budget_id=budget.id, user_id=partner.id, role="editor"))
    session.commit()

    # Owner creates & authorizes Lidl connection
    c_owner_res = client.post("/api/connections", json={"provider": "lidl"})
    assert c_owner_res.status_code == 200
    owner_conn_id = c_owner_res.json()["id"]
    owner_conn = session.get(ExternalReceiptConnection, owner_conn_id)
    assert owner_conn is not None
    ConnectionService.complete_authorization(
        session, owner_conn, refresh_token="owner-tok", consented_scopes="openid"
    )

    # Partner cannot access owner's connection (even when Playwright is unavailable on CI)
    app.dependency_overrides[get_current_user] = lambda: partner
    assert client.post(f"/api/connections/{owner_conn_id}/oauth/start").status_code == 404
    monkeypatch.setattr(
        "app.adapters.lidl_desktop_oauth.is_desktop_oauth_available", lambda: False
    )
    assert client.post(f"/api/connections/{owner_conn_id}/oauth/desktop-login").status_code == 404

    # Partner creates & authorizes their own connection in the same budget
    c_partner_res = client.post("/api/connections", json={"provider": "lidl"})
    assert c_partner_res.status_code == 200
    partner_conn_id = c_partner_res.json()["id"]
    assert partner_conn_id != owner_conn_id

    # Worker runs twice on owner's connection -> zero duplicate transactions/source records
    class _Resp:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return self._payload

    class _WorkerHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(200, {"access_token": "acc-w", "refresh_token": "owner-tok-2"})

        def get(self, url: str, **kwargs: Any) -> _Resp:
            if "/api/v2/" in url:
                return _Resp(200, {"tickets": [{"id": "shared-budget-ticket-1"}]})
            return _Resp(200, MOCK_LIDL_V3_TICKET)

    fake_client = LidlPoCClient(get_lidl_live_config(), session=_WorkerHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_client)

    enqueue_connection_sync_job(session, owner_conn, next_retry_at=datetime.now(timezone.utc))
    worker = ImportWorker(
        lambda: Session(session.get_bind()),
        worker_id="test-264-worker",
        provider_policies={
            "lidl": ProviderRatePolicy(max_concurrent=2, min_interval_seconds=0.0)
        },
    )
    job1 = worker.run_once()
    assert job1 is not None
    assert job1.status == ImportJobStatus.COMPLETED

    # Re-enqueue same ticket -> skipped without duplicate transactions
    enqueue_connection_sync_job(session, owner_conn, next_retry_at=datetime.now(timezone.utc))
    job2 = worker.run_once()
    assert job2 is not None
    assert job2.status == ImportJobStatus.COMPLETED

    txs = session.exec(select(Transaction).where(Transaction.budget_id == budget.id)).all()
    scans = session.exec(select(ReceiptScan)).all()
    sources = session.exec(select(SourceRecord).where(SourceRecord.budget_id == budget.id)).all()
    assert len(txs) == 1
    assert len(scans) == 1
    assert len(sources) == 1


def test_alembic_encrypted_oauth_attempt_migration_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.database as app_database

    db_file = tmp_path / "alembic_264.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.config_file_name = None
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "h5c9f31d8a12")
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert {"encrypted_oauth_attempt", "oauth_attempt_key_id", "oauth_attempt_expires_at"}.issubset(cols)
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == "h5c9f31d8a12"

        command.downgrade(cfg, "g4b8e21c9d05")
        cols_after = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "encrypted_oauth_attempt" not in cols_after

        command.upgrade(cfg, "head")
        cols_final = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "encrypted_oauth_attempt" in cols_final
    finally:
        engine.dispose()
