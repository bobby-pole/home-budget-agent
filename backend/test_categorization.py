import asyncio
from app.database import operations_engine
from sqlmodel import Session, select, col
from app.models import Transaction, TransactionLine, Category
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

from app.services import AIService  # noqa: E402

async def test_categorization():
    with Session(operations_engine) as session:
        tx = session.exec(select(Transaction).order_by(col(Transaction.id).desc()).limit(1)).first()
        if not tx:
            print("No tx")
            return
            
        print(f"Latest Transaction: {tx.id} - {tx.merchant_name}")
        
        lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
        categories = session.exec(select(Category).where(Category.budget_id == tx.budget_id)).all()
        cat_dicts = [{"id": c.id, "name": c.name} for c in categories]
        
        print(f"Categories count: {len(cat_dicts)}")
        if len(cat_dicts) == 0:
            print("Still 0 categories in DB!?")
            return
            
        data = {"items": []}
        for line in lines:
            data["items"].append({
                "name": line.name,
                "price": line.price,
                "quantity": line.quantity,
                "category": None,
                "is_adjustment": line.is_adjustment
            })
            
        print("Categorizing via AI...")
        result = AIService._categorize_parsed_items(data, cat_dicts, tx.uploaded_by)
        print("Result:")
        for item in (result or {}).get("items", []):
            print(f"  {item['name']} -> {item['category']}")

if __name__ == "__main__":
    asyncio.run(test_categorization())
