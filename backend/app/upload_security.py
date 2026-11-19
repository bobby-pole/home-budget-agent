"""Shared upload ingress validation (#122) and per-user/budget rate limiting (#121)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.config import settings
from app.models import ImportJob, ImportJobStatus, ReceiptScan, ScanStatus, ScanUsageLog, Transaction, User

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
BLOCKED_EXTENSIONS = {
    "html",
    "htm",
    "svg",
    "xml",
    "zip",
    "gz",
    "tar",
    "exe",
    "dll",
    "sh",
    "bat",
    "js",
    "mjs",
    "ts",
    "csv",
    "xlsx",
    "xls",
}
BLOCKED_MIME_PREFIXES = (
    "text/html",
    "image/svg+xml",
    "application/zip",
    "application/x-msdownload",
    "application/x-sh",
    "application/javascript",
    "text/javascript",
    "text/csv",
)

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadValidationError(Exception):
    """Raised when an uploaded receipt/document fails server-side ingress validation (#122)."""

    def __init__(self, error_code: str, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


class UploadRateLimitError(Exception):
    """Raised when upload ingestion rate limits or demo quotas are exceeded (#121)."""

    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        retry_after_seconds: int = 60,
        status_code: int = 429,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedDocument:
    filename: str
    safe_extension: str
    content_type: str
    file_bytes: bytes
    file_hash: str
    is_eparagon: bool


def sanitize_filename(raw_name: Optional[str], *, fallback: str = "receipt") -> str:
    """Return a path-safe base filename truncated to 120 chars without directory traversal."""
    candidate = Path((raw_name or "").replace("\\", "/")).name.strip()
    if not candidate or candidate in (".", ".."):
        return fallback
    cleaned = _FILENAME_SAFE_RE.sub("_", candidate).strip("._")
    if not cleaned:
        return fallback
    return cleaned[:120]


async def read_upload_bounded(upload: UploadFile, *, is_demo: bool) -> bytes:
    """Read an uploaded file in bounded chunks so oversized payloads fail before buffering all bytes."""
    max_bytes = (
        settings.DEMO_UPLOAD_MAX_FILE_BYTES if is_demo else settings.UPLOAD_MAX_FILE_BYTES
    )
    limit_mb = max(1, max_bytes // (1024 * 1024))
    chunk_size = 64 * 1024
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            detail = (
                f"Plik przekracza maksymalny rozmiar {limit_mb} MB dla wersji demonstracyjnej."
                if is_demo
                else f"File exceeds maximum allowed size of {limit_mb} MB."
            )
            raise UploadValidationError("FILE_TOO_LARGE", detail, status_code=400)
        chunks.append(chunk)

    return b"".join(chunks)


def _detect_magic_kind(file_bytes: bytes) -> Optional[tuple[str, str, str]]:
    """Return (kind, canonical_extension, canonical_mime) from magic bytes or None."""
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return ("jpeg", "jpg", "image/jpeg")
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("png", "png", "image/png")
    if len(file_bytes) >= 12 and file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return ("webp", "webp", "image/webp")
    stripped = file_bytes.lstrip()
    if stripped.startswith(b"%PDF-"):
        return ("pdf", "pdf", "application/pdf")
    if stripped.startswith(b"{"):
        try:
            parsed = json.loads(file_bytes.decode("utf-8"))
            if isinstance(parsed, dict):
                return ("json", "json", "application/json")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    return None


def validate_uploaded_document(
    *,
    filename: Optional[str],
    content_type: Optional[str],
    file_bytes: bytes,
    is_demo: bool,
) -> ValidatedDocument:
    """Validate uploaded receipt file size, extension, MIME, and magic-byte signature (#122)."""
    safe_name = sanitize_filename(filename)

    if not file_bytes:
        raise UploadValidationError("EMPTY_FILE", "Uploaded file is empty.", status_code=400)

    max_bytes = (
        settings.DEMO_UPLOAD_MAX_FILE_BYTES if is_demo else settings.UPLOAD_MAX_FILE_BYTES
    )
    if len(file_bytes) > max_bytes:
        limit_mb = max(1, max_bytes // (1024 * 1024))
        detail = (
            f"Plik przekracza maksymalny rozmiar {limit_mb} MB dla wersji demonstracyjnej."
            if is_demo
            else f"File exceeds maximum allowed size of {limit_mb} MB."
        )
        raise UploadValidationError("FILE_TOO_LARGE", detail, status_code=400)

    ext = Path(safe_name).suffix.lower().lstrip(".")
    mime = (content_type or "").split(";")[0].strip().lower()

    if ext in BLOCKED_EXTENSIONS or any(mime.startswith(prefix) for prefix in BLOCKED_MIME_PREFIXES):
        raise UploadValidationError(
            "UNSUPPORTED_FILE_TYPE",
            "Unsupported file type. Allowed formats: JPG, PNG, WebP, PDF, JSON (e-Paragon).",
            status_code=400,
        )

    detected = _detect_magic_kind(file_bytes)
    if detected is None:
        raise UploadValidationError(
            "INVALID_FILE_SIGNATURE",
            "Nieobsługiwany lub uszkodzony plik. Dozwolone formaty: JPG, PNG, WebP, PDF, e-Paragon JSON.",
            status_code=400,
        )

    kind, canonical_ext, canonical_mime = detected

    # Guard against extension/MIME spoofing across binary families
    if kind in ("jpeg", "png", "webp"):
        if ext and ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise UploadValidationError(
                "FILE_SIGNATURE_MISMATCH",
                "File extension does not match image signature.",
                status_code=400,
            )
        if mime and not mime.startswith("image/") and mime != "application/octet-stream":
            raise UploadValidationError(
                "FILE_SIGNATURE_MISMATCH",
                "Content-Type does not match image signature.",
                status_code=400,
            )
    elif kind == "pdf":
        if ext and ext != "pdf":
            raise UploadValidationError(
                "FILE_SIGNATURE_MISMATCH",
                "File extension does not match PDF signature.",
                status_code=400,
            )
        if mime and mime not in ("application/pdf", "application/octet-stream"):
            raise UploadValidationError(
                "FILE_SIGNATURE_MISMATCH",
                "Content-Type does not match PDF signature.",
                status_code=400,
            )
    elif kind == "json":
        parsed = json.loads(file_bytes.decode("utf-8"))
        has_eparagon_keys = any(
            key in parsed
            for key in (
                "dokument",
                "document",
                "protoVersion",
                "paragon",
                "naglowek",
                "header",
                "body",
                "items",
            )
        ) or isinstance(parsed.get("data"), str)
        if ext and ext != "json":
            raise UploadValidationError(
                "FILE_SIGNATURE_MISMATCH",
                "File extension does not match JSON payload.",
                status_code=400,
            )
        if not has_eparagon_keys:
            raise UploadValidationError(
                "UNSUPPORTED_FILE_TYPE",
                "JSON document does not look like a supported e-Paragon export.",
                status_code=400,
            )

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    return ValidatedDocument(
        filename=safe_name,
        safe_extension=canonical_ext,
        content_type=canonical_mime,
        file_bytes=file_bytes,
        file_hash=file_hash,
        is_eparagon=(kind == "json"),
    )


def get_demo_custom_scans_used_today(
    session: Session,
    *,
    user_id: int,
    now: Optional[datetime] = None,
) -> int:
    current = now or datetime.now(timezone.utc)
    start_of_day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    custom_logs_used = session.exec(
        select(func.count(col(ScanUsageLog.id))).where(
            col(ScanUsageLog.user_id) == user_id,
            col(ScanUsageLog.scan_type) == "custom",
            col(ScanUsageLog.created_at) >= start_of_day,
        )
    ).one()
    legacy_custom_used = session.exec(
        select(func.count(col(ReceiptScan.id)))
        .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
        .where(
            col(Transaction.uploaded_by) == user_id,
            col(ReceiptScan.created_at) >= start_of_day,
            col(ReceiptScan.status) != ScanStatus.FAILED.value,
            ~col(ReceiptScan.content_hash).startswith("sample_"),
        )
    ).one()
    return int(max(custom_logs_used, legacy_custom_used))


def check_upload_rate_limit(
    session: Session,
    *,
    user: User,
    budget_id: int,
    is_demo: bool,
    now: Optional[datetime] = None,
) -> None:
    """Enforce per-user / per-budget durable rate limits for document uploads (#121)."""
    current = now or datetime.now(timezone.utc)
    if user.id is None:
        return

    if is_demo:
        used_today = get_demo_custom_scans_used_today(session, user_id=user.id, now=current)
        if used_today >= 5:
            raise UploadRateLimitError(
                "DEMO_DAILY_LIMIT_EXCEEDED",
                "Dzienny limit 5 skanów demonstracyjnych został wyczerpany. Spróbuj ponownie jutro lub przetestuj wzorcowe paragony demo.",
                retry_after_seconds=3600,
            )

    window_seconds = max(1, settings.UPLOAD_RATE_LIMIT_WINDOW_SECONDS)
    max_in_window = max(1, settings.UPLOAD_RATE_LIMIT_MAX_COUNT)
    window_start = current - timedelta(seconds=window_seconds)

    recent_doc_jobs = int(
        session.exec(
            select(func.count(col(ImportJob.id))).where(
                col(ImportJob.budget_id) == budget_id,
                col(ImportJob.job_type) == "document_ingest",
                col(ImportJob.created_at) >= window_start,
            )
        ).one()
    )
    if recent_doc_jobs >= max_in_window:
        raise UploadRateLimitError(
            "UPLOAD_RATE_LIMITED",
            f"Upload rate limit exceeded ({max_in_window} documents per {window_seconds // 60} min). Try again shortly.",
            retry_after_seconds=min(300, window_seconds),
        )

    active_doc_jobs = int(
        session.exec(
            select(func.count(col(ImportJob.id))).where(
                col(ImportJob.budget_id) == budget_id,
                col(ImportJob.job_type) == "document_ingest",
                col(ImportJob.status).in_(
                    [ImportJobStatus.PENDING.value, ImportJobStatus.RUNNING.value]
                ),
            )
        ).one()
    )
    if active_doc_jobs >= max_in_window:
        raise UploadRateLimitError(
            "UPLOAD_QUEUE_FULL",
            "Too many pending document jobs in queue for this budget. Wait for active jobs to finish.",
            retry_after_seconds=30,
        )
