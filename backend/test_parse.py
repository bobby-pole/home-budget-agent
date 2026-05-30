import traceback
from app.services import AIService

def run():
    try:
        res = AIService.parse_receipt("static/uploads/8f85cd65-3172-4c1e-adac-a16bcb4d37d4.pdf")
        print("Result:", res)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    run()
