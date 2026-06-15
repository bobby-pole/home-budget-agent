# backend/app/services.py
import os
import json
import base64
from typing import Optional

from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy_key_for_tests")
client = OpenAI(api_key=OPENAI_API_KEY)

MODEL_NAME = "gpt-4o-mini"


class AIService:

    # ── Receipt parsing ────────────────────────────────────────────────────────

    @staticmethod
    def parse_receipt(
        image_path: str,
        categories: Optional[list[dict]] = None,
        filename: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Entry point for receipt parsing.
        Pipeline: Google Vision OCR → line reconstruction → merchant detection → parser | AI fallback.
        """
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            print(f"❌ Error reading image: {e}")
            return None

        actual_filename = filename or os.path.basename(image_path)
        return AIService._run_ocr_pipeline(image_bytes, categories, filename=actual_filename, user_id=user_id)

    @staticmethod
    def _run_ocr_pipeline(
        image_bytes: bytes,
        categories: Optional[list[dict]] = None,
        filename: str = "",
        user_id: Optional[int] = None,
    ) -> Optional[dict]:
        from .pipeline_logger import PipelineLogger
        from .pipeline_runner import AICallbacks, PipelineRunner

        logger = PipelineLogger(verbose=False)  # production: no terminal spam
        ai = AICallbacks(
            structurize=AIService._ai_structurize,
            vision_fallback=AIService._ai_vision_fallback,
            categorize=lambda data: AIService._categorize_parsed_items(data, categories, user_id),
        )
        runner = PipelineRunner(logger=logger, ai=ai)
        return runner.run(image_bytes, filename)

    @staticmethod
    def _categorize_parsed_items(
        data: Optional[dict],
        categories: Optional[list[dict]],
        user_id: Optional[int],
    ) -> Optional[dict]:
        """
        Batch-categorize items produced by any parser using cache-first approach.
        """
        if data is None or not categories:
            return data

        items = data.get("items") or []
        targets = [
            (idx, item) for idx, item in enumerate(items)
            if not item.get("is_adjustment") and not item.get("category")
        ]
        if not targets:
            return data

        from .database import get_ops_session
        from .cache_service import fuzzy_match_cache, save_to_cache
        
        # Executor runs without injected session, create a short-lived one
        db_session = next(get_ops_session())

        names = [item["name"] for _, item in targets]
        
        try:
            hits = {}
            misses = names
            if user_id:
                hits, misses = fuzzy_match_cache(db_session, user_id, names)
                if hits:
                    print(f"🎯 [Categorization] Cache hits: {len(hits)} / {len(names)}")
                
            # For hits, assign category ID and map back to name
            if hits:
                cat_id_to_name = {c["id"]: c["name"] for c in categories}
                for idx, item in targets:
                    if item["name"] in hits:
                        cat_id = hits[item["name"]]
                        cat_name = cat_id_to_name.get(cat_id)
                        if cat_name:
                            items[idx]["category"] = cat_name

            mapping = {}
            if misses:
                print(f"🧠 [Categorization] Asking AI for {len(misses)} unknown items...")
                mapping = AIService.categorize_descriptions(misses, categories)
                if mapping:
                    print(f"✅ [Categorization] AI mapped {len(mapping)} items successfully")
                else:
                    print("⚠️ [Categorization] AI returned empty mapping")
                
            valid_cat_names = {c["name"]: c["id"] for c in categories}
            new_cache_mappings = {}
            
            for idx, item in targets:
                # If we have a newly mapped category from AI
                if item["name"] in mapping:
                    cat = mapping[item["name"]]
                    if cat in valid_cat_names:
                        items[idx]["category"] = cat
                        new_cache_mappings[item["name"]] = valid_cat_names[cat]
                        
            if user_id and new_cache_mappings:
                print(f"💾 [Categorization] Saving {len(new_cache_mappings)} new mappings to cache")
                save_to_cache(db_session, user_id, new_cache_mappings)
                
        except Exception as e:
            print(f"⚠️ [Categorization] Cache/AI failed: {e}")
        finally:
            db_session.close()

        return data

    @staticmethod
    def _validate_and_annotate(data: Optional[dict]) -> Optional[dict]:
        """Run ReceiptValidator and attach validation metadata to the result dict."""
        if data is None:
            return None

        from decimal import Decimal
        from .receipt_validator import ReceiptValidator

        ocr_total = Decimal(str(data.get("total_amount", 0)))
        result = ReceiptValidator().validate(data, ocr_total)

        data["_validation"] = {
            "is_valid": result.is_valid,
            "issues": [i.value for i in result.issues],
            "confidence": result.confidence,
            "message": result.message,
        }

        if not result.is_valid:
            print(f"❌ [Validation] FAILED — {result.message}")
        elif result.issues:
            print(f"⚠️ [Validation] NEEDS_REVIEW — {result.message}")
        else:
            print(f"✅ [Validation] OK — confidence {result.confidence:.2f}")

        return data

    @staticmethod
    def _ai_structurize(receipt_text: str) -> Optional[dict]:
        """AI structurizer — called for unknown merchant formats after OCR + line reconstruction."""

        system_prompt = """You are an expert receipt parser.
Extract structured data from the following receipt text.

Return ONLY valid JSON with this structure:
{
    "merchant_name": "Store Name",
    "date": "YYYY-MM-DD",
    "total_amount": 123.45,
    "currency": "PLN",
    "items": [
        {"name": "Product name", "price": 3.50, "quantity": 1}
    ]
}

Rules:
- date: YYYY-MM-DD format. Use today if missing.
- total_amount: the final sum paid (after discounts).
- Each item price is the unit price. quantity defaults to 1.
- Include discounts as negative-price items if visible."""

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": receipt_text},
                ],
                response_format={"type": "json_object"},
                max_tokens=8000,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            print(f"❌ AI Structurize Error: {e}")
            return None

    @staticmethod
    def _ai_vision_fallback(image_bytes: bytes) -> Optional[dict]:
        """
        Direct AI vision — used only when Google Vision is not configured.
        Sends the whole image as-is (no chunking).
        """

        system_prompt = """You are an expert receipt parser. Extract data from the receipt image into JSON.
Return: merchant_name, date (YYYY-MM-DD), total_amount, currency, items (name/price/quantity).
Return ONLY valid JSON."""

        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Parse this receipt."},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        }},
                    ]},
                ],
                response_format={"type": "json_object"},
                max_tokens=4000,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            print(f"❌ AI Vision Fallback Error: {e}")
            return None

    # ── Categorization ─────────────────────────────────────────────────────────

    @staticmethod
    def categorize_descriptions(descriptions: list[str], categories: list[dict]) -> dict[str, str]:
        """
        Assigns a category to each transaction description.
        Returns {description: category_name}. Processes up to 50 at once.
        """
        if not descriptions:
            return {}

        cat_list_str = ", ".join(f'"{c["name"]}"' for c in categories)
        
        # Create indexed descriptions so AI returns predictable keys
        indexed_desc = {str(i): d for i, d in enumerate(descriptions)}
        input_json = json.dumps(indexed_desc, ensure_ascii=False)

        system_prompt = f"""You are a financial assistant. Categorize each transaction description.
For each description pick EXACTLY ONE category from: [{cat_list_str}].
If no category fits, use the closest match.
The user provides a JSON map: {{"ID": "description"}}. 
You MUST return ONLY a JSON map: {{"ID": "Category"}}.
Do NOT change the IDs."""

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": input_json},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
            )
            raw_mapping = json.loads(response.choices[0].message.content or "{}")
            
            # Reconstruct original mapping
            result = {}
            for k, cat in raw_mapping.items():
                if k in indexed_desc:
                    result[indexed_desc[k]] = cat
            return result
        except Exception as e:
            print(f"❌ AI Categorization Error: {e}")
            return {}

    # ── Bank statement parsing ─────────────────────────────────────────────────

    @staticmethod
    def parse_bank_statement_text(raw_text: str) -> list[dict]:
        """
        Parses raw text from a bank statement PDF.
        Returns [{date, merchant, amount, currency, title}].
        """
        if not raw_text or len(raw_text.strip()) < 50:
            return []

        system_prompt = """You are a financial data extractor. Extract ALL transactions from this bank statement text.

For each transaction return:
- date: YYYY-MM-DD
- merchant: receiver or sender name (clean)
- title: full transaction description
- amount: number — expenses NEGATIVE, incomes POSITIVE
- currency: e.g. "PLN"

Guidelines for Polish banks (ING, mBank, PKO, Santander):
- "Obciążenie" / "-" = expense (negative)
- "Uznanie" / "+" = income (positive)
- Skip headers, footers, balance rows.

Return ONLY valid JSON: {"transactions": [...]}"""

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": raw_text[:30000]},
                ],
                response_format={"type": "json_object"},
                max_tokens=4000,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            if isinstance(parsed, list):
                return parsed
            return parsed.get("transactions", [])
        except Exception as e:
            print(f"❌ AI Bank Statement Parse Error: {e}")
            return []
