#!/usr/bin/env python3
"""
CLI Test Harness for Canonical Receipt Parsing Architecture.

Runs receipt files (JSON, PDF, PNG, JPG) through PipelineRunner,
displays normalized line items with unit prices, discounts, and line totals,
and validates against the receipt total.

Usage:
    python backend/scripts/test_pipeline_cli.py /Users/robert/Documents/paragony/
    python backend/scripts/test_pipeline_cli.py /Users/robert/Documents/paragony/receipt\\ 2.json
    python backend/scripts/test_pipeline_cli.py /Users/robert/Documents/paragony/ --summary
    python backend/scripts/test_pipeline_cli.py /Users/robert/Documents/paragony/ --json-report report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from typing import Any, Optional

# Ensure app package is importable
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

# Try loading .env from repo root or backend/
load_dotenv(os.path.join(_BACKEND_DIR, "..", ".env"))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from app.pipeline_logger import PipelineLogger  # noqa: E402
from app.pipeline_runner import AICallbacks, PipelineRunner  # noqa: E402
from app.receipt_schema import to_decimal  # noqa: E402


def _serialize(obj: Any) -> Any:
    """JSON serializer for Decimal and other non-standard types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)


def _format_money(val: Any) -> str:
    try:
        d = to_decimal(val)
        return f"{d:.2f} zł"
    except Exception:
        return f"{val} zł"


def _format_qty(val: Any) -> str:
    try:
        d = to_decimal(val)
        if d == d.to_integral():
            return f"{int(d)}"
        return f"{d:.3f}".rstrip("0")
    except Exception:
        return str(val)


def _truncate(text: str, max_len: int = 35) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def find_receipt_files(target_path: str) -> list[str]:
    """Find all eligible receipt files given a path or directory."""
    if not os.path.exists(target_path):
        print(f"❌ Error: Path does not exist: {target_path}", file=sys.stderr)
        return []

    if os.path.isfile(target_path):
        return [target_path]

    valid_exts = {".json", ".pdf", ".png", ".jpg", ".jpeg"}
    files: list[str] = []
    for entry in sorted(os.listdir(target_path)):
        if entry.startswith("."):
            continue
        full_p = os.path.join(target_path, entry)
        if os.path.isfile(full_p):
            _, ext = os.path.splitext(entry)
            if ext.lower() in valid_exts:
                files.append(full_p)
    return files


