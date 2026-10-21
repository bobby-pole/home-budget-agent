"""Lifecycle, OAuth2 PKCE authorization, and receipt synchronization for external connections."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.adapters.lidl_poc_client import (
    AuthorizationAttempt,
    LidlPoCClient,
    MerchantRequestError,
    OAuthCallbackError,
    TicketMappingError,
    extract_ticket_list_entries,
    get_lidl_live_config,
    lidl_ticket_to_canonical,
)
from app.core.encryption import DecryptionError, EncryptionKeyError, get_encryption_service
from app.models import (
    BudgetMember,
    Category,
    ConnectionDisconnectResponse,
    ConnectionErrorCode,
    ConnectionOAuthCallbackRequest,
    ConnectionOAuthStartResponse,
    ConnectionStatus,
    ConnectionSyncNowResponse,
    ExternalReceiptConnection,
    ExternalReceiptConnectionCreate,
    ExternalReceiptConnectionRead,
    ReceiptScan,
    ScanStatus,
    Transaction,
    TransactionLine,
    User,
)


CONNECTION_WRITE_ROLES = {"owner", "editor"}

# Ephemeral in-memory store of active PKCE authorization attempts keyed by connection_id
_PENDING_OAUTH_ATTEMPTS: dict[int, tuple[AuthorizationAttempt, datetime]] = {}
_OAUTH_ATTEMPT_TTL = timedelta(minutes=15)


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
    def start_oauth(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
        client_override: Optional[LidlPoCClient] = None,
    ) -> ConnectionOAuthStartResponse:
        """Generate an OAuth2 PKCE S256 authorization URL and bind it to the connection."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.provider != "lidl":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Live OAuth PKCE flow is currently only supported for Lidl Plus (got '{conn.provider}')",
            )
        try:
            get_encryption_service().primary_key_id
        except EncryptionKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Store authorization is not configured on this server",
            ) from exc
        lidl_client = client_override or LidlPoCClient(get_lidl_live_config())
        attempt = lidl_client.create_authorization_attempt()
        authorize_url = lidl_client.build_authorize_url(attempt)
        _PENDING_OAUTH_ATTEMPTS[conn.id or 0] = (attempt, datetime.now(timezone.utc))
        return ConnectionOAuthStartResponse(
            connection_id=conn.id or 0,
            provider=conn.provider,
            authorize_url=authorize_url,
            state=attempt.state,
            redirect_uri=lidl_client.config.redirect_uri,
        )

    @staticmethod
    def complete_oauth_callback(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
        data: ConnectionOAuthCallbackRequest,
        client_override: Optional[LidlPoCClient] = None,
    ) -> ExternalReceiptConnectionRead:
        """Validate callback URL/code, exchange PKCE code for tokens, and persist encrypted refresh_token."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.provider != "lidl":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Live OAuth PKCE flow is currently only supported for Lidl Plus (got '{conn.provider}')",
            )

        pending = _PENDING_OAUTH_ATTEMPTS.get(conn.id or 0)
        if not pending:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active OAuth authorization attempt found. Start authorization first.",
            )
        attempt, created_at = pending
        if datetime.now(timezone.utc) - created_at > _OAUTH_ATTEMPT_TTL:
            _PENDING_OAUTH_ATTEMPTS.pop(conn.id or 0, None)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth authorization attempt expired. Please start authorization again.",
            )

        lidl_client = client_override or LidlPoCClient(get_lidl_live_config())
        try:
            code = lidl_client.validate_callback(
                data.callback_url_or_code, attempt, allow_raw_code=True
            )
        except OAuthCallbackError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        try:
            token_payload = lidl_client.exchange_code(code, attempt)
        except MerchantRequestError as exc:
            conn.status = ConnectionStatus.REAUTH_REQUIRED
            conn.last_error_code = ConnectionErrorCode.AUTH_EXPIRED.value
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Provider token exchange failed: {exc}",
            ) from exc

        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Provider did not return a refresh_token",
            )

        _PENDING_OAUTH_ATTEMPTS.pop(conn.id or 0, None)
        scopes_str = str(token_payload.get("scope") or " ".join(lidl_client.config.scopes))
        return ConnectionService.complete_authorization(
            session,
            conn,
            refresh_token=refresh_token,
            consented_scopes=scopes_str,
        )

    @staticmethod
    def complete_authorization(
        session: Session,
        connection: ExternalReceiptConnection,
        *,
        refresh_token: str,
        consented_scopes: Optional[str],
    ) -> ExternalReceiptConnectionRead:
        """Persist an adapter's server-side authorization result, encrypted at rest."""
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
    def _ingest_lidl_canonical_receipt(
        session: Session,
        budget_id: int,
        user_id: int,
        ticket_id: str,
        raw_ticket: dict,
    ) -> tuple[bool, bool]:
        """Map a Lidl v3 ticket to CanonicalReceipt and persist it in ReceiptScan/Transaction inbox.

        Returns (imported, skipped). Raises TicketMappingError on invalid payload.
        """
        content_hash = hashlib.sha256(f"lidl_plus:{budget_id}:{ticket_id}".encode("utf-8")).hexdigest()
        existing_scan = session.exec(
            select(ReceiptScan).where(
                ReceiptScan.content_hash == content_hash,
                ReceiptScan.transaction_id.in_(  # type: ignore
                    select(Transaction.id).where(Transaction.budget_id == budget_id)
                ),
            )
        ).first()
        if existing_scan:
            return False, True

        canonical = lidl_ticket_to_canonical(raw_ticket)
        receipt_dict = canonical.to_dict()

        db_categories = session.exec(
            select(Category).where(
                (Category.budget_id == budget_id) | (Category.is_system)
            )
        ).all()
        cat_dicts = [{"id": c.id, "name": c.name} for c in db_categories if c.id is not None]
        if cat_dicts:
            try:
                from app.services import AIService

                categorized = AIService._categorize_parsed_items(receipt_dict, cat_dicts, user_id)
                if categorized:
                    receipt_dict = categorized
            except Exception:
                pass

        try:
            tx_date = datetime.strptime(canonical.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            tx_date = datetime.now(timezone.utc)

        tx = Transaction(
            merchant_name=canonical.merchant_name,
            total_amount=float(canonical.total_amount),
            currency=canonical.currency,
            date=tx_date,
            is_manual=False,
            type="expense",
            uploaded_by=user_id,
            budget_id=budget_id,
            import_hash=content_hash,
            note=f"Lidl Plus #{ticket_id}",
        )
        session.add(tx)
        session.flush()  # Persist the receipt and all its lines in one transaction.

        needs_review = canonical.get("validation_status") != "verified"
        scan = ReceiptScan(
            transaction_id=tx.id or 0,
            image_path=None,
            status=ScanStatus.NEEDS_REVIEW.value if needs_review else ScanStatus.CATEGORIZATION_OK.value,
            content_hash=content_hash,
            needs_review=needs_review,
            validation_message=canonical.get("validation_error"),
        )
        session.add(scan)

        cat_name_to_id = {c.name.lower(): c.id for c in db_categories if c.id is not None}
        for item_raw in receipt_dict.get("items", []):
            cat_name = str(item_raw.get("category") or "").strip().lower()
            cat_id = cat_name_to_id.get(cat_name) if cat_name else None
            orig = item_raw.get("original_price")
            fin = item_raw.get("final_price")
            session.add(
                TransactionLine(
                    name=str(item_raw.get("name") or "Pozycja"),
                    price=float(item_raw.get("price", 0.0)),
                    quantity=float(item_raw.get("quantity", 1.0)),
                    category_id=cat_id,
                    category_source=item_raw.get("category_source"),
                    transaction_id=tx.id,
                    original_price=float(orig) if orig is not None else None,
                    discount_total=float(item_raw.get("discount_total", 0.0)),
                    final_price=float(fin) if fin is not None else None,
                    is_adjustment=bool(item_raw.get("is_adjustment", False)),
                )
            )

        session.commit()
        return True, False

    @staticmethod
    def trigger_sync_now(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
        *,
        execute_live: bool = False,
        max_tickets: int = 10,
        client_override: Optional[LidlPoCClient] = None,
    ) -> ConnectionSyncNowResponse:
        """Queue or execute synchronization for an authorised, active connection owned by the caller."""
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

        if not execute_live or conn.provider != "lidl":
            return ConnectionSyncNowResponse(
                connection_id=conn.id or 0,
                status=ConnectionStatus(conn.status),
                sync_requested_at=now,
                message="Synchronization request recorded. Processing requires a configured provider adapter and background worker.",
            )

        refresh_token = ConnectionService.get_decrypted_token(session, conn)
        if not refresh_token:
            session.refresh(conn)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored connection token could not be decrypted; re-authorization required.",
            )

        lidl_client = client_override or LidlPoCClient(get_lidl_live_config())
        try:
            token_data = lidl_client.refresh_access_token(refresh_token)
        except MerchantRequestError as exc:
            if exc.status_code in (400, 401, 403):
                conn.status = ConnectionStatus.REAUTH_REQUIRED
                conn.last_error_code = ConnectionErrorCode.AUTH_EXPIRED.value
            else:
                conn.status = ConnectionStatus.SYNC_ERROR
                conn.last_error_code = ConnectionErrorCode.NETWORK_ERROR.value
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Lidl token refresh failed: {exc}",
            ) from exc

        access_token = str(token_data.get("access_token") or "").strip()
        new_refresh_token = str(token_data.get("refresh_token") or "").strip()
        if not access_token:
            conn.status = ConnectionStatus.SYNC_ERROR
            conn.last_error_code = ConnectionErrorCode.SYNC_FAILED.value
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Lidl token refresh did not return an access_token",
            )

        # Rotate refresh token if Lidl issued a new one
        if new_refresh_token:
            ciphertext, key_id = get_encryption_service().encrypt(new_refresh_token)
            conn.encrypted_refresh_token = ciphertext
            conn.encryption_key_id = key_id

        try:
            list_payload = lidl_client.get_tickets_list(access_token, page_number=1)
        except MerchantRequestError as exc:
            conn.status = ConnectionStatus.SYNC_ERROR
            conn.last_error_code = (
                ConnectionErrorCode.RATE_LIMITED.value
                if exc.status_code == 429
                else ConnectionErrorCode.SYNC_FAILED.value
            )
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch Lidl ticket list: {exc}",
            ) from exc

        entries = extract_ticket_list_entries(list_payload)[:max_tickets]
        imported_count = 0
        skipped_count = 0
        failed_count = 0

        for entry in entries:
            ticket_id = str(entry.get("id") or "").strip()
            if not ticket_id:
                failed_count += 1
                continue
            try:
                raw_ticket = lidl_client.get_ticket_detail(access_token, ticket_id)
                imported, skipped = ConnectionService._ingest_lidl_canonical_receipt(
                    session, budget_id, user.id or 0, ticket_id, raw_ticket
                )
                if imported:
                    imported_count += 1
                elif skipped:
                    skipped_count += 1
            except (MerchantRequestError, TicketMappingError):
                failed_count += 1

        finish_now = datetime.now(timezone.utc)
        conn.status = ConnectionStatus.SYNC_ERROR if failed_count else ConnectionStatus.ACTIVE
        conn.last_error_code = ConnectionErrorCode.SYNC_FAILED.value if failed_count else None
        if not failed_count:
            conn.last_success_at = finish_now
        conn.sync_requested_at = None
        # Scheduling is delivered by #257; do not advertise a nonexistent next run.
        conn.next_sync_at = None
        conn.updated_at = finish_now
        session.add(conn)
        session.commit()
        session.refresh(conn)

        return ConnectionSyncNowResponse(
            connection_id=conn.id or 0,
            status=ConnectionStatus(conn.status),
            sync_requested_at=finish_now,
            message=f"Synchronizacja zakończona: pobrano {imported_count} nowych paragonów (pominięto duplikatów: {skipped_count}, błędów: {failed_count}).",
            imported_count=imported_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
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
        conn.sync_requested_at = None
        conn.next_sync_at = None
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
