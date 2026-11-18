"""Regression & feature tests for #260: Lidl Plus pilot vertical slice.

Covers:
- Multi-page initial sync and incremental cursor stop/checkpointing
- Duplicate ticket ID deduplication and zero-duplicate retries
- Full UTC purchase timestamp preservation and basket couponsUsed reconciliation
- Explicit user-visible states & BudgetAlerts for AUTH_EXPIRED, MFA_REQUIRED,
  RATE_LIMITED, and PROVIDER_SCHEMA_CHANGED without overwriting partial errors
- Independent connector disablement (LIDL_CONNECTOR_ENABLED=false + per-connection
  is_enabled pause/resume) without breaking manual receipt uploads
- Alembic migration roundtrip for external_receipt_connection.is_enabled
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, select

from app.adapters.lidl_poc_client import (
    MOCK_LIDL_V3_TICKET,
    LidlPoCClient,
    get_lidl_live_config,
    lidl_ticket_to_canonical,
)
from app.auth import get_current_user
from app.config import settings
from app.connection_service import ConnectionService
from app.core.encryption import get_encryption_service
from app.import_scheduler import (
    ImportWorker,
    ProviderRatePolicy,
    enqueue_connection_sync_job,
    schedule_due_connections,
)
from app.ingestion_service import ingest_receipt_result
from app.adapters.receipt_adapters import LidlPlusReceiptAdapter
from app.main import app
from app.models import (
    Budget,
    BudgetAlert,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJob,
    ImportJobStatus,
    RawPayloadPolicy,
    SourceRecord,
    Transaction,
    User,
)


@pytest.fixture(autouse=True)
def setup_260_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    monkeypatch.setenv("IMPORT_WORKER_ROLE", "trusted_local")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("LIDL_CONNECTOR_ENABLED", "true")
    monkeypatch.setenv("LIDL_SYNC_MAX_PAGES", "5")
    monkeypatch.setenv("LIDL_SYNC_MAX_TICKETS", "50")
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "IMPORT_WORKER_ROLE", "trusted_local")
    monkeypatch.setattr(settings, "LIDL_CONNECTOR_ENABLED", None)
    monkeypatch.setattr(settings, "LIDL_SYNC_MAX_PAGES", settings._initial_lidl_sync_max_pages)
    monkeypatch.setattr(settings, "LIDL_SYNC_MAX_TICKETS", settings._initial_lidl_sync_max_tickets)
    get_encryption_service(reload_env=True)


class _Resp:
    def __init__(
        self,
        status_code: int,
        payload: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _seed_active_lidl_connection(client: TestClient, session: Session) -> tuple[Budget, User, ExternalReceiptConnection]:
    budget = session.exec(select(Budget)).one()
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    res = client.post("/api/connections", json={"provider": "lidl"})
    assert res.status_code == 200
    conn_id = res.json()["id"]
    conn = session.get(ExternalReceiptConnection, conn_id)
    assert conn is not None
    ConnectionService.complete_authorization(
        session, conn, refresh_token="seed-refresh-token", consented_scopes="openid offline_access"
    )
    session.refresh(conn)
    return budget, owner, conn


def test_lidl_timestamp_preservation_and_basket_coupons_mapping(
    client: TestClient,
    session: Session,
):
    budget, owner, conn = _seed_active_lidl_connection(client, session)

    # 1. Ticket with explicit purchase time + basket-level coupon not in itemsLine
    ticket_with_coupon = {
        "id": "tkt-coupon-01",
        "date": "2026-11-10T17:45:30+01:00",
        "storeCode": "PL0422",
        "totalAmount": "12.00",
        "itemsLine": [
            {"name": "Mleko 3.2%", "quantity": "2", "currentUnitPrice": "7.50", "discounts": []},
        ],
        "couponsUsed": [
            {"title": "Lidl Plus 3 PLN", "discountAmount": "3.00"},
        ],
    }
    res = LidlPlusReceiptAdapter().extract(
        ticket_with_coupon,
        budget_id=budget.id or 0,
        connection_id=conn.id,
        ticket_id="tkt-coupon-01",
    )
    assert res.provenance.raw_payload_policy == RawPayloadPolicy.CANONICAL_ONLY
    assert res.validation_status == "verified"
    assert res.receipt.date == "2026-11-10"
    assert res.receipt["purchase_timestamp"] == "2026-11-10T16:45:30+00:00"
    assert len(res.receipt.items) == 2
    assert res.receipt.items[1].is_adjustment is True
    assert res.receipt.items[1].final_line_total == Decimal("-3.00")

    outcome = ingest_receipt_result(
        session,
        res,
        budget_id=budget.id or 0,
        user_id=owner.id or 0,
        categorize=False,
    )
    assert outcome.imported is True
    tx = session.get(Transaction, outcome.transaction_id)
    assert tx is not None and tx.date is not None
    assert tx.date.hour == 16 and tx.date.minute == 45 and tx.date.second == 30

    # 2. Ticket where coupon discount is already reflected inside itemsLine -> do not double count
    ticket_already_discounted = {
        "id": "tkt-coupon-02",
        "date": "2026-11-11T10:15:00Z",
        "storeCode": "PL0422",
        "totalAmount": "12.00",
        "itemsLine": [
            {
                "name": "Mleko 3.2%",
                "quantity": "2",
                "currentUnitPrice": "7.50",
                "discounts": [{"amount": "3.00"}],
            },
        ],
        "couponsUsed": [
            {"title": "Lidl Plus 3 PLN", "discountAmount": "3.00"},
        ],
    }
    canonical2 = lidl_ticket_to_canonical(ticket_already_discounted)
    assert canonical2["validation_status"] == "verified"
    assert canonical2.calculated_total == Decimal("12.00")
    assert len(canonical2.items) == 1


def test_multipage_initial_sync_incremental_cursor_and_batch_dedup(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    budget, owner, conn = _seed_active_lidl_connection(client, session)

    pages: dict[int, dict[str, Any]] = {
        1: {"tickets": [{"id": "tkt-04"}, {"id": "tkt-03"}], "totalCount": 4, "size": 2},
        2: {"tickets": [{"id": "tkt-02"}, {"id": "tkt-01"}], "totalCount": 4, "size": 2},
    }
    detail_calls: list[str] = []

    class _PagedHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(200, {"access_token": "acc-1", "refresh_token": "ref-2"})

        def get(self, url: str, **kwargs: Any) -> _Resp:
            if "/api/v2/" in url:
                page = 1 if "pageNumber=1" in url else 2
                return _Resp(200, pages[page])
            tid = url.rsplit("/", 1)[-1]
            detail_calls.append(tid)
            payload = dict(MOCK_LIDL_V3_TICKET)
            payload["id"] = tid
            payload["date"] = "2026-11-12T12:00:00Z"
            return _Resp(200, payload)

    fake_client = LidlPoCClient(get_lidl_live_config(), session=_PagedHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_client)

    # Initial sync via durable worker fetches both pages (4 tickets)
    enqueue_connection_sync_job(session, conn, next_retry_at=datetime.now(timezone.utc))
    worker = ImportWorker(
        lambda: Session(session.get_bind()),
        worker_id="w-260-pages",
        provider_policies={"lidl": ProviderRatePolicy(max_concurrent=1, min_interval_seconds=0.0)},
    )
    job1 = worker.run_once()
    assert job1 is not None and job1.status == ImportJobStatus.COMPLETED
    assert job1.cursor == "latest:tkt-04"
    assert detail_calls == ["tkt-04", "tkt-03", "tkt-02", "tkt-01"]
    assert len(session.exec(select(SourceRecord).where(SourceRecord.budget_id == budget.id)).all()) == 4

    # Incremental sync: provider returns duplicate tkt-05 in batch and stops at known_latest tkt-04
    detail_calls.clear()
    pages[1] = {
        "tickets": [{"id": "tkt-05"}, {"id": "tkt-05"}, {"id": "tkt-04"}, {"id": "tkt-03"}],
        "totalCount": 5,
        "size": 4,
    }
    enqueue_connection_sync_job(session, conn, next_retry_at=datetime.now(timezone.utc))
    job2 = worker.run_once()
    assert job2 is not None and job2.status == ImportJobStatus.COMPLETED
    assert job2.cursor == "latest:tkt-05"
    assert detail_calls == ["tkt-05"]
    assert len(session.exec(select(Transaction).where(Transaction.budget_id == budget.id)).all()) == 5


def test_partial_errors_preserve_cursor_and_surface_mfa_rate_limit_schema_change(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    budget, owner, conn = _seed_active_lidl_connection(client, session)

    # 1. MFA challenge from OAuth callback query parameter
    start_res = client.post(f"/api/connections/{conn.id}/oauth/start")
    assert start_res.status_code == 200
    mfa_cb = client.post(
        f"/api/connections/{conn.id}/oauth/callback",
        json={"callback_url_or_code": "com.lidlplus.app://callback?error=interaction_required"},
    )
    assert mfa_cb.status_code == 400
    session.refresh(conn)
    assert conn.status == ConnectionStatus.REAUTH_REQUIRED
    assert conn.last_error_code == ConnectionErrorCode.MFA_REQUIRED.value

    # Re-activate for sync error scenarios
    ConnectionService.complete_authorization(
        session, conn, refresh_token="tok-ok", consented_scopes="openid"
    )

    # 2. Schema drift failure on ticket #2 preserves PROVIDER_SCHEMA_CHANGED & leaves cursor intact
    class _SchemaDriftHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(200, {"access_token": "acc-1", "refresh_token": "tok-2"})

        def get(self, url: str, **kwargs: Any) -> _Resp:
            if "/api/v2/" in url:
                return _Resp(200, {"tickets": [{"id": "tkt-broken"}, {"id": "tkt-good"}]})
            if url.endswith("/tkt-broken"):
                return _Resp(200, {"id": "tkt-broken", "unexpectedShape": True})
            payload = dict(MOCK_LIDL_V3_TICKET)
            payload["id"] = "tkt-good"
            return _Resp(200, payload)

    fake_schema = LidlPoCClient(get_lidl_live_config(), session=_SchemaDriftHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_schema)

    sync_res = client.post(f"/api/connections/{conn.id}/sync-now?live=true")
    assert sync_res.status_code == 200
    body = sync_res.json()
    assert body["imported_count"] == 1
    assert body["failed_count"] == 1
    assert body["status"] == ConnectionStatus.SYNC_ERROR.value

    session.refresh(conn)
    assert conn.last_error_code == ConnectionErrorCode.PROVIDER_SCHEMA_CHANGED.value

    # 3. Rate limit HTTP 429 aborts loop immediately and sets RATE_LIMITED + BudgetAlert on worker permanent fail
    get_calls: list[str] = []

    class _RateLimitHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(200, {"access_token": "acc-1", "refresh_token": "tok-3"})

        def get(self, url: str, **kwargs: Any) -> _Resp:
            get_calls.append(url)
            if "/api/v2/" in url:
                return _Resp(200, {"tickets": [{"id": "tkt-1"}, {"id": "tkt-2"}, {"id": "tkt-3"}]})
            if url.endswith("/tkt-2"):
                return _Resp(429, {"error": "too_many_requests"}, headers={"Retry-After": "45"})
            payload = dict(MOCK_LIDL_V3_TICKET)
            payload["id"] = "tkt-1"
            return _Resp(200, payload)

    fake_rl = LidlPoCClient(get_lidl_live_config(), session=_RateLimitHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_rl)

    # Cancel any pending jobs from complete_authorization before creating a max_attempts=1 job
    for j in session.exec(select(ImportJob)).all():
        j.status = ImportJobStatus.COMPLETED
        session.add(j)
    session.commit()

    rl_job = enqueue_connection_sync_job(
        session, conn, max_attempts=1, next_retry_at=datetime.now(timezone.utc)
    )
    worker = ImportWorker(
        lambda: Session(session.get_bind()),
        worker_id="w-260-rl",
        provider_policies={"lidl": ProviderRatePolicy(max_concurrent=1, min_interval_seconds=0.0)},
    )
    finished_rl = worker.run_once()
    assert finished_rl is not None and finished_rl.id == rl_job.id
    assert finished_rl.status == ImportJobStatus.FAILED
    assert finished_rl.last_error_code == ConnectionErrorCode.RATE_LIMITED.value
    # tkt-3 was never requested because 429 aborted the batch immediately
    assert not any(u.endswith("/tkt-3") for u in get_calls)

    session.refresh(conn)
    assert conn.status == ConnectionStatus.SYNC_ERROR
    assert conn.last_error_code == ConnectionErrorCode.RATE_LIMITED.value
    alerts = session.exec(select(BudgetAlert).where(BudgetAlert.budget_id == budget.id)).all()
    assert any("rate-limited" in a.message.lower() for a in alerts)

    # 4. Token refresh MFA error classifies into REAUTH_REQUIRED + MFA_REQUIRED
    class _MfaRefreshHttp:
        def post(self, url: str, **kwargs: Any) -> _Resp:
            return _Resp(403, {"error": "mfa_required", "secret_ignore": "do-not-leak"})

    fake_mfa = LidlPoCClient(get_lidl_live_config(), session=_MfaRefreshHttp())  # type: ignore[arg-type]
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_mfa)
    mfa_job = enqueue_connection_sync_job(
        session, conn, max_attempts=1, next_retry_at=datetime.now(timezone.utc)
    )
    finished_mfa = worker.run_once()
    assert finished_mfa is not None and finished_mfa.id == mfa_job.id
    assert finished_mfa.status == ImportJobStatus.FAILED
    assert finished_mfa.last_error_code == ConnectionErrorCode.MFA_REQUIRED.value
    session.refresh(conn)
    assert conn.status == ConnectionStatus.REAUTH_REQUIRED
    assert conn.last_error_code == ConnectionErrorCode.MFA_REQUIRED.value

    # 5. Live sync 502 error on refresh clears sync_requested_at and next_sync_at
    ConnectionService.complete_authorization(
        session, conn, refresh_token="tok-ok-5", consented_scopes="openid"
    )
    fail_sync_res = client.post(f"/api/connections/{conn.id}/sync-now?live=true")
    assert fail_sync_res.status_code == 502
    session.refresh(conn)
    assert conn.status == ConnectionStatus.REAUTH_REQUIRED
    assert conn.last_error_code == ConnectionErrorCode.MFA_REQUIRED.value
    assert conn.sync_requested_at is None
    assert conn.next_sync_at is None


def test_independent_disablement_and_manual_eparagon_upload_preserved(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.api as app_api

    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(app_api, "operations_engine", session.bind)

    budget, owner, conn = _seed_active_lidl_connection(client, session)
    app.dependency_overrides[get_current_user] = lambda: owner

    # 1. Per-connection pause keeps encrypted token and cancels pending jobs
    pause_res = client.patch(f"/api/connections/{conn.id}/enabled", json={"enabled": False})
    assert pause_res.status_code == 200
    assert pause_res.json()["is_enabled"] is False
    assert pause_res.json()["has_token"] is True

    session.refresh(conn)
    assert conn.is_enabled is False
    assert conn.encrypted_refresh_token is not None
    assert client.post(f"/api/connections/{conn.id}/sync-now?live=true").status_code == 409
    assert schedule_due_connections(session, now=datetime.now(timezone.utc) + timedelta(days=1)) == []

    # Resume restores scheduling capability
    resume_res = client.patch(f"/api/connections/{conn.id}/enabled", json={"enabled": True})
    assert resume_res.status_code == 200
    assert resume_res.json()["is_enabled"] is True

    # 2. Global LIDL_CONNECTOR_ENABLED=false fails closed on Lidl routes without touching manual scan
    monkeypatch.setenv("LIDL_CONNECTOR_ENABLED", "false")
    cfg_res = client.get("/api/config")
    assert cfg_res.status_code == 200
    assert cfg_res.json()["lidl_connector_enabled"] is False

    assert client.post(f"/api/connections/{conn.id}/oauth/start").status_code == 503
    assert client.post(
        f"/api/connections/{conn.id}/oauth/callback",
        json={"callback_url_or_code": "com.lidlplus.app://callback?code=c&state=s"},
    ).status_code == 503
    assert client.post(f"/api/connections/{conn.id}/oauth/desktop-login").status_code == 503
    assert client.post(f"/api/connections/{conn.id}/sync-now?live=true").status_code == 503
    assert schedule_due_connections(session, now=datetime.now(timezone.utc) + timedelta(days=1)) == []

    # Manual e-Paragon JSON upload still works normally with Lidl connector disabled
    fixture_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "conformance"
        / "eparagon"
        / "success.json"
    )
    scan_res = client.post(
        "/api/transactions/scan",
        files={
            "file": (
                "manual_eparagon.json",
                fixture_path.read_bytes(),
                "application/json",
            )
        },
    )
    assert scan_res.status_code == 200


def test_alembic_connection_is_enabled_migration_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.database as app_database

    db_file = tmp_path / "alembic_260.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.config_file_name = None
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "h5c9f31d8a12")
    engine = create_engine(db_url)
    try:
        cols_pre = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "is_enabled" not in cols_pre

        command.upgrade(cfg, "head")
        cols_up = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "is_enabled" in cols_up
        with engine.connect() as db_conn:
            ver = db_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == "j7e1b42a9c03"

        command.downgrade(cfg, "h5c9f31d8a12")
        cols_down = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "is_enabled" not in cols_down

        command.upgrade(cfg, "head")
        cols_final = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "is_enabled" in cols_final
    finally:
        engine.dispose()
