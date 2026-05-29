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
        return AIService._run_ocr_pipeline(image_bytes, categories, filename=actual_filename)

    @staticmethod
    def _run_ocr_pipeline(
        image_bytes: bytes,
        categories: Optional[list[dict]] = None,
        filename: str = "",
    ) -> Optional[dict]:
        from .ocr_pipeline import (
            ReceiptSource,
            ReceiptSourceDetector,
            GoogleVisionOCRService,
            reconstruct_lines,
            detect_merchant,
            PDFTextLayerAdapter,
            EParagonJSONAdapter,
        )

        try:
            # Detect source using magic bytes / filename
            source = ReceiptSourceDetector.detect(filename=filename, file_bytes=image_bytes)
            print(f"📡 [Pipeline] Detected source: {source.value}")

            if source == ReceiptSource.EPARAGON:
                print("⚡ [Pipeline] Structured e-Paragon JSON detected. Running fast extraction.")
                data = EParagonJSONAdapter.parse(image_bytes)
                data = AIService._categorize_parsed_items(data, categories)
                return AIService._validate_and_annotate(data)

            if source == ReceiptSource.PDF_TEXT:
                if PDFTextLayerAdapter.has_text_layer(image_bytes):
                    print("📄 [Pipeline] PDF has text layer. skipping Google Vision OCR.")
                    text = PDFTextLayerAdapter.extract_text(image_bytes)
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                else:
                    print("⚠️ [Pipeline] PDF has no text layer. Rendering first page to PNG.")
                    converted_png = PDFTextLayerAdapter.convert_to_image(image_bytes)
                    ocr = GoogleVisionOCRService()
                    result = ocr.extract(converted_png)
                    lines = reconstruct_lines(result.words)
            else:
                ocr = GoogleVisionOCRService()
                result = ocr.extract(image_bytes)
                lines = reconstruct_lines(result.words)

            merchant = detect_merchant(lines)
            print(f"🔍 [Pipeline] Detected merchant: {merchant or 'unknown'}")

            if merchant == "lidl":
                from .lidl_parser import LidlReceiptParser
                parsed = LidlReceiptParser().parse(lines)
                data = parsed.to_dict()
                # Deterministic parsers don't assign categories. Run AI categorization
                # here so Lidl items reach the staging area pre-categorized.
                # (Cache-first lookup will plug in here once #178 lands.)
                data = AIService._categorize_parsed_items(data, categories)
            else:
                # AI structurizer fallback for all unknown / not-yet-parsed merchants.
                # Categories are already assigned inside the structurizer prompt.
                data = AIService._ai_structurize("\n".join(lines), categories)

            return AIService._validate_and_annotate(data)

        except RuntimeError as e:
            # Google Vision not configured — fall back to direct AI vision (legacy path)
            print(f"⚠️ [Pipeline] OCR unavailable ({e}), falling back to AI vision")
            data = AIService._ai_vision_fallback(image_bytes, categories)
            return AIService._validate_and_annotate(data)
        except Exception as e:
            print(f"❌ OCR Pipeline Error: {e}")
            return None

    @staticmethod
    def _categorize_parsed_items(
        data: Optional[dict],
        categories: Optional[list[dict]],
    ) -> Optional[dict]:
        """
        Batch-categorize items produced by a deterministic parser.

        Skips items already categorized and basket-level adjustments (kaucja etc.).
        On AI failure leaves items without a category — staging area will let the
        user assign one manually.
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

        names = [item["name"] for _, item in targets]
        try:
            mapping = AIService.categorize_descriptions(names, categories)
        except Exception as e:
            print(f"⚠️ [Categorization] AI call failed: {e}")
            return data

        valid_cat_names = {c["name"] for c in categories}
        for idx, item in targets:
            cat = mapping.get(item["name"])
            if cat in valid_cat_names:
                items[idx]["category"] = cat

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
    def _ai_structurize(receipt_text: str, categories: Optional[list[dict]] = None) -> Optional[dict]:
        """AI structurizer — called for unknown merchant formats after OCR + line reconstruction."""
        cat_context = ""
        if categories:
            cat_list = ", ".join(f'"{c["name"]}"' for c in categories)
            cat_context = f"\nCRITICAL: Assign a category to each item using ONLY names from this list: [{cat_list}]. Do NOT invent new categories."

        system_prompt = f"""You are an expert receipt parser.
Extract structured data from the following receipt text.

Return ONLY valid JSON with this structure:
{{
    "merchant_name": "Store Name",
    "date": "YYYY-MM-DD",
    "total_amount": 123.45,
    "currency": "PLN",
    "items": [
        {{"name": "Product name", "price": 3.50, "quantity": 1, "category": "Food"}}
    ]
}}

Rules:
- date: YYYY-MM-DD format. Use today if missing.
- total_amount: the final sum paid (after discounts).
- Each item price is the unit price. quantity defaults to 1.
- Include discounts as negative-price items if visible.
{cat_context}"""

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
    def _ai_vision_fallback(image_bytes: bytes, categories: Optional[list[dict]] = None) -> Optional[dict]:
        """
        Direct AI vision — used only when Google Vision is not configured.
        Sends the whole image as-is (no chunking).
        """
        cat_context = ""
        if categories:
            cat_list = ", ".join(f'"{c["name"]}"' for c in categories)
            cat_context = f"\nCRITICAL: Assign categories ONLY from: [{cat_list}]."

        system_prompt = f"""You are an expert receipt parser. Extract data from the receipt image into JSON.
Return: merchant_name, date (YYYY-MM-DD), total_amount, currency, items (name/price/quantity/category).
{cat_context}
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

        system_prompt = f"""You are a financial assistant. Categorize each bank transaction description.
For each description pick EXACTLY ONE category from: [{cat_list_str}].
If no category fits, use the closest match.
Return ONLY a JSON object: {{"Description": "Category", ...}}"""

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(descriptions)},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            print(f"❌ AI Categorization Error: {e}")
            # Empty mapping lets callers leave items uncategorized rather than
            # poisoning the result with a non-existent "Other" category.
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
