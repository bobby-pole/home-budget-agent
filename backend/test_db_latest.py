from app.database import operations_engine
from sqlmodel import Session, select, col
from app.models import Transaction, TransactionLine, Category

with Session(operations_engine) as session:
    tx = session.exec(select(Transaction).order_by(col(Transaction.id).desc()).limit(1)).first()
    if tx:
        print(f"Transaction: {tx.id} - {tx.merchant_name}")
        lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
        for line in lines:
            print(f"  Line: {line.name} (Cat ID: {line.category_id})")
        
        cats = session.exec(select(Category).where(Category.budget_id == tx.budget_id)).all()
        print(f"Available categories for this budget ({tx.budget_id}): {len(cats)}")
        for c in cats:
            print(f"  {c.id} - {c.name}")
    else:
        print("No transactions")
