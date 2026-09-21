"""
backend/app/services/connection_service.py

Service managing external receipt provider connections, lifecycle transitions,
token encryption at rest, key rotation, and authorization enforcement.

Scope & Boundary Rules:
- Phase 1 Web MVP: Privacy-first server-side token encryption at rest.
- Provider-agnostic lifecycle: Does not implement store-specific scrapers, reverse-engineered
  native clients, or background sync worker (#257).
- "Sync now" registers a timestamped queue request without asserting false sync completion.
- "Disconnect" atomically deletes stored tokens at rest and records a neutral revocation status.
- Never logs tokens, ciphertexts, or raw provider payload responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.encryption import (
    DecryptionError,
    EncryptionKeyError,
    get_encryption_service,
)
from app.models import (
    ConnectionDisconnectResponse,
    ConnectionErrorCode,
    ConnectionStatus,
    ConnectionSyncNowResponse,
    ExternalReceiptConnection,
    ExternalReceiptConnectionCreate,
    ExternalReceiptConnectionRead,
    ExternalReceiptConnectionUpdate,
    User,
)


def to_read_dto(conn: ExternalReceiptConnection) -> ExternalReceiptConnectionRead:
    """Convert an internal DB model to an API-safe DTO without leaking ciphertexts."""
    return ExternalReceiptConnectionRead(
        id=conn.id or 0,
        budget_id=conn.budget_id,
        owner_user_id=conn.owner_user_id,
        provider=conn.provider,
        account_identifier=conn.account_identifier,
        consented_scopes=conn.consented_scopes,
        consented_at=conn.consented_at,
        status=conn.status,
        has_token=bool(conn.encrypted_refresh_token),
        last_success_at=conn.last_success_at,
        last_error_code=conn.last_error_code,
        next_sync_at=conn.next_sync_at,
        sync_requested_at=conn.sync_requested_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


class ConnectionService:
    """Orchestrates connection lifecycle operations."""

    @staticmethod
    def list_connections(session: Session, budget_id: int) -> List[ExternalReceiptConnectionRead]:
        """List all external receipt connections belonging to the specified budget."""
        connections = session.exec(
            select(ExternalReceiptConnection).where(ExternalReceiptConnection.budget_id == budget_id)
        ).all()
        return [to_read_dto(c) for c in connections]

    @staticmethod
    def get_connection(
        session: Session, budget_id: int, connection_id: int
    ) -> ExternalReceiptConnection:
        """
        Fetch a single connection verifying budget ownership.

        Raises:
            HTTPException 404: If connection is missing or belongs to a different budget.
        """
        conn = session.get(ExternalReceiptConnection, connection_id)
        if not conn or conn.budget_id != budget_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found",
            )
        return conn

    @staticmethod
    def create_or_update_connection(
        session: Session,
        budget_id: int,
        user: User,
        data: ExternalReceiptConnectionCreate,
    ) -> ExternalReceiptConnectionRead:
        """
        Register or update a provider connection for a budget.
        Encrypts refresh tokens at rest with the active primary key.
        """
        provider_clean = data.provider.strip().lower()
        if not provider_clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provider cannot be blank",
            )

        now = datetime.now(timezone.utc)
        encrypted_token: Optional[str] = None
        key_id: Optional[str] = None

        if data.refresh_token:
            token_clean = data.refresh_token.strip()
            if token_clean:
                encryption_svc = get_encryption_service()
                try:
                    encrypted_token, key_id = encryption_svc.encrypt(token_clean)
                except EncryptionKeyError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Token encryption service is not configured (fail-closed)",
                    ) from exc

        existing = session.exec(
            select(ExternalReceiptConnection).where(
                ExternalReceiptConnection.budget_id == budget_id,
                ExternalReceiptConnection.provider == provider_clean,
            )
        ).first()

        if existing:
            existing.account_identifier = data.account_identifier or existing.account_identifier
            existing.consented_scopes = data.consented_scopes or existing.consented_scopes
            existing.status = ConnectionStatus.ACTIVE.value
            existing.last_error_code = None
            existing.updated_at = now
            if encrypted_token and key_id:
                existing.encrypted_refresh_token = encrypted_token
                existing.encryption_key_id = key_id
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return to_read_dto(existing)

        new_conn = ExternalReceiptConnection(
            budget_id=budget_id,
            owner_user_id=user.id or 0,
            provider=provider_clean,
            account_identifier=data.account_identifier,
            consented_scopes=data.consented_scopes,
            status=ConnectionStatus.ACTIVE.value,
            consented_at=now,
            encrypted_refresh_token=encrypted_token,
            encryption_key_id=key_id,
            created_at=now,
            updated_at=now,
        )
        session.add(new_conn)
        session.commit()
        session.refresh(new_conn)
        return to_read_dto(new_conn)

    @staticmethod
    def update_connection(
        session: Session,
        budget_id: int,
        connection_id: int,
        data: ExternalReceiptConnectionUpdate,
    ) -> ExternalReceiptConnectionRead:
        """Update connection metadata or refresh token."""
        conn = ConnectionService.get_connection(session, budget_id, connection_id)
        now = datetime.now(timezone.utc)

        if data.account_identifier is not None:
            conn.account_identifier = data.account_identifier
        if data.consented_scopes is not None:
            conn.consented_scopes = data.consented_scopes
        if data.status is not None:
            conn.status = data.status

        if data.refresh_token is not None:
            token_clean = data.refresh_token.strip()
            if token_clean:
                encryption_svc = get_encryption_service()
                try:
                    encrypted_token, key_id = encryption_svc.encrypt(token_clean)
                    conn.encrypted_refresh_token = encrypted_token
                    conn.encryption_key_id = key_id
                except EncryptionKeyError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Token encryption service is not configured (fail-closed)",
                    ) from exc
            else:
                conn.encrypted_refresh_token = None
                conn.encryption_key_id = None

        conn.updated_at = now
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return to_read_dto(conn)

    @staticmethod
    def trigger_sync_now(
        session: Session,
        budget_id: int,
        connection_id: int,
    ) -> ConnectionSyncNowResponse:
        """
        Record immediate synchronization request timestamp.
        Does NOT report false success when the asynchronous sync worker (#257) is absent.
        """
        conn = ConnectionService.get_connection(session, budget_id, connection_id)
        if conn.status == ConnectionStatus.DISCONNECTED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot synchronize a disconnected connection",
            )

        now = datetime.now(timezone.utc)
        conn.sync_requested_at = now
        conn.updated_at = now
        session.add(conn)
        session.commit()
        session.refresh(conn)

        return ConnectionSyncNowResponse(
            connection_id=conn.id or 0,
            status=conn.status,
            sync_requested_at=now,
            message="Synchronization requested and queued. Background sync worker will process this request.",
        )

    @staticmethod
    def reconnect(
        session: Session,
        budget_id: int,
        connection_id: int,
    ) -> ExternalReceiptConnectionRead:
        """
        Set connection to reauth_required state and prepare integration handoff.
        """
        conn = ConnectionService.get_connection(session, budget_id, connection_id)
        now = datetime.now(timezone.utc)
        conn.status = ConnectionStatus.REAUTH_REQUIRED.value
        conn.last_error_code = ConnectionErrorCode.REAUTH_REQUIRED.value
        conn.updated_at = now

        session.add(conn)
        session.commit()
        session.refresh(conn)
        return to_read_dto(conn)

    @staticmethod
    def disconnect(
        session: Session,
        budget_id: int,
        connection_id: int,
    ) -> ConnectionDisconnectResponse:
        """
        Atomically delete stored tokens at rest, clear credentials, and record
        neutral revocation availability without false claims of remote revocation.
        """
        conn = ConnectionService.get_connection(session, budget_id, connection_id)
        now = datetime.now(timezone.utc)

        # Atomic token erasure at rest
        conn.encrypted_refresh_token = None
        conn.encryption_key_id = None
        conn.status = ConnectionStatus.DISCONNECTED.value
        conn.last_error_code = ConnectionErrorCode.PROVIDER_REVOCATION_UNAVAILABLE.value
        conn.updated_at = now

        session.add(conn)
        session.commit()
        session.refresh(conn)

        return ConnectionDisconnectResponse(
            connection_id=conn.id or 0,
            status=conn.status,
            revocation_status="provider_revocation_unavailable",
            message="Stored tokens and credentials deleted locally. Remote provider revocation is not available.",
        )

    @staticmethod
    def get_decrypted_token(
        session: Session,
        conn: ExternalReceiptConnection,
    ) -> Optional[str]:
        """
        Decrypt stored refresh token for execution workers (#257).
        Automatically re-encrypts under active primary key if key rotation occurred.
        """
        if not conn.encrypted_refresh_token:
            return None

        encryption_svc = get_encryption_service()
        try:
            plaintext = encryption_svc.decrypt(
                conn.encrypted_refresh_token, key_id=conn.encryption_key_id
            )
            # Check key rotation
            new_ciphertext, new_key_id, did_reencrypt = encryption_svc.reencrypt_if_needed(
                conn.encrypted_refresh_token, conn.encryption_key_id
            )
            if did_reencrypt:
                conn.encrypted_refresh_token = new_ciphertext
                conn.encryption_key_id = new_key_id
                conn.updated_at = datetime.now(timezone.utc)
                session.add(conn)
                session.commit()

            return plaintext
        except (EncryptionKeyError, DecryptionError):
            return None
