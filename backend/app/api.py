# backend/app/api.py
import asyncio
import copy
import logging
import shutil
import os
import hashlib
import re
import time
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks, Path, Header, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select, desc, col, delete, SQLModel
from sqlalchemy import extract, func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from .models import (
    Transaction, TransactionLine, TransactionRead, TransactionUpdate,
    TransactionLineUpdate, ManualTransactionCreate, TransferCreate,
    ReceiptScan, ScanStatus, TransactionStatus, VerifyRequest,
    ReviewStatus, AutoMergePolicy,
    ScanUsageLog, SourceRecord, SourceType, RawPayloadPolicy,
    Budget, BudgetMember, BudgetCreate, BudgetUpdate,
    Account, AccountCreate, AccountUpdate, AccountRead,
    MonthlyBudgetSummary, CategoryBudgetSummaryItem, EnvelopeAllocation, EnvelopeAllocationUpdate,
    User, UserCreate, UserRead, Token,
    Category, Tag, CategoryCreate, CategoryUpdate, CategoryRead, TagCreate, TagRead, TagUpdate, TransactionTagLink,
    BudgetMemberCreate, BudgetMemberRead,
    BudgetAlert, AppStatusRead, AppConfigRead,
    UserBudgetRead, ChangePasswordRequest, UserUpdate,
    ExternalReceiptConnection,
    ExternalReceiptConnectionRead, ExternalReceiptConnectionCreate,
    ConnectionSettingsUpdate,
    ImportJob,
    ConnectionSyncNowResponse, ConnectionDisconnectResponse,
    ConnectionOAuthStartResponse, ConnectionOAuthCallbackRequest, ConnectionToggleRequest,
    ReconciliationActionResponse, ReconciliationListResponse, ReconciliationStatus,
    BankCsvPreviewResponse, DuplicateMergeRequest,
    InboxBulkActionResponse, InboxBulkApproveRequest, InboxRejectRequest,
)
from .adapters import (
    AdapterContractError,
    EParagonReceiptAdapter,
    IngCsvTransactionAdapter,
    IngPdfTransactionAdapter,
    OcrPipelineReceiptAdapter,
    parse_ing_pdf_text,
)
from .connection_service import ConnectionService, to_read_dto
from .database import get_session, get_ops_session, operations_engine
from .inbox_service import (
    InboxNotFoundError,
    InboxValidationError,
    approve_inbox_items,
    check_envelope_balance_and_alert,
    list_inbox_items,
    promote_transaction_to_approved,
    reject_transaction_preserving_provenance,
    restore_inbox_item,
)
from .ingestion_service import (
    apply_receipt_result_to_existing_scan,
    ingest_transaction_batch,
    preview_transaction_batch,
)
from .reconciliation_service import (
    ReconciliationConflictError,
    ReconciliationNotFoundError,
    ReconciliationPermissionError,
    accept_reconciliation_link,
    cleanup_reconciliation_before_transaction_delete,
    cleanup_reconciliation_for_budget,
    discover_reconciliation_candidates,
    list_reconciliation_links,
    merge_receipt_duplicate_link,
    reject_reconciliation_link,
    require_reconciliation_write_access,
    unlink_reconciliation_link,
)
from .ocr_pipeline import ReceiptSource, ReceiptSourceDetector
from .provenance_service import (
    build_source_record,
    delete_source_records_for_transaction,
    extract_eparagon_external_id,
    find_existing_source_record,
    has_legacy_scan_duplicate,
    record_manual_source_provenance,
    record_source_provenance,
    update_scan_source_metadata,
)
from .services import AIService
from .category_service import get_budget_categories, seed_default_categories
from .auth import get_current_user, get_current_user_optional, hash_password, verify_password, create_access_token, is_demo_user
from .demo_seed import seed_demo_environment
from .demo_samples_data import SAMPLE_BIEDRONKA_DATA, SAMPLE_LIDL_DATA
from .config import settings
from .money import quantize_money, quantize_unit_price, MoneyDecimal
from typing import List, Optional

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(settings.OCR_WORKER_CONCURRENCY)

router = APIRouter()
# Ensure UPLOAD_DIR is robustly handled
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("/health")
def health_check():
    return {"status": "ok", "message": "Backend is running!"}


@router.get("/config", response_model=AppConfigRead)
def get_app_config():
    from .adapters.lidl_desktop_oauth import is_desktop_oauth_available
    from .import_scheduler import is_trusted_worker_environment

    return AppConfigRead(
        demo_mode=bool(settings.DEMO_MODE),
        environment=settings.ENVIRONMENT,
        import_worker_role=settings.resolve_import_worker_role(),
        trusted_local=is_trusted_worker_environment(),
        desktop_oauth_available=is_desktop_oauth_available(),
        lidl_connector_enabled=settings.is_provider_enabled("lidl"),
    )


# --- DEPENDENCY: resolve current user's budget (lazy-create if missing) ---

def seed_default_account(session: Session, budget_id: int):
    if session.exec(select(Account).where(Account.budget_id == budget_id)).first():
        return
    acc = Account(name="Cash", type="checking", currency="PLN", budget_id=budget_id)
    session.add(acc)
    session.commit()


def ensure_budget_defaults(session: Session, budget_id: int):
    """Seed each default independently so partially migrated budgets are repaired."""
    if not session.exec(select(Category).where(Category.budget_id == budget_id)).first():
        seed_default_categories(session, budget_id)
    seed_default_account(session, budget_id)


def validate_account_category(session: Session, budget_id: int, category_id: Optional[int]):
    if category_id is None:
        return
    category = session.get(Category, category_id)
    if not category or category.budget_id != budget_id:
        raise HTTPException(status_code=422, detail="Category does not belong to the current budget")


def validate_transaction_accounts(
    session: Session,
    budget_id: int,
    account_id: Optional[int],
    transfer_id: Optional[int],
):
    if account_id is not None and transfer_id == account_id:
        raise HTTPException(status_code=422, detail="Transfer source and destination must differ")
    for account_id_to_validate in (account_id, transfer_id):
        if account_id_to_validate is None:
            continue
        account = session.get(Account, account_id_to_validate)
        if not account or account.budget_id != budget_id or not account.is_active:
            raise HTTPException(status_code=422, detail="Account does not belong to the current budget or is inactive")

