from app.database import operations_engine
from sqlmodel import Session, select
from app.models import Category

with Session(operations_engine) as session:
    cats = session.exec(select(Category)).all()
    print("Found categories:", len(cats))
    if len(cats) > 0:
        print("First category:", cats[0].name, cats[0].icon)
