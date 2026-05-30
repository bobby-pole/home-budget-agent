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
            print("No transaction found")
            return
        lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
        categories = session.exec(select(Category).where(Category.budget_id == tx.budget_id)).all()
        cat_dicts = [{"id": c.id, "name": c.name} for c in categories]
        
        names = [line.name for line in lines]
        print("Descriptions:", names)
        print("Categories:", [c["name"] for c in cat_dicts])
        
        print("Calling categorize_descriptions...")
        mapping = AIService.categorize_descriptions(names, cat_dicts)
        print("Mapping from AI:", mapping)

if __name__ == "__main__":
    asyncio.run(test_categorization())