def get_current_budget(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session),
    x_budget_id: Optional[str] = Header(None),
) -> Budget:
    if x_budget_id:
        try:
            budget_id = int(x_budget_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid X-Budget-Id header")

        membership = session.exec(
            select(BudgetMember).where(
                BudgetMember.user_id == current_user.id,
                BudgetMember.budget_id == budget_id
            )
        ).first()

        if membership:
            budget = session.get(Budget, membership.budget_id)
            if budget:
                if budget.id is not None:
                    ensure_budget_defaults(session, budget.id)
                return budget
        raise HTTPException(status_code=403, detail="Access denied to the requested budget")

    membership = session.exec(
        select(BudgetMember).where(BudgetMember.user_id == current_user.id)
    ).first()

    if membership:
        budget = session.get(Budget, membership.budget_id)
        if budget:
            if budget.id is not None:
                ensure_budget_defaults(session, budget.id)
            return budget

    # Lazy migration: user existed before multi-tenancy — create a default budget on the fly
    new_budget = Budget(name="Domowy", owner_id=current_user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)
    if new_budget.id is None:
        raise HTTPException(status_code=500, detail="Failed to create budget")
    session.add(BudgetMember(budget_id=new_budget.id, user_id=current_user.id, role="owner"))
    session.commit()
    ensure_budget_defaults(session, new_budget.id)
    return new_budget


# --- AUTH ---

@router.post("/auth/register", response_model=Token)
def register(
    user_data: UserCreate,
    session: Session = Depends(get_session),
    ops_session: Session = Depends(get_ops_session)
):
    existing = session.exec(select(User).where(User.email == user_data.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=user_data.email, hashed_password=hash_password(user_data.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    if user.id is None:
        raise HTTPException(status_code=500, detail="Failed to create user")

    # Create default budget for the new user and link user as owner
    new_budget = Budget(name="Domowy", owner_id=user.id)
    ops_session.add(new_budget)
    ops_session.commit()
    ops_session.refresh(new_budget)
    if new_budget.id is None:
        raise HTTPException(status_code=500, detail="Failed to create budget")
    ops_session.add(BudgetMember(budget_id=new_budget.id, user_id=user.id, role="owner"))
    ops_session.commit()

    ensure_budget_defaults(ops_session, new_budget.id)

    token = create_access_token({"sub": user.email})
    return Token(access_token=token, user=UserRead(id=user.id, email=user.email, default_budget_id=user.default_budget_id, created_at=user.created_at))


@router.post("/auth/login", response_model=Token)
def login(user_data: UserCreate, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == user_data.email)).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    token = create_access_token({"sub": user.email})
    return Token(access_token=token, user=UserRead(id=user.id, email=user.email, default_budget_id=user.default_budget_id, created_at=user.created_at))


@router.post("/auth/demo", response_model=Token)
def login_demo(
    x_demo_session_id: Optional[str] = Header(None, alias="X-Demo-Session-ID"),
    x_demo_locale: Optional[str] = Header(None, alias="X-Demo-Locale"),
    accept_language: Optional[str] = Header(None, alias="Accept-Language"),
    ops_session: Session = Depends(get_ops_session),
):
    """
    Authenticate as the demo user for showcase/recruitment evaluation.
    If X-Demo-Session-ID is provided, ensures an isolated ephemeral demo user
    and budget for this recruiter session.
    """
    locale = x_demo_locale or (accept_language.split(",")[0].split("-")[0] if accept_language else "pl")
    if locale not in ("pl", "en"):
        locale = "pl"

    if x_demo_session_id:
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", x_demo_session_id)[:32]
        if clean_id:
            logger.info("Ephemeral demo login request: session=%s, locale=%s", clean_id, locale)
            ephemeral_email = f"demo_{clean_id}@rachownik.app"
            user = ops_session.exec(select(User).where(User.email == ephemeral_email)).first()
            if not user:
                from .demo_seed import DEMO_USER_PASSWORD
                user = User(
                    email=ephemeral_email,
                    hashed_password=hash_password(DEMO_USER_PASSWORD),
                    created_at=datetime.now(timezone.utc),
                )
                ops_session.add(user)
                ops_session.commit()
                ops_session.refresh(user)
                demo_user = seed_demo_environment(ops_session, force_reset=False, custom_user=user)
            else:
                demo_user = seed_demo_environment(ops_session, force_reset=False, custom_user=user)
            token = create_access_token({"sub": demo_user.email})
            assert demo_user.id is not None
            return Token(
                access_token=token,
                user=UserRead(
                    id=demo_user.id,
                    email=demo_user.email,
                    default_budget_id=demo_user.default_budget_id,
                    created_at=demo_user.created_at,
                ),
            )

    demo_user = seed_demo_environment(ops_session, force_reset=False)
    token = create_access_token({"sub": demo_user.email})
    assert demo_user.id is not None
    return Token(
        access_token=token,
        user=UserRead(
            id=demo_user.id,
            email=demo_user.email,
            default_budget_id=demo_user.default_budget_id,
            created_at=demo_user.created_at,
        ),
    )


@router.post("/auth/demo/reset")
def reset_demo(
    current_user: Optional[User] = Depends(get_current_user_optional),
    ops_session: Session = Depends(get_ops_session),
):
    """
    Reset demo environment back to baseline state.
    Allowed for authenticated demo user or when DEMO_MODE=True.
    """
    user_is_demo = is_demo_user(current_user)
    if not user_is_demo and not settings.DEMO_MODE:
        raise HTTPException(
            status_code=403,
            detail="Resetting demo data is only permitted for the demo user or when DEMO_MODE is active.",
        )
    target_user = ops_session.get(User, current_user.id) if (current_user and current_user.id and user_is_demo) else None
    seed_demo_environment(ops_session, force_reset=True, custom_user=target_user)
    return {"status": "ok", "message": "Demo data reset successfully"}


@router.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/users/me", response_model=UserRead)
def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Demo account profile cannot be modified")

    if data.default_budget_id is not None:
        membership = session.exec(
            select(BudgetMember).where(
                BudgetMember.user_id == current_user.id,
                BudgetMember.budget_id == data.default_budget_id
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=403, detail="Not a member of this budget")
        current_user.default_budget_id = data.default_budget_id

    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.post("/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Demo account password cannot be changed")

    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid old password")

    current_user.hashed_password = hash_password(data.new_password)
    session.add(current_user)
    session.commit()
    return {"status": "ok"}


@router.get("/users/me/budgets", response_model=List[UserBudgetRead])
def get_my_budgets(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session)
):
    memberships = session.exec(
        select(BudgetMember, Budget)
        .join(Budget, col(BudgetMember.budget_id) == Budget.id)
        .where(BudgetMember.user_id == current_user.id)
    ).all()

    return [
        UserBudgetRead(id=b.id or 0, name=b.name, role=m.role)
        for m, b in memberships
    ]


@router.delete("/budgets/{budget_id}")
def delete_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session)
):
    budget = session.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Demo budget cannot be deleted")

    if budget.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete the budget")

    # Counts total budgets the user belongs to, preventing deletion of their last remaining budget access.
    membered_budget_count = session.exec(select(func.count(col(BudgetMember.id))).where(BudgetMember.user_id == current_user.id)).one()
    if membered_budget_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete your only budget.")

    session.exec(delete(BudgetAlert).where(col(BudgetAlert.budget_id) == budget_id))
    session.exec(delete(EnvelopeAllocation).where(col(EnvelopeAllocation.budget_id) == budget_id))
    cleanup_reconciliation_for_budget(session, budget_id=budget_id)
    session.exec(delete(SourceRecord).where(col(SourceRecord.budget_id) == budget_id))
    session.exec(delete(ImportJob).where(col(ImportJob.budget_id) == budget_id))
    session.exec(delete(ExternalReceiptConnection).where(col(ExternalReceiptConnection.budget_id) == budget_id))

    transactions = session.exec(select(Transaction).where(col(Transaction.budget_id) == budget_id)).all()
    for t in transactions:
        session.exec(delete(TransactionLine).where(col(TransactionLine.transaction_id) == t.id))
        session.exec(delete(ReceiptScan).where(col(ReceiptScan.transaction_id) == t.id))
        session.exec(delete(TransactionTagLink).where(col(TransactionTagLink.transaction_id) == t.id))
        session.delete(t)

    session.exec(delete(Tag).where(col(Tag.budget_id) == budget_id))
    session.exec(delete(Category).where(col(Category.budget_id) == budget_id))
    session.exec(delete(BudgetMember).where(col(BudgetMember.budget_id) == budget_id))

    session.delete(budget)
    session.commit()
    return {"status": "ok"}


@router.post("/budgets", response_model=UserBudgetRead)
def create_budget(
    data: BudgetCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session)
):
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Budget creation is disabled in demo mode")

    new_budget = Budget(name=data.name, owner_id=current_user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)

    if new_budget.id is None:
        raise HTTPException(status_code=500, detail="Failed to create budget")

    session.add(BudgetMember(budget_id=new_budget.id, user_id=current_user.id, role="owner"))
    session.commit()

    ensure_budget_defaults(session, new_budget.id)

    return UserBudgetRead(id=new_budget.id, name=new_budget.name, role="owner")


@router.patch("/budgets/{budget_id}", response_model=UserBudgetRead)
def update_budget(
    budget_id: int,
    data: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session)
):
    budget = session.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Demo budget cannot be modified")

    if budget.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit the budget")

    budget.name = data.name
    session.add(budget)
    session.commit()
    session.refresh(budget)

    if budget.id is None:
        raise HTTPException(status_code=500, detail="Invalid budget state")

    return UserBudgetRead(id=budget.id, name=budget.name, role="owner")



# --- ASYNC OCR WORKER ---

def _set_scan_status(
    scan_id: int,
    status: ScanStatus,
    error_message: Optional[str] = None,
    needs_review: Optional[bool] = None,
) -> None:
    with Session(operations_engine) as s:
        scan = s.get(ReceiptScan, scan_id)
        if scan:
            scan.status = status
            if error_message is not None:
                scan.error_message = error_message
            if needs_review is not None:
                scan.needs_review = needs_review
            elif status == ScanStatus.FAILED:
                scan.needs_review = True
            if status == ScanStatus.FAILED:
                update_scan_source_metadata(s, receipt_scan_id=scan_id, quality="0.00")
            s.add(scan)
            s.commit()


async def _process_scan(scan_id: int, transaction_id: int, image_path: str) -> None:
    _set_scan_status(scan_id, ScanStatus.RUNNING)
    logger.info("OCR job started", extra={"scan_id": scan_id, "transaction_id": transaction_id})

    with Session(operations_engine) as session:
        transaction = session.get(Transaction, transaction_id)
        scan = session.get(ReceiptScan, scan_id)

        if not transaction or not scan:
            logger.error("Transaction or ReceiptScan not found", extra={"scan_id": scan_id})
            _set_scan_status(scan_id, ScanStatus.FAILED, error_message="record not found")
            return

        db_categories = (
            get_budget_categories(session, transaction.budget_id)
            if transaction.budget_id is not None
            else []
        )
        cat_dicts = [{"id": c.id, "name": c.name} for c in db_categories]

        stage_start = time.monotonic()
        is_sample_biedronka = bool(scan.content_hash and "sample_biedronka" in scan.content_hash)
        is_sample_lidl = bool(scan.content_hash and "sample_lidl" in scan.content_hash)

        # Real OCR pipeline: always parse via AIService for both custom uploads and sample receipts
        data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: AIService.parse_receipt(image_path, categories=cat_dicts, user_id=transaction.uploaded_by)
        )

        # Resilient fallback ONLY for sample receipts if real pipeline returned no data
        # (e.g. offline unit testing or CI without Vision / OpenAI credentials)
        if not data and (is_sample_biedronka or is_sample_lidl):
            logger.warning(
                "Real OCR pipeline returned no data for sample receipt; falling back to curated sample data",
                extra={"scan_id": scan_id},
            )
            if is_sample_biedronka:
                data = copy.deepcopy(SAMPLE_BIEDRONKA_DATA)
            else:
                data = copy.deepcopy(SAMPLE_LIDL_DATA)
        logger.info(
            "OCR completed",
            extra={"scan_id": scan_id, "duration_ms": int((time.monotonic() - stage_start) * 1000)},
        )

        if not data:
            logger.error("OCR pipeline returned no data", extra={"scan_id": scan_id})
            _set_scan_status(scan_id, ScanStatus.FAILED, error_message="pipeline returned no data")
            return

        _set_scan_status(scan_id, ScanStatus.OCR_OK)

        stage_start = time.monotonic()
        scan2 = session.get(ReceiptScan, scan_id)
        if not scan2:
            return

        is_eparagon_scan = (
            any(sr.source_type == SourceType.E_RECEIPT for sr in (scan2.source_records or []))
            or data.get("_processed_via")
            in ("eparagon_json_adapter", "biedronka_json_parser", "zabka_json_parser")
        )
        adapter_result = OcrPipelineReceiptAdapter.from_pipeline_output(
            data,
            file_hash=scan2.content_hash,
            raw_payload_policy=(
                RawPayloadPolicy.CANONICAL_ONLY
                if is_eparagon_scan
                else RawPayloadPolicy.EPHEMERAL_IMAGE
            ),
        )
        if is_eparagon_scan and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as ep_file:
                    ep_bytes = ep_file.read()
                ep_result = EParagonReceiptAdapter().extract(
                    ep_bytes,
                    budget_id=transaction.budget_id or 0,
                    raw_payload_policy=RawPayloadPolicy.CANONICAL_ONLY,
                )
                adapter_result.warnings = list(
                    dict.fromkeys([*ep_result.warnings, *adapter_result.warnings])
                )
                adapter_result.quality = min(adapter_result.quality, ep_result.quality)
            except AdapterContractError as ep_err:
                logger.warning(
                    "EParagonReceiptAdapter metadata check failed",
                    extra={"scan_id": scan_id, "error": str(ep_err)},
                )
        uploader_is_demo = is_demo_user(transaction.uploader) if transaction.uploader else settings.DEMO_MODE
        final_status = apply_receipt_result_to_existing_scan(
            session,
            scan=scan2,
            transaction=transaction,
            result=adapter_result,
            db_categories=db_categories,
            is_demo_uploader=settings.DEMO_MODE or uploader_is_demo,
        )
        if final_status == ScanStatus.FAILED:
            logger.warning(
                "Validation failed on empty receipt",
                extra={"scan_id": scan_id, "validation_message": adapter_result.validation_message},
            )
        else:
            logger.info(
                "Categorization stage completed",
                extra={"scan_id": scan_id, "duration_ms": int((time.monotonic() - stage_start) * 1000)},
            )
        if scan2.needs_review:
            logger.info("OCR job finished — NEEDS_REVIEW", extra={"scan_id": scan_id, "transaction_id": transaction_id})
        else:
            logger.info("OCR job finished — CATEGORIZATION_OK", extra={"scan_id": scan_id, "transaction_id": transaction_id})


