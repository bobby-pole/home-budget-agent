"""Durable SQLite-backed import scheduler, atomic leasing, and worker runner (#257)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import random
import re
import signal
import socket
import threading
import time
from typing import Any, Callable, Optional
import uuid

from sqlalchemy import case, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, col, select

from app.config import settings
from app.models import (
    BudgetAlert,
    ConnectionErrorCode,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJob,
    ImportJobStatus,
    ImportProviderLimit,
    ensure_tz_aware,
)

logger = logging.getLogger(__name__)

DEFAULT_JOB_TYPE = "connection_sync"
TRUSTED_WORKER_ROLE = "trusted_local"

_FORBIDDEN_CURSOR_RE = re.compile(
    r"(access_token|refresh_token|code_verifier|authorization_code|client_secret|bearer\s+|eyJ[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_SAFE_CURSOR_RE = re.compile(r"^[A-Za-z0-9._:=\-/|,]{1,256}$")


@dataclass(frozen=True)
class ProviderRatePolicy:
    """Rate limiting and concurrency thresholds for an external receipt provider."""

    max_concurrent: int = 1
    min_interval_seconds: float = 1.0
    sync_interval_seconds: int = 21600


DEFAULT_PROVIDER_POLICIES: dict[str, ProviderRatePolicy] = {
    "lidl": ProviderRatePolicy(
        max_concurrent=2,
        min_interval_seconds=1.0,
        sync_interval_seconds=settings.IMPORT_SYNC_INTERVAL_SECONDS,
    ),
}


@dataclass(frozen=True)
class SyncExecutionOutcome:
    """Structured result returned by a connector sync executor (zero secrets/PII)."""

    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    next_cursor: Optional[str] = None
    error_classification: Optional[str] = None  # None | "transient" | "permanent"
    error_code: Optional[ConnectionErrorCode] = None
    retry_after_seconds: Optional[int] = None


SyncExecutorFn = Callable[[Session, ExternalReceiptConnection, ImportJob], SyncExecutionOutcome]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    dt = ensure_tz_aware(value)
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc)
    return None


def is_trusted_worker_environment(role: Optional[str] = None) -> bool:
    """Return True only when executing inside the owner-approved trusted local boundary."""
    resolved_role = (role if role is not None else settings.IMPORT_WORKER_ROLE).strip().lower()
    return resolved_role == TRUSTED_WORKER_ROLE


def assert_trusted_worker_environment(role: Optional[str] = None) -> None:
    """Refuse to run credential-bearing merchant jobs on an untrusted/central VPS host."""
    if not is_trusted_worker_environment(role):
        resolved_role = role if role is not None else settings.IMPORT_WORKER_ROLE
        raise RuntimeError(
            f"Merchant import worker cannot run under IMPORT_WORKER_ROLE={resolved_role!r}; "
            f"requires {TRUSTED_WORKER_ROLE!r}."
        )


def get_provider_policy(
    provider: str,
    policies: Optional[dict[str, ProviderRatePolicy]] = None,
) -> ProviderRatePolicy:
    registry = policies if policies is not None else DEFAULT_PROVIDER_POLICIES
    normalized = (provider or "").strip().lower()
    return registry.get(
        normalized,
        ProviderRatePolicy(
            max_concurrent=1,
            min_interval_seconds=1.0,
            sync_interval_seconds=settings.IMPORT_SYNC_INTERVAL_SECONDS,
        ),
    )


def sanitize_cursor(raw_cursor: Optional[str]) -> Optional[str]:
    """Validate an opaque pagination cursor and reject secrets, tokens, or PII."""
    if raw_cursor is None:
        return None
    cleaned = str(raw_cursor).strip()
    if not cleaned:
        return None
    if _FORBIDDEN_CURSOR_RE.search(cleaned):
        raise ValueError("Cursor rejected because it matches a forbidden secret/token pattern")
    if not _SAFE_CURSOR_RE.fullmatch(cleaned):
        raise ValueError("Cursor contains unsupported characters or exceeds length limit")
    return cleaned


def compute_backoff_seconds(
    attempt_count: int,
    *,
    base_seconds: Optional[int] = None,
    max_seconds: Optional[int] = None,
    retry_after_seconds: Optional[int] = None,
) -> int:
    """Compute bounded exponential backoff while honoring explicit Retry-After hints."""
    base = max(1, base_seconds if base_seconds is not None else settings.IMPORT_WORKER_BASE_BACKOFF_SECONDS)
    ceiling = max(base, max_seconds if max_seconds is not None else settings.IMPORT_WORKER_MAX_BACKOFF_SECONDS)
    exponent = max(0, attempt_count - 1)
    exp_delay = min(ceiling, int(base * (2**exponent)))
    if retry_after_seconds is not None and retry_after_seconds > 0:
        hint = min(int(retry_after_seconds), 86400)
        return max(exp_delay, hint)
    return exp_delay


def _log_job_event(
    level: int,
    event: str,
    *,
    job: ImportJob,
    worker_id: Optional[str] = None,
    imported_count: Optional[int] = None,
    skipped_count: Optional[int] = None,
    failed_count: Optional[int] = None,
) -> None:
    """Emit structured operational log line containing strictly non-PII, non-secret metadata."""
    parts = [
        f"event={event}",
        f"job_id={job.id}",
        f"correlation_id={job.correlation_id}",
        f"connection_id={job.connection_id}",
        f"budget_id={job.budget_id}",
        f"provider={job.provider}",
        f"job_type={job.job_type}",
        f"status={job.status.value if isinstance(job.status, ImportJobStatus) else job.status}",
        f"attempt={job.attempt_count}/{job.max_attempts}",
    ]
    if worker_id:
        parts.append(f"worker_id={worker_id}")
    if job.last_error_code:
        parts.append(f"error_code={job.last_error_code}")
    if imported_count is not None:
        parts.append(f"imported={imported_count}")
    if skipped_count is not None:
        parts.append(f"skipped={skipped_count}")
    if failed_count is not None:
        parts.append(f"failed={failed_count}")
    logger.log(level, "import_worker %s", " ".join(parts))


def _create_connection_alert(
    session: Session,
    *,
    conn: ExternalReceiptConnection,
    error_code: ConnectionErrorCode,
    now: datetime,
) -> None:
    """Create a user-visible alert on permanent failure without leaking tokens or PII."""
    category_tag = f"connector:{conn.provider}"
    existing_unread = session.exec(
        select(BudgetAlert).where(
            col(BudgetAlert.budget_id) == conn.budget_id,
            col(BudgetAlert.user_id) == conn.owner_user_id,
            col(BudgetAlert.category_name) == category_tag,
            col(BudgetAlert.is_read) == False,  # noqa: E712
        )
    ).first()
    message = (
        f"Connection '{conn.provider}' failed permanently ({error_code.value}) "
        f"and requires attention."
    )
    if existing_unread is not None:
        existing_unread.message = message
        existing_unread.created_at = now
        session.add(existing_unread)
        return

    session.add(
        BudgetAlert(
            budget_id=conn.budget_id,
            user_id=conn.owner_user_id,
            category_name=category_tag,
            message=message,
            is_read=False,
            created_at=now,
        )
    )


def enqueue_connection_sync_job(
    session: Session,
    conn: ExternalReceiptConnection,
    *,
    job_type: str = DEFAULT_JOB_TYPE,
    max_attempts: Optional[int] = None,
    correlation_id: Optional[str] = None,
    next_retry_at: Optional[datetime] = None,
    cursor: Optional[str] = None,
    expedite_if_pending: bool = False,
    commit: bool = True,
) -> ImportJob:
    """Idempotently enqueue a durable sync job for a connection unless one is already active."""
    if conn.id is None:
        raise ValueError("Connection must be persisted before enqueueing an import job")

    now = utc_now()
    due_at = _as_utc(next_retry_at) or now

    existing = session.exec(
        select(ImportJob).where(
            col(ImportJob.connection_id) == conn.id,
            col(ImportJob.job_type) == job_type,
            col(ImportJob.status).in_([ImportJobStatus.PENDING.value, ImportJobStatus.RUNNING.value]),
        )
    ).first()
    if existing is not None:
        existing_due = _as_utc(existing.next_retry_at)
        if (
            expedite_if_pending
            and existing.status == ImportJobStatus.PENDING
            and (existing_due is None or due_at < existing_due)
        ):
            existing.next_retry_at = due_at
            existing.updated_at = now
            session.add(existing)
            if commit:
                session.commit()
                session.refresh(existing)
            else:
                session.flush()
            _log_job_event(logging.INFO, "job_expedited", job=existing)
        return existing

    if cursor is not None:
        safe_cursor = sanitize_cursor(cursor)
    else:
        last_completed_cursor = session.exec(
            select(ImportJob.cursor)
            .where(
                col(ImportJob.connection_id) == conn.id,
                col(ImportJob.job_type) == job_type,
                col(ImportJob.status) == ImportJobStatus.COMPLETED.value,
                col(ImportJob.cursor).is_not(None),
            )
            .order_by(col(ImportJob.id).desc())
            .limit(1)
        ).first()
        safe_cursor = sanitize_cursor(last_completed_cursor)
    resolved_max_attempts = max(
        1, max_attempts if max_attempts is not None else settings.IMPORT_WORKER_MAX_ATTEMPTS
    )
    job = ImportJob(
        job_type=job_type,
        provider=conn.provider,
        connection_id=conn.id,
        budget_id=conn.budget_id,
        status=ImportJobStatus.PENDING,
        attempt_count=0,
        max_attempts=resolved_max_attempts,
        next_retry_at=due_at,
        cursor=safe_cursor,
        correlation_id=correlation_id or uuid.uuid4().hex,
        lease_owner=None,
        lease_expires_at=None,
        last_error_code=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        existing_raced = session.exec(
            select(ImportJob).where(
                col(ImportJob.connection_id) == conn.id,
                col(ImportJob.job_type) == job_type,
                col(ImportJob.status).in_(
                    [ImportJobStatus.PENDING.value, ImportJobStatus.RUNNING.value]
                ),
            )
        ).first()
        if existing_raced is not None:
            return existing_raced
        raise

    if commit:
        session.commit()
        session.refresh(job)
    _log_job_event(logging.INFO, "job_enqueued", job=job)
    return job


def schedule_due_connections(
    session: Session,
    *,
    now: Optional[datetime] = None,
    commit: bool = True,
) -> list[ImportJob]:
    """Enqueue sync jobs for active connections whose next_sync_at has fallen due."""
    current = _as_utc(now) or utc_now()
    due_conns = session.exec(
        select(ExternalReceiptConnection).where(
            col(ExternalReceiptConnection.status) == ConnectionStatus.ACTIVE.value,
            col(ExternalReceiptConnection.encrypted_refresh_token).is_not(None),
            col(ExternalReceiptConnection.next_sync_at).is_not(None),
            col(ExternalReceiptConnection.next_sync_at) <= current,
        )
    ).all()

    enqueued: list[ImportJob] = []
    for conn in due_conns:
        job = enqueue_connection_sync_job(session, conn, next_retry_at=current, commit=False)
        enqueued.append(job)

    if commit and enqueued:
        session.commit()
        for job in enqueued:
            session.refresh(job)
    return enqueued


def recover_stale_jobs(
    session: Session,
    *,
    now: Optional[datetime] = None,
    commit: bool = True,
) -> int:
    """Recover running jobs whose lease expired (e.g. crashed/killed worker)."""
    current = _as_utc(now) or utc_now()
    stale_jobs = session.exec(
        select(ImportJob).where(
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_expires_at).is_not(None),
            col(ImportJob.lease_expires_at) <= current,
        )
    ).all()

    recovered_count = 0
    for stale in stale_jobs:
        if stale.id is None:
            continue
        if stale.attempt_count < stale.max_attempts:
            res = session.exec(
                update(ImportJob)
                .where(
                    col(ImportJob.id) == stale.id,
                    col(ImportJob.status) == ImportJobStatus.RUNNING.value,
                    col(ImportJob.lease_expires_at).is_not(None),
                    col(ImportJob.lease_expires_at) <= current,
                )
                .values(
                    status=ImportJobStatus.PENDING.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=ConnectionErrorCode.NETWORK_ERROR.value,
                    next_retry_at=current,
                    updated_at=current,
                )
            )
            if (res.rowcount or 0) == 1:
                recovered_count += 1
                session.refresh(stale)
                _log_job_event(logging.WARNING, "stale_lease_recovered", job=stale)
        else:
            err_code = ConnectionErrorCode.SYNC_FAILED
            res = session.exec(
                update(ImportJob)
                .where(
                    col(ImportJob.id) == stale.id,
                    col(ImportJob.status) == ImportJobStatus.RUNNING.value,
                    col(ImportJob.lease_expires_at).is_not(None),
                    col(ImportJob.lease_expires_at) <= current,
                )
                .values(
                    status=ImportJobStatus.FAILED.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=err_code.value,
                    completed_at=current,
                    updated_at=current,
                )
            )
            if (res.rowcount or 0) == 1:
                recovered_count += 1
                conn = session.get(ExternalReceiptConnection, stale.connection_id)
                if conn is not None:
                    conn.status = ConnectionStatus.SYNC_ERROR
                    conn.last_error_code = err_code.value
                    conn.next_sync_at = None
                    conn.sync_requested_at = None
                    conn.updated_at = current
                    session.add(conn)
                    _create_connection_alert(session, conn=conn, error_code=err_code, now=current)
                session.refresh(stale)
                _log_job_event(logging.ERROR, "stale_job_exhausted", job=stale)

    if commit and recovered_count > 0:
        session.commit()
    return recovered_count


def _is_provider_limit_throttled(
    limit_row: Optional[ImportProviderLimit],
    *,
    now: datetime,
    policy: ProviderRatePolicy,
    active_provider_runs: int,
) -> bool:
    if active_provider_runs >= max(1, policy.max_concurrent):
        return True
    if limit_row is None:
        return False

    cooldown_until = _as_utc(limit_row.cooldown_until)
    if cooldown_until is not None and cooldown_until > now:
        return True

    last_dispatched = _as_utc(limit_row.last_dispatched_at)
    if last_dispatched is not None and policy.min_interval_seconds > 0:
        elapsed = (now - last_dispatched).total_seconds()
        if elapsed < policy.min_interval_seconds:
            return True

    return False


def _upsert_provider_limit(
    session: Session,
    *,
    provider: str,
    now: datetime,
    last_dispatched_at: Optional[datetime] = None,
    cooldown_until: Optional[datetime] = None,
) -> None:
    """Atomically insert or update import_provider_limits without SELECT+INSERT races."""
    dialect_name = session.get_bind().dialect.name
    insert_fn = pg_insert if dialect_name == "postgresql" else sqlite_insert
    values: dict[str, Any] = {
        "provider": provider,
        "cooldown_until": cooldown_until,
        "last_dispatched_at": last_dispatched_at,
        "updated_at": now,
    }
    set_clause: dict[str, Any] = {"updated_at": now}
    if last_dispatched_at is not None:
        set_clause["last_dispatched_at"] = last_dispatched_at
    if cooldown_until is not None:
        cooldown_col = col(ImportProviderLimit.cooldown_until)
        set_clause["cooldown_until"] = case(
            (cooldown_col.is_(None), cooldown_until),
            (cooldown_until > cooldown_col, cooldown_until),
            else_=cooldown_col,
        )
    stmt = (
        insert_fn(ImportProviderLimit)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[ImportProviderLimit.provider],
            set_=set_clause,
        )
    )
    session.execute(stmt)


def _touch_provider_dispatch(session: Session, *, provider: str, now: datetime) -> None:
    _upsert_provider_limit(session, provider=provider, now=now, last_dispatched_at=now)


def _set_provider_cooldown(
    session: Session, *, provider: str, cooldown_until: datetime, now: datetime
) -> None:
    _upsert_provider_limit(
        session,
        provider=provider,
        now=now,
        cooldown_until=cooldown_until,
    )


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
    per_connection_concurrency: int = 1,
    provider_policies: Optional[dict[str, ProviderRatePolicy]] = None,
) -> Optional[ImportJob]:
    """Atomically claim the next eligible job respecting leases and throttling limits."""
    current = _as_utc(now) or utc_now()
    resolved_lease = max(
        1, lease_seconds if lease_seconds is not None else settings.IMPORT_WORKER_LEASE_SECONDS
    )
    lease_until = current + timedelta(seconds=resolved_lease)
    conn_limit = max(1, per_connection_concurrency)

    for lock_attempt in range(8):
        try:
            recover_stale_jobs(session, now=current, commit=True)

            active_runs = session.exec(
                select(ImportJob).where(
                    col(ImportJob.status) == ImportJobStatus.RUNNING.value,
                    col(ImportJob.lease_expires_at).is_not(None),
                    col(ImportJob.lease_expires_at) > current,
                )
            ).all()
            running_by_conn: dict[int, int] = {}
            running_by_provider: dict[str, int] = {}
            for active_job in active_runs:
                running_by_conn[active_job.connection_id] = (
                    running_by_conn.get(active_job.connection_id, 0) + 1
                )
                running_by_provider[active_job.provider] = (
                    running_by_provider.get(active_job.provider, 0) + 1
                )

            blocked_connection_ids = {
                cid for cid, count in running_by_conn.items() if count >= conn_limit
            }
            limits_by_provider = {
                row.provider: row
                for row in session.exec(select(ImportProviderLimit)).all()
            }
            throttled_providers: set[str] = set()
            for provider_name in set(running_by_provider) | set(limits_by_provider):
                policy = get_provider_policy(provider_name, provider_policies)
                if _is_provider_limit_throttled(
                    limits_by_provider.get(provider_name),
                    now=current,
                    policy=policy,
                    active_provider_runs=running_by_provider.get(provider_name, 0),
                ):
                    throttled_providers.add(provider_name)

            stmt = select(ImportJob).where(
                col(ImportJob.status) == ImportJobStatus.PENDING.value,
                col(ImportJob.next_retry_at) <= current,
            )
            if blocked_connection_ids:
                stmt = stmt.where(col(ImportJob.connection_id).not_in(blocked_connection_ids))
            if throttled_providers:
                stmt = stmt.where(col(ImportJob.provider).not_in(throttled_providers))

            candidates = session.exec(
                stmt.order_by(col(ImportJob.next_retry_at).asc(), col(ImportJob.id).asc()).limit(25)
            ).all()
            if not candidates:
                return None

            lost_race = False
            for candidate in candidates:
                if candidate.id is None:
                    continue

                res = session.exec(
                    update(ImportJob)
                    .where(
                        col(ImportJob.id) == candidate.id,
                        col(ImportJob.status) == ImportJobStatus.PENDING.value,
                        col(ImportJob.next_retry_at) <= current,
                    )
                    .values(
                        status=ImportJobStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=lease_until,
                        attempt_count=ImportJob.attempt_count + 1,
                        updated_at=current,
                    )
                )
                if (res.rowcount or 0) != 1:
                    # Refresh active counts & throttled providers after losing a claim race.
                    session.rollback()
                    lost_race = True
                    break

                _touch_provider_dispatch(session, provider=candidate.provider, now=current)
                session.commit()
                claimed = session.get(ImportJob, candidate.id)
                if claimed is not None:
                    _log_job_event(logging.INFO, "job_claimed", job=claimed, worker_id=worker_id)
                return claimed

            if lost_race and lock_attempt < 7:
                time.sleep(random.uniform(0.005, 0.02))
                continue
            return None
        except OperationalError as exc:
            session.rollback()
            err_msg = str(exc).lower()
            if ("locked" in err_msg or "busy" in err_msg) and lock_attempt < 7:
                time.sleep(0.01 * (lock_attempt + 1) + random.uniform(0.0, 0.02))
                continue
            raise
    return None


def extend_job_lease(
    session: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Extend an active lease still owned by worker_id."""
    current = _as_utc(now) or utc_now()
    resolved_lease = max(
        1, lease_seconds if lease_seconds is not None else settings.IMPORT_WORKER_LEASE_SECONDS
    )
    lease_until = current + timedelta(seconds=resolved_lease)
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.id) == job_id,
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_owner) == worker_id,
        )
        .values(lease_expires_at=lease_until, updated_at=current)
    )
    session.commit()
    return (res.rowcount or 0) == 1


