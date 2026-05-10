#!/usr/bin/env python3
"""
Quick diagnostic script for the OCR pipeline.
Run from backend/: python3 test_pipeline.py <image_path>

Tests each stage separately so you can see exactly where things break.
"""
from __future__ import annotations

import sys
import os
import json

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.ocr_pipeline import (  # noqa: E402
    ReceiptSourceDetector,
    GoogleVisionOCRService,
    reconstruct_lines,
    detect_merchant,
)


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def check_config() -> dict:
    section("0. Configuration")
    config = {
        "google_vision": bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "openai": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_API_KEY") != "dummy_key_for_tests"),
    }
    print(f"  Google Vision credentials : {'✅' if config['google_vision'] else '❌ set GOOGLE_APPLICATION_CREDENTIALS'}")
    print(f"  OpenAI API key            : {'✅' if config['openai'] else '❌ set OPENAI_API_KEY'}")

    try:
        from google.cloud import vision  # noqa: F401
        config["google_vision_sdk"] = True
        print("  google-cloud-vision SDK   : ✅ installed")
    except ImportError:
        config["google_vision_sdk"] = False
        print("  google-cloud-vision SDK   : ❌ run: pip install google-cloud-vision")

    return config


def test_source_detection(image_path: str) -> None:
    section("1. Source Detection")
    filename = os.path.basename(image_path)
    source = ReceiptSourceDetector.detect(filename)
    print(f"  File    : {filename}")
    print(f"  Source  : {source.value}")


def test_google_vision(image_path: str) -> list | None:
    section("2. Google Vision OCR")
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        ocr = GoogleVisionOCRService()
        if not ocr.available:
            print("  ⚠️  google-cloud-vision not installed — skipping")
            return None

        result = ocr.extract(image_bytes)
        print(f"  Words extracted : {len(result.words)}")
        print(f"  Engine          : {result.source_engine}")
        print("\n  Raw text (first 300 chars):")
        print(f"  {result.raw_text[:300]!r}")
        return result.words

    except RuntimeError as e:
        print(f"  ⚠️  {e}")
        return None
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def test_line_reconstruction(words) -> list[str] | None:
    section("3. Line Reconstruction")
    if words is None:
        print("  ⚠️  Skipped — no OCR words (step 2 failed)")
        return None

    lines = reconstruct_lines(words)
    print(f"  Lines reconstructed : {len(lines)}")
    print("\n  First 20 lines:")
    for i, line in enumerate(lines[:20]):
        print(f"  {i+1:3}  {line}")
    if len(lines) > 20:
        print(f"       ... ({len(lines) - 20} more lines)")
    return lines


def test_merchant_detection(lines: list[str] | None) -> str | None:
    section("4. Merchant Detection")
    if lines is None:
        print("  ⚠️  Skipped — no lines (step 3 failed)")
        return None

    merchant = detect_merchant(lines)
    if merchant:
        print(f"  ✅ Detected: {merchant}")
        print("     → will use deterministic parser (when implemented in #175)")
    else:
        print("  ❓ Unknown merchant — will fall back to AI structurizer")
    return merchant


def test_ai_fallback(image_path: str, config: dict) -> None:
    section("5. AI Fallback (full parse_receipt)")
    if not config["openai"]:
        print("  ⚠️  Skipped — OPENAI_API_KEY not set")
        return

    print("  Running AIService.parse_receipt() ...")
    print("  (This will call OpenAI API — costs ~$0.001)")

    from app.services import AIService
    result = AIService.parse_receipt(image_path)

    if result is None:
        print("  ❌ parse_receipt returned None")
        return

    print(f"\n  merchant_name  : {result.get('merchant_name')}")
    print(f"  date           : {result.get('date')}")
    print(f"  total_amount   : {result.get('total_amount')} {result.get('currency', '')}")
    items = result.get("items", [])
    print(f"  items count    : {len(items)}")
    if items:
        print("\n  First 5 items:")
        for item in items[:5]:
            print(f"    - {item.get('name'):35} {item.get('price'):>7.2f} PLN  [{item.get('category', '?')}]")
        if len(items) > 5:
            print(f"    ... ({len(items) - 5} more items)")

    print("\n  Full JSON saved to: /tmp/pipeline_result.json")
    with open("/tmp/pipeline_result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        # Default to first available test image
        uploads = "static/uploads"
        images = [f for f in os.listdir(uploads) if f.endswith((".png", ".jpg", ".jpeg"))]
        if not images:
            print("Usage: python3 test_pipeline.py <image_path>")
            sys.exit(1)
        image_path = os.path.join(uploads, images[0])
        print(f"No image specified, using: {image_path}")
    else:
        image_path = sys.argv[1]

    if not os.path.exists(image_path):
        print(f"❌ File not found: {image_path}")
        sys.exit(1)

    print(f"\n🔬 Pipeline diagnostic for: {image_path}")

    config = check_config()
    test_source_detection(image_path)
    words = test_google_vision(image_path)
    lines = test_line_reconstruction(words)
    test_merchant_detection(lines)
    test_ai_fallback(image_path, config)

    print(f"\n{'─' * 60}")
    print("  Done.")
    print('─' * 60)


if __name__ == "__main__":
    main()