async def _run_with_semaphore(scan_id: int, transaction_id: int, image_path: str) -> None:
    async with _semaphore:
        try:
            await asyncio.wait_for(
                _process_scan(scan_id, transaction_id, image_path),
                timeout=settings.OCR_JOB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "OCR job timed out",
                extra={"scan_id": scan_id, "timeout_s": settings.OCR_JOB_TIMEOUT_SECONDS},
            )
            _set_scan_status(scan_id, ScanStatus.FAILED, error_message="timeout")


async def process_transaction_in_background(transaction_id: int, scan_id: int, image_path: str) -> None:
    """Async entry point for BackgroundTasks — wraps the worker with semaphore and timeout."""
    await _run_with_semaphore(scan_id, transaction_id, image_path)



def _check_envelope_balance_and_alert(session: Session, transaction: Transaction, delta_amount: Decimal | float):
    del delta_amount  # Balance threshold checks inspect net spent vs allocation directly.
    check_envelope_balance_and_alert(session, transaction)


# --- TRANSACTIONS ---

@router.post("/transactions/manual", response_model=TransactionRead)
def create_manual_transaction(
    data: ManualTransactionCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    validate_transaction_accounts(session, current_budget.id, data.account_id, data.transfer_id)
    total = (
        quantize_money(sum((line.price * line.quantity for line in data.lines), Decimal("0.00")))
        if data.lines
        else quantize_money(data.total_amount)
    )

    # Resolve category from account if not provided
    final_category_id = data.category_id
    if not final_category_id and data.account_id:
        acc = session.get(Account, data.account_id)
        if acc and acc.category_id:
            final_category_id = acc.category_id

    if data.type == "transfer" and data.transfer_id is not None:
        source_acc = session.get(Account, data.account_id) if data.account_id else None
        dest_acc = session.get(Account, data.transfer_id)
        if source_acc and dest_acc and source_acc.is_on_budget and not dest_acc.is_on_budget and not final_category_id:
            raise HTTPException(
                status_code=422,
                detail="Category is required for transfers to tracking accounts",
            )

    tx_date = data.date or datetime.now(timezone.utc)
    if tx_date.tzinfo is None:
        tx_date = tx_date.replace(tzinfo=timezone.utc)

    transaction = Transaction(
        merchant_name=data.merchant_name,
        total_amount=total,
        currency=data.currency,
        date=tx_date,
        is_manual=True,
        type=data.type,
        status=data.status,
        uploaded_by=current_user.id,
        budget_id=current_budget.id,
        category_id=final_category_id,
        account_id=data.account_id,
        transfer_id=data.transfer_id,
        note=data.note,
    )

    if data.tag_ids:
        tags = session.exec(select(Tag).where(col(Tag.id).in_(data.tag_ids))).all()
        transaction.tags = list(tags)

    session.add(transaction)
    session.flush()

    if transaction.id is not None and current_budget.id is not None:
        record_manual_source_provenance(
            session,
            budget_id=current_budget.id,
            transaction_id=transaction.id,
        )

    session.commit()
    session.refresh(transaction)

    if data.lines:
        for line_data in data.lines:
            session.add(TransactionLine(
                name=line_data.name,
                price=line_data.price,
                quantity=line_data.quantity,
                category_id=line_data.category_id,
                original_price=line_data.original_price,
                discount_total=line_data.discount_total,
                final_price=line_data.final_price,
                is_adjustment=line_data.is_adjustment,
                transaction_id=transaction.id,
            ))
    elif data.type != "transfer" or final_category_id is not None:
        session.add(TransactionLine(
            name=data.note or ("Transfer" if data.type == "transfer" else "Manual entry"),
            price=data.total_amount,
            quantity=Decimal("1"),
            category_id=final_category_id,
            transaction_id=transaction.id,
        ))

    _check_envelope_balance_and_alert(session, transaction, transaction.total_amount)

    session.commit()
    if current_budget.id is not None:
        discover_reconciliation_candidates(session, budget_id=current_budget.id, commit=True)
    session.refresh(transaction)

    return transaction


# --- TRANSFERS ---

@router.post("/transfers", response_model=TransactionRead)
def create_transfer(
    data: TransferCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    validate_transaction_accounts(
        session, current_budget.id, data.source_account_id, data.destination_account_id
    )

    source_acc = session.get(Account, data.source_account_id)
    dest_acc = session.get(Account, data.destination_account_id)
    if not source_acc or not dest_acc:
        raise HTTPException(status_code=422, detail="Account not found")

    if source_acc.is_on_budget and not dest_acc.is_on_budget and not data.category_id:
        raise HTTPException(
            status_code=422,
            detail="Category is required for transfers to tracking accounts",
        )

    if data.category_id:
        category = session.get(Category, data.category_id)
        if not category or category.budget_id != current_budget.id:
            raise HTTPException(status_code=422, detail="Category not found in current budget")

    merchant_name = f"Transfer: {source_acc.name} -> {dest_acc.name}"

    transaction = Transaction(
        merchant_name=merchant_name,
        total_amount=quantize_money(data.amount),
        currency=data.currency,
        date=data.date or datetime.now(timezone.utc),
        category_id=data.category_id,
        note=data.note,
        type="transfer",
        status=data.status,
        account_id=data.source_account_id,
        transfer_id=data.destination_account_id,
        is_manual=True,
        budget_id=current_budget.id,
        uploaded_by=current_user.id,
    )
    session.add(transaction)
    session.flush()

    if transaction.id is not None and current_budget.id is not None:
        record_manual_source_provenance(
            session,
            budget_id=current_budget.id,
            transaction_id=transaction.id,
        )

    session.commit()
    session.refresh(transaction)
    return transaction


@router.delete("/transfers/{transfer_id}", status_code=204)
def delete_transfer(
    transfer_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    transaction = session.get(Transaction, transfer_id)
    if not transaction or transaction.budget_id != current_budget.id or transaction.type != "transfer":
        raise HTTPException(status_code=404, detail="Transfer not found")
    delete_source_records_for_transaction(session, transfer_id)
    session.expire(transaction, ["source_records"])
    session.delete(transaction)
    session.commit()
    return None


@router.post("/transactions/scan", response_model=TransactionRead)
async def scan_transaction(
    background_tasks: BackgroundTasks,
    force: bool = False,
    note: Optional[str] = Form(None),
    file: UploadFile = File(...),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    file_content = await file.read()
    await file.seek(0)

    if is_demo_user(current_user):
        # 1. Quota check: max 5 custom scans today (persistent + legacy fallback)
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        custom_logs_used = session.exec(
            select(func.count(col(ScanUsageLog.id))).where(
                col(ScanUsageLog.user_id) == current_user.id,
                col(ScanUsageLog.scan_type) == "custom",
                col(ScanUsageLog.created_at) >= start_of_day,
            )
        ).one()
        legacy_custom_used = session.exec(
            select(func.count(col(ReceiptScan.id)))
            .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
            .where(
                col(Transaction.uploaded_by) == current_user.id,
                col(ReceiptScan.created_at) >= start_of_day,
                col(ReceiptScan.status) != ScanStatus.FAILED.value,
                ~col(ReceiptScan.content_hash).startswith("sample_"),
            )
        ).one()
        daily_scans_used = max(custom_logs_used, legacy_custom_used)
        if daily_scans_used >= 5:
            raise HTTPException(
                status_code=429,
                detail="Dzienny limit 5 skanów demonstracyjnych został wyczerpany. Spróbuj ponownie jutro lub przetestuj wzorcowe paragony demo.",
            )

        # 2. File size check (max 5 MB)
        if len(file_content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="Plik przekracza maksymalny rozmiar 5 MB dla wersji demonstracyjnej.",
            )

        # 3. MIME type check
        allowed_types = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
        if file.content_type and file.content_type.lower() not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Nieobsługiwany format pliku. Dozwolone formaty: JPG, PNG, WebP, PDF.",
            )

    file_hash = hashlib.sha256(file_content).hexdigest()
    filename = file.filename or "upload.jpg"
    detected_source = ReceiptSourceDetector.detect(
        filename=filename,
        content_type=file.content_type,
        file_bytes=file_content,
    )
    if detected_source == ReceiptSource.EPARAGON:
        src_type = SourceType.E_RECEIPT
        src_provider = "eparagon_json"
        src_external_id = extract_eparagon_external_id(file_content)
        src_adapter_version = "eparagon_v1"
        src_quality = "1.00"
        src_policy = RawPayloadPolicy.CANONICAL_ONLY
    else:
        src_type = SourceType.OCR_PHOTO
        src_provider = "receipt_upload"
        src_external_id = None
        src_adapter_version = "ocr_pipeline_v1"
        src_quality = "0.85"
        src_policy = RawPayloadPolicy.EPHEMERAL_IMAGE

    existing_provenance = find_existing_source_record(
        session,
        budget_id=current_budget.id,
        provider=src_provider,
        external_id=src_external_id,
        canonical_hash=file_hash,
    )
    existing_legacy_scan = has_legacy_scan_duplicate(
        session,
        budget_id=current_budget.id,
        content_hash=file_hash,
    )
    if not force and (existing_provenance is not None or existing_legacy_scan is not None):
        raise HTTPException(
            status_code=409,
            detail="Duplicate receipt detected. Use force=true to upload anyway.",
        )

    file_extension = filename.split(".")[-1]
    unique_filename = f"{uuid4()}.{file_extension}"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    allow_unique_keys = not (force and existing_provenance is not None)
    new_transaction: Optional[Transaction] = None
    scan: Optional[ReceiptScan] = None

    for attempt in range(2):
        try:
            with session.begin_nested():
                candidate_tx = Transaction(
                    merchant_name="Processing...",
                    uploaded_by=current_user.id,
                    budget_id=current_budget.id,
                    note=note,
                    review_status=ReviewStatus.PENDING,
                )
                session.add(candidate_tx)
                session.flush()
                if candidate_tx.id is None:
                    raise HTTPException(status_code=500, detail="Failed to create transaction")

                candidate_scan = ReceiptScan(
                    transaction_id=candidate_tx.id,
                    image_path=file_path,
                    status=ScanStatus.QUEUED,
                    content_hash=file_hash,
                    # keep_image defaults to False; final decision is made by user at verify time
                )
                session.add(candidate_scan)
                if is_demo_user(current_user) and current_user.id is not None:
                    session.add(ScanUsageLog(user_id=current_user.id, scan_type="custom"))
                session.flush()
                if candidate_scan.id is None:
                    raise HTTPException(status_code=500, detail="Failed to create receipt scan")

                session.add(
                    build_source_record(
                        budget_id=current_budget.id,
                        transaction_id=candidate_tx.id,
                        receipt_scan_id=candidate_scan.id,
                        source_type=src_type,
                        provider=src_provider,
                        external_id=src_external_id if allow_unique_keys else None,
                        canonical_hash=file_hash if allow_unique_keys else None,
                        adapter_version=src_adapter_version,
                        quality=src_quality,
                        raw_payload_policy=src_policy,
                    )
                )
                session.flush()
                new_transaction = candidate_tx
                scan = candidate_scan
            break
        except IntegrityError:
            raced = find_existing_source_record(
                session,
                budget_id=current_budget.id,
                provider=src_provider,
                external_id=src_external_id,
                canonical_hash=file_hash,
            )
            if raced is not None and not force:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                raise HTTPException(
                    status_code=409,
                    detail="Duplicate receipt detected. Use force=true to upload anyway.",
                )
            if force and allow_unique_keys and attempt == 0:
                allow_unique_keys = False
                continue
            raise

    if new_transaction is None or new_transaction.id is None or scan is None or scan.id is None:
        raise HTTPException(status_code=500, detail="Failed to persist receipt scan")

    session.commit()
    session.refresh(scan)

    background_tasks.add_task(process_transaction_in_background, new_transaction.id, scan.id, file_path)

    session.refresh(new_transaction)
    return new_transaction


@router.get("/demo/quota")
def get_demo_quota(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session),
):
    """Return remaining scan quota for the current demo user/session."""
    user_is_demo = is_demo_user(current_user)
    if not user_is_demo:
        return {
            "is_demo": False,
            "daily_limit": 9999,
            "used": 0,
            "remaining": 9999,
            "can_scan": True,
            "samples": {
                "biedronka": {
                    "daily_limit": 9999,
                    "used": 0,
                    "remaining": 9999,
                    "can_scan": True,
                },
                "lidl": {
                    "daily_limit": 9999,
                    "used": 0,
                    "remaining": 9999,
                    "can_scan": True,
                },
            },
        }

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Custom scans quota (max 5/day)
    custom_logs_used = session.exec(
        select(func.count(col(ScanUsageLog.id))).where(
            col(ScanUsageLog.user_id) == current_user.id,
            col(ScanUsageLog.scan_type) == "custom",
            col(ScanUsageLog.created_at) >= start_of_day,
        )
    ).one()
    legacy_custom_used = session.exec(
        select(func.count(col(ReceiptScan.id)))
        .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
        .where(
            col(Transaction.uploaded_by) == current_user.id,
            col(ReceiptScan.created_at) >= start_of_day,
            col(ReceiptScan.status) != ScanStatus.FAILED.value,
            ~col(ReceiptScan.content_hash).startswith("sample_"),
        )
    ).one()
    scans_used = max(custom_logs_used, legacy_custom_used)
    daily_limit = 5
    remaining = max(0, daily_limit - scans_used)

    # 2. Sample receipts quota (max 2/day per sample)
    sample_limit = 2

    biedronka_logs = session.exec(
        select(func.count(col(ScanUsageLog.id))).where(
            col(ScanUsageLog.user_id) == current_user.id,
            col(ScanUsageLog.scan_type) == "sample_biedronka",
            col(ScanUsageLog.created_at) >= start_of_day,
        )
    ).one()
    biedronka_legacy = session.exec(
        select(func.count(col(ReceiptScan.id)))
        .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
        .where(
            col(Transaction.uploaded_by) == current_user.id,
            col(ReceiptScan.created_at) >= start_of_day,
            col(ReceiptScan.status) != ScanStatus.FAILED.value,
            col(ReceiptScan.content_hash).startswith("sample_biedronka"),
        )
    ).one()
    biedronka_used = max(biedronka_logs, biedronka_legacy)
    biedronka_remaining = max(0, sample_limit - biedronka_used)

    lidl_logs = session.exec(
        select(func.count(col(ScanUsageLog.id))).where(
            col(ScanUsageLog.user_id) == current_user.id,
            col(ScanUsageLog.scan_type) == "sample_lidl",
            col(ScanUsageLog.created_at) >= start_of_day,
        )
    ).one()
    lidl_legacy = session.exec(
        select(func.count(col(ReceiptScan.id)))
        .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
        .where(
            col(Transaction.uploaded_by) == current_user.id,
            col(ReceiptScan.created_at) >= start_of_day,
            col(ReceiptScan.status) != ScanStatus.FAILED.value,
            col(ReceiptScan.content_hash).startswith("sample_lidl"),
        )
    ).one()
    lidl_used = max(lidl_logs, lidl_legacy)
    lidl_remaining = max(0, sample_limit - lidl_used)

    return {
        "is_demo": True,
        "daily_limit": daily_limit,
        "used": scans_used,
        "remaining": remaining,
        "can_scan": remaining > 0,
        "samples": {
            "biedronka": {
                "daily_limit": sample_limit,
                "used": biedronka_used,
                "remaining": biedronka_remaining,
                "can_scan": biedronka_remaining > 0,
            },
            "lidl": {
                "daily_limit": sample_limit,
                "used": lidl_used,
                "remaining": lidl_remaining,
                "can_scan": lidl_remaining > 0,
            },
        },
    }


@router.post("/transactions/scan-sample", response_model=TransactionRead)
async def scan_sample_transaction(
    background_tasks: BackgroundTasks,
    sample_id: str = Query(..., pattern="^(biedronka|lidl)$"),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """
    Instantly trigger processing of a curated sample receipt (Biedronka or Lidl)
    without requiring file upload from client or consuming custom upload quota.
    """
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    if is_demo_user(current_user):
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        sample_key = f"sample_{sample_id}"
        sample_logs_used = session.exec(
            select(func.count(col(ScanUsageLog.id))).where(
                col(ScanUsageLog.user_id) == current_user.id,
                col(ScanUsageLog.scan_type) == sample_key,
                col(ScanUsageLog.created_at) >= start_of_day,
            )
        ).one()
        legacy_used = session.exec(
            select(func.count(col(ReceiptScan.id)))
            .join(Transaction, col(ReceiptScan.transaction_id) == col(Transaction.id))
            .where(
                col(Transaction.uploaded_by) == current_user.id,
                col(ReceiptScan.created_at) >= start_of_day,
                col(ReceiptScan.status) != ScanStatus.FAILED.value,
                col(ReceiptScan.content_hash).startswith(f"sample_{sample_id}"),
            )
        ).one()
        if max(sample_logs_used, legacy_used) >= 2:
            merchant_name = "Biedronka" if sample_id == "biedronka" else "Lidl"
            raise HTTPException(
                status_code=429,
                detail=f"Dzienny limit 2 skanów dla przykładowego paragonu {merchant_name} został wyczerpany.",
            )

    sample_filename = "biedronka_katowice.png" if sample_id == "biedronka" else "lidl_rybnik.png"
    sample_src_path = os.path.join(os.path.dirname(__file__), "static", "demo_samples", sample_filename)

    if not os.path.exists(sample_src_path):
        raise HTTPException(status_code=404, detail=f"Sample receipt {sample_id} not found")

    with open(sample_src_path, "rb") as f:
        file_content = f.read()

    file_hash = f"sample_{sample_id}_{uuid4().hex[:12]}"
    unique_filename = f"{uuid4()}.png"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"

    with open(file_path, "wb") as f_out:
        f_out.write(file_content)

    merchant_label = "Biedronka (Wzorzec)" if sample_id == "biedronka" else "Lidl Plus (Wzorzec)"
    new_transaction = Transaction(
        merchant_name=merchant_label,
        uploaded_by=current_user.id,
        budget_id=current_budget.id,
        note=f"Wzorcowy paragon demonstracyjny: {sample_id.capitalize()}",
        review_status=ReviewStatus.PENDING,
    )
    session.add(new_transaction)
    session.flush()
    assert new_transaction.id is not None

    scan = ReceiptScan(
        transaction_id=new_transaction.id,
        image_path=file_path,
        status=ScanStatus.QUEUED.value,
        processed_via=f"demo_sample_{sample_id}",
        content_hash=file_hash,
    )
    session.add(scan)
    if is_demo_user(current_user) and current_user.id is not None:
        session.add(ScanUsageLog(user_id=current_user.id, scan_type=f"sample_{sample_id}"))
    session.flush()
    assert scan.id is not None
    assert current_budget.id is not None

    record_source_provenance(
        session,
        budget_id=current_budget.id,
        transaction_id=new_transaction.id,
        receipt_scan_id=scan.id,
        source_type=SourceType.OCR_PHOTO,
        provider="demo_sample",
        external_id=None,
        canonical_hash=file_hash,
        adapter_version="demo_sample_v1",
        quality="1.00",
        raw_payload_policy=RawPayloadPolicy.EPHEMERAL_IMAGE,
    )
    session.commit()
    session.refresh(scan)

    background_tasks.add_task(process_transaction_in_background, new_transaction.id, scan.id, file_path)
    session.refresh(new_transaction)
    return new_transaction


@router.post("/transactions/{transaction_id}/retry", response_model=TransactionRead)
async def retry_transaction(
    transaction_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to retry this transaction")

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="No receipt scan found for this transaction")

    if scan.status not in (ScanStatus.FAILED, "error"):
        raise HTTPException(status_code=400, detail="Only failed scans can be retried")

    if not scan.image_path or not os.path.exists(scan.image_path):
        raise HTTPException(status_code=404, detail="Original image file not found. Please re-upload.")

    scan.status = ScanStatus.QUEUED
    scan.error_message = None
    scan.needs_review = False
    session.add(scan)
    session.commit()
    session.refresh(transaction)

    if transaction.id is None:
        raise HTTPException(status_code=500, detail="Invalid transaction state")
    if scan.id is None:
        raise HTTPException(status_code=500, detail="Invalid scan state")
    background_tasks.add_task(process_transaction_in_background, transaction.id, scan.id, scan.image_path)

    return transaction


@router.get("/transactions", response_model=List[TransactionRead])
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    type: Optional[str] = None,
    account_id: Optional[int] = None,
    status: Optional[TransactionStatus] = None,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    statement = (
        select(Transaction)
        .where(
            Transaction.budget_id == current_budget.id,
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) == ReviewStatus.APPROVED.value,
        )
    )

    if type:
        statement = statement.where(Transaction.type == type)

    if account_id is not None:
        statement = statement.where(
            or_(
                col(Transaction.account_id) == account_id,
                and_(col(Transaction.transfer_id) == account_id, col(Transaction.type) == "transfer"),
            )
        )

    if status is not None:
        statement = statement.where(col(Transaction.status) == status)

    statement = statement.order_by(desc(Transaction.date)).offset(offset).limit(limit)
    results = session.exec(statement).all()
    return results


@router.get("/status", response_model=AppStatusRead)
async def get_app_status(
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Fetch global app status: inbox items and unread alerts."""
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    inbox_results = list_inbox_items(
        session,
        budget_id=current_budget.id,
        tab="exceptions",
    )

    alerts_statement = select(BudgetAlert).where(
        BudgetAlert.budget_id == current_budget.id,
        BudgetAlert.user_id == current_user.id,
        BudgetAlert.is_read == False  # noqa: E712
    ).order_by(col(BudgetAlert.created_at))
    unread_alerts = session.exec(alerts_statement).all()

    return {
        "inbox_items": list(inbox_results),
        "unread_alerts": list(unread_alerts)
    }


@router.post("/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    alert = session.get(BudgetAlert, alert_id)
    if not alert or alert.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_read = True
    session.add(alert)
    session.commit()
    return {"status": "ok"}


@router.get("/transactions/inbox", response_model=List[TransactionRead])
async def get_inbox(
    tab: str = Query(default="exceptions", pattern="^(exceptions|rejected|all)$"),
    source_type: Optional[str] = Query(default=None, description="Optional source provenance filter"),
    needs_review: Optional[bool] = Query(default=None, description="Filter by needs_review flag"),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Fetch Import Inbox transactions across hybrid exception, rejected, and all views."""
    del current_user  # Budget scope resolved via get_current_budget dependency.
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    return list_inbox_items(
        session,
        budget_id=current_budget.id,
        tab=tab,
        source_type=source_type,
        needs_review=needs_review,
    )


@router.get("/transactions/{transaction_id}/receipt")
async def get_transaction_receipt(
    transaction_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Securely serve the receipt image file for a given transaction."""
    transaction = session.get(Transaction, transaction_id)
    if not transaction or transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=404, detail="Transaction or receipt not found")

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()

    if not scan or not scan.image_path:
        raise HTTPException(status_code=404, detail="Receipt image record not found")

    # Robustly resolve path
    full_path = scan.image_path
    if not full_path:
        raise HTTPException(status_code=404, detail="No image path stored")

    # If the path is relative, resolve against BASE_DIR.
    # Strip legacy 'backend/' prefix first to avoid double-nesting.
    clean_rel_path = full_path
    if not os.path.isabs(full_path):
        if full_path.startswith("backend/"):
            clean_rel_path = full_path.replace("backend/", "", 1)
        full_path = os.path.join(BASE_DIR, clean_rel_path)

    if not os.path.exists(full_path):
        print(f"⚠️  Image file NOT FOUND at: {full_path}")
        # Fallback: try resolving relative to current working directory
        cwd_path = os.path.abspath(clean_rel_path)
        if os.path.exists(cwd_path):
            full_path = cwd_path
        else:
            raise HTTPException(status_code=404, detail=f"Receipt image file not found at {full_path}")

    return FileResponse(full_path)


@router.post("/transactions/{transaction_id}/verify", response_model=TransactionRead)
async def verify_transaction(
    transaction_id: int,
    body: VerifyRequest,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Verify and finalize an AI-scanned transaction. User confirms data and decides whether to keep the image."""
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction or db_transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=404, detail="Transaction not found")

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Receipt scan record not found")

    # Apply transaction field updates
    update_data = body.transaction_update.model_dump(exclude_unset=True, exclude={"tag_ids"})
    for key, value in update_data.items():
        if key == "date" and isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        setattr(db_transaction, key, value)

    validate_transaction_accounts(
        session,
        current_budget.id,
        db_transaction.account_id,
        db_transaction.transfer_id,
    )
    validate_account_category(session, current_budget.id, db_transaction.category_id)

    # Resolve category from account if not provided
    if not db_transaction.category_id and db_transaction.account_id:
        acc = session.get(Account, db_transaction.account_id)
        if acc and acc.category_id:
            db_transaction.category_id = acc.category_id

    if body.transaction_update.tag_ids is not None:
        tags = session.exec(select(Tag).where(col(Tag.id).in_(body.transaction_update.tag_ids))).all()
        db_transaction.tags = list(tags)

    # Apply line updates
    cache_updates: dict[str, int] = {}
    if body.lines_update:
        existing_lines = db_transaction.lines
        for i, line_data in enumerate(body.lines_update):
            line_dict = line_data.model_dump(exclude_unset=True)
            if "category_id" in line_dict:
                validate_account_category(session, current_budget.id, line_dict["category_id"])
            if i < len(existing_lines):
                db_line = existing_lines[i]
                new_cat_id = line_dict.get("category_id")
                category_changed = "category_id" in line_dict and new_cat_id != db_line.category_id
                for key, value in line_dict.items():
                    setattr(db_line, key, value)
                if category_changed:
                    db_line.category_source = "manual"
                    if new_cat_id is not None and db_line.name:
                        cache_updates[db_line.name] = new_cat_id
                session.add(db_line)
            else:
                new_cat_id = line_dict.get("category_id")
                new_line = TransactionLine(
                    **line_dict,
                    transaction_id=db_transaction.id,
                    category_source="manual" if new_cat_id is not None else None,
                )
                session.add(new_line)
                if new_cat_id is not None and new_line.name:
                    cache_updates[new_line.name] = new_cat_id

    # Persist user's keep_image decision and promote to approved ledger state
    scan.keep_image = body.keep_image
    if scan.id is not None:
        update_scan_source_metadata(
            session,
            receipt_scan_id=scan.id,
            raw_payload_policy=(
                RawPayloadPolicy.RETAINED_IMAGE if scan.keep_image else RawPayloadPolicy.CANONICAL_ONLY
            ),
        )
    promote_transaction_to_approved(
        session,
        transaction=db_transaction,
        scan=scan,
        finalize_scan=True,
        commit=False,
    )

    session.commit()
    if cache_updates and current_user.id is not None:
        from .cache_service import save_to_cache
        save_to_cache(session, current_user.id, cache_updates, overwrite=True)
    if current_budget.id is not None:
        discover_reconciliation_candidates(session, budget_id=current_budget.id, commit=True)
    session.refresh(db_transaction)

    # Delete image only if user did not request to keep it
    if not scan.keep_image and scan.image_path and os.path.exists(scan.image_path):
        try:
            os.remove(scan.image_path)
            scan.image_path = None
            session.add(scan)
            session.commit()
            print(f"🗑️ Deleted image after verification for transaction #{transaction_id}")
        except Exception as e:
            print(f"⚠️ Failed to delete image {scan.image_path}: {e}")

    return db_transaction


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    transaction_update: TransactionUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if db_transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this transaction")

    old_amount = db_transaction.total_amount
    old_category = db_transaction.category_id

    transaction_data = transaction_update.model_dump(exclude_unset=True, exclude={"tag_ids"})
    for key, value in transaction_data.items():
        if key == "date" and isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        setattr(db_transaction, key, value)

    validate_transaction_accounts(
        session,
        current_budget.id,
        db_transaction.account_id,
        db_transaction.transfer_id,
    )
    validate_account_category(session, current_budget.id, db_transaction.category_id)

    if db_transaction.type == "transfer" and db_transaction.transfer_id is not None:
        source_acc = session.get(Account, db_transaction.account_id) if db_transaction.account_id else None
        dest_acc = session.get(Account, db_transaction.transfer_id)
        if source_acc and dest_acc and source_acc.is_on_budget and not dest_acc.is_on_budget and not db_transaction.category_id:
            raise HTTPException(
                status_code=422,
                detail="Category is required for transfers to tracking accounts",
            )

    if transaction_update.tag_ids is not None:
        tags = session.exec(select(Tag).where(col(Tag.id).in_(transaction_update.tag_ids))).all()
        db_transaction.tags = list(tags)

    delta_amount = db_transaction.total_amount if old_category != db_transaction.category_id else (db_transaction.total_amount - old_amount)
    _check_envelope_balance_and_alert(session, db_transaction, delta_amount)

    session.add(db_transaction)
    session.flush()
    discover_reconciliation_candidates(session, budget_id=current_budget.id, commit=False)
    session.commit()
    session.refresh(db_transaction)

    return db_transaction


@router.patch("/transactions/{transaction_id}/lines/{line_id}", response_model=TransactionLine)
async def update_line(
    transaction_id: int,
    line_id: int,
    line_update: TransactionLineUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    db_line = session.get(TransactionLine, line_id)
    if not db_line or db_line.transaction_id != transaction_id:
        raise HTTPException(status_code=404, detail="Transaction line not found")

    parent_transaction = session.get(Transaction, transaction_id)
    if not parent_transaction or parent_transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this line")

    line_data = line_update.model_dump(exclude_unset=True)
    if "category_id" in line_data:
        if current_budget.id is None:
            raise HTTPException(status_code=404, detail="Budget not found")
        validate_account_category(session, current_budget.id, line_data["category_id"])

    category_changed = False
    new_category_id = None
    if "category_id" in line_data and line_data["category_id"] != db_line.category_id:
        category_changed = True
        new_category_id = line_data["category_id"]

    for key, value in line_data.items():
        setattr(db_line, key, value)

    if category_changed:
        db_line.category_source = "manual"

    session.add(db_line)
    session.commit()
    session.refresh(db_line)

    if category_changed and new_category_id is not None and current_user.id is not None:
        from .cache_service import save_to_cache
        save_to_cache(session, current_user.id, {db_line.name: new_category_id}, overwrite=True)

    return db_line


@router.delete("/transactions/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: int,
    preserve_source: bool = Query(
        default=False,
        description="Soft-reject while preserving SourceRecord tombstones so re-imports skip deleted receipts.",
    ),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this transaction")

    if preserve_source and current_user.id is not None:
        try:
            require_reconciliation_write_access(session, current_user, current_budget.id)
        except ReconciliationPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        reject_transaction_preserving_provenance(
            session,
            budget_id=current_budget.id,
            transaction_id=transaction_id,
            user_id=current_user.id,
            reason="deleted_by_user",
            commit=True,
        )
        return None

    cleanup_reconciliation_before_transaction_delete(session, transaction_id=transaction_id)
    delete_source_records_for_transaction(session, transaction_id)
    session.expire(transaction, ["source_records"])

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()
    if scan:
        if scan.image_path and os.path.exists(scan.image_path):
            try:
                os.remove(scan.image_path)
            except OSError:
                pass
        session.delete(scan)

    for line in transaction.lines:
        session.delete(line)

    session.delete(transaction)
    session.commit()
    return None


@router.post("/inbox/bulk-approve", response_model=InboxBulkActionResponse)
async def bulk_approve_inbox_items(
    body: InboxBulkApproveRequest,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Bulk-approve eligible Import Inbox transactions onto a required target account."""
    if not current_budget or current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    try:
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return approve_inbox_items(
            session,
            budget_id=current_budget.id,
            transaction_ids=body.transaction_ids,
            account_id=body.account_id,
            user_id=current_user.id,
        )
    except ReconciliationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InboxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/inbox/{transaction_id}/reject", response_model=TransactionRead)
async def reject_inbox_item_endpoint(
    transaction_id: int,
    body: Optional[InboxRejectRequest] = None,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Reversibly reject/delete an imported transaction while retaining provenance tombstones."""
    if not current_budget or current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    try:
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return reject_transaction_preserving_provenance(
            session,
            budget_id=current_budget.id,
            transaction_id=transaction_id,
            user_id=current_user.id,
            reason=body.reason if body else None,
            commit=True,
        )
    except ReconciliationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InboxNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/inbox/{transaction_id}/restore", response_model=TransactionRead)
async def restore_inbox_item_endpoint(
    transaction_id: int,
    account_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Restore a rejected transaction back into the Import Inbox review queue."""
    if not current_budget or current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    try:
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return restore_inbox_item(
            session,
            budget_id=current_budget.id,
            transaction_id=transaction_id,
            account_id=account_id,
            commit=True,
        )
    except ReconciliationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InboxNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InboxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- IMPORT ---

# parse_ing_pdf_text moved to app.adapters.transaction_adapters (#259) and re-exported here for callers.
_ = parse_ing_pdf_text


def detect_transaction_type(merchant: str, title: str, amount: Decimal | float, user_names: list[str]) -> str:
    """
    Heurystyka do oznaczania transferów wewnętrznych i przelewów P2P.
    """
    merchant_upper = (merchant or "").upper()
    title_upper = (title or "").upper()
    combined_text = f"{merchant_upper} {title_upper}"

    # 1. Reguły słów kluczowych dla transferów
    transfer_keywords = [
        "PRZELEW WEWNĘTRZNY", "PRZELEW WŁASNY", "PRZELEW NA TELEFON",
        "PRZELEW NA KONTO", "ZASILENIE", "WPŁATA WŁASNA", "SPLIT",
        "ROZLICZENIE", "PRZELEW WEW", "PRZELEW WŁASNY"
    ]

    # Dla BLIKa sprawdzamy, czy to nie jest płatność w sklepie
    if "PŁATNOŚĆ BLIK" not in combined_text and "ZAKUP" not in combined_text:
        if "BLIK" in combined_text and ("PRZELEW" in combined_text or "TELEFON" in combined_text):
            transfer_keywords.append("BLIK")

    for keyword in transfer_keywords:
        if keyword in combined_text:
            return "transfer"

    # 2. Sprawdzanie obecności imienia i nazwiska z profilu
    for name in user_names:
        if name and name in combined_text:
            return "transfer"

    # Domyślny fallback: jeśli nie jest to ewidentny transfer, to wydatek lub przychód
    return "expense" if amount < 0 else "income"


def _extract_statement_batch_for_user(
    *,
    content: bytes,
    filename: str,
    budget_id: int,
    user_email: str,
):
    local_part = user_email.split("@")[0]
    clean_part = local_part.replace(".", " ").replace("-", " ").replace("_", " ").upper()
    name_parts = [p.strip() for p in clean_part.split() if p.strip() and len(p) > 2 and p.isalpha()]
    user_names: list[str] = []
    if len(name_parts) >= 2:
        user_names.append(f"{name_parts[0]} {name_parts[1]}")
        user_names.append(f"{name_parts[1]} {name_parts[0]}")

    is_pdf = filename.lower().endswith(".pdf")
    adapter = IngPdfTransactionAdapter() if is_pdf else IngCsvTransactionAdapter()
    try:
        batch = adapter.extract_transactions(
            content,
            budget_id=budget_id,
            filename=filename,
            raw_payload_policy=RawPayloadPolicy.NONE,
        )
    except AdapterContractError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return batch, is_pdf, user_names


@router.post("/transactions/import/preview", response_model=BankCsvPreviewResponse)
async def preview_import_transactions(
    file: UploadFile = File(...),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    """Dry-run parse a bank CSV/PDF statement and suggest an active account before committing."""
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="CSV import is disabled in demo mode")
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    content = await file.read()
    filename = file.filename or ""
    batch, _, user_names = _extract_statement_batch_for_user(
        content=content,
        filename=filename,
        budget_id=current_budget.id,
        user_email=current_user.email,
    )
    return preview_transaction_batch(
        session,
        batch,
        budget_id=current_budget.id,
        filename=filename,
        tx_type_classifier=lambda item: detect_transaction_type(
            merchant=item.transaction.counterparty,
            title=item.transaction.title,
            amount=item.transaction.amount,
            user_names=user_names,
        ),
    )


@router.post("/transactions/import", response_model=dict)
async def import_transactions(
    file: UploadFile = File(...),
    account_id: Optional[int] = Form(default=None),
    auto_merge_policy: str = Form(default=AutoMergePolicy.MANUAL.value),
    dry_run: bool = Form(default=False),
    require_account: bool = Form(default=False),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="CSV import is disabled in demo mode")

    if not current_budget or current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    try:
        normalized_policy = AutoMergePolicy(auto_merge_policy.strip().lower()).value
    except ValueError as err:
        raise HTTPException(
            status_code=422,
            detail="Unsupported auto_merge_policy; use 'auto' or 'manual'",
        ) from err

    if account_id is not None:
        acc = session.get(Account, account_id)
        if acc is None or acc.budget_id != current_budget.id or not acc.is_active:
            raise HTTPException(
                status_code=422,
                detail="Selected account is invalid or inactive in this budget",
            )
    elif require_account and not dry_run:
        raise HTTPException(
            status_code=422,
            detail="Account selection is required for bank statement import",
        )

    content = await file.read()
    filename = file.filename or ""
    batch, is_pdf, user_names = _extract_statement_batch_for_user(
        content=content,
        filename=filename,
        budget_id=current_budget.id,
        user_email=current_user.email,
    )

    classifier = lambda item: detect_transaction_type(  # noqa: E731
        merchant=item.transaction.counterparty,
        title=item.transaction.title,
        amount=item.transaction.amount,
        user_names=user_names,
    )

    if dry_run:
        preview = preview_transaction_batch(
            session,
            batch,
            budget_id=current_budget.id,
            filename=filename,
            tx_type_classifier=classifier,
        )
        return preview.model_dump(mode="json")

    return ingest_transaction_batch(
        session,
        batch,
        budget_id=current_budget.id,
        user_id=current_user.id,
        filename=filename,
        enable_ai_categorization=not is_pdf,
        tx_type_classifier=classifier,
        account_id=account_id,
        auto_merge_policy=normalized_policy,
        auto_approve_clean=True,
        require_account=require_account,
    )


# --- BUDGET ---

@router.get("/budget/{year}/{month}/limits", response_model=List[EnvelopeAllocation])
def get_limits(
    year: int,
    month: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(EnvelopeAllocation).where(
        EnvelopeAllocation.budget_id == current_budget.id,
        EnvelopeAllocation.year == year,
        EnvelopeAllocation.month == month
    )
    return session.exec(statement).all()

@router.put("/budget/{year}/{month}/limits/{category_id}", response_model=EnvelopeAllocation)
def set_budget_limit(
    year: int,
    month: int,
    category_id: int,
    limit_data: EnvelopeAllocationUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    # Check if category exists and belongs to this budget
    category = session.get(Category, category_id)
    if not category or category.budget_id != current_budget.id:
        raise HTTPException(status_code=404, detail="Category not found in this budget")

    if limit_data.amount < Decimal("0"):
        raise HTTPException(status_code=400, detail="Limit amount must be non-negative")

    # Check for existing allocation
    statement = select(EnvelopeAllocation).where(
        EnvelopeAllocation.budget_id == current_budget.id,
        EnvelopeAllocation.category_id == category_id,
        EnvelopeAllocation.year == year,
        EnvelopeAllocation.month == month
    )
    allocation = session.exec(statement).first()

    if allocation:
        allocation.amount = limit_data.amount
    else:
        assert current_budget.id is not None
        allocation = EnvelopeAllocation(
            budget_id=current_budget.id,
            category_id=category_id,
            year=year,
            month=month,
            amount=limit_data.amount
        )

    session.add(allocation)
    session.commit()
    session.refresh(allocation)
    return allocation

@router.delete("/budget/{year}/{month}/limits/{category_id}", status_code=204)
def delete_budget_limit(
    year: int,
    month: int,
    category_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(EnvelopeAllocation).where(
        EnvelopeAllocation.budget_id == current_budget.id,
        EnvelopeAllocation.category_id == category_id,
        EnvelopeAllocation.year == year,
        EnvelopeAllocation.month == month
    )
    allocation = session.exec(statement).first()
    if allocation:
        session.delete(allocation)
        session.commit()
    return None

@router.get("/budget/{year}/{month}/summary", response_model=MonthlyBudgetSummary)
def get_summary(
    year: int = Path(..., ge=2000, le=2100, description="Year of the budget"),
    month: int = Path(..., ge=1, le=12, description="Month of the budget (1-12)"),
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    if current_user and is_demo_user(current_user):
        from .demo_seed import ensure_demo_data_for_month
        assert current_budget.id is not None
        assert current_user.id is not None
        ensure_demo_data_for_month(session, current_budget.id, current_user.id, year, month)

    source_acc = aliased(Account)
    dest_acc = aliased(Account)

    # 1. Calculate total income
    income_stmt = select(func.sum(Transaction.total_amount)).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "income",
        col(Transaction.reconciled_into_id).is_(None),
        col(Transaction.review_status) == ReviewStatus.APPROVED.value,
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month
    )
    regular_income = session.scalar(income_stmt) or Decimal("0.00")

    # Inflow from Tracking (Off-Budget) to On-Budget account
    tracking_income_stmt = (
        select(func.sum(Transaction.total_amount))
        .join(source_acc, col(Transaction.account_id) == source_acc.id)
        .join(dest_acc, col(Transaction.transfer_id) == dest_acc.id)
        .where(
            Transaction.budget_id == current_budget.id,
            col(Transaction.type) == "transfer",
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) == ReviewStatus.APPROVED.value,
            extract('year', col(Transaction.date)) == year,
            extract('month', col(Transaction.date)) == month,
            col(source_acc.is_on_budget).is_(False),
            col(dest_acc.is_on_budget).is_(True),
        )
    )
    tracking_income = session.scalar(tracking_income_stmt) or Decimal("0.00")
    total_income = quantize_money(regular_income) + quantize_money(tracking_income)

    # 2. Calculate total spent (from expenses)
    expense_stmt = select(func.sum(Transaction.total_amount)).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "expense",
        col(Transaction.reconciled_into_id).is_(None),
        col(Transaction.review_status) == ReviewStatus.APPROVED.value,
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month
    )
    regular_spent = session.scalar(expense_stmt) or Decimal("0.00")

    # Outflow from On-Budget to Tracking (Off-Budget) account
    tracking_expense_stmt = (
        select(func.sum(Transaction.total_amount))
        .join(source_acc, col(Transaction.account_id) == source_acc.id)
        .join(dest_acc, col(Transaction.transfer_id) == dest_acc.id)
        .where(
            Transaction.budget_id == current_budget.id,
            col(Transaction.type) == "transfer",
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) == ReviewStatus.APPROVED.value,
            extract('year', col(Transaction.date)) == year,
            extract('month', col(Transaction.date)) == month,
            col(source_acc.is_on_budget).is_(True),
            col(dest_acc.is_on_budget).is_(False),
        )
    )
    tracking_spent = session.scalar(tracking_expense_stmt) or Decimal("0.00")
    total_spent = quantize_money(regular_spent) + quantize_money(tracking_spent)

    # 3. Retrieve category allocations (planning)
    allocations_stmt = select(EnvelopeAllocation).where(
        EnvelopeAllocation.budget_id == current_budget.id,
        EnvelopeAllocation.year == year,
        EnvelopeAllocation.month == month
    )
    allocations = session.exec(allocations_stmt).all()
    total_planned = sum((quantize_money(a.amount) for a in allocations), Decimal("0.00"))

    # Calculate category expenses breakdown
    no_lines_stmt = select(
        Transaction.category_id,
        func.sum(Transaction.total_amount)
    ).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "expense",
        col(Transaction.reconciled_into_id).is_(None),
        col(Transaction.review_status) == ReviewStatus.APPROVED.value,
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month,
        col(Transaction.category_id).is_not(None),
        ~col(Transaction.id).in_(select(TransactionLine.transaction_id).where(col(TransactionLine.transaction_id).is_not(None)))
    ).group_by(col(Transaction.category_id))

    spent_no_lines = dict(session.exec(no_lines_stmt).all())

    lines_stmt = select(
        TransactionLine.category_id,
        func.sum(TransactionLine.price * TransactionLine.quantity)
    ).join(Transaction, col(Transaction.id) == col(TransactionLine.transaction_id)).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "expense",
        col(Transaction.reconciled_into_id).is_(None),
        col(Transaction.review_status) == ReviewStatus.APPROVED.value,
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month,
        col(TransactionLine.category_id).is_not(None)
    ).group_by(col(TransactionLine.category_id))

    spent_with_lines = dict(session.exec(lines_stmt).all())

    # Category breakdown for transfers to Tracking accounts
    tracking_cat_stmt = (
        select(
            Transaction.category_id,
            func.sum(Transaction.total_amount)
        )
        .join(source_acc, col(Transaction.account_id) == source_acc.id)
        .join(dest_acc, col(Transaction.transfer_id) == dest_acc.id)
        .where(
            Transaction.budget_id == current_budget.id,
            col(Transaction.type) == "transfer",
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) == ReviewStatus.APPROVED.value,
            extract('year', col(Transaction.date)) == year,
            extract('month', col(Transaction.date)) == month,
            col(source_acc.is_on_budget).is_(True),
            col(dest_acc.is_on_budget).is_(False),
            col(Transaction.category_id).is_not(None),
        )
        .group_by(col(Transaction.category_id))
    )
    spent_tracking_cat = dict(session.exec(tracking_cat_stmt).all())

    spent_by_category: dict[int, Decimal] = {}
    for cat_id, amt in spent_no_lines.items():
        if cat_id is not None and amt is not None:
            spent_by_category[cat_id] = spent_by_category.get(cat_id, Decimal("0.00")) + quantize_money(amt)

    for cat_id, amt in spent_with_lines.items():
        if cat_id is not None and amt is not None:
            spent_by_category[cat_id] = spent_by_category.get(cat_id, Decimal("0.00")) + quantize_money(amt)

    for cat_id, amt in spent_tracking_cat.items():
        if cat_id is not None and amt is not None:
            spent_by_category[cat_id] = spent_by_category.get(cat_id, Decimal("0.00")) + quantize_money(amt)


    # Build the category summary items
    categories_summary = []
    # Get only categories belonging to this budget
    all_categories = session.exec(
        select(Category).where(Category.budget_id == current_budget.id)
    ).all()

    allocations_by_cat = {a.category_id: quantize_money(a.amount) for a in allocations}

    for cat in all_categories:
        if cat.id is None:
            continue
        planned = allocations_by_cat.get(cat.id, Decimal("0.00"))
        spent = spent_by_category.get(cat.id, Decimal("0.00"))

        # Only include if there is planned or spent amount
        if planned > Decimal("0.00") or spent > Decimal("0.00"):
            categories_summary.append(CategoryBudgetSummaryItem(
                category_id=cat.id,
                category_name=cat.name,
                planned=planned,
                spent=spent,
                remaining=planned - spent
            ))

    net_cash_flow = total_income - total_spent

    return MonthlyBudgetSummary(
        year=year,
        month=month,
        total_planned=total_planned,
        total_spent=total_spent,
        net_cash_flow=net_cash_flow,
        total_income=total_income,
        categories=categories_summary
    )


@router.post("/budget/members", response_model=BudgetMemberRead)
async def invite_member(
    member_data: BudgetMemberCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Inviting budget members is disabled in demo mode")

    # Verify if current user is owner/editor of the budget
    # We need to query from identity_engine to find the user by email,
    # but the membership is in operations_engine.
    # Actually User is in identity_engine, and BudgetMember is in operations_engine.
    # Our get_ops_session and get_session point to the same DB for now.

    # Find the user to invite by email
    from .database import identity_engine
    with Session(identity_engine) as auth_session:
        target_user = auth_session.exec(select(User).where(User.email == member_data.email)).first()

    if not target_user:
        raise HTTPException(status_code=404, detail=f"User with email {member_data.email} found")

    # Check permissions and existing membership in ops session
    membership = session.exec(
        select(BudgetMember).where(
            BudgetMember.budget_id == current_budget.id,
            BudgetMember.user_id == current_user.id
        )
    ).first()

    if not membership or membership.role not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Only owners or editors can invite members")

    # Check if already a member
    existing = session.exec(
        select(BudgetMember).where(
            BudgetMember.budget_id == current_budget.id,
            BudgetMember.user_id == target_user.id
        )
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this budget")

    new_member = BudgetMember(
        budget_id=current_budget.id,
        user_id=target_user.id,
        role=member_data.role
    )
    session.add(new_member)
    session.commit()
    session.refresh(new_member)
    return new_member

@router.get("/categories", response_model=List[CategoryRead])
async def get_categories(
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(Category).where(
        Category.budget_id == current_budget.id
    )
    categories = session.exec(statement).all()
    return categories

@router.post("/categories", response_model=CategoryRead)
async def create_category(
    category_data: CategoryCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    dump_data = category_data.model_dump(exclude={"is_system"})
    category = Category(
        **dump_data,
        budget_id=current_budget.id,
        is_system=False
    )
    session.add(category)
    session.commit()
    session.refresh(category)
    return category

@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this category")

    update_data = category_update.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] != category.name:
        category.is_system = False
    for key, value in update_data.items():
        setattr(category, key, value)

    session.add(category)
    session.commit()
    session.refresh(category)
    return category

@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    reassign_to: Optional[int] = None,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this category")

    target_category_id = reassign_to
    if target_category_id is not None:
        target_category = session.get(Category, target_category_id)
        if not target_category or target_category.budget_id != current_budget.id:
            raise HTTPException(status_code=400, detail="Invalid target category for reassignment")
    else:
        target_category_id = category.parent_id

    transactions_statement = select(Transaction).where(Transaction.category_id == category_id)
    transactions = session.exec(transactions_statement).all()
    for t in transactions:
        t.category_id = target_category_id
        session.add(t)

    subcategories_statement = select(Category).where(Category.parent_id == category_id)
    subcategories = session.exec(subcategories_statement).all()
    for sub in subcategories:
        sub.parent_id = target_category_id
        session.add(sub)

    session.delete(category)
    session.commit()
    return None


# --- TAGS ---

@router.get("/tags", response_model=List[TagRead])
async def get_tags(
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(Tag).where(Tag.budget_id == current_budget.id)
    return session.exec(statement).all()

@router.post("/tags", response_model=TagRead)
async def create_tag(
    tag_data: TagCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    tag = Tag(**tag_data.model_dump(), budget_id=current_budget.id)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.patch("/tags/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_update: TagUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this tag")

    update_data = tag_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tag, key, value)

    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this tag")

    links_statement = select(TransactionTagLink).where(TransactionTagLink.tag_id == tag_id)
    links = session.exec(links_statement).all()
    for link in links:
        session.delete(link)

    session.delete(tag)
    session.commit()
    return None


# --- ACCOUNTS ---

@router.get("/accounts", response_model=List[AccountRead])
async def get_accounts(
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(Account).where(
        Account.budget_id == current_budget.id,
        Account.is_active,
    )
    accounts = session.exec(statement).all()
    return accounts

@router.post("/accounts", response_model=AccountRead)
async def create_account(
    account_data: AccountCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    validate_account_category(session, current_budget.id, account_data.category_id)
    init_balance = quantize_money(account_data.initial_balance)
    account = Account(**account_data.model_dump(exclude={"initial_balance"}), budget_id=current_budget.id)
    account.initial_balance = Decimal("0.00") # Prevent double counting
    account.current_balance = init_balance
    session.add(account)
    session.commit()
    session.refresh(account)

    if init_balance != Decimal("0.00"):
        tx_type = "income" if init_balance > Decimal("0.00") else "expense"
        tx = Transaction(
            merchant_name="Saldo początkowe",
            total_amount=abs(init_balance),
            currency=account.currency,
            date=datetime.now(timezone.utc),
            is_manual=True,
            type=tx_type,
            status=TransactionStatus.CLEARED,
            uploaded_by=current_user.id,
            budget_id=current_budget.id,
            account_id=account.id,
            note="Auto-generated initial balance"
        )
        session.add(tx)
        session.flush()
        if tx.id is not None:
            record_manual_source_provenance(
                session,
                budget_id=current_budget.id,
                transaction_id=tx.id,
                provider="system_opening_balance",
                adapter_version="account_v1",
                acquired_at=tx.date,
            )
        session.commit()
        session.refresh(tx)
        line = TransactionLine(
            name="Saldo początkowe",
            price=quantize_unit_price(abs(init_balance)),
            quantity=Decimal("1"),
            transaction_id=tx.id,
            is_adjustment=True
        )
        session.add(line)
        session.commit()
        session.refresh(account)

    return account

@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    account_update: AccountUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget or current_budget.id is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this account")

    update_data = account_update.model_dump(exclude_unset=True)
    validate_account_category(session, current_budget.id, update_data.get("category_id", account.category_id))
    for key, value in update_data.items():
        setattr(account, key, value)

    session.add(account)
    session.commit()
    session.refresh(account)
    return account

@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this account")

    account.is_active = False
    session.add(account)
    session.commit()
    return None

class AccountReconcileRequest(SQLModel):
    real_balance: MoneyDecimal

@router.post("/accounts/{account_id}/reconcile", response_model=AccountRead)
async def reconcile_account(
    account_id: int,
    data: AccountReconcileRequest,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    account = session.get(Account, account_id)
    if not account or account.budget_id != current_budget.id:
        raise HTTPException(status_code=404, detail="Account not found")

    diff = quantize_money(data.real_balance) - quantize_money(account.current_balance)
    if diff != Decimal("0.00"):
        tx_type = "income" if diff > Decimal("0.00") else "expense"
        tx = Transaction(
            merchant_name="Rekonsyliacja",
            total_amount=abs(diff),
            currency=account.currency,
            date=datetime.now(timezone.utc),
            is_manual=True,
            type=tx_type,
            status=TransactionStatus.CLEARED,
            uploaded_by=current_user.id,
            budget_id=current_budget.id,
            account_id=account.id,
            note="System adjustment"
        )
        session.add(tx)
        session.flush()
        if tx.id is not None and current_budget.id is not None:
            record_manual_source_provenance(
                session,
                budget_id=current_budget.id,
                transaction_id=tx.id,
                provider="system_reconcile",
                adapter_version="account_v1",
                acquired_at=tx.date,
            )
        session.commit()
        session.refresh(tx)
        line = TransactionLine(
            name="Wyrównanie salda",
            price=quantize_unit_price(abs(diff)),
            quantity=Decimal("1"),
            transaction_id=tx.id,
            is_adjustment=True
        )
        session.add(line)
        session.commit()
        session.refresh(account)

    return account


# ─── External Receipt Connections Lifecycle ──────────────────────────────────

@router.get("/connections", response_model=List[ExternalReceiptConnectionRead])
def list_receipt_connections(
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """List all external receipt connections configured for the current budget."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.list_connections(session, current_budget.id, current_user)


@router.post("/connections", response_model=ExternalReceiptConnectionRead)
def create_or_update_receipt_connection(
    data: ExternalReceiptConnectionCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Create a credential-free connection placeholder for the current user."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.create_connection(session, current_budget.id, current_user, data)


@router.get("/connections/{connection_id}", response_model=ExternalReceiptConnectionRead)
def get_receipt_connection(
    connection_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Get connection details by ID within the current budget."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    conn = ConnectionService.get_connection(session, current_budget.id, connection_id, current_user)
    return to_read_dto(conn, session=session)


@router.patch("/connections/{connection_id}/settings", response_model=ExternalReceiptConnectionRead)
def update_receipt_connection_settings(
    connection_id: int,
    body: ConnectionSettingsUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Update per-connection import settings (default account, auto-merge policy, sync_from_date)."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.update_connection_settings(
        session, current_budget.id, connection_id, current_user, body
    )


@router.post("/connections/{connection_id}/oauth/start", response_model=ConnectionOAuthStartResponse)
def start_receipt_connection_oauth(
    connection_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Generate an OAuth2 PKCE authorization URL for an external receipt connection."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.start_oauth(session, current_budget.id, connection_id, current_user)


@router.post("/connections/{connection_id}/oauth/callback", response_model=ExternalReceiptConnectionRead)
def complete_receipt_connection_oauth(
    connection_id: int,
    data: ConnectionOAuthCallbackRequest,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Complete OAuth2 PKCE flow using the captured redirect callback URL or authorization code."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.complete_oauth_callback(
        session, current_budget.id, connection_id, current_user, data
    )


@router.post("/connections/{connection_id}/oauth/desktop-login", response_model=ExternalReceiptConnectionRead)
async def desktop_login_receipt_connection_oauth(
    connection_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Run trusted-local interactive desktop OAuth capture without manual callback copying."""
    from .adapters.lidl_desktop_oauth import (
        DesktopOAuthCancelledError,
        DesktopOAuthUnavailableError,
        capture_lidl_oauth_callback,
        is_desktop_oauth_available,
    )

    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    ConnectionService.require_trusted_local_execution()
    conn = ConnectionService.get_connection(session, current_budget.id, connection_id, current_user)
    ConnectionService.require_provider_enabled(conn.provider)
    if not is_desktop_oauth_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Interactive desktop browser login is unavailable on this host; "
                "use the manual OAuth callback flow or run scripts/poc_lidl_auth.py on your desktop."
            ),
        )

    start_res = ConnectionService.start_oauth(session, current_budget.id, connection_id, current_user)
    try:
        callback_url = await asyncio.get_running_loop().run_in_executor(
            None, lambda: capture_lidl_oauth_callback(start_res.authorize_url)
        )
    except DesktopOAuthUnavailableError as exc:
        ConnectionService.clear_pending_oauth_attempt(
            session, current_budget.id, connection_id, current_user
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DesktopOAuthCancelledError as exc:
        ConnectionService.clear_pending_oauth_attempt(
            session, current_budget.id, connection_id, current_user
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ConnectionService.complete_oauth_callback(
        session,
        current_budget.id,
        connection_id,
        current_user,
        ConnectionOAuthCallbackRequest(callback_url_or_code=callback_url),
        allow_raw_code=False,
    )


@router.post("/connections/{connection_id}/sync-now", response_model=ConnectionSyncNowResponse)
def sync_now_receipt_connection(
    connection_id: int,
    live: bool = Query(default=False),
    sync_from_date: Optional[str] = Query(default=None),
    auto_merge_policy: Optional[str] = Query(default=None),
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Trigger an immediate sync queue request (or live sync when live=true) for a connection."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.trigger_sync_now(
        session,
        current_budget.id,
        connection_id,
        current_user,
        execute_live=live,
        sync_from_date=sync_from_date,
        auto_merge_policy=auto_merge_policy,
    )


@router.post("/connections/{connection_id}/reconnect", response_model=ExternalReceiptConnectionRead)
def reconnect_receipt_connection(
    connection_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Transition connection to reauth_required state."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.reconnect(session, current_budget.id, connection_id, current_user)


@router.patch("/connections/{connection_id}/enabled", response_model=ExternalReceiptConnectionRead)
def set_receipt_connection_enabled(
    connection_id: int,
    body: ConnectionToggleRequest,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Pause or resume automatic synchronization for an owned connection without deleting tokens."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.set_connection_enabled(
        session, current_budget.id, connection_id, current_user, body.enabled
    )


@router.post("/connections/{connection_id}/disconnect", response_model=ConnectionDisconnectResponse)
def disconnect_receipt_connection(
    connection_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Atomically erase stored tokens and mark connection as disconnected."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    return ConnectionService.disconnect(session, current_budget.id, connection_id, current_user)


# --- RECONCILIATION ---


def _handle_reconciliation_action(fn):
    try:
        return fn()
    except ReconciliationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReconciliationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReconciliationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reconciliation/candidates", response_model=ReconciliationListResponse)
def get_reconciliation_candidates(
    status: Optional[ReconciliationStatus] = Query(default=None),
    refresh: bool = Query(default=False),
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """List explainable receipt-bank reconciliation candidates and decisions for the active budget."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")
    if refresh:
        try:
            require_reconciliation_write_access(session, current_user, current_budget.id)
        except ReconciliationPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return list_reconciliation_links(
        session,
        budget_id=current_budget.id,
        status=status,
        auto_discover=refresh,
    )


@router.post("/reconciliation/refresh", response_model=ReconciliationListResponse)
def refresh_reconciliation_candidates(
    status: Optional[ReconciliationStatus] = Query(default=None),
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Recompute deterministic receipt-bank reconciliation candidates without altering prior decisions."""
    if current_budget.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget")

    def _run() -> ReconciliationListResponse:
        assert current_budget.id is not None
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return list_reconciliation_links(
            session,
            budget_id=current_budget.id,
            status=status,
            auto_discover=True,
        )

    return _handle_reconciliation_action(_run)


@router.post("/reconciliation/{link_id}/accept", response_model=ReconciliationActionResponse)
def accept_reconciliation_candidate(
    link_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Confirm a reconciliation match between a bank row and a receipt/manual transaction."""
    if current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget or user")

    def _run() -> ReconciliationActionResponse:
        assert current_budget.id is not None and current_user.id is not None
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return accept_reconciliation_link(
            session,
            budget_id=current_budget.id,
            link_id=link_id,
            user_id=current_user.id,
        )

    return _handle_reconciliation_action(_run)


@router.post("/reconciliation/{link_id}/reject", response_model=ReconciliationActionResponse)
def reject_reconciliation_candidate(
    link_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Reject a proposed reconciliation candidate and keep that decision across re-imports."""
    if current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget or user")

    def _run() -> ReconciliationActionResponse:
        assert current_budget.id is not None and current_user.id is not None
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return reject_reconciliation_link(
            session,
            budget_id=current_budget.id,
            link_id=link_id,
            user_id=current_user.id,
        )

    return _handle_reconciliation_action(_run)


@router.post("/reconciliation/{link_id}/unlink", response_model=ReconciliationActionResponse)
def unlink_reconciliation_candidate(
    link_id: int,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Reversibly unlink a previously accepted reconciliation match."""
    if current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget or user")

    def _run() -> ReconciliationActionResponse:
        assert current_budget.id is not None and current_user.id is not None
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return unlink_reconciliation_link(
            session,
            budget_id=current_budget.id,
            link_id=link_id,
            user_id=current_user.id,
        )

    return _handle_reconciliation_action(_run)


@router.post("/reconciliation/{link_id}/merge-duplicate", response_model=ReconciliationActionResponse)
def merge_reconciliation_duplicate(
    link_id: int,
    body: Optional[DuplicateMergeRequest] = None,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
    current_user: User = Depends(get_current_user),
):
    """Reversibly merge a detected cross-source duplicate receipt onto the chosen surviving entry."""
    if current_budget.id is None or current_user.id is None:
        raise HTTPException(status_code=400, detail="Invalid budget or user")

    def _run() -> ReconciliationActionResponse:
        assert current_budget.id is not None and current_user.id is not None
        require_reconciliation_write_access(session, current_user, current_budget.id)
        return merge_receipt_duplicate_link(
            session,
            budget_id=current_budget.id,
            link_id=link_id,
            user_id=current_user.id,
            keep_transaction_id=body.keep_transaction_id if body else None,
            commit=True,
        )

    return _handle_reconciliation_action(_run)