def release_job_lease(
    session: Session,
    *,
    job_id: int,
    worker_id: str,
    now: Optional[datetime] = None,
) -> bool:
    """Release an active lease cleanly on worker shutdown so another worker can resume."""
    current = _as_utc(now) or utc_now()
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.id) == job_id,
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_owner) == worker_id,
        )
        .values(
            status=ImportJobStatus.PENDING.value,
            lease_owner=None,
            lease_expires_at=None,
            next_retry_at=current,
            updated_at=current,
        )
    )
    session.commit()
    released = (res.rowcount or 0) == 1
    if released:
        job = session.get(ImportJob, job_id)
        if job is not None:
            _log_job_event(logging.INFO, "lease_released", job=job, worker_id=worker_id)
    return released


def release_worker_leases(
    session: Session,
    *,
    worker_id: str,
    now: Optional[datetime] = None,
) -> int:
    """Release all running leases currently owned by worker_id during shutdown."""
    current = _as_utc(now) or utc_now()
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_owner) == worker_id,
        )
        .values(
            status=ImportJobStatus.PENDING.value,
            lease_owner=None,
            lease_expires_at=None,
            next_retry_at=current,
            updated_at=current,
        )
    )
    session.commit()
    return int(res.rowcount or 0)


def cancel_pending_jobs_for_connection(
    session: Session,
    *,
    connection_id: int,
    now: Optional[datetime] = None,
    error_code: Optional[ConnectionErrorCode] = None,
    commit: bool = False,
) -> int:
    """Cancel active jobs when a connection is disconnected by the user."""
    current = _as_utc(now) or utc_now()
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.connection_id) == connection_id,
            col(ImportJob.status).in_(
                [ImportJobStatus.PENDING.value, ImportJobStatus.RUNNING.value]
            ),
        )
        .values(
            status=ImportJobStatus.FAILED.value,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code.value if error_code else None,
            completed_at=current,
            updated_at=current,
        )
    )
    if commit:
        session.commit()
    return int(res.rowcount or 0)


