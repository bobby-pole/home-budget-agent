# backend/app/services.py
import os
import json
import base64
from openai import OpenAI
from .models import Receipt, Item

# API setup
# Pamiętaj, że w środowisku lokalnym/Docker klucz musi być w zmiennych środowiskowych
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Select model (Cheap and fast)
MODEL_NAME = "gpt-4o-mini"

class AIService:
    @staticmethod
    def parse_receipt(image_path: str) -> dict:
        """
        Sends image to OpenAI and enforces JSON response.
        """
        
        # 1. Encode image to base64
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            print(f"❌ Error reading image: {e}")
            return None

        # 2. Prepare Prompt
        system_prompt = """
        You are an expert receipt parser. 
        Extract data from the receipt image into a strict JSON format.
        Identify:
        1. Merchant name (store).
        2. Date (YYYY-MM-DD format). If missing, use today.
        3. Total amount (as a number).
        4. Currency (PLN, EUR, USD, etc.).
        5. List of items (name, price, quantity, category).
        
        Assign a category to each item (e.g., Food, Fast Food, Snacks, Transport, Utilities, Entertainment, Health, Other).
        
        Return ONLY valid JSON.
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
            # 3. Call OpenAI API
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this receipt image."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            
            raw_text = response.choices[0].message.content
            
            # 4. Parse JSON
            parsed_data = json.loads(raw_text)
            print("✅ AI Parsed Data:", parsed_data)
            return parsed_data

        except Exception as e:
            print(f"❌ AI Error: {e}")
            return None
