from app.database import operations_engine
from sqlmodel import Session, select
from app.models import Category
from app.api import seed_default_categories

with Session(operations_engine) as session:
    cats = session.exec(select(Category)).all()
    print("Categories before:", len(cats))
    if len(cats) == 0:
        seed_default_categories(session, 1)
    cats = session.exec(select(Category)).all()
    print("Categories after:", len(cats))
