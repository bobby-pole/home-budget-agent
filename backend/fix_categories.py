from app.database import operations_engine
from sqlmodel import Session, select, col
from app.models import Transaction, TransactionLine, Category
from app.services import AIService
import asyncio

async def fix():
    with Session(operations_engine) as session:
        tx = session.exec(select(Transaction).order_by(col(Transaction.id).desc()).limit(1)).first()
        if not tx:
            return
        
        lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
        categories = session.exec(select(Category).where(Category.budget_id == tx.budget_id)).all()
        cat_dicts = [{"id": c.id, "name": c.name} for c in categories]
        
        data = {"items": []}
        for line in lines:
            data["items"].append({
                "name": line.name,
                "price": line.price,
                "quantity": line.quantity,
                "category": None,
                "is_adjustment": line.is_adjustment
            })
            
        print("Categorizing...")
        result = AIService._categorize_parsed_items(data, cat_dicts, tx.uploaded_by)
        print("Result:", result)
        
        # update lines
        cat_name_to_id = {c.name.lower(): c.id for c in categories}
        for i, item in enumerate((result or {}).get("items", [])):
            if item.get("category"):
                cat_id = cat_name_to_id.get(item["category"].lower())
                if cat_id:
                    lines[i].category_id = cat_id
                    session.add(lines[i])
                    
        session.commit()
        print("Fixed.")

if __name__ == "__main__":
    asyncio.run(fix())
