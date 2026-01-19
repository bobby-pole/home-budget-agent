# backend/app/database.py
from sqlmodel import SQLModel, create_engine, Session

# Plik bazy danych będzie w folderze data (zmapowanym w Dockerze)
SQLITE_FILE_NAME = "database.db"
DATABASE_URL = f"sqlite:///./data/{SQLITE_FILE_NAME}"

# check_same_thread=False jest wymagane dla SQLite w FastAPI
connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session