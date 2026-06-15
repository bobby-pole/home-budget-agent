#!/usr/bin/env python3
"""
Receipt Pipeline Debug CLI.

Runs the full OCR pipeline on a local file with structured logging.
Supports all receipt formats: PNG, JPG, PDF, JSON (e-Paragon).

Usage:
    python scripts/debug_pipeline.py <file_path> [options]

Examples:
    python scripts/debug_pipeline.py data/receipt.json
    python scripts/debug_pipeline.py data/receipt.pdf --no-ai
    python scripts/debug_pipeline.py data/receipt.pdf --output-dir ./my_logs
    python scripts/debug_pipeline.py data/receipt.pdf --stage 3
    python scripts/debug_pipeline.py data/receipt.pdf --quiet

Inside Docker:
    docker-compose exec backend python scripts/debug_pipeline.py data/receipt.json --no-ai
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure app package is importable when run from backend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env from project root
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".env"))

from app.pipeline_logger import PipelineLogger  # noqa: E402
from app.pipeline_runner import AICallbacks, PipelineRunner  # noqa: E402


_STAGE_NAMES = {
    1: "Source Detection",
    2: "Content Extraction",
    3: "Merchant Detection",
    4: "Parsing",
    5: "Categorization",
    6: "Validation",
}


def _check_config() -> dict[str, bool]:
    """Check availability of external services."""
    config: dict[str, bool] = {
        "google_vision_credentials": bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CREDENTIALS_JSON")),
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_API_KEY") != "dummy_key_for_tests"),
    }

    try:
        from google.cloud import vision  # noqa: F401
        config["google_vision_sdk"] = True
    except ImportError:
        config["google_vision_sdk"] = False

    return config


def _build_ai_callbacks(no_ai: bool, config: dict[str, bool]) -> AICallbacks | None:
    """Build AI callbacks if AI is enabled and available."""
    if no_ai:
        return None

    ai = AICallbacks()

    if config.get("openai_api_key"):
        try:
            from app.services import AIService

            ai.structurize = AIService._ai_structurize
            ai.vision_fallback = AIService._ai_vision_fallback
            # Note: categorize is skipped in CLI mode (needs user_id + categories from DB)
        except Exception as e:
            print(f"⚠️  Could not load AI services: {e}")
    else:
        print("⚠️  OPENAI_API_KEY not set — AI structurizer/fallback unavailable")

    return ai


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receipt Pipeline Debug CLI — test OCR pipeline on local files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Stage numbers (for --stage flag):
  1  Source Detection     Detect file format (PNG/JPG/PDF/JSON)
  2  Content Extraction   Extract text/lines via OCR or text layer
  3  Merchant Detection   Identify merchant from header lines
  4  Parsing              Deterministic parser or AI structurizer
  5  Categorization       Cache + AI categorization (skipped in CLI)
  6  Validation           Sum check, zero-price, future date
        """,
    )
    parser.add_argument(
        "file",
        help="Path to receipt file (PNG, JPG, PDF, or JSON)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip all AI calls (OpenAI structurizer, categorization, vision fallback)",
    )
    parser.add_argument(
        "--output-dir",
        default="debug_logs",
        help="Directory for log files (default: debug_logs/)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress terminal output, only save log file",
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=[1, 2, 3, 4, 5, 6],
        help="Run only up to stage N (see stage list below)",
    )
    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}")
        sys.exit(1)

    with open(args.file, "rb") as f:
        file_bytes = f.read()

    if not file_bytes:
        print(f"❌ File is empty: {args.file}")
        sys.exit(1)

    filename = os.path.basename(args.file)

    # Check config
    config = _check_config()
    if not args.quiet:
        print("\n🔧 Configuration:")
        print(f"   Google Vision credentials : {'✅' if config['google_vision_credentials'] else '❌'}")
        print(f"   Google Vision SDK         : {'✅' if config.get('google_vision_sdk') else '❌'}")
        print(f"   OpenAI API key            : {'✅' if config['openai_api_key'] else '❌'}")
        print(f"   Mode                      : {'🚫 --no-ai' if args.no_ai else '🧠 AI enabled'}")
        if args.stage:
            print(f"   Max stage                 : {args.stage} ({_STAGE_NAMES.get(args.stage, '?')})")

    # Build AI callbacks
    ai = _build_ai_callbacks(args.no_ai, config)

    # Setup logger & runner
    logger = PipelineLogger(verbose=not args.quiet)
    runner = PipelineRunner(
        logger=logger,
        no_ai=args.no_ai,
        ai=ai,
        max_stage=args.stage,
    )

    # Run pipeline
    result = runner.run(file_bytes, filename)

    # Print summary
    if not args.quiet:
        logger.print_summary()

    # Save structured log
    log_path = logger.save(args.output_dir)

    # Save pipeline result as separate JSON
    if result:
        result_path = log_path.replace(".json", "_result.json")
        # Separate internal metadata from the result
        clean_result: dict = {}
        internal_keys: dict = {}
        for k, v in result.items():
            if k.startswith("_"):
                internal_keys[k] = v
            else:
                clean_result[k] = v

        output = {
            "result": clean_result,
            "metadata": internal_keys,
        }
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        if not args.quiet:
            print(f"  Result saved: {result_path}")

    # Exit code
    if result is None:
        sys.exit(1)

    validation = result.get("_validation", {})
    if validation and not validation.get("is_valid", True):
        sys.exit(2)  # Pipeline ran but validation failed

    sys.exit(0)


if __name__ == "__main__":
    main()
