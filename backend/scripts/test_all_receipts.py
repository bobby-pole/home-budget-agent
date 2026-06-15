#!/usr/bin/env python3
"""
Test all receipt formats through the pipeline and produce a structured report.

Runs each receipt file through PipelineRunner with --no-ai mode,
captures full pipeline output, and saves a combined JSON report.

Usage:
    cd backend
    uv run python scripts/test_all_receipts.py
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

# Ensure app package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".env"))

from app.pipeline_logger import PipelineLogger  # noqa: E402
from app.pipeline_runner import AICallbacks, PipelineRunner  # noqa: E402


# ── Receipt files to test ──────────────────────────────────────────────────────

RECEIPT_FILES = [
    {
        "path": "/Users/robert/Documents/paragony/Żabka eParagon 14.06.2026.json",
        "label": "Żabka eParagon (JSON)",
        "store": "Żabka",
        "format": "JSON (e-paragon)",
    },
    {
        "path": "/Users/robert/Documents/paragony/receipt 2.json",
        "label": "Biedronka eParagon (JSON)",
        "store": "Biedronka",
        "format": "JSON (e-paragon)",
    },
    {
        "path": "/Users/robert/Documents/paragony/Żabka eParagon 14.06.2026.pdf",
        "label": "Żabka eParagon (PDF)",
        "store": "Żabka",
        "format": "PDF",
    },
    {
        "path": "/Users/robert/Documents/paragony/receipt 3.pdf",
        "label": "Biedronka eParagon (PDF)",
        "store": "Biedronka",
        "format": "PDF",
    },
    {
        "path": "/Users/robert/Documents/paragony/Obrazek PNG-4C1B-B70C-9A-0.png",
        "label": "Lidl paragon #1 (PNG)",
        "store": "Lidl",
        "format": "PNG (OCR required)",
    },
    {
        "path": "/Users/robert/Documents/paragony/Obrazek PNG-280671829BB0-1.png",
        "label": "Lidl paragon #2 (PNG)",
        "store": "Lidl",
        "format": "PNG (OCR required)",
    },
]


def _serialize(obj):
    """JSON serializer for Decimal and other non-standard types."""
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _compute_items_sum(items: list[dict]) -> dict:
    """Compute items sum, discount totals, and expected total."""
    items_sum = Decimal("0")
    discount_sum = Decimal("0")
    adjustment_sum = Decimal("0")
    
    for item in items:
        price = Decimal(str(item.get("price", 0)))
        qty = Decimal(str(item.get("quantity", 1)))
        discount = Decimal(str(item.get("discount_total", 0)))
        
        if item.get("is_adjustment"):
            adjustment_sum += price * qty
        else:
            items_sum += price * qty
            discount_sum += discount
    
    return {
        "items_sum": float(items_sum),
        "adjustment_sum": float(adjustment_sum),
        "discount_sum": float(discount_sum),
        "items_plus_adjustments": float(items_sum + adjustment_sum),
    }


def _normalize_items_for_display(items: list[dict]) -> list[dict]:
    """
    Normalize items to uniform display format:
    {name, category, unit_price, quantity, discount, total_after_discount}
    """
    normalized = []
    for item in items:
        price = float(item.get("price", 0))
        qty = float(item.get("quantity", 1))
        original_price = item.get("original_price")
        discount_total = float(item.get("discount_total", 0))
        is_adjustment = item.get("is_adjustment", False)
        
        # Compute unit price and total
        if original_price is not None:
            unit_price = float(original_price)
        else:
            unit_price = price
        
        # Total after discount = price * qty (where price already includes discount per unit)
        total_after_discount = round(price * qty, 2)
        
        normalized.append({
            "name": item.get("name", "?"),
            "category": item.get("category"),
            "unit_price": round(unit_price, 2),
            "quantity": qty,
            "discount": round(discount_total, 2),
            "total_after_discount": round(total_after_discount, 2),
            "is_adjustment": is_adjustment,
        })
    
    return normalized


def run_single_receipt(file_info: dict) -> dict:
    """Run pipeline on a single receipt and capture results."""
    path = file_info["path"]
    label = file_info["label"]
    
    print(f"\n{'=' * 80}")
    print(f"  TESTING: {label}")
    print(f"  File: {path}")
    print(f"{'=' * 80}")
    
    if not os.path.exists(path):
        return {
            "label": label,
            "store": file_info["store"],
            "format": file_info["format"],
            "error": f"File not found: {path}",
        }
    
    with open(path, "rb") as f:
        file_bytes = f.read()
    
    filename = os.path.basename(path)
    
    # Run pipeline without AI
    logger = PipelineLogger(verbose=True)
    runner = PipelineRunner(
        logger=logger,
        no_ai=True,
        ai=AICallbacks(),
    )
    
    result = runner.run(file_bytes, filename)
    logger.print_summary()
    
    # Build report entry
    report: dict = {
        "label": label,
        "store": file_info["store"],
        "format": file_info["format"],
        "filename": filename,
        "file_size_bytes": len(file_bytes),
        "pipeline_log": logger.to_dict(),
    }
    
    if result is None:
        report["error"] = "Pipeline returned None"
        report["result"] = None
        return report
    
    # Separate result from metadata
    clean_result = {}
    metadata = {}
    for k, v in result.items():
        if k.startswith("_"):
            metadata[k] = v
        else:
            clean_result[k] = v
    
    report["result"] = clean_result
    report["metadata"] = metadata
    
    # Compute sum analysis
    items = clean_result.get("items", [])
    total_from_receipt = float(clean_result.get("total_amount", 0))
    sum_analysis = _compute_items_sum(items)
    sum_analysis["receipt_total"] = total_from_receipt
    sum_analysis["delta"] = round(
        sum_analysis["items_plus_adjustments"] - total_from_receipt, 2
    )
    sum_analysis["is_matching"] = abs(sum_analysis["delta"]) <= 0.01
    report["sum_analysis"] = sum_analysis
    
    # Normalize items for display
    report["normalized_items"] = _normalize_items_for_display(items)
    
    # Summary stats
    report["stats"] = {
        "items_count": len([i for i in items if not i.get("is_adjustment")]),
        "adjustments_count": len([i for i in items if i.get("is_adjustment")]),
        "has_discounts": any(float(i.get("discount_total", 0)) != 0 for i in items),
        "merchant_name": clean_result.get("merchant_name"),
        "date": clean_result.get("date"),
        "total_amount": total_from_receipt,
        "parser_used": None,  # will be filled from stages
    }
    
    # Extract parser info from stages
    for stage in logger.stages:
        if stage.stage_name in ("content_extraction", "parsing"):
            if stage.route_chosen:
                report["stats"]["parser_used"] = stage.route_chosen
    
    # Validation
    validation = metadata.get("_validation", {})
    report["validation"] = {
        "is_valid": validation.get("is_valid"),
        "confidence": validation.get("confidence"),
        "issues": validation.get("issues", []),
        "message": validation.get("message"),
    }
    
    return report


def main() -> None:
    all_reports = []
    
    for file_info in RECEIPT_FILES:
        try:
            report = run_single_receipt(file_info)
        except Exception as e:
            report = {
                "label": file_info["label"],
                "store": file_info["store"],
                "format": file_info["format"],
                "error": f"Exception: {e}",
            }
            import traceback
            traceback.print_exc()
        
        all_reports.append(report)
    
    # Save combined report
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "debug_logs",
        "all_receipts_test_report.json",
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2, ensure_ascii=False, default=_serialize)
    
    print(f"\n\n{'#' * 80}")
    print(f"  COMBINED REPORT SAVED: {output_path}")
    print(f"{'#' * 80}")
    
    # Print quick summary table
    print(f"\n{'─' * 100}")
    print(f"  {'Label':<35} {'Parser':<30} {'Total':>10} {'Items∑':>10} {'Δ':>8} {'OK?':>5}")
    print(f"{'─' * 100}")
    
    for r in all_reports:
        label = r["label"][:35]
        if "error" in r and r.get("result") is None:
            print(f"  {label:<35} {'ERROR':<30} {'—':>10} {'—':>10} {'—':>8} {'❌':>5}")
            continue
        
        stats = r.get("stats", {})
        sa = r.get("sum_analysis", {})
        parser = (stats.get("parser_used") or "—")[:30]
        total = f"{sa.get('receipt_total', 0):.2f}"
        items_sum = f"{sa.get('items_plus_adjustments', 0):.2f}"
        delta = f"{sa.get('delta', 0):.2f}"
        ok = "✅" if sa.get("is_matching") else "❌"
        
        print(f"  {label:<35} {parser:<30} {total:>10} {items_sum:>10} {delta:>8} {ok:>5}")
    
    print(f"{'─' * 100}")


if __name__ == "__main__":
    main()
