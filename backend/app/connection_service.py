"""Lifecycle, OAuth2 PKCE authorization, and receipt synchronization for external connections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
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
)
from app.adapters.receipt_adapters import LidlPlusReceiptAdapter
from app.config import settings
from app.core.encryption import DecryptionError, EncryptionKeyError, get_encryption_service
from app.import_scheduler import (
    SyncExecutionOutcome,
    cancel_pending_jobs_for_connection,
    complete_pending_jobs_for_connection,
    enqueue_connection_sync_job,
    get_provider_policy,
    is_trusted_worker_environment,
    sanitize_cursor,
)
from app.ingestion_service import ingest_receipt_result
from app.models import (
    BudgetMember,
    ConnectionDisconnectResponse,
    ConnectionErrorCode,
    ConnectionOAuthCallbackRequest,
    ConnectionOAuthStartResponse,
    ConnectionStatus,
    ConnectionSyncNowResponse,
    ExternalReceiptConnection,
    ExternalReceiptConnectionCreate,
    ExternalReceiptConnectionRead,
    ImportJob,
    User,
    ensure_tz_aware,
)


CONNECTION_WRITE_ROLES = {"owner", "editor"}

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
        is_enabled=bool(conn.is_enabled),
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
    def require_trusted_local_execution() -> None:
        """Fail closed when merchant credential or live sync endpoints are called outside trusted_local."""
        if not is_trusted_worker_environment():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Merchant authorization and live synchronization are restricted to the "
                    "trusted local executor (IMPORT_WORKER_ROLE=trusted_local)."
                ),
            )

    @staticmethod
    def require_provider_enabled(provider: str) -> None:
        """Fail closed with 503 when a specific connector is independently disabled."""
        if not settings.is_provider_enabled(provider):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"The {provider.capitalize()} connector is currently disabled; "
                    "manual receipt uploads remain available."
                ),
            )

    @staticmethod
    def _clear_oauth_attempt(conn: ExternalReceiptConnection) -> None:
        conn.encrypted_oauth_attempt = None
        conn.oauth_attempt_key_id = None
        conn.oauth_attempt_expires_at = None

    @staticmethod
    def clear_pending_oauth_attempt(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
    ) -> None:
        """Clear any pending PKCE authorization attempt after a cancelled/aborted desktop login."""
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.encrypted_oauth_attempt is not None or conn.oauth_attempt_expires_at is not None:
            ConnectionService._clear_oauth_attempt(conn)
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()

    @staticmethod
    def _save_oauth_attempt(
        session: Session,
        conn: ExternalReceiptConnection,
        attempt: AuthorizationAttempt,
    ) -> None:
        payload = json.dumps(
            {
                "code_verifier": attempt.code_verifier,
                "state": attempt.state,
                "nonce": attempt.nonce,
            }
        )
        try:
            ciphertext, key_id = get_encryption_service().encrypt(payload)
        except EncryptionKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Store authorization is not configured on this server",
            ) from exc

        now = datetime.now(timezone.utc)
        conn.encrypted_oauth_attempt = ciphertext
        conn.oauth_attempt_key_id = key_id
        conn.oauth_attempt_expires_at = now + _OAUTH_ATTEMPT_TTL
        conn.updated_at = now
        session.add(conn)
        session.commit()

    @staticmethod
    def _load_oauth_attempt(
        session: Session,
        conn: ExternalReceiptConnection,
    ) -> AuthorizationAttempt:
        if not conn.encrypted_oauth_attempt or conn.oauth_attempt_expires_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active OAuth authorization attempt found. Start authorization first.",
            )

        expires_at = ensure_tz_aware(conn.oauth_attempt_expires_at)
        now = datetime.now(timezone.utc)
        if not isinstance(expires_at, datetime) or expires_at <= now:
            ConnectionService._clear_oauth_attempt(conn)
            conn.updated_at = now
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth authorization attempt expired. Please start authorization again.",
            )

        try:
            plaintext = get_encryption_service().decrypt(
                conn.encrypted_oauth_attempt,
                key_id=conn.oauth_attempt_key_id,
            )
            data = json.loads(plaintext)
            verifier = str(data["code_verifier"])
            state = str(data["state"])
            nonce = str(data["nonce"])
        except EncryptionKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Store authorization is not configured on this server",
            ) from exc
        except (DecryptionError, KeyError, TypeError, ValueError) as exc:
            ConnectionService._clear_oauth_attempt(conn)
            conn.updated_at = now
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stored OAuth authorization attempt is invalid. Please start authorization again.",
            ) from exc

        return AuthorizationAttempt(code_verifier=verifier, state=state, nonce=nonce)

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
        """Generate an OAuth2 PKCE S256 authorization URL and persist the encrypted attempt."""
        ConnectionService.require_trusted_local_execution()
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.provider != "lidl":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Live OAuth PKCE flow is currently only supported for Lidl Plus (got '{conn.provider}')",
            )
        ConnectionService.require_provider_enabled(conn.provider)
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
        ConnectionService._save_oauth_attempt(session, conn, attempt)
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
        allow_raw_code: bool = True,
    ) -> ExternalReceiptConnectionRead:
        """Validate callback URL/code, exchange PKCE code for tokens, and persist encrypted refresh_token."""
        ConnectionService.require_trusted_local_execution()
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        if conn.provider != "lidl":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Live OAuth PKCE flow is currently only supported for Lidl Plus (got '{conn.provider}')",
            )
        ConnectionService.require_provider_enabled(conn.provider)

        attempt = ConnectionService._load_oauth_attempt(session, conn)

        lidl_client = client_override or LidlPoCClient(get_lidl_live_config())
        try:
            code = lidl_client.validate_callback(
                data.callback_url_or_code, attempt, allow_raw_code=allow_raw_code
            )
        except OAuthCallbackError as exc:
            if getattr(exc, "error_code", None) == ConnectionErrorCode.MFA_REQUIRED.value:
                ConnectionService._clear_oauth_attempt(conn)
                conn.status = ConnectionStatus.REAUTH_REQUIRED
                conn.last_error_code = ConnectionErrorCode.MFA_REQUIRED.value
                conn.updated_at = datetime.now(timezone.utc)
                session.add(conn)
                session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        try:
            token_payload = lidl_client.exchange_code(code, attempt)
        except MerchantRequestError as exc:
            _, err_code, _ = ConnectionService._classify_merchant_error(
                exc, is_token_refresh=True
            )
            ConnectionService._clear_oauth_attempt(conn)
            conn.status = ConnectionStatus.REAUTH_REQUIRED
            conn.last_error_code = (
                ConnectionErrorCode.MFA_REQUIRED.value
                if err_code == ConnectionErrorCode.MFA_REQUIRED
                else ConnectionErrorCode.AUTH_EXPIRED.value
            )
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Provider token exchange failed: {exc}",
            ) from exc

        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        if not refresh_token:
            ConnectionService._clear_oauth_attempt(conn)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Provider did not return a refresh_token",
            )

        ConnectionService._clear_oauth_attempt(conn)
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
        connection.next_sync_at = now
        connection.updated_at = now
        session.add(connection)
        session.commit()
        session.refresh(connection)
        enqueue_connection_sync_job(session, connection, next_retry_at=now, commit=True)
        return to_read_dto(connection)

    @staticmethod
    def _ingest_lidl_canonical_receipt(
        session: Session,
        budget_id: int,
        user_id: int,
        ticket_id: str,
        raw_ticket: dict,
        *,
        connection_id: Optional[int] = None,
    ) -> tuple[bool, bool]:
        """Map a Lidl v3 ticket via ``LidlPlusReceiptAdapter`` and commit via shared ingestion.

        Returns (imported, skipped). Raises TicketMappingError on invalid payload.
        """
        clean_ticket_id = ticket_id.strip()
        result = LidlPlusReceiptAdapter().extract(
            raw_ticket,
            budget_id=budget_id,
            connection_id=connection_id,
            ticket_id=clean_ticket_id,
        )
        outcome = ingest_receipt_result(
            session,
            result,
            budget_id=budget_id,
            user_id=user_id,
            note=f"Lidl Plus #{clean_ticket_id}",
            categorize=True,
            commit=True,
        )
        return outcome.imported, outcome.skipped

    @staticmethod
    def _classify_merchant_error(
        exc: MerchantRequestError,
        *,
        is_token_refresh: bool = False,
    ) -> tuple[str, ConnectionErrorCode, Optional[int]]:
        """Classify a provider HTTP/network failure as transient or permanent."""
        status_code = exc.status_code
        retry_after = exc.retry_after_seconds
        if getattr(exc, "error_hint", None) == "mfa_required":
            return ("permanent", ConnectionErrorCode.MFA_REQUIRED, None)
        if is_token_refresh and status_code in (400, 401, 403):
            return ("permanent", ConnectionErrorCode.AUTH_EXPIRED, None)
        if not is_token_refresh and status_code in (401, 403):
            return ("permanent", ConnectionErrorCode.AUTH_EXPIRED, None)
        if status_code == 429:
            return ("transient", ConnectionErrorCode.RATE_LIMITED, retry_after)
        if status_code is not None and status_code >= 500:
            return ("transient", ConnectionErrorCode.PROVIDER_UNAVAILABLE, retry_after)
        if status_code is None:
            return ("transient", ConnectionErrorCode.NETWORK_ERROR, None)
        return ("permanent", ConnectionErrorCode.SYNC_FAILED, None)

    @staticmethod
    def _safe_lidl_cursor_from_top_id(
        top_id: Optional[str], previous_cursor: Optional[str]
    ) -> Optional[str]:
        """Build an opaque, non-secret checkpoint cursor string."""
        if top_id:
            try:
                return sanitize_cursor(f"latest:{top_id}")
            except ValueError:
                pass
        return previous_cursor or "page:1"

    @staticmethod
    def _parse_lidl_cursor(cursor: Optional[str]) -> tuple[int, Optional[str]]:
        """Parse page number and known newest ticket ID from opaque cursor."""
        if not cursor:
            return (1, None)
        page_number = 1
        latest_id: Optional[str] = None
        for part in cursor.split("|"):
            piece = part.strip()
            if piece.startswith("page:"):
                suffix = piece.split(":", 1)[1].strip()
                if suffix.isdigit() and int(suffix) >= 1:
                    page_number = int(suffix)
            elif piece.startswith("latest:"):
                candidate = piece.split(":", 1)[1].strip()
                if candidate:
                    latest_id = candidate
        return (page_number, latest_id)

    @staticmethod
    def execute_connection_sync(
        session: Session,
        conn: ExternalReceiptConnection,
        *,
        job: Optional[ImportJob] = None,
        max_tickets: Optional[int] = None,
        max_pages: Optional[int] = None,
        client_override: Optional[LidlPoCClient] = None,
    ) -> SyncExecutionOutcome:
        """Execute a single connector sync pass without raising HTTP errors.

        Shared by both the durable background worker and manual live sync.
        """
        if not is_trusted_worker_environment():
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.SYNC_FAILED,
            )

        if conn.provider != "lidl":
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.SYNC_FAILED,
            )

        if not settings.is_provider_enabled(conn.provider) or not conn.is_enabled:
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.CONNECTOR_DISABLED,
            )

        if conn.status not in (ConnectionStatus.ACTIVE, ConnectionStatus.SYNC_ERROR) or not conn.encrypted_refresh_token:
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.REAUTH_REQUIRED,
            )

        refresh_token = ConnectionService.get_decrypted_token(session, conn)
        if not refresh_token:
            session.refresh(conn)
            code = ConnectionErrorCode.TOKEN_DECRYPTION_FAILED
            if conn.last_error_code == ConnectionErrorCode.ENCRYPTION_KEY_MISSING.value:
                code = ConnectionErrorCode.ENCRYPTION_KEY_MISSING
            elif conn.last_error_code == ConnectionErrorCode.REAUTH_REQUIRED.value:
                code = ConnectionErrorCode.REAUTH_REQUIRED
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=code,
            )

        lidl_client = client_override or LidlPoCClient(get_lidl_live_config())
        try:
            token_data = lidl_client.refresh_access_token(refresh_token)
        except MerchantRequestError as exc:
            classification, err_code, retry_after = ConnectionService._classify_merchant_error(
                exc, is_token_refresh=True
            )
            return SyncExecutionOutcome(
                error_classification=classification,
                error_code=err_code,
                retry_after_seconds=retry_after,
            )

        access_token = str(token_data.get("access_token") or "").strip()
        new_refresh_token = str(token_data.get("refresh_token") or "").strip()
        if not access_token:
            return SyncExecutionOutcome(
                error_classification="permanent",
                error_code=ConnectionErrorCode.SYNC_FAILED,
            )

        # Rotate refresh token if Lidl issued a new one
        if new_refresh_token:
            ciphertext, key_id = get_encryption_service().encrypt(new_refresh_token)
            conn.encrypted_refresh_token = ciphertext
            conn.encryption_key_id = key_id
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()

        previous_cursor = job.cursor if job else None
        parsed_page, known_latest_id = ConnectionService._parse_lidl_cursor(previous_cursor)
        start_page = 1 if known_latest_id is not None else parsed_page
        effective_max_pages = max(
            1, max_pages if max_pages is not None else settings.get_lidl_sync_max_pages()
        )
        effective_max_tickets = max(
            1, max_tickets if max_tickets is not None else settings.get_lidl_sync_max_tickets()
        )

        imported_count = 0
        skipped_count = 0
        failed_count = 0
        processed_details = 0
        newest_top_id: Optional[str] = None
        seen_ticket_ids: set[str] = set()
        first_ticket_classification: Optional[str] = None
        first_ticket_error_code: Optional[ConnectionErrorCode] = None
        first_retry_after: Optional[int] = None

        for current_page in range(start_page, start_page + effective_max_pages):
            try:
                list_payload = lidl_client.get_tickets_list(access_token, page_number=current_page)
            except MerchantRequestError as exc:
                classification, err_code, retry_after = ConnectionService._classify_merchant_error(
                    exc, is_token_refresh=False
                )
                if imported_count == 0 and skipped_count == 0 and failed_count == 0:
                    return SyncExecutionOutcome(
                        error_classification=classification,
                        error_code=err_code,
                        retry_after_seconds=retry_after,
                    )
                failed_count += 1
                if first_ticket_classification is None:
                    first_ticket_classification = classification
                    first_ticket_error_code = err_code
                    first_retry_after = retry_after
                break

            page_entries = extract_ticket_list_entries(list_payload)
            if not page_entries:
                break

            if newest_top_id is None:
                candidate_top = str(page_entries[0].get("id") or "").strip()
                if candidate_top:
                    newest_top_id = candidate_top

            new_ids_on_page = 0
            reached_known_latest = False
            hit_ticket_cap = False
            abort_sync = False

            for entry in page_entries:
                ticket_id = str(entry.get("id") or "").strip()
                if not ticket_id:
                    failed_count += 1
                    if first_ticket_classification is None:
                        first_ticket_classification = "permanent"
                        first_ticket_error_code = ConnectionErrorCode.PROVIDER_SCHEMA_CHANGED
                    continue
                if known_latest_id is not None and ticket_id == known_latest_id:
                    reached_known_latest = True
                    break
                if ticket_id in seen_ticket_ids:
                    continue
                seen_ticket_ids.add(ticket_id)
                new_ids_on_page += 1

                if processed_details >= effective_max_tickets:
                    hit_ticket_cap = True
                    break
                processed_details += 1

                try:
                    raw_ticket = lidl_client.get_ticket_detail(access_token, ticket_id)
                    imported, skipped = ConnectionService._ingest_lidl_canonical_receipt(
                        session,
                        conn.budget_id,
                        conn.owner_user_id,
                        ticket_id,
                        raw_ticket,
                        connection_id=conn.id,
                    )
                    if imported:
                        imported_count += 1
                    elif skipped:
                        skipped_count += 1
                except MerchantRequestError as exc:
                    failed_count += 1
                    classification, err_code, retry_after = ConnectionService._classify_merchant_error(
                        exc, is_token_refresh=False
                    )
                    if first_ticket_classification is None:
                        first_ticket_classification = classification
                        first_ticket_error_code = err_code
                        first_retry_after = retry_after
                    if err_code in (
                        ConnectionErrorCode.RATE_LIMITED,
                        ConnectionErrorCode.AUTH_EXPIRED,
                        ConnectionErrorCode.MFA_REQUIRED,
                    ):
                        abort_sync = True
                        break
                except TicketMappingError:
                    failed_count += 1
                    if first_ticket_classification is None:
                        first_ticket_classification = "permanent"
                        first_ticket_error_code = ConnectionErrorCode.PROVIDER_SCHEMA_CHANGED

            if abort_sync or reached_known_latest or hit_ticket_cap or new_ids_on_page == 0:
                break

            raw_total_count = list_payload.get("totalCount")
            raw_page_size = list_payload.get("size") or list_payload.get("pageSize")
            if isinstance(raw_total_count, int) and isinstance(raw_page_size, int) and raw_page_size > 0:
                if current_page * raw_page_size >= raw_total_count:
                    break

        if failed_count > 0:
            return SyncExecutionOutcome(
                imported_count=imported_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                next_cursor=previous_cursor,
                error_classification=first_ticket_classification or "transient",
                error_code=first_ticket_error_code or ConnectionErrorCode.SYNC_FAILED,
                retry_after_seconds=first_retry_after,
            )

        next_cursor = ConnectionService._safe_lidl_cursor_from_top_id(
            newest_top_id, previous_cursor
        )
        return SyncExecutionOutcome(
            imported_count=imported_count,
            skipped_count=skipped_count,
            failed_count=0,
            next_cursor=next_cursor,
        )

    @staticmethod
    def trigger_sync_now(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
        *,
        execute_live: bool = False,
        max_tickets: Optional[int] = None,
        max_pages: Optional[int] = None,
        client_override: Optional[LidlPoCClient] = None,
    ) -> ConnectionSyncNowResponse:
        """Queue a durable sync job or execute an immediate live sync pass."""
        ConnectionService.require_trusted_local_execution()
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        ConnectionService.require_provider_enabled(conn.provider)
        if not conn.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Connection synchronization is currently paused; resume it before syncing.",
            )
        if conn.status not in (ConnectionStatus.ACTIVE, ConnectionStatus.SYNC_ERROR) or not conn.encrypted_refresh_token:
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
            enqueue_connection_sync_job(
                session,
                conn,
                next_retry_at=now,
                expedite_if_pending=True,
                commit=True,
            )
            return ConnectionSyncNowResponse(
                connection_id=conn.id or 0,
                status=ConnectionStatus(conn.status),
                sync_requested_at=now,
                message="Synchronization job queued for durable background worker processing.",
            )

        outcome = ConnectionService.execute_connection_sync(
            session,
            conn,
            max_tickets=max_tickets,
            max_pages=max_pages,
            client_override=client_override,
        )
        session.refresh(conn)
        if (
            outcome.error_classification is not None
            and outcome.imported_count == 0
            and outcome.skipped_count == 0
            and outcome.failed_count == 0
        ):
            err_code = outcome.error_code or ConnectionErrorCode.SYNC_FAILED
            if err_code in (
                ConnectionErrorCode.ENCRYPTION_KEY_MISSING,
                ConnectionErrorCode.TOKEN_DECRYPTION_FAILED,
                ConnectionErrorCode.REAUTH_REQUIRED,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Stored connection token could not be decrypted; re-authorization required.",
                )

            if err_code in (ConnectionErrorCode.AUTH_EXPIRED, ConnectionErrorCode.MFA_REQUIRED):
                conn.status = ConnectionStatus.REAUTH_REQUIRED
            else:
                conn.status = ConnectionStatus.SYNC_ERROR
            conn.last_error_code = err_code.value
            conn.sync_requested_at = None
            conn.next_sync_at = None
            conn.updated_at = datetime.now(timezone.utc)
            session.add(conn)
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Lidl synchronization failed ({err_code.value}).",
            )

        finish_now = datetime.now(timezone.utc)
        if outcome.failed_count:
            err_code = outcome.error_code or ConnectionErrorCode.SYNC_FAILED
            if err_code in (
                ConnectionErrorCode.AUTH_EXPIRED,
                ConnectionErrorCode.MFA_REQUIRED,
                ConnectionErrorCode.REAUTH_REQUIRED,
            ):
                conn.status = ConnectionStatus.REAUTH_REQUIRED
            else:
                conn.status = ConnectionStatus.SYNC_ERROR
            conn.last_error_code = err_code.value
            conn.next_sync_at = None
        else:
            conn.status = ConnectionStatus.ACTIVE
            conn.last_error_code = None
            conn.last_success_at = finish_now
            policy = get_provider_policy(conn.provider)
            conn.next_sync_at = finish_now + timedelta(
                seconds=max(60, policy.sync_interval_seconds)
            )
            if conn.id is not None:
                complete_pending_jobs_for_connection(
                    session,
                    connection_id=conn.id,
                    next_cursor=outcome.next_cursor,
                    now=finish_now,
                    commit=False,
                )
        conn.sync_requested_at = None
        conn.updated_at = finish_now
        session.add(conn)
        session.commit()
        session.refresh(conn)

        return ConnectionSyncNowResponse(
            connection_id=conn.id or 0,
            status=ConnectionStatus(conn.status),
            sync_requested_at=finish_now,
            message=(
                f"Synchronizacja zakończona: pobrano {outcome.imported_count} nowych paragonów "
                f"(pominięto duplikatów: {outcome.skipped_count}, błędów: {outcome.failed_count})."
            ),
            imported_count=outcome.imported_count,
            skipped_count=outcome.skipped_count,
            failed_count=outcome.failed_count,
        )

    @staticmethod
    def set_connection_enabled(
        session: Session,
        budget_id: int,
        connection_id: int,
        user: User,
        enabled: bool,
    ) -> ExternalReceiptConnectionRead:
        """Pause or resume automatic synchronization without removing stored credentials."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        now = datetime.now(timezone.utc)
        conn.is_enabled = bool(enabled)
        conn.updated_at = now
        if not conn.is_enabled:
            conn.sync_requested_at = None
            conn.next_sync_at = None
            session.add(conn)
            if conn.id is not None:
                cancel_pending_jobs_for_connection(
                    session,
                    connection_id=conn.id,
                    error_code=ConnectionErrorCode.CONNECTOR_DISABLED,
                    commit=False,
                )
        else:
            if conn.last_error_code == ConnectionErrorCode.CONNECTOR_DISABLED.value:
                conn.last_error_code = None
            if (
                conn.status == ConnectionStatus.ACTIVE
                and conn.encrypted_refresh_token
                and conn.next_sync_at is None
            ):
                conn.next_sync_at = now
            session.add(conn)
        session.commit()
        session.refresh(conn)
        return to_read_dto(conn)

    @staticmethod
    def reconnect(
        session: Session, budget_id: int, connection_id: int, user: User
    ) -> ExternalReceiptConnectionRead:
        """Move an owned connection to the authorization-required state."""
        ConnectionService._require_write_member(session, budget_id, user)
        conn = ConnectionService.get_connection(session, budget_id, connection_id, user)
        ConnectionService._clear_oauth_attempt(conn)
        conn.status = ConnectionStatus.REAUTH_REQUIRED
        conn.last_error_code = ConnectionErrorCode.REAUTH_REQUIRED.value
        conn.next_sync_at = None
        conn.sync_requested_at = None
        conn.updated_at = datetime.now(timezone.utc)
        session.add(conn)
        if conn.id is not None:
            cancel_pending_jobs_for_connection(
                session,
                connection_id=conn.id,
                error_code=ConnectionErrorCode.REAUTH_REQUIRED,
                commit=False,
            )
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
        ConnectionService._clear_oauth_attempt(conn)
        conn.status = ConnectionStatus.DISCONNECTED
        conn.sync_requested_at = None
        conn.next_sync_at = None
        conn.last_error_code = ConnectionErrorCode.PROVIDER_REVOCATION_UNAVAILABLE.value
        conn.updated_at = datetime.now(timezone.utc)
        session.add(conn)
        if conn.id is not None:
            cancel_pending_jobs_for_connection(session, connection_id=conn.id, commit=False)
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
        if conn.status not in (ConnectionStatus.ACTIVE, ConnectionStatus.SYNC_ERROR) or not conn.encrypted_refresh_token:
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
