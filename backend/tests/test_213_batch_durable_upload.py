"""Comprehensive integration & migration tests for Batch Document Upload & Durable Jobs (#213)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

import app.api as app_api
from app.auth import get_current_user
from app.main import app
from app.config import settings
from app.import_scheduler import (
    DEFAULT_JOB_TYPE,
    DOCUMENT_JOB_TYPE,
    ImportWorker,
    enqueue_connection_sync_job,
    process_claimed_job,
    recover_stale_jobs,
)
from app.models import (
    Account,
    Budget,
    BudgetMember,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJob,
    ImportJobStatus,
    ReceiptScan,
    ReviewStatus,
    ScanStatus,
    Transaction,
    User,
)


def _get_user_budget(session: Session) -> tuple[User, Budget]:
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user is not None and user.id is not None
    assert budget is not None and budget.id is not None
    return user, budget


def _jpeg_bytes(tag: bytes = b"1") -> bytes:
    return b"\xff\xd8\xff\xe0" + tag + b"-mock-jpeg-receipt-payload"


def _pdf_bytes(tag: bytes = b"1") -> bytes:
    return b"%PDF-1.4\n%MockReceipt-" + tag + b"\n%%EOF"


def test_alembic_213_import_jobs_document_migration_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.database as app_database

    db_path = tmp_path / "migration_213.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "k8f2c53b0d14")
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(db_url)

    inspector = inspect(engine)
    cols = {c["name"]: c for c in inspector.get_columns("import_jobs")}
    assert cols["connection_id"]["nullable"] is True
    for expected in ("transaction_id", "receipt_scan_id", "import_batch_id", "source_filename"):
        assert expected in cols
    idx_names = {idx["name"] for idx in inspector.get_indexes("import_jobs")}
    assert "uq_import_jobs_active_scan_type" in idx_names
    assert "ix_import_jobs_batch_status" in idx_names

    command.downgrade(alembic_cfg, "k8f2c53b0d14")
    inspector_down = inspect(engine)
    cols_down = {c["name"]: c for c in inspector_down.get_columns("import_jobs")}
    assert cols_down["connection_id"]["nullable"] is False
    assert "receipt_scan_id" not in cols_down

    command.upgrade(alembic_cfg, "head")
    inspector_reup = inspect(engine)
    cols_reup = {c["name"]: c for c in inspector_reup.get_columns("import_jobs")}
    assert cols_reup["connection_id"]["nullable"] is True
    assert "receipt_scan_id" in cols_reup


def test_batch_upload_isolates_invalid_and_duplicate_files_and_tracks_jobs(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, budget = _get_user_budget(session)
    assert budget.id is not None
    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))

    acc = Account(name="Konto Domowe", type="checking", currency="PLN", budget_id=budget.id)
    session.add(acc)
    session.commit()
    session.refresh(acc)
    assert acc.id is not None

    jpg_1 = _jpeg_bytes(b"first-shop")
    bad_html_as_jpg = b"<!DOCTYPE html><html><body>not a receipt</body></html>"
    pdf_2 = _pdf_bytes(b"second-shop")

    res = client.post(
        "/api/transactions/scan-batch",
        data={"account_id": str(acc.id), "auto_merge_policy": "manual"},
        files=[
            ("files", ("paragon_1.jpg", jpg_1, "image/jpeg")),
            ("files", ("evil.jpg", bad_html_as_jpg, "image/jpeg")),
            ("files", ("paragon_1_copy.jpg", jpg_1, "image/jpeg")),
            ("files", ("faktura_2.pdf", pdf_2, "application/pdf")),
        ],
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total_files"] == 4
    assert payload["queued_count"] == 2
    assert payload["failed_count"] == 1
    assert payload["duplicate_count"] == 1
    assert payload["rate_limited_count"] == 0

    by_name = {item["filename"]: item for item in payload["results"]}
    assert by_name["paragon_1.jpg"]["status"] == "queued"
    assert by_name["evil.jpg"]["status"] == "rejected"
    assert by_name["evil.jpg"]["error_code"] == "INVALID_FILE_SIGNATURE"
    assert by_name["paragon_1_copy.jpg"]["status"] == "duplicate"
    assert by_name["faktura_2.pdf"]["status"] == "queued"

    batch_id = payload["import_batch_id"]
    jobs_res = client.get(f"/api/import-jobs?import_batch_id={batch_id}")
    assert jobs_res.status_code == 200
    jobs = jobs_res.json()
    assert len(jobs) == 2
    assert all(j["status"] == "pending" for j in jobs)
    assert all(j["job_type"] == DOCUMENT_JOB_TYPE for j in jobs)
    assert all(j["import_batch_id"] == batch_id for j in jobs)

    # Check inbox transaction embeds its durable import_job
    inbox_res = client.get("/api/transactions/inbox?tab=exceptions")
    assert inbox_res.status_code == 200
    inbox_items = inbox_res.json()
    assert len(inbox_items) == 2
    assert all(item["import_job"] is not None for item in inbox_items)
    assert all(item["import_job"]["import_batch_id"] == batch_id for item in inbox_items)


def test_document_worker_runs_in_untrusted_role_while_connection_sync_stays_blocked(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "worker_boundary.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        user = User(email="worker-test@example.com", hashed_password="x")
        s.add(user)
        s.commit()
        s.refresh(user)
        assert user.id is not None

        budget = Budget(name="Dom", owner_id=user.id)
        s.add(budget)
        s.commit()
        s.refresh(budget)
        assert budget.id is not None

        acc = Account(name="Checking", type="checking", currency="PLN", budget_id=budget.id)
        s.add(acc)
        s.commit()
        s.refresh(acc)
        assert acc.id is not None

        conn = ExternalReceiptConnection(
            budget_id=budget.id,
            owner_user_id=user.id,
            provider="lidl",
            status=ConnectionStatus.ACTIVE,
            is_enabled=True,
        )
        s.add(conn)
        s.commit()
        s.refresh(conn)

        sync_job = enqueue_connection_sync_job(s, conn)

        img_path = tmp_path / "receipt_ok.jpg"
        img_path.write_bytes(_jpeg_bytes(b"real-shop"))
        tx = Transaction(
            merchant_name="Processing...",
            uploaded_by=user.id,
            budget_id=budget.id,
            account_id=acc.id,
            review_status=ReviewStatus.PENDING,
        )
        s.add(tx)
        s.commit()
        s.refresh(tx)
        assert tx.id is not None
        scan = ReceiptScan(
            transaction_id=tx.id,
            image_path=str(img_path),
            status=ScanStatus.QUEUED.value,
            content_hash="hash-boundary-doc-1",
        )
        s.add(scan)
        s.commit()
        s.refresh(scan)
        assert scan.id is not None

        from app.import_scheduler import enqueue_document_ingest_job

        doc_job = enqueue_document_ingest_job(
            s,
            budget_id=budget.id,
            transaction_id=tx.id,
            receipt_scan_id=scan.id,
            provider="receipt_upload",
            source_filename="receipt_ok.jpg",
        )
        sync_job_id = sync_job.id
        doc_job_id = doc_job.id
        tx_id = tx.id

    def _fake_parse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "merchant_name": "Lidl Polska",
            "date": "2026-06-15",
            "total_amount": 12.50,
            "currency": "PLN",
            "items": [
                {"name": "Chleb", "price": 12.50, "quantity": 1, "category": "Food"}
            ],
        }

    monkeypatch.setattr(app_api.AIService, "parse_receipt", staticmethod(_fake_parse))

    # Document-only worker in central_vps executes document_ingest without touching connection_sync
    doc_worker = ImportWorker(
        lambda: Session(engine),
        worker_id="doc-vps-worker",
        allowed_job_types=(DOCUMENT_JOB_TYPE,),
        role="central_vps",
    )
    processed = doc_worker.run_once()
    assert processed is not None
    assert processed.id == doc_job_id
    assert processed.status == ImportJobStatus.COMPLETED

    # Even if an untrusted worker directly tries to process a connection_sync job, it fails closed
    with Session(engine) as s:
        persisted_sync = s.get(ImportJob, sync_job_id)
        persisted_tx = s.get(Transaction, tx_id)
        assert persisted_sync is not None
        assert persisted_sync.status == ImportJobStatus.PENDING
        assert persisted_tx is not None
        assert persisted_tx.merchant_name == "Lidl Polska"

        with pytest.raises(RuntimeError):
            process_claimed_job(
                s,
                persisted_sync,
                worker_id="doc-vps-worker",
                role="central_vps",
            )
    assert DEFAULT_JOB_TYPE != DOCUMENT_JOB_TYPE


def test_transient_retry_stale_lease_recovery_and_manual_retry_rbac(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None
    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))

    upload_res = client.post(
        "/api/transactions/scan",
        files={"file": ("retry_me.jpg", _jpeg_bytes(b"retry"), "image/jpeg")},
    )
    assert upload_res.status_code == 200
    tx_id = upload_res.json()["id"]
    job_id = upload_res.json()["import_job"]["id"]
    scan = session.exec(select(ReceiptScan).where(ReceiptScan.transaction_id == tx_id)).first()
    assert scan is not None and scan.image_path is not None
    image_path = Path(scan.image_path)
    assert image_path.exists()

    # 1. Transient failure preserves image file and schedules backoff retry
    def _raise_timeout(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise TimeoutError("Vision API timed out")

    monkeypatch.setattr(app_api.AIService, "parse_receipt", staticmethod(_raise_timeout))

    worker = ImportWorker(
        lambda: Session(session.get_bind()),
        worker_id="retry-worker",
        allowed_job_types=(DOCUMENT_JOB_TYPE,),
        role="central_vps",
    )
    first_run = worker.run_once()
    assert first_run is not None
    assert first_run.status == ImportJobStatus.PENDING
    assert first_run.attempt_count == 1
    assert first_run.last_error_code == "OCR_TRANSIENT_ERROR"
    assert image_path.exists()

    # 2. Simulate crash mid-flight (RUNNING + expired lease) -> recovered & retries until permanent FAILED
    job_db = session.get(ImportJob, job_id)
    assert job_db is not None
    job_db.status = ImportJobStatus.RUNNING
    job_db.lease_owner = "crashed-worker"
    job_db.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job_db.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    job_db.attempt_count = job_db.max_attempts - 1
    session.add(job_db)
    session.commit()

    exhausted_run = worker.run_once()
    assert exhausted_run is not None
    assert exhausted_run.status == ImportJobStatus.FAILED

    session.refresh(scan)
    assert scan.status == ScanStatus.FAILED

    # 3. Viewer cannot retry job (RBAC 403), owner succeeds and re-queues cleanly
    viewer = User(email="viewer@example.com", hashed_password="x")
    session.add(viewer)
    session.commit()
    session.refresh(viewer)
    assert viewer.id is not None
    session.add(BudgetMember(budget_id=budget.id, user_id=viewer.id, role="viewer"))
    session.commit()

    app.dependency_overrides[get_current_user] = lambda: viewer
    forbidden_res = client.post(f"/api/import-jobs/{job_id}/retry")
    assert forbidden_res.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: user
    retry_res = client.post(f"/api/import-jobs/{job_id}/retry")
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "pending"

    monkeypatch.setattr(
        app_api.AIService,
        "parse_receipt",
        staticmethod(
            lambda *a, **kw: {
                "merchant_name": "Biedronka",
                "date": "2026-06-16",
                "total_amount": 9.99,
                "currency": "PLN",
                "items": [{"name": "Masło", "price": 9.99, "quantity": 1, "category": "Food"}],
            }
        ),
    )
    recovered_run = worker.run_once()
    assert recovered_run is not None
    assert recovered_run.status == ImportJobStatus.COMPLETED
    tx_refreshed = session.get(Transaction, tx_id)
    assert tx_refreshed is not None
    assert tx_refreshed.merchant_name == "Biedronka"


def test_private_upload_validation_and_rate_limiting(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_MAX_FILE_BYTES", 128)
    monkeypatch.setattr(settings, "UPLOAD_RATE_LIMIT_MAX_COUNT", 2)

    # Oversized file rejected for private user (#122)
    too_big = _jpeg_bytes(b"X" * 200)
    big_res = client.post(
        "/api/transactions/scan",
        files={"file": ("big.jpg", too_big, "image/jpeg")},
    )
    assert big_res.status_code == 400

    # Batch with 3 valid files under rate limit max 2 -> first 2 queue, 3rd returns rate_limited (#121)
    monkeypatch.setattr(settings, "UPLOAD_MAX_FILE_BYTES", 1024 * 1024)
    batch_res = client.post(
        "/api/transactions/scan-batch",
        files=[
            ("files", ("a.jpg", _jpeg_bytes(b"a"), "image/jpeg")),
            ("files", ("b.jpg", _jpeg_bytes(b"b"), "image/jpeg")),
            ("files", ("c.jpg", _jpeg_bytes(b"c"), "image/jpeg")),
        ],
    )
    assert batch_res.status_code == 200
    body = batch_res.json()
    assert body["queued_count"] == 2
    assert body["rate_limited_count"] == 1
    assert body["results"][2]["status"] == "rate_limited"


def test_review_fixes_rbac_json_validation_stale_exhaustion_and_delete_cleanup(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, budget = _get_user_budget(session)
    assert budget.id is not None
    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))

    # 1. Non-eparagon JSON object rejected even with application/json Content-Type
    bad_json_res = client.post(
        "/api/transactions/scan",
        files={"file": ("arbitrary.json", b'{"foo": "bar"}', "application/json")},
    )
    assert bad_json_res.status_code == 400
    assert "e-Paragon" in bad_json_res.json()["detail"]

    # 2. Viewer cannot upload via /scan, /scan-batch, or /scan-sample (RBAC 403)
    viewer = User(email="upload-viewer@example.com", hashed_password="x")
    session.add(viewer)
    session.commit()
    session.refresh(viewer)
    assert viewer.id is not None
    session.add(BudgetMember(budget_id=budget.id, user_id=viewer.id, role="viewer"))
    session.commit()

    app.dependency_overrides[get_current_user] = lambda: viewer
    assert (
        client.post(
            "/api/transactions/scan",
            files={"file": ("v.jpg", _jpeg_bytes(b"v"), "image/jpeg")},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/transactions/scan-batch",
            files=[("files", ("v2.jpg", _jpeg_bytes(b"v2"), "image/jpeg"))],
        ).status_code
        == 403
    )
    assert client.post("/api/transactions/scan-sample?sample_id=biedronka").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: user

    # 3. Exhausted stale lease on document_ingest marks both ImportJob & ReceiptScan FAILED
    up1 = client.post(
        "/api/transactions/scan",
        files={"file": ("stale_doc.jpg", _jpeg_bytes(b"stale-doc"), "image/jpeg")},
    )
    assert up1.status_code == 200
    tx1_id = up1.json()["id"]
    job1_id = up1.json()["import_job"]["id"]
    scan1_id = up1.json()["import_job"]["receipt_scan_id"]

    job1 = session.get(ImportJob, job1_id)
    assert job1 is not None
    job1.status = ImportJobStatus.RUNNING
    job1.lease_owner = "dead-worker"
    job1.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job1.attempt_count = job1.max_attempts
    session.add(job1)
    session.commit()

    recovered = recover_stale_jobs(session, now=datetime.now(timezone.utc), commit=True)
    assert recovered == 1
    session.refresh(job1)
    scan1 = session.get(ReceiptScan, scan1_id)
    assert job1.status == ImportJobStatus.FAILED
    assert job1.last_error_code == "DOCUMENT_INGEST_FAILED"
    assert scan1 is not None
    assert scan1.status == ScanStatus.FAILED

    # 4. Hard delete removes ImportJob; soft-reject cleans pending ImportJob
    assert client.delete(f"/api/transactions/{tx1_id}").status_code == 204
    assert session.get(ImportJob, job1_id) is None

    up2 = client.post(
        "/api/transactions/scan",
        files={"file": ("soft_del.jpg", _jpeg_bytes(b"soft-del"), "image/jpeg")},
    )
    assert up2.status_code == 200
    tx2_id = up2.json()["id"]
    job2_id = up2.json()["import_job"]["id"]
    assert client.delete(f"/api/transactions/{tx2_id}?preserve_source=true").status_code == 204
    assert session.get(ImportJob, job2_id) is None

