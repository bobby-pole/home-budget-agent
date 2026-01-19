# backend/app/services.py
import os
import json
import google.generativeai as genai
from .models import Receipt, Item

# API setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Select model
MODEL_NAME = "gemini-2.5-flash"

class AIService:
    @staticmethod
    def parse_receipt(image_path: str) -> dict:
        """
        Wysyła obraz do Gemini i wymusza zwrot w formacie JSON.
        """
        model = genai.GenerativeModel(MODEL_NAME)
        
        # Load image data
        with open(image_path, "rb") as f:
            image_data = f.read()

        # --- PROMPT ENGINEERING ---
        # Instructions for the AI model
        prompt = """
        Analyze this receipt image and extract data into a strict JSON format.
        Identify:
        1. Merchant name (store).
        2. Date (YYYY-MM-DD format). If missing, use today.
        3. Total amount.
        4. Currency (PLN, EUR, USD, etc.).
        5. List of items (name, price, quantity, category).
        
        Assign a category to each item (e.g., Food, Chemicals, Alcohol, Electronics, Other).
        
        Output strictly valid JSON only. No markdown formatting (```json).
        Structure:
        {
            "merchant_name": "Store Name",
            "date": "2024-01-01",
            "total_amount": 123.45,
            "currency": "PLN",
            "items": [
                {"name": "Milk", "price": 3.50, "quantity": 1, "category": "Food"},
                {"name": "Beer", "price": 5.00, "quantity": 2, "category": "Alcohol"}
            ]
        }
        """

        try:
            # Run AI
            response = model.generate_content([
                {'mime_type': 'image/jpeg', 'data': image_data},
                prompt
            ])
            
            # Serializing response text
            raw_text = response.text.replace("```json", "").replace("```", "").strip()
            
            # Parse JSON
            parsed_data = json.loads(raw_text)
            print("✅ AI Parsed Data:", parsed_data)
            return parsed_data

        except Exception as e:
            print(f"❌ AI Error: {e}")
            return None