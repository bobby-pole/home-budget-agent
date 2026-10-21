"""Lifecycle and authorization policy for external receipt connections.

This module deliberately does not expose merchant credentials through the web
API. A future approved provider adapter completes authorization server-side and
calls :meth:`complete_authorization`; the public API can only create a local
placeholder and manage its lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.encryption import DecryptionError, EncryptionKeyError, get_encryption_service
from app.models import (
    BudgetMember,
    ConnectionDisconnectResponse,
    ConnectionErrorCode,
    ConnectionStatus,
    ConnectionSyncNowResponse,
    ExternalReceiptConnection,
    ExternalReceiptConnectionCreate,
    ExternalReceiptConnectionRead,
    User,
)


CONNECTION_WRITE_ROLES = {"owner", "editor"}


def to_read_dto(conn: ExternalReceiptConnection) -> ExternalReceiptConnectionRead:
    """Return the public, credential-free representation of a connection."""
    return ExternalReceiptConnectionRead(
        id=conn.id or 0,
        budget_id=conn.budget_id,
        owner_user_id=conn.owner_user_id,
        provider=conn.provider,
        consented_scopes=conn.consented_scopes,
        consented_at=conn.consented_at,
        status=ConnectionStatus(conn.status),
        has_token=bool(conn.encrypted_refresh_token),
        last_success_at=conn.last_success_at,
        last_error_code=conn.last_error_code,
        next_sync_at=conn.next_sync_at,
        sync_requested_at=conn.sync_requested_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


class ConnectionService:
    """Orchestrates a per-user, per-budget connection lifecycle."""

    @staticmethod
    def _require_write_member(session: Session, budget_id: int, user: User) -> None:
        membership = session.exec(
            select(BudgetMember).where(
                BudgetMember.budget_id == budget_id,
                BudgetMember.user_id == user.id,
            )
        ).first()
        if not membership or membership.role not in CONNECTION_WRITE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only budget owners and editors can manage receipt connections",
            )

    @staticmethod
    def list_connections(
        session: Session, budget_id: int, user: User
    ) -> list[ExternalReceiptConnectionRead]:
        """List only connections owned by the authenticated household member."""
        connections = session.exec(
            select(ExternalReceiptConnection).where(
                ExternalReceiptConnection.budget_id == budget_id,
                ExternalReceiptConnection.owner_user_id == user.id,
            )
        ).all()
        return [to_read_dto(connection) for connection in connections]

    @staticmethod
    def get_connection(
        session: Session, budget_id: int, connection_id: int, user: User
    ) -> ExternalReceiptConnection:
        """Fetch an owned connection without disclosing another member's record."""
        conn = session.get(ExternalReceiptConnection, connection_id)
        if not conn or conn.budget_id != budget_id or conn.owner_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        return conn

    @staticmethod
    def create_connection(
        session: Session,
        budget_id: int,
        user: User,
        data: ExternalReceiptConnectionCreate,
    ) -> ExternalReceiptConnectionRead:
        """Create an unauthorised placeholder; credentials are never accepted here."""
        ConnectionService._require_write_member(session, budget_id, user)
        provider_clean = data.provider.strip().lower()
        if not provider_clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provider cannot be blank",
            )

        existing = session.exec(
            select(ExternalReceiptConnection).where(
                ExternalReceiptConnection.budget_id == budget_id,
                ExternalReceiptConnection.owner_user_id == user.id,
                ExternalReceiptConnection.provider == provider_clean,
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A connection for this provider already exists for this user",
            )

        now = datetime.now(timezone.utc)
        connection = ExternalReceiptConnection(
            budget_id=budget_id,
            owner_user_id=user.id or 0,
            provider=provider_clean,
            status=ConnectionStatus.REAUTH_REQUIRED,
            last_error_code=ConnectionErrorCode.REAUTH_REQUIRED.value,
            created_at=now,
            updated_at=now,
        )
        session.add(connection)
        session.commit()
        session.refresh(connection)
        return to_read_dto(connection)

    @staticmethod
    def complete_authorization(
        session: Session,
        connection: ExternalReceiptConnection,
        *,
        refresh_token: str,
        consented_scopes: Optional[str],
    ) -> ExternalReceiptConnectionRead:
        """Persist an adapter's server-side authorization result, encrypted at rest.

        This is intentionally not routed through FastAPI. Only a future approved
        adapter callback may provide credentials to this boundary.
        """
        token_clean = refresh_token.strip()
        if not token_clean:
            raise ValueError("Authorization result must include a refresh token")
        try:
            ciphertext, key_id = get_encryption_service().encrypt(token_clean)
        except EncryptionKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token encryption service is not configured (fail-closed)",
            ) from exc

        now = datetime.now(timezone.utc)
        connection.encrypted_refresh_token = ciphertext
        connection.encryption_key_id = key_id
        connection.consented_scopes = consented_scopes
        connection.consented_at = now
        connection.status = ConnectionStatus.ACTIVE
        connection.last_error_code = None
        connection.updated_at = now
        session.add(connection)
        session.commit()
        session.refresh(connection)
        return to_read_dto(connection)

    @staticmethod
    def trigger_sync_now(
        session: Session, budget_id: int, connection_id: int, user: User
    ) -> ConnectionSyncNowResponse:
        """Queue sync only for an authorised, active connection owned by the caller."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.status != ConnectionStatus.ACTIVE or not conn.encrypted_refresh_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Connection requires a completed authorization before synchronization",
            )

        now = datetime.now(timezone.utc)
        conn.sync_requested_at = now
        conn.updated_at = now
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return ConnectionSyncNowResponse(
            connection_id=conn.id or 0,
            status=ConnectionStatus(conn.status),
            sync_requested_at=now,
            message="Synchronization requested and queued. Background sync worker will process this request.",
        )

    @staticmethod
    def reconnect(
        session: Session, budget_id: int, connection_id: int, user: User
    ) -> ExternalReceiptConnectionRead:
        """Move an owned connection to the authorization-required state."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        conn.status = ConnectionStatus.REAUTH_REQUIRED
        conn.last_error_code = ConnectionErrorCode.REAUTH_REQUIRED.value
        conn.updated_at = datetime.now(timezone.utc)
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return to_read_dto(conn)

    @staticmethod
    def disconnect(
        session: Session, budget_id: int, connection_id: int, user: User
    ) -> ConnectionDisconnectResponse:
        """Atomically erase local credentials for a connection owned by the caller."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        conn.encrypted_refresh_token = None
        conn.encryption_key_id = None
        conn.status = ConnectionStatus.DISCONNECTED
        conn.last_error_code = ConnectionErrorCode.PROVIDER_REVOCATION_UNAVAILABLE.value
        conn.updated_at = datetime.now(timezone.utc)
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return ConnectionDisconnectResponse(
            connection_id=conn.id or 0,
            status=ConnectionStatus(conn.status),
            revocation_status="provider_revocation_unavailable",
            message="Stored tokens and credentials deleted locally. Remote provider revocation is not available.",
        )

    @staticmethod
    def get_decrypted_token(session: Session, conn: ExternalReceiptConnection) -> Optional[str]:
        """Return a worker-only token and fail visibly if it cannot be decrypted."""
        if conn.status != ConnectionStatus.ACTIVE or not conn.encrypted_refresh_token:
            return None

        try:
            encryption_service = get_encryption_service()
            plaintext = encryption_service.decrypt(
                conn.encrypted_refresh_token, key_id=conn.encryption_key_id
            )
            ciphertext, key_id, did_reencrypt = encryption_service.reencrypt_if_needed(
                conn.encrypted_refresh_token, conn.encryption_key_id
            )
            if did_reencrypt:
                conn.encrypted_refresh_token = ciphertext
                conn.encryption_key_id = key_id
                conn.updated_at = datetime.now(timezone.utc)
                session.add(conn)
                session.commit()
            return plaintext
        except EncryptionKeyError:
            ConnectionService._mark_reauth_required(
                session, conn, ConnectionErrorCode.ENCRYPTION_KEY_MISSING
            )
        except DecryptionError:
            ConnectionService._mark_reauth_required(
                session, conn, ConnectionErrorCode.TOKEN_DECRYPTION_FAILED
            )
        return None

    @staticmethod
    def _mark_reauth_required(
        session: Session,
        conn: ExternalReceiptConnection,
        error_code: ConnectionErrorCode,
    ) -> None:
        """Persist a visible failure without deleting recoverable ciphertext."""
        conn.status = ConnectionStatus.REAUTH_REQUIRED
        conn.last_error_code = error_code.value
        conn.updated_at = datetime.now(timezone.utc)
        session.add(conn)
        session.commit()
