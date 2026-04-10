# backend/app/services.py
import os
import json
import base64
from typing import Optional
from openai import OpenAI

# API setup
# Pamiętaj, że w środowisku lokalnym/Docker klucz musi być w zmiennych środowiskowych
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy_key_for_tests")
client = OpenAI(api_key=OPENAI_API_KEY)

# Select model (Cheap and fast)
MODEL_NAME = "gpt-4o-mini"

class AIService:
    @staticmethod
    def parse_receipt(image_path: str, categories: Optional[list[dict]] = None) -> Optional[dict]:
        """
        Sends image to OpenAI and enforces JSON response.
        If categories are provided, instructs AI to use exactly one of the provided category names.
        """
        
        # 1. Encode image to base64
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            print(f"❌ Error reading image: {e}")
            return None

        # Prepare Categories Context
        cat_context = ""
        if categories:
            cat_list_str = ", ".join([f'"{c["name"]}"' for c in categories])
            cat_context = f"\nCRITICAL: You MUST assign a category to each item strictly from this exact list: [{cat_list_str}]. Do NOT invent new categories. Pick the closest match."
        else:
            cat_context = "\nAssign a category to each item (e.g., Food, Fast Food, Snacks, Transport, Utilities, Entertainment, Health, Other)."

        # 2. Prepare Prompt
        system_prompt = f"""
        You are an expert receipt parser. 
        Extract data from the receipt image into a strict JSON format.
        Identify:
        1. Merchant name (store).
        2. Date (YYYY-MM-DD format). If missing, use today.
        3. Total amount (as a number).
        4. Currency (PLN, EUR, USD, etc.).
        5. List of items (name, price, quantity, category).
        {cat_context}
        
        Return ONLY valid JSON.
        Structure:
        {{
            "merchant_name": "Store Name",
            "date": "2024-01-01",
            "total_amount": 123.45,
            "currency": "PLN",
            "items": [
                {{"name": "Milk", "price": 3.50, "quantity": 1, "category": "Food"}},
                {{"name": "Beer", "price": 5.00, "quantity": 2, "category": "Alcohol"}}
            ]
        }}
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
            
            if raw_text is None:
                print("❌ AI Error: Empty response content")
                return None
            
            # 4. Parse JSON
            parsed_data = json.loads(raw_text)
            print("✅ AI Parsed Data:", parsed_data)
            return parsed_data

        except Exception as e:
            print(f"❌ AI Error: {e}")
            return None

    @staticmethod
    def categorize_descriptions(descriptions: list[str], categories: list[dict]) -> dict[str, str]:
        """
        Takes a list of transaction descriptions and assigns a category to each.
        Returns a mapping: { "description": "category_name" }
        Uses batching to process up to 50 descriptions at once for efficiency.
        """
        if not descriptions:
            return {}

        cat_list_str = ", ".join([f'"{c["name"]}"' for c in categories])
        
        system_prompt = f"""
        You are a financial assistant. Categorize the following bank transaction descriptions.
        For each description, pick EXACTLY ONE category from this list: [{cat_list_str}].
        If no category fits well, use "Other" or the closest possible match.
        Return ONLY a JSON object where keys are descriptions and values are category names.
        
        Format:
        {{
            "Description 1": "Category A",
            "Description 2": "Category B"
        }}
        """

        try:
            # Join descriptions into a single string for the user prompt
            user_content = "\n".join(descriptions)
            
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Categorize these descriptions:\n{user_content}"}
                ],
                response_format={"type": "json_object"},
                max_tokens=1500
            )
            
            raw_text = response.choices[0].message.content
            if not raw_text:
                return {}
                
            mapping = json.loads(raw_text)
            print(f"✅ AI Categorized {len(descriptions)} descriptions.")
            return mapping

        except Exception as e:
            print(f"❌ AI Categorization Error: {e}")
            # Fallback: assign "Other" or empty to everything
            return {desc: "Other" for desc in descriptions}

    @staticmethod
    def parse_bank_statement_text(raw_text: str) -> list[dict]:
        """
        Parses raw text from a bank statement PDF and extracts transactions.
        Returns a list of dicts: [{date, merchant, amount, currency, title}]
        """
        if not raw_text or len(raw_text.strip()) < 50:
            return []

        system_prompt = """
        You are a financial data extractor. I will provide you with a raw text dump from a bank statement PDF.
        Your task is to extract ALL transactions into a strict JSON list.
        
        Fields to extract for each transaction:
        1. date: Format YYYY-MM-DD.
        2. merchant: The receiver or sender name (clean version).
        3. title: The full transaction title or description.
        4. amount: A number. VERY IMPORTANT: Expenses MUST be negative, Incomes MUST be positive.
        5. currency: e.g., "PLN", "EUR".
        
        Guidelines for ING/PL banks:
        - "Obciążenia" or "-" signs are expenses (negative).
        - "Uznania" or "+" signs are incomes (positive).
        - Ignore headers, footers, summary tables, and balances.
        
        Return ONLY valid JSON.
        Format:
        [
            {"date": "2024-04-01", "merchant": "BIEDRONKA", "title": "Zakupy", "amount": -45.50, "currency": "PLN"},
            {"date": "2024-04-02", "merchant": "COMPANY X", "title": "SALARY", "amount": 5000.00, "currency": "PLN"}
        ]
        """

        try:
            # We use a large context model (gpt-4o-mini is fine for 128k context)
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract transactions from this text:\n\n{raw_text[:30000]}"} # Limit to ~30k chars for safety
                ],
                response_format={"type": "json_object"},
                max_tokens=4000
            )
            
            raw_text_res = response.choices[0].message.content
            if not raw_text_res:
                return []
                
            # The AI might return {"transactions": [...]} instead of a list if told to be strict JSON
            # We fix that by parsing and checking
            parsed = json.loads(raw_text_res)
            if isinstance(parsed, dict) and "transactions" in parsed:
                return parsed["transactions"]
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                # Maybe it returned a dict where keys are not "transactions" but it's still a dict of something
                # Let's try to find the list
                for val in parsed.values():
                    if isinstance(val, list):
                        return val
            return []

        except Exception as e:
            print(f"❌ AI PDF Parse Error: {e}")
            return []