def complete_pending_jobs_for_connection(
    session: Session,
    *,
    connection_id: int,
    next_cursor: Optional[str] = None,
    now: Optional[datetime] = None,
    commit: bool = False,
) -> int:
    """Close pending jobs after a successful synchronous manual live sync."""
    current = _as_utc(now) or utc_now()
    safe_cursor = sanitize_cursor(next_cursor)
    values: dict[str, Any] = {
        "status": ImportJobStatus.COMPLETED.value,
        "lease_owner": None,
        "lease_expires_at": None,
        "last_error_code": None,
        "completed_at": current,
        "updated_at": current,
    }
    if safe_cursor is not None:
        values["cursor"] = safe_cursor
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.connection_id) == connection_id,
            col(ImportJob.status) == ImportJobStatus.PENDING.value,
        )
        .values(**values)
    )
    if commit:
        session.commit()
    return int(res.rowcount or 0)


def finalize_job_success(
    session: Session,
    *,
    job: ImportJob,
    worker_id: str,
    outcome: SyncExecutionOutcome,
    now: Optional[datetime] = None,
    provider_policies: Optional[dict[str, ProviderRatePolicy]] = None,
) -> ImportJob:
    """Mark job completed and update connection freshness and next scheduled sync."""
    current = _as_utc(now) or utc_now()
    policy = get_provider_policy(job.provider, provider_policies)
    next_sync_at = current + timedelta(seconds=max(60, policy.sync_interval_seconds))
    safe_cursor = sanitize_cursor(outcome.next_cursor)

    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.id) == job.id,
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_owner) == worker_id,
        )
        .values(
            status=ImportJobStatus.COMPLETED.value,
            cursor=safe_cursor if safe_cursor is not None else job.cursor,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=None,
            completed_at=current,
            updated_at=current,
        )
    )
    if (res.rowcount or 0) != 1:
        session.rollback()
        refreshed = session.get(ImportJob, job.id)
        if refreshed is not None:
            return refreshed
        return job

    conn = session.get(ExternalReceiptConnection, job.connection_id)
    if conn is not None and conn.status != ConnectionStatus.DISCONNECTED:
        conn.status = ConnectionStatus.ACTIVE
        conn.last_error_code = None
        conn.last_success_at = current
        conn.sync_requested_at = None
        conn.next_sync_at = next_sync_at
        conn.updated_at = current
        session.add(conn)

    session.commit()
    session.refresh(job)
    _log_job_event(
        logging.INFO,
        "job_completed",
        job=job,
        worker_id=worker_id,
        imported_count=outcome.imported_count,
        skipped_count=outcome.skipped_count,
        failed_count=outcome.failed_count,
    )
    return job


