# backend/app/api.py
import shutil
import os
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlmodel import Session, select, desc
from .models import Receipt, Item, ReceiptCreate, ReceiptRead
from .database import get_session
from .services import AIService
from typing import List

router = APIRouter()
UPLOAD_DIR = "static/uploads"

# --- TASK IN BACKGROUND ---
def process_receipt_in_background(receipt_id: int, image_path: str, session: Session):
    print(f"🤖 AI Processing started for receipt #{receipt_id}...")
    
    # 1. Call AI to parse receipt
    data = AIService.parse_receipt(image_path)
    
    # Load receipt from DB
    # Uwaga: W prawdziwym kodzie produkcyjnym zarządzanie sesją w tle jest trudniejsze,
    # ale dla uproszczenia tutaj przekażemy sesję (FastAPI to obsłuży w ramach requestu)
    # lub lepiej: utworzymy nową. Tu dla uproszczenia zakładamy, że sesja jest ok.
    receipt = session.get(Receipt, receipt_id)
    
    if not data or not receipt:
        print("❌ AI Failed or Receipt not found")
        if receipt:
            receipt.status = "error"
            session.add(receipt)
            session.commit()
        return

    # 2. Update receipt details
    receipt.merchant_name = data.get("merchant_name", "Unknown")
    receipt.total_amount = data.get("total_amount", 0.0)
    receipt.currency = data.get("currency", "PLN")
    receipt.status = "done"
    
    # 3. Add positions
    items_data = data.get("items", [])
    for item_raw in items_data:
        new_item = Item(
            name=item_raw["name"],
            price=item_raw["price"],
            quantity=item_raw.get("quantity", 1),
            category=item_raw.get("category", "Other"),
            receipt_id=receipt.id
        )
        session.add(new_item)
    
    session.add(receipt)
    session.commit()
    print(f"✅ AI Processing finished for receipt #{receipt_id}")


# --- ENDPOINT ---
@router.post("/upload", response_model=Receipt)
async def upload_receipt(
    background_tasks: BackgroundTasks,  # Running background tasks via FastAPI
    file: UploadFile = File(...), 
    session: Session = Depends(get_session)
):
    # File saving
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid4()}.{file_extension}"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create initial Receipt entry with status "processing"
    new_receipt = Receipt(
        merchant_name="Processing...",
        image_path=file_path,
        status="processing"
    )
    
    session.add(new_receipt)
    session.commit()
    session.refresh(new_receipt)
    
    # AI agent works in background
    background_tasks.add_task(process_receipt_in_background, new_receipt.id, file_path, session)
    
    return new_receipt

@router.get("/receipts", response_model=List[ReceiptRead])
async def get_receipts(session: Session = Depends(get_session)):
    # Pobieramy paragony posortowane od najnowszego (data malejąco)
    statement = select(Receipt).order_by(desc(Receipt.date))
    results = session.exec(statement).all()
    return results