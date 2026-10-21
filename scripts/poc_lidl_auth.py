#!/usr/bin/env python3
"""Network-free safety and contract harness for Issue #255.

No merchant login, callback interception, token exchange, refresh-token argument,
or endpoint probing is exposed here. Those actions require provider-issued
Rachownik OAuth configuration and an approved, separately reviewed test plan.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters.lidl_poc_client import MOCK_LIDL_V3_TICKET, lidl_ticket_to_canonical  # noqa: E402


def run_dry_run() -> bool:
    """Validate the local mapping contract using deliberately synthetic data."""
    receipt = lidl_ticket_to_canonical(MOCK_LIDL_V3_TICKET)
    difference = abs(receipt.calculated_total - receipt.total_amount)
    if receipt["validation_status"] != "verified" or difference > Decimal("0.01"):
        raise RuntimeError("synthetic mapping invariant failed")
    print("Local PoC contract checks passed (synthetic fixture only; no merchant access attempted).")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue #255 local safety harness")
    parser.add_argument("--dry-run", action="store_true", help="validate synthetic mapping only")
    parser.parse_args()
    run_dry_run()


if __name__ == "__main__":
    main()