def finalize_job_failure(
    session: Session,
    *,
    job: ImportJob,
    worker_id: str,
    error_classification: str,
    error_code: ConnectionErrorCode,
    next_cursor: Optional[str] = None,
    retry_after_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
    base_backoff_seconds: Optional[int] = None,
    max_backoff_seconds: Optional[int] = None,
) -> ImportJob:
    """Schedule exponential-backoff retry for transient errors or fail permanently + alert user."""
    current = _as_utc(now) or utc_now()
    safe_cursor = sanitize_cursor(next_cursor)
    is_permanent = error_classification == "permanent" or job.attempt_count >= job.max_attempts

    if not is_permanent:
        delay_seconds = compute_backoff_seconds(
            job.attempt_count,
            base_seconds=base_backoff_seconds,
            max_seconds=max_backoff_seconds,
            retry_after_seconds=retry_after_seconds,
        )
        retry_at = current + timedelta(seconds=delay_seconds)
        res = session.exec(
            update(ImportJob)
            .where(
                col(ImportJob.id) == job.id,
                col(ImportJob.status) == ImportJobStatus.RUNNING.value,
                col(ImportJob.lease_owner) == worker_id,
            )
            .values(
                status=ImportJobStatus.PENDING.value,
                cursor=safe_cursor if safe_cursor is not None else job.cursor,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=error_code.value,
                next_retry_at=retry_at,
                updated_at=current,
            )
        )
        if (res.rowcount or 0) == 1:
            if error_code == ConnectionErrorCode.RATE_LIMITED or (
                retry_after_seconds is not None and retry_after_seconds > 0
            ):
                cooldown_secs = retry_after_seconds if retry_after_seconds else delay_seconds
                _set_provider_cooldown(
                    session,
                    provider=job.provider,
                    cooldown_until=current + timedelta(seconds=max(1, cooldown_secs)),
                    now=current,
                )
            conn = session.get(ExternalReceiptConnection, job.connection_id)
            if conn is not None and conn.status != ConnectionStatus.DISCONNECTED:
                conn.status = ConnectionStatus.SYNC_ERROR
                conn.last_error_code = error_code.value
                conn.next_sync_at = retry_at
                conn.updated_at = current
                session.add(conn)
            session.commit()
            session.refresh(job)
            _log_job_event(logging.WARNING, "job_retry_scheduled", job=job, worker_id=worker_id)
        else:
            session.rollback()
        return job

    # Permanent failure (or retries exhausted)
    res = session.exec(
        update(ImportJob)
        .where(
            col(ImportJob.id) == job.id,
            col(ImportJob.status) == ImportJobStatus.RUNNING.value,
            col(ImportJob.lease_owner) == worker_id,
        )
        .values(
            status=ImportJobStatus.FAILED.value,
            cursor=safe_cursor if safe_cursor is not None else job.cursor,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code.value,
            completed_at=current,
            updated_at=current,
        )
    )
    if (res.rowcount or 0) == 1:
        conn = session.get(ExternalReceiptConnection, job.connection_id)
        if conn is not None:
            if conn.status != ConnectionStatus.DISCONNECTED:
                reauth_codes = {
                    ConnectionErrorCode.AUTH_EXPIRED,
                    ConnectionErrorCode.REAUTH_REQUIRED,
                    ConnectionErrorCode.ENCRYPTION_KEY_MISSING,
                    ConnectionErrorCode.TOKEN_DECRYPTION_FAILED,
                }
                conn.status = (
                    ConnectionStatus.REAUTH_REQUIRED
                    if error_code in reauth_codes
                    else ConnectionStatus.SYNC_ERROR
                )
                conn.last_error_code = error_code.value
                conn.next_sync_at = None
                conn.sync_requested_at = None
                conn.updated_at = current
                session.add(conn)
                _create_connection_alert(session, conn=conn, error_code=error_code, now=current)
        session.commit()
        session.refresh(job)
        _log_job_event(logging.ERROR, "job_failed_permanently", job=job, worker_id=worker_id)
    else:
        session.rollback()
    return job


