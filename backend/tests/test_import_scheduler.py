"""Tests for durable import scheduler, atomic SQLite leasing, backoff, rate limits, and privacy (#257)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, inspect
from sqlmodel import SQLModel, Session, create_engine, select

from app.adapters.lidl_poc_client import (
    LidlPoCClient,
    MerchantOAuthConfiguration,
    MerchantRequestError,
)
from app.core.encryption import get_encryption_service
from app.import_scheduler import (
    ImportWorker,
    ProviderRatePolicy,
    SyncExecutionOutcome,
    assert_trusted_worker_environment,
    claim_next_job,
    compute_backoff_seconds,
    enqueue_connection_sync_job,
    is_trusted_worker_environment,
    process_claimed_job,
    recover_stale_jobs,
    release_worker_leases,
    sanitize_cursor,
    schedule_due_connections,
)
from app.models import (
    Budget,
    BudgetAlert,
    BudgetMember,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJob,
    ImportJobStatus,
    ImportProviderLimit,
    SourceRecord,
    Transaction,
    User,
)


class _FakeHttpResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class _FakeLidlSyncSession:
    """Deterministic Lidl API stub supporting refresh rotation, ticket fetch, and forced errors."""

    def __init__(
        self,
        *,
        refresh_token_secret: str,
        access_token_secret: str,
        rotated_refresh_secret: str,
        ticket_id: str = "LIDL-TICKET-9001",
        refresh_status: int = 200,
        list_status: int = 200,
        list_headers: dict[str, str] | None = None,
    ) -> None:
        self.refresh_token_secret = refresh_token_secret
        self.access_token_secret = access_token_secret
        self.rotated_refresh_secret = rotated_refresh_secret
        self.ticket_id = ticket_id
        self.refresh_status = refresh_status
        self.list_status = list_status
        self.list_headers = list_headers or {}

    def post(self, url: str, **kwargs: Any) -> _FakeHttpResponse:
        if self.refresh_status != 200:
            return _FakeHttpResponse(self.refresh_status, {"error": "invalid_grant"})
        return _FakeHttpResponse(
            200,
            {
                "access_token": self.access_token_secret,
                "refresh_token": self.rotated_refresh_secret,
            },
        )

    def get(self, url: str, **kwargs: Any) -> _FakeHttpResponse:
        if "/api/v2/" in url:
            if self.list_status != 200:
                return _FakeHttpResponse(
                    self.list_status,
                    {"error": "rate_limit"},
                    headers=self.list_headers,
                )
            return _FakeHttpResponse(200, {"tickets": [{"id": self.ticket_id}]})
        return _FakeHttpResponse(
            200,
            {
                "id": self.ticket_id,
                "date": "2026-11-10T14:25:00Z",
                "totalAmount": 24.50,
                "store": {"address": "ul. Testowa 1", "city": "Warszawa"},
                "itemsLine": [
                    {
                        "name": "PRIVATE_BREAD_ITEM",
                        "quantity": 1,
                        "unitPrice": "6.50",
                        "extendedAmount": "6.50",
                    },
                    {
                        "name": "PRIVATE_COFFEE_ITEM",
                        "quantity": 1,
                        "unitPrice": "18.00",
                        "extendedAmount": "18.00",
                    },
                ],
            },
        )


def _create_wal_engine(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def setup_test_encryption_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    get_encryption_service(reload_env=True)


def _seed_user_budget_and_connection(
    session: Session,
    *,
    email: str = "worker-test@example.com",
    provider: str = "lidl",
    refresh_token: str = "super-secret-refresh-token-xyz",
) -> tuple[User, Budget, ExternalReceiptConnection]:
    user = User(email=email, hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None

    budget = Budget(name="Worker Budget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    assert budget.id is not None

    session.add(BudgetMember(budget_id=budget.id, user_id=user.id, role="owner"))
    ciphertext, key_id = get_encryption_service().encrypt(refresh_token)
    conn = ExternalReceiptConnection(
        budget_id=budget.id,
        owner_user_id=user.id,
        provider=provider,
        consented_scopes="openid offline_access",
        status=ConnectionStatus.ACTIVE,
        consented_at=datetime.now(timezone.utc),
        encrypted_refresh_token=ciphertext,
        encryption_key_id=key_id,
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)
    return user, budget, conn


def test_sync_now_enqueues_durable_job_idempotently(
    client: TestClient,
    session: Session,
):
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    ciphertext, key_id = get_encryption_service().encrypt("tok-enqueue-secret")
    conn = ExternalReceiptConnection(
        budget_id=budget.id or 0,
        owner_user_id=owner.id or 0,
        provider="lidl",
        status=ConnectionStatus.ACTIVE,
        consented_at=datetime.now(timezone.utc),
        encrypted_refresh_token=ciphertext,
        encryption_key_id=key_id,
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)

    first = client.post(f"/api/connections/{conn.id}/sync-now")
    second = client.post(f"/api/connections/{conn.id}/sync-now")
    assert first.status_code == 200
    assert second.status_code == 200

    jobs = session.exec(
        select(ImportJob).where(ImportJob.connection_id == conn.id)
    ).all()
    assert len(jobs) == 1
    assert jobs[0].status == ImportJobStatus.PENDING
    assert jobs[0].attempt_count == 0
    assert jobs[0].correlation_id
    assert jobs[0].next_retry_at.tzinfo is not None

    # Disconnecting fails pending jobs cleanly so workers will not execute them
    disconnect_res = client.post(f"/api/connections/{conn.id}/disconnect")
    assert disconnect_res.status_code == 200
    session.refresh(jobs[0])
    assert jobs[0].status == ImportJobStatus.FAILED


def test_concurrent_workers_atomic_lease_prevents_double_execution(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "race.db")
    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s)
        job = enqueue_connection_sync_job(s, conn)
        assert job.id is not None

    exec_lock = threading.Lock()
    executed_workers: list[str] = []
    barrier = threading.Barrier(2)

    def slow_executor(s: Session, c: ExternalReceiptConnection, j: ImportJob) -> SyncExecutionOutcome:
        with exec_lock:
            executed_workers.append(j.lease_owner or "")
        time.sleep(0.12)
        return SyncExecutionOutcome(imported_count=1, next_cursor="page:1")

    results: list[ImportJob | None] = []

    def run_worker(worker_name: str) -> None:
        barrier.wait(timeout=5.0)
        worker = ImportWorker(
            lambda: Session(engine),
            worker_id=worker_name,
            lease_seconds=30,
            sync_executor=slow_executor,
        )
        res = worker.run_once()
        results.append(res)

    t1 = threading.Thread(target=run_worker, args=("worker-alpha",))
    t2 = threading.Thread(target=run_worker, args=("worker-beta",))
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert len(executed_workers) == 1
    assert sum(1 for r in results if r is not None) == 1
    with Session(engine) as s:
        persisted = s.get(ImportJob, job.id)
        assert persisted is not None
        assert persisted.status == ImportJobStatus.COMPLETED
        assert persisted.attempt_count == 1
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None


def test_stale_lease_recovery_after_worker_crash(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "stale.db")
    base_time = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s)
        job = enqueue_connection_sync_job(s, conn, next_retry_at=base_time, max_attempts=3)
        # Simulate crashed worker holding an expired lease
        job.status = ImportJobStatus.RUNNING
        job.lease_owner = "crashed-container-pid-999"
        job.lease_expires_at = base_time - timedelta(seconds=5)
        job.attempt_count = 1
        s.add(job)

        # Also simulate an exhausted crashed job (attempt_count == max_attempts)
        _, _, conn2 = _seed_user_budget_and_connection(
            s, email="exhausted@example.com", provider="biedronka"
        )
        exhausted = enqueue_connection_sync_job(s, conn2, next_retry_at=base_time, max_attempts=2)
        exhausted.status = ImportJobStatus.RUNNING
        exhausted.lease_owner = "crashed-container-pid-888"
        exhausted.lease_expires_at = base_time - timedelta(seconds=10)
        exhausted.attempt_count = 2
        s.add(exhausted)
        s.commit()
        assert job.id is not None
        assert exhausted.id is not None

        recovered = recover_stale_jobs(s, now=base_time)
        assert recovered == 2

        s.refresh(job)
        s.refresh(exhausted)
        assert job.status == ImportJobStatus.PENDING
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        assert job.last_error_code == ConnectionErrorCode.NETWORK_ERROR.value

        assert exhausted.status == ImportJobStatus.FAILED
        assert exhausted.completed_at is not None
        alerts = s.exec(select(BudgetAlert)).all()
        assert len(alerts) == 1

    # A healthy worker immediately claims and completes the recovered job
    worker = ImportWorker(
        lambda: Session(engine),
        worker_id="healthy-worker",
        sync_executor=lambda _s, _c, _j: SyncExecutionOutcome(imported_count=2, next_cursor="latest:99"),
    )
    completed = worker.run_once(now=base_time + timedelta(seconds=1))
    assert completed is not None
    assert completed.status == ImportJobStatus.COMPLETED
    assert completed.attempt_count == 2
    assert completed.cursor == "latest:99"


def test_transient_retry_backoff_retry_after_and_permanent_failure(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "errors.db")
    t0 = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)

    assert compute_backoff_seconds(1, base_seconds=30, max_seconds=3600) == 30
    assert compute_backoff_seconds(2, base_seconds=30, max_seconds=3600) == 60
    assert compute_backoff_seconds(3, base_seconds=30, max_seconds=3600) == 120
    assert compute_backoff_seconds(1, base_seconds=30, max_seconds=3600, retry_after_seconds=240) == 240

    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s)
        enqueue_connection_sync_job(s, conn, next_retry_at=t0, max_attempts=3)
        claimed = claim_next_job(s, worker_id="w1", now=t0)
        assert claimed is not None

        # Attempt 1: 429 RATE_LIMITED with Retry-After=180
        after_429 = process_claimed_job(
            s,
            claimed,
            worker_id="w1",
            now=t0,
            sync_executor=lambda _s, _c, _j: SyncExecutionOutcome(
                error_classification="transient",
                error_code=ConnectionErrorCode.RATE_LIMITED,
                retry_after_seconds=180,
                next_cursor="page:1",
            ),
        )
        assert after_429.status == ImportJobStatus.PENDING
        assert after_429.last_error_code == ConnectionErrorCode.RATE_LIMITED.value
        assert after_429.next_retry_at == t0 + timedelta(seconds=180)
        limit_row = s.get(ImportProviderLimit, "lidl")
        assert limit_row is not None
        assert limit_row.cooldown_until == t0 + timedelta(seconds=180)

        # Cannot be claimed before 180s cooldown elapses
        assert claim_next_job(s, worker_id="w1", now=t0 + timedelta(seconds=100)) is None

        # Attempt 2 at t0 + 185s: permanent AUTH_EXPIRED stops immediately & alerts user
        t1 = t0 + timedelta(seconds=185)
        claimed2 = claim_next_job(s, worker_id="w1", now=t1)
        assert claimed2 is not None
        failed = process_claimed_job(
            s,
            claimed2,
            worker_id="w1",
            now=t1,
            sync_executor=lambda _s, _c, _j: SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.AUTH_EXPIRED,
            ),
        )
        assert failed.status == ImportJobStatus.FAILED
        assert failed.attempt_count == 2  # Stopped immediately without hitting max_attempts=3
        assert failed.completed_at == t1
        s.refresh(conn)
        assert conn.status == ConnectionStatus.REAUTH_REQUIRED
        assert conn.last_error_code == ConnectionErrorCode.AUTH_EXPIRED.value
        assert conn.next_sync_at is None
        alerts = s.exec(select(BudgetAlert)).all()
        assert len(alerts) == 1
        assert "AUTH_EXPIRED" in alerts[0].message


def test_lidl_client_parses_retry_after_on_429():
    cfg = MerchantOAuthConfiguration(
        authorization_endpoint="https://accounts.example.test/authorize",
        token_endpoint="https://accounts.example.test/token",
        ticket_list_endpoint="https://tickets.example.test/api/v2/PL/tickets",
        ticket_detail_endpoint_template="https://tickets.example.test/api/v3/PL/tickets/{ticket_id}",
        client_id="TestClient",
        redirect_uri="http://localhost/cb",
    )
    fake_session = _FakeLidlSyncSession(
        refresh_token_secret="r1",
        access_token_secret="a1",
        rotated_refresh_secret="r2",
        list_status=429,
        list_headers={"Retry-After": "95"},
    )
    client_obj = LidlPoCClient(cfg, session=fake_session)  # type: ignore[arg-type]
    with pytest.raises(MerchantRequestError) as exc_info:
        client_obj.get_tickets_list("a1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 95


def test_per_connection_and_provider_throttling(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "throttle.db")
    t0 = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    policies = {"lidl": ProviderRatePolicy(max_concurrent=1, min_interval_seconds=10.0)}

    with Session(engine) as s:
        _, _, conn1 = _seed_user_budget_and_connection(s, email="c1@example.com")
        _, _, conn2 = _seed_user_budget_and_connection(s, email="c2@example.com")
        enqueue_connection_sync_job(s, conn1, next_retry_at=t0)
        enqueue_connection_sync_job(s, conn2, next_retry_at=t0)

        # Claiming first Lidl connection locks provider concurrency=1
        first = claim_next_job(s, worker_id="w1", now=t0, provider_policies=policies)
        assert first is not None
        assert first.connection_id == conn1.id

        # Second Lidl connection blocked while first is running
        assert claim_next_job(s, worker_id="w2", now=t0 + timedelta(seconds=1), provider_policies=policies) is None

        # Finish first job; min_interval_seconds=10 still throttles immediate dispatch until t0+10s
        process_claimed_job(
            s,
            first,
            worker_id="w1",
            now=t0 + timedelta(seconds=2),
            sync_executor=lambda _s, _c, _j: SyncExecutionOutcome(imported_count=0),
            provider_policies=policies,
        )
        assert claim_next_job(s, worker_id="w2", now=t0 + timedelta(seconds=5), provider_policies=policies) is None

        second = claim_next_job(s, worker_id="w2", now=t0 + timedelta(seconds=11), provider_policies=policies)
        assert second is not None
        assert second.connection_id == conn2.id


def test_graceful_shutdown_releases_unfinished_leases_and_finishes_loop(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "shutdown.db")
    t0 = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s)
        job = enqueue_connection_sync_job(s, conn, next_retry_at=t0)
        claimed = claim_next_job(s, worker_id="graceful-worker", now=t0)
        assert claimed is not None

        # Release active worker leases explicitly (simulating interrupted shutdown)
        released = release_worker_leases(s, worker_id="graceful-worker", now=t0 + timedelta(seconds=1))
        assert released == 1
        s.refresh(job)
        assert job.status == ImportJobStatus.PENDING
        assert job.lease_owner is None
        assert job.lease_expires_at is None

    # Async loop exits cleanly when shutdown_event is requested
    async def _run_and_stop() -> None:
        worker = ImportWorker(
            lambda: Session(engine),
            worker_id="loop-worker",
            poll_interval_seconds=0.05,
            sync_executor=lambda _s, _c, _j: SyncExecutionOutcome(imported_count=1),
        )
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.12)
        worker.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run_and_stop())
    with Session(engine) as s:
        final_job = s.get(ImportJob, job.id)
        assert final_job is not None
        assert final_job.status == ImportJobStatus.COMPLETED


def test_privacy_boundary_zero_secrets_in_db_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    refresh_secret = "PLAIN_REFRESH_TOKEN_SHOULD_NEVER_LEAK_999"
    access_secret = "PLAIN_ACCESS_TOKEN_SHOULD_NEVER_LEAK_888"
    rotated_secret = "PLAIN_ROTATED_TOKEN_SHOULD_NEVER_LEAK_777"

    # Untrusted VPS role must refuse running credential-bearing workers
    assert is_trusted_worker_environment("trusted_local") is True
    assert is_trusted_worker_environment("central_vps") is False
    with pytest.raises(RuntimeError):
        assert_trusted_worker_environment("central_vps")

    # Cursor rejects token / secret payloads
    with pytest.raises(ValueError):
        sanitize_cursor("access_token=abc")
    with pytest.raises(ValueError):
        sanitize_cursor("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb")
    assert sanitize_cursor("latest:LIDL-TICKET-9001") == "latest:LIDL-TICKET-9001"

    engine = _create_wal_engine(tmp_path / "privacy.db")
    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s, refresh_token=refresh_secret)
        enqueue_connection_sync_job(s, conn)

    cfg = MerchantOAuthConfiguration(
        authorization_endpoint="https://accounts.example.test/authorize",
        token_endpoint="https://accounts.example.test/token",
        ticket_list_endpoint="https://tickets.example.test/api/v2/PL/tickets",
        ticket_detail_endpoint_template="https://tickets.example.test/api/v3/PL/tickets/{ticket_id}",
        client_id="TestClient",
        redirect_uri="http://localhost/cb",
    )
    fake_client = LidlPoCClient(
        cfg,
        session=_FakeLidlSyncSession(  # type: ignore[arg-type]
            refresh_token_secret=refresh_secret,
            access_token_secret=access_secret,
            rotated_refresh_secret=rotated_secret,
        ),
    )

    from app.connection_service import ConnectionService

    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_client)

    caplog.set_level(logging.INFO)
    worker = ImportWorker(lambda: Session(engine), worker_id="privacy-worker")
    completed = worker.run_once()
    assert completed is not None
    assert completed.status == ImportJobStatus.COMPLETED

    # Verify idempotent ingest + schedule_due_connections next run
    with Session(engine) as s:
        txs = s.exec(select(Transaction)).all()
        srs = s.exec(select(SourceRecord)).all()
        assert len(txs) == 1
        assert len(srs) == 1
        conn_row = s.exec(select(ExternalReceiptConnection)).one()
        assert conn_row.last_success_at is not None
        assert conn_row.next_sync_at is not None
        # Token rotated cleanly to new encrypted value
        decrypted_after = ConnectionService.get_decrypted_token(s, conn_row)
        assert decrypted_after == rotated_secret

        # Audit logs contain correlation ID and ZERO secrets or raw receipt line items
        log_dump = "\n".join(rec.getMessage() for rec in caplog.records)
        assert completed.correlation_id in log_dump
        for forbidden in (
            refresh_secret,
            access_secret,
            rotated_secret,
            "PRIVATE_BREAD_ITEM",
            "PRIVATE_COFFEE_ITEM",
            "24.50",
        ):
            assert forbidden not in log_dump

        # Audit import_jobs row contains ZERO secrets or receipt text
        job_row = s.get(ImportJob, completed.id)
        assert job_row is not None
        job_text = f"{job_row.cursor} {job_row.last_error_code} {job_row.correlation_id}"
        for forbidden in (
            refresh_secret,
            access_secret,
            rotated_secret,
            "PRIVATE_BREAD_ITEM",
            "PRIVATE_COFFEE_ITEM",
        ):
            assert forbidden not in job_text

        # Scheduling due connection later re-enqueues cleanly without duplicating transactions
        future = conn_row.next_sync_at + timedelta(seconds=5)
        scheduled = schedule_due_connections(s, now=future)
        assert len(scheduled) == 1

    rerun = worker.run_once(now=future + timedelta(seconds=1))
    assert rerun is not None
    assert rerun.status == ImportJobStatus.COMPLETED
    with Session(engine) as s:
        assert len(s.exec(select(Transaction)).all()) == 1
        assert len(s.exec(select(SourceRecord)).all()) == 1


def test_alembic_import_jobs_migration_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.database as app_database

    db_path = tmp_path / "import_jobs_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "e9a1c3d5f702")
    engine = create_engine(db_url)
    insp_pre = inspect(engine)
    assert "import_jobs" not in insp_pre.get_table_names()

    command.upgrade(alembic_cfg, "head")
    insp_up = inspect(engine)
    tables_up = insp_up.get_table_names()
    assert "import_jobs" in tables_up
    assert "import_provider_limits" in tables_up
    indexes = {idx["name"] for idx in insp_up.get_indexes("import_jobs")}
    assert "uq_import_jobs_active_connection_type" in indexes
    assert "ix_import_jobs_claimable" in indexes

    command.downgrade(alembic_cfg, "e9a1c3d5f702")
    insp_down = inspect(engine)
    tables_down = insp_down.get_table_names()
    assert "import_jobs" not in tables_down
    assert "import_provider_limits" not in tables_down

    command.upgrade(alembic_cfg, "head")
    insp_reup = inspect(engine)
    assert "import_jobs" in insp_reup.get_table_names()


def test_complete_authorization_initializes_schedule_and_live_sync_preserves_it(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.connection_service import ConnectionService
    from app.models import ExternalReceiptConnectionCreate

    user, budget, _ = _seed_user_budget_and_connection(
        session, email="auth-sched@example.com", provider="other"
    )
    # Create a fresh placeholder connection and complete authorization via service
    created_dto = ConnectionService.create_connection(
        session, budget.id or 0, user, ExternalReceiptConnectionCreate(provider="biedronka")
    )
    conn = session.get(ExternalReceiptConnection, created_dto.id)
    assert conn is not None

    auth_dto = ConnectionService.complete_authorization(
        session,
        conn,
        refresh_token="fresh-auth-token",
        consented_scopes="openid offline_access",
    )
    assert auth_dto.next_sync_at is not None
    jobs = session.exec(select(ImportJob).where(ImportJob.connection_id == conn.id)).all()
    assert len(jobs) == 1
    assert jobs[0].status == ImportJobStatus.PENDING

    # Live sync success on Lidl keeps a scheduled next_sync_at and completes pending job
    lidl_dto = ConnectionService.create_connection(
        session, budget.id or 0, user, ExternalReceiptConnectionCreate(provider="lidl")
    )
    lidl_conn = session.get(ExternalReceiptConnection, lidl_dto.id)
    assert lidl_conn is not None
    ConnectionService.complete_authorization(
        session, lidl_conn, refresh_token="lidl-tok", consented_scopes="openid"
    )
    cfg = MerchantOAuthConfiguration(
        authorization_endpoint="https://accounts.example.test/authorize",
        token_endpoint="https://accounts.example.test/token",
        ticket_list_endpoint="https://tickets.example.test/api/v2/PL/tickets",
        ticket_detail_endpoint_template="https://tickets.example.test/api/v3/PL/tickets/{ticket_id}",
        client_id="TestClient",
        redirect_uri="http://localhost/cb",
    )
    fake_client = LidlPoCClient(
        cfg,
        session=_FakeLidlSyncSession(  # type: ignore[arg-type]
            refresh_token_secret="lidl-tok",
            access_token_secret="acc-tok",
            rotated_refresh_secret="lidl-tok-2",
        ),
    )
    monkeypatch.setattr("app.connection_service.LidlPoCClient", lambda *_a, **_kw: fake_client)

    ConnectionService.trigger_sync_now(
        session,
        budget.id or 0,
        lidl_conn.id or 0,
        user,
        execute_live=True,
        client_override=fake_client,
    )
    session.refresh(lidl_conn)
    assert lidl_conn.last_success_at is not None
    assert lidl_conn.next_sync_at is not None
    assert lidl_conn.next_sync_at > lidl_conn.last_success_at
    lidl_job = session.exec(select(ImportJob).where(ImportJob.connection_id == lidl_conn.id)).one()
    assert lidl_job.status == ImportJobStatus.COMPLETED
    assert lidl_job.cursor == "latest:LIDL-TICKET-9001"


def test_manual_sync_now_expedites_backed_off_pending_job(
    client: TestClient,
    session: Session,
):
    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    ciphertext, key_id = get_encryption_service().encrypt("tok-expedite")
    conn = ExternalReceiptConnection(
        budget_id=budget.id or 0,
        owner_user_id=owner.id or 0,
        provider="lidl",
        status=ConnectionStatus.SYNC_ERROR,
        consented_at=datetime.now(timezone.utc),
        encrypted_refresh_token=ciphertext,
        encryption_key_id=key_id,
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)

    far_future = datetime.now(timezone.utc) + timedelta(hours=2)
    backed_off = enqueue_connection_sync_job(session, conn, next_retry_at=far_future)
    assert backed_off.next_retry_at > datetime.now(timezone.utc) + timedelta(hours=1)

    res = client.post(f"/api/connections/{conn.id}/sync-now")
    assert res.status_code == 200
    session.refresh(backed_off)
    assert backed_off.next_retry_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_head_of_line_cooldown_does_not_starve_other_providers(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "hol.db")
    t0 = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        # Enqueue >25 Lidl jobs (exceeding batch limit=25) plus one biedronka job later
        for idx in range(30):
            _, _, conn = _seed_user_budget_and_connection(
                s, email=f"lidl-{idx}@example.com", provider="lidl"
            )
            enqueue_connection_sync_job(s, conn, next_retry_at=t0 - timedelta(minutes=30 - idx))

        _, _, biedronka_conn = _seed_user_budget_and_connection(
            s, email="biedronka@example.com", provider="biedronka"
        )
        biedronka_job = enqueue_connection_sync_job(s, biedronka_conn, next_retry_at=t0)

        # Put lidl in cooldown for 10 minutes
        s.add(
            ImportProviderLimit(
                provider="lidl",
                cooldown_until=t0 + timedelta(minutes=10),
                last_dispatched_at=t0 - timedelta(seconds=5),
                updated_at=t0,
            )
        )
        s.commit()

        claimed = claim_next_job(s, worker_id="hol-worker", now=t0)
        assert claimed is not None
        assert claimed.id == biedronka_job.id
        assert claimed.provider == "biedronka"


def test_concurrent_provider_limit_race_refreshes_counts_and_atomic_upsert(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "provider_race.db")
    t0 = datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)
    with Session(engine) as s:
        _, _, conn1 = _seed_user_budget_and_connection(s, email="p1@example.com", provider="lidl")
        _, _, conn2 = _seed_user_budget_and_connection(s, email="p2@example.com", provider="lidl")
        enqueue_connection_sync_job(s, conn1, next_retry_at=t0)
        enqueue_connection_sync_job(s, conn2, next_retry_at=t0)

    policies = {"lidl": ProviderRatePolicy(max_concurrent=1, min_interval_seconds=0.0)}
    barrier = threading.Barrier(2)
    claimed_ids: list[int] = []
    claim_lock = threading.Lock()

    def race_claim(worker_name: str) -> None:
        barrier.wait(timeout=5.0)
        with Session(engine) as ws:
            job = claim_next_job(
                ws,
                worker_id=worker_name,
                lease_seconds=30,
                now=t0,
                provider_policies=policies,
            )
            if job is not None and job.id is not None:
                with claim_lock:
                    claimed_ids.append(job.id)

    th1 = threading.Thread(target=race_claim, args=("race-w1",))
    th2 = threading.Thread(target=race_claim, args=("race-w2",))
    th1.start()
    th2.start()
    th1.join(timeout=10.0)
    th2.join(timeout=10.0)

    # Strictly one job claimed when provider max_concurrent=1 and zero IntegrityError on upsert
    assert len(claimed_ids) == 1


def test_lease_heartbeat_extends_long_running_job_past_lease_seconds(tmp_path: Path):
    engine = _create_wal_engine(tmp_path / "heartbeat.db")
    with Session(engine) as s:
        _, _, conn = _seed_user_budget_and_connection(s, email="hb@example.com")
        job = enqueue_connection_sync_job(s, conn)
        assert job.id is not None

    recovered_during_run: list[int] = []

    def long_executor(_s: Session, _c: ExternalReceiptConnection, j: ImportJob) -> SyncExecutionOutcome:
        time.sleep(1.3)
        # Mid-flight stale recovery must NOT touch this job because heartbeat extended its lease
        with Session(engine) as check_s:
            recovered_during_run.append(recover_stale_jobs(check_s))
        return SyncExecutionOutcome(imported_count=1)

    worker = ImportWorker(
        lambda: Session(engine),
        worker_id="hb-worker",
        lease_seconds=1,
        heartbeat_interval_seconds=0.25,
        sync_executor=long_executor,
    )
    finished = worker.run_once()
    assert finished is not None
    assert finished.status == ImportJobStatus.COMPLETED
    assert recovered_during_run == [0]


def test_reconnect_cancels_pending_jobs_and_cursor_stops_at_known_latest(
    client: TestClient,
    session: Session,
):
    from unittest.mock import Mock
    from app.connection_service import ConnectionService

    budget = next(iter(session.exec(select(Budget))))
    owner = session.get(User, budget.owner_id)
    assert owner is not None
    ciphertext, key_id = get_encryption_service().encrypt("tok-reconnect")
    conn = ExternalReceiptConnection(
        budget_id=budget.id or 0,
        owner_user_id=owner.id or 0,
        provider="lidl",
        status=ConnectionStatus.ACTIVE,
        consented_at=datetime.now(timezone.utc),
        encrypted_refresh_token=ciphertext,
        encryption_key_id=key_id,
        next_sync_at=datetime.now(timezone.utc),
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)

    # Known cursor stops detail fetching on known top ticket without requesting older tickets
    mock_client = Mock()
    mock_client.refresh_access_token.return_value = {"access_token": "acc"}
    mock_client.get_tickets_list.return_value = {
        "tickets": [{"id": "T-102"}, {"id": "T-101"}, {"id": "T-100"}]
    }
    mock_client.get_ticket_detail.return_value = {
        "id": "T-102",
        "date": "2026-11-14T10:00:00Z",
        "totalAmount": 12.00,
        "store": {"address": "ul. Demo 1", "city": "Warszawa"},
        "itemsLine": [
            {"name": "Milk", "quantity": 1, "unitPrice": "12.00", "extendedAmount": "12.00"}
        ],
    }
    job = enqueue_connection_sync_job(session, conn, cursor="latest:T-101")
    outcome = ConnectionService.execute_connection_sync(
        session, conn, job=job, client_override=mock_client
    )
    assert outcome.imported_count == 1
    assert outcome.next_cursor == "latest:T-102"
    assert mock_client.get_ticket_detail.call_count == 1
    mock_client.get_ticket_detail.assert_called_once_with("acc", "T-102")

    # Reconnect cancels active pending job so worker will not emit a redundant BudgetAlert
    reconn_res = client.post(f"/api/connections/{conn.id}/reconnect")
    assert reconn_res.status_code == 200
    session.refresh(job)
    session.refresh(conn)
    assert job.status == ImportJobStatus.FAILED
    assert job.last_error_code == ConnectionErrorCode.REAUTH_REQUIRED.value
    assert conn.next_sync_at is None
    assert session.exec(select(BudgetAlert)).all() == []


def test_settings_import_worker_disabled_under_pytest_and_overrideable(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.config import settings

    assert settings.is_import_worker_enabled() is False
    monkeypatch.setenv("IMPORT_WORKER_ENABLED", "true")
    assert settings.is_import_worker_enabled() is True
    monkeypatch.setattr(settings, "IMPORT_WORKER_ENABLED", False)
    assert settings.is_import_worker_enabled() is False

