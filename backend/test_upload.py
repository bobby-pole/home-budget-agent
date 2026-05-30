from app.database import operations_engine
from sqlmodel import Session, select, col
from app.models import ReceiptScan

def check():
    with Session(operations_engine) as session:
        scans = session.exec(select(ReceiptScan).order_by(col(ReceiptScan.id).desc()).limit(1)).all()
        for s in scans:
            print(f"Scan {s.id}: status={s.status}, error={s.error_message}, validation={s.validation_message}, path={s.image_path}")

if __name__ == "__main__":
    check()