def _default_sync_executor(
    session: Session,
    conn: ExternalReceiptConnection,
    job: ImportJob,
) -> SyncExecutionOutcome:
    from app.connection_service import ConnectionService

    return ConnectionService.execute_connection_sync(session, conn, job=job)


def process_claimed_job(
    session: Session,
    job: ImportJob,
    *,
    worker_id: str,
    sync_executor: Optional[SyncExecutorFn] = None,
    now: Optional[datetime] = None,
    provider_policies: Optional[dict[str, ProviderRatePolicy]] = None,
    base_backoff_seconds: Optional[int] = None,
    max_backoff_seconds: Optional[int] = None,
) -> ImportJob:
    """Execute one already-leased job and transition queue + connection state."""
    current = _as_utc(now) or utc_now()
    conn = session.get(ExternalReceiptConnection, job.connection_id)
    if conn is None or conn.status == ConnectionStatus.DISCONNECTED:
        return finalize_job_failure(
            session,
            job=job,
            worker_id=worker_id,
            error_classification="permanent",
            error_code=ConnectionErrorCode.REAUTH_REQUIRED,
            now=current,
        )

    executor = sync_executor or _default_sync_executor
    try:
        outcome = executor(session, conn, job)
    except Exception:
        # Never persist or log arbitrary exception payloads (may contain provider details).
        session.rollback()
        return finalize_job_failure(
            session,
            job=job,
            worker_id=worker_id,
            error_classification="transient",
            error_code=ConnectionErrorCode.SYNC_FAILED,
            now=current,
            base_backoff_seconds=base_backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
        )

    if outcome.error_classification is None:
        return finalize_job_success(
            session,
            job=job,
            worker_id=worker_id,
            outcome=outcome,
            now=now,
            provider_policies=provider_policies,
        )

    return finalize_job_failure(
        session,
        job=job,
        worker_id=worker_id,
        error_classification=outcome.error_classification,
        error_code=outcome.error_code or ConnectionErrorCode.SYNC_FAILED,
        next_cursor=outcome.next_cursor,
        retry_after_seconds=outcome.retry_after_seconds,
        now=now,
        base_backoff_seconds=base_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
    )


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class ImportWorker:
    """Durable background import worker with atomic leasing and graceful shutdown."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        worker_id: Optional[str] = None,
        poll_interval_seconds: Optional[float] = None,
        lease_seconds: Optional[int] = None,
        per_connection_concurrency: int = 1,
        provider_policies: Optional[dict[str, ProviderRatePolicy]] = None,
        sync_executor: Optional[SyncExecutorFn] = None,
        role: Optional[str] = None,
        heartbeat_interval_seconds: Optional[float] = None,
    ) -> None:
        self._session_factory = session_factory
        self.worker_id = worker_id or default_worker_id()
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.IMPORT_WORKER_POLL_INTERVAL_SECONDS
        )
        self.lease_seconds = (
            lease_seconds if lease_seconds is not None else settings.IMPORT_WORKER_LEASE_SECONDS
        )
        self.per_connection_concurrency = per_connection_concurrency
        self.provider_policies = provider_policies
        self.sync_executor = sync_executor
        self.role = role
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.shutdown_event = asyncio.Event()
        self._in_flight_job_id: Optional[int] = None

    def request_shutdown(self) -> None:
        self.shutdown_event.set()

    def _can_run_background_heartbeat(self, session: Session) -> bool:
        if self.lease_seconds <= 0:
            return False
        bind = session.get_bind()
        db_name = getattr(getattr(bind, "url", None), "database", None)
        return bool(db_name and db_name != ":memory:")

    def _start_lease_heartbeat(
        self, *, job_id: int
    ) -> tuple[threading.Event, threading.Thread]:
        stop_event = threading.Event()
        interval = (
            self.heartbeat_interval_seconds
            if self.heartbeat_interval_seconds is not None
            else max(1.0, self.lease_seconds / 3.0)
        )

        def _beat() -> None:
            while not stop_event.wait(max(0.02, interval)):
                try:
                    with self._session_factory() as hb_session:
                        extended = extend_job_lease(
                            hb_session,
                            job_id=job_id,
                            worker_id=self.worker_id,
                            lease_seconds=self.lease_seconds,
                        )
                        if not extended:
                            break
                except Exception:
                    logger.debug(
                        "import_worker event=lease_heartbeat_error job_id=%s worker_id=%s",
                        job_id,
                        self.worker_id,
                    )

        thread = threading.Thread(
            target=_beat,
            name=f"import-hb-{job_id}",
            daemon=True,
        )
        thread.start()
        return stop_event, thread

    def run_once(self, *, now: Optional[datetime] = None) -> Optional[ImportJob]:
        """Claim and execute at most one due job synchronously."""
        assert_trusted_worker_environment(self.role)
        if self.shutdown_event.is_set():
            return None

        with self._session_factory() as session:
            schedule_due_connections(session, now=now, commit=True)
            job = claim_next_job(
                session,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                now=now,
                per_connection_concurrency=self.per_connection_concurrency,
                provider_policies=self.provider_policies,
            )
            if job is None or job.id is None:
                return None

            self._in_flight_job_id = job.id
            hb_stop: Optional[threading.Event] = None
            hb_thread: Optional[threading.Thread] = None
            if self._can_run_background_heartbeat(session):
                hb_stop, hb_thread = self._start_lease_heartbeat(job_id=job.id)
            try:
                return process_claimed_job(
                    session,
                    job,
                    worker_id=self.worker_id,
                    sync_executor=self.sync_executor,
                    now=now,
                    provider_policies=self.provider_policies,
                )
            finally:
                if hb_stop is not None:
                    hb_stop.set()
                if hb_thread is not None:
                    hb_thread.join(timeout=2.0)
                self._in_flight_job_id = None

    def release_active_leases(self) -> int:
        with self._session_factory() as session:
            return release_worker_leases(session, worker_id=self.worker_id)

    def install_signal_handlers(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        target_loop = loop or asyncio.get_running_loop()

        def _handle_signal() -> None:
            logger.info("import_worker event=shutdown_signal_received worker_id=%s", self.worker_id)
            self.request_shutdown()

        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, RuntimeError):
                target_loop.add_signal_handler(sig, _handle_signal)

    async def run_forever(self, *, install_signals: bool = False) -> None:
        """Run polling + processing loop until shutdown_event is triggered or cancelled."""
        assert_trusted_worker_environment(self.role)
        if install_signals:
            self.install_signal_handlers()

        logger.info("import_worker event=worker_started worker_id=%s", self.worker_id)
        was_cancelled = False
        try:
            while not self.shutdown_event.is_set():
                try:
                    processed = await asyncio.to_thread(self.run_once)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("import_worker event=loop_iteration_error worker_id=%s", self.worker_id)
                    processed = None

                if self.shutdown_event.is_set():
                    break
                if processed is not None:
                    await asyncio.sleep(0)
                    continue

                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=max(0.05, self.poll_interval_seconds),
                    )
        except asyncio.CancelledError:
            was_cancelled = True
            self.request_shutdown()
            raise
        finally:
            released = await asyncio.to_thread(self.release_active_leases)
            logger.info(
                "import_worker event=%s worker_id=%s released_leases=%d",
                "worker_cancelled" if was_cancelled else "worker_stopped",
                self.worker_id,
                released,
            )


def get_pending_or_running_job_count(session: Session, connection_id: int) -> int:
    return int(
        session.exec(
            select(func.count(col(ImportJob.id))).where(
                col(ImportJob.connection_id) == connection_id,
                col(ImportJob.status).in_(
                    [ImportJobStatus.PENDING.value, ImportJobStatus.RUNNING.value]
                ),
            )
        ).one()
    )