def run_file(
    file_path: str,
    no_ai: bool = True,
    verbose: bool = False,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Run a single file through the pipeline runner."""
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    logger = PipelineLogger(verbose=verbose)

    ai_callbacks = AICallbacks()
    if not no_ai:
        from app.services import AIService

        ai_callbacks = AICallbacks(
            structurize=AIService._ai_structurize,
            vision_fallback=AIService._ai_vision_fallback,
        )

    runner = PipelineRunner(
        logger=logger,
        no_ai=no_ai,
        ai=ai_callbacks,
    )

    result = runner.run(file_bytes, filename)
    log_dict = logger.to_dict()

    # Determine route / parser chosen
    parser_used = "unknown"
    for stage in logger.stages:
        if stage.route_chosen:
            parser_used = stage.route_chosen

    file_info = {
        "file_path": file_path,
        "filename": filename,
        "size_bytes": len(file_bytes),
        "parser_used": parser_used,
        "pipeline_log": log_dict,
    }

    return file_info, result


def display_receipt_detail(file_info: dict[str, Any], result: Optional[dict[str, Any]]) -> None:
    """Print a rich ASCII table of the receipt items and calculations."""
    filename = file_info["filename"]
    print("\n" + "=" * 96)
    print(f" 📄 FILE: {filename}  ({file_info['size_bytes']:,} bytes)")
    print("=" * 96)

    if result is None:
        print(" ❌ Pipeline execution returned no data (Failed).")
        return

    merchant = result.get("merchant_name", "Unknown")
    date = result.get("date", "—")
    currency = result.get("currency", "PLN")
    total_amount = to_decimal(result.get("total_amount", 0))
    items = result.get("items", [])

    print(f"  Merchant: {merchant:<30} Date: {date:<15} Parser: {file_info['parser_used']}")
    print(f"  Document Total: {_format_money(total_amount)} ({currency})")
    print("─" * 96)

    # Items table header
    # Columns: # | Product Name | Qty | Unit Price | Discount | Line Total | Type
    print(
        f" {'#':<3} | {'Product Name':<34} | {'Qty':>6} | {'Unit Price':>11} | {'Discount':>10} | {'Line Total':>11} | {'Type':<6}"
    )
    print("─" * 96)

    calculated_sum = Decimal("0")
    for idx, item in enumerate(items, start=1):
        name = _truncate(str(item.get("name", "Unknown")), 34)
        qty = _format_qty(item.get("quantity", 1))
        unit_price = _format_money(item.get("unit_price", item.get("price", 0)))
        
        disc_val = to_decimal(item.get("discount_total", 0))
        discount_str = _format_money(disc_val) if disc_val != Decimal("0") else "—"
        
        line_tot = to_decimal(item.get("final_line_total", to_decimal(item.get("price", 0)) * to_decimal(item.get("quantity", 1))))
        line_tot_str = _format_money(line_tot)
        calculated_sum += line_tot

        is_adj = item.get("is_adjustment", False)
        item_type = "Adj" if is_adj else "Item"

        print(
            f" {idx:<3} | {name:<34} | {qty:>6} | {unit_price:>11} | {discount_str:>10} | {line_tot_str:>11} | {item_type:<6}"
        )

    print("─" * 96)

    # Sum check & validation
    delta = calculated_sum - total_amount
    delta_str = f"{delta:+.2f} zł"
    is_sum_ok = abs(delta) <= Decimal("0.01")
    sum_symbol = "✅ OK" if is_sum_ok else "❌ MISMATCH"

    val_meta = result.get("_validation", {})
    is_valid = val_meta.get("is_valid", is_sum_ok)
    confidence = val_meta.get("confidence", 1.0)
    issues = val_meta.get("issues", [])
    val_msg = val_meta.get("message", "OK")

    print(
        f"  Items Sum: {_format_money(calculated_sum)}  vs  Doc Total: {_format_money(total_amount)}  "
        f"(Delta: {delta_str})  -->  Sum Check: {sum_symbol}"
    )
    status_str = "✅ VALID" if is_valid and not issues else ("⚠️ REVIEW NEEDED" if is_valid else "❌ INVALID")
    print(f"  Validation Status: {status_str} (Confidence: {confidence:.2f}, Issues: {issues or 'None'}, Msg: {val_msg})")


def print_summary_table(reports: list[dict[str, Any]]) -> None:
    """Print concise summary table of all processed files."""
    print("\n" + "#" * 105)
    print("  BATCH PIPELINE TEST SUMMARY")
    print("#" * 105)
    print(
        f"  {'Filename':<32} {'Merchant':<14} {'Items':>5} {'Doc Total':>11} {'Items Sum':>11} {'Delta':>8} {'Sum':<4} {'Validation':<12}"
    )
    print("─" * 105)

    for r in reports:
        fname = _truncate(r["filename"], 32)
        res = r.get("result")
        if not res:
            print(f"  {fname:<32} {'ERROR':<14} {'—':>5} {'—':>11} {'—':>11} {'—':>8} {'❌':<4} {'FAILED':<12}")
            continue

        merchant = _truncate(res.get("merchant_name", "Unknown"), 14)
        items = res.get("items", [])
        total_amount = to_decimal(res.get("total_amount", 0))
        
        calc_sum = Decimal("0")
        for it in items:
            calc_sum += to_decimal(it.get("final_line_total", to_decimal(it.get("price", 0)) * to_decimal(it.get("quantity", 1))))

        delta = calc_sum - total_amount
        sum_ok = "✅" if abs(delta) <= Decimal("0.01") else "❌"

        val_meta = res.get("_validation", {})
        is_valid = val_meta.get("is_valid", abs(delta) <= Decimal("0.01"))
        issues = val_meta.get("issues", [])

        if not is_valid:
            status = "❌ FAIL"
        elif issues:
            status = "⚠️ REVIEW"
        else:
            status = "✅ VALID"

        print(
            f"  {fname:<32} {merchant:<14} {len(items):>5} {float(total_amount):>9.2f} zł {float(calc_sum):>9.2f} zł {float(delta):>+7.2f} {sum_ok:<4} {status:<12}"
        )

    print("─" * 105)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI Test Harness for Canonical Receipt Parsing Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", help="Path to a receipt file or directory of receipts")
    parser.add_argument(
        "--no-ai",
        dest="ai",
        action="store_false",
        default=False,
        help="Disable AI fallbacks (default: True, deterministic mode)",
    )
    parser.add_argument(
        "--ai",
        dest="ai",
        action="store_true",
        help="Enable AI fallbacks (Vision / GPT-4o-mini structurizer)",
    )
    parser.add_argument(
        "--json-report",
        type=str,
        default=None,
        help="Optional file path to output structured JSON report",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only summary table across all receipts",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed stage-by-stage pipeline logs",
    )

    args = parser.parse_args()

    files = find_receipt_files(args.path)
    if not files:
        print(f"No valid receipt files found in: {args.path}")
        return 1

    print(f"\n🔍 Found {len(files)} receipt file(s) to test in '{args.path}' (AI Enabled: {args.ai})")

    reports: list[dict[str, Any]] = []
    for fpath in files:
        file_info, result = run_file(fpath, no_ai=(not args.ai), verbose=args.verbose)
        if not args.summary:
            display_receipt_detail(file_info, result)
        
        report_entry = {
            "filename": file_info["filename"],
            "file_path": file_info["file_path"],
            "parser_used": file_info["parser_used"],
            "result": result,
        }
        reports.append(report_entry)

    # Always show summary table if more than 1 file or if --summary was specified
    if len(files) > 1 or args.summary:
        print_summary_table(reports)

    if args.json_report:
        try:
            with open(args.json_report, "w", encoding="utf-8") as f:
                json.dump(reports, f, indent=2, ensure_ascii=False, default=_serialize)
            print(f"\n💾 JSON report written to: {args.json_report}")
        except Exception as e:
            print(f"❌ Failed to write JSON report: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
