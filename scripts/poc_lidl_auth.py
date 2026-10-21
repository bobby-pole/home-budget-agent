#!/usr/bin/env python3
"""Research & live feasibility harness for Issue #255 (Lidl Plus OAuth2 PKCE + Tickets v2/v3).

Modes:
1. `--dry-run` (default when no subcommand given):
   Validate synthetic mapping contract locally without network access.
2. `login`:
   Generate PKCE S256 authorize URL, open browser (or prompt for callback URL/code),
   exchange code for tokens, and persist encrypted/local PoC session in `scratch/lidl_poc_session.json`.
3. `refresh`:
   Test token refresh durability using the stored `refresh_token` from `scratch/lidl_poc_session.json`.
4. `tickets`:
   Fetch `/api/v2/PL/tickets` and `/api/v3/PL/tickets/{id}`, validate mapping to
   `CanonicalReceipt` / `CanonicalItem` with ±0.01 PLN tolerance, and save a redacted
   structural report in `scratch/lidl_poc_last_report.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import sys
import webbrowser
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
SCRATCH_DIR = PROJECT_ROOT / "scratch"
SESSION_FILE = SCRATCH_DIR / "lidl_poc_session.json"
REPORT_FILE = SCRATCH_DIR / "lidl_poc_last_report.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from app.core.encryption import get_encryption_service  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.adapters.lidl_poc_client import (  # noqa: E402
    MOCK_LIDL_V3_TICKET,
    AuthorizationAttempt,
    LidlPoCClient,
    extract_ticket_list_entries,
    get_lidl_live_config,
    lidl_ticket_to_canonical,
)


def run_dry_run() -> bool:
    """Validate the local mapping contract using deliberately synthetic data."""
    receipt = lidl_ticket_to_canonical(MOCK_LIDL_V3_TICKET)
    difference = abs(receipt.calculated_total - receipt.total_amount)
    if receipt["validation_status"] != "verified" or difference > Decimal("0.01"):
        raise RuntimeError("synthetic mapping invariant failed")
    print("Local PoC contract checks passed (synthetic fixture only; no merchant access attempted).")
    return True


def _save_session(token_data: dict[str, Any], target: dict[str, int] | None = None) -> None:
    """Atomically store an encrypted session, including its explicit connection binding."""
    encryption = get_encryption_service(reload_env=True)
    record = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
        "token_type": token_data.get("token_type"),
        "target": target,
    }
    ciphertext, key_id = encryption.encrypt(json.dumps(record))
    envelope = {"version": 1, "key_id": key_id, "ciphertext": ciphertext}
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".lidl-session-", dir=SESSION_FILE.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, SESSION_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _load_session() -> dict[str, Any]:
    if not SESSION_FILE.exists():
        raise RuntimeError("No PoC session found. Run scripts/poc_lidl_auth.py login first.")
    envelope = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    if "ciphertext" not in envelope:
        # Migrate legacy plaintext in place; never create a plaintext backup.
        _save_session(envelope)
        envelope = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    if envelope.get("version") != 1:
        raise RuntimeError("Unsupported encrypted session format")
    encryption = get_encryption_service(reload_env=True)
    plaintext = encryption.decrypt(envelope["ciphertext"], envelope.get("key_id"))
    return json.loads(plaintext)


def _try_playwright_login(authorize_url: str, redirect_scheme: str = "com.lidlplus.app://") -> str | None:
    """Attempt to capture the custom-scheme callback automatically via Playwright + CDP."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return None

    captured_url: list[str] = []
    print("Opening interactive Chromium window via Playwright...")
    print("Log into your Lidl Plus account in the browser window. It will close automatically upon redirect.")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(locale="pl-PL")
        page = context.new_page()

        # Listen on both Playwright requests and CDP Network responses (302 Location header)
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")

        def on_cdp_response(params: dict[str, Any]) -> None:
            response = params.get("response", {})
            headers = response.get("headers", {})
            for k, v in headers.items():
                if k.lower() == "location" and isinstance(v, str) and v.startswith(redirect_scheme):
                    captured_url.append(v)

        def on_cdp_request(params: dict[str, Any]) -> None:
            req_url = params.get("request", {}).get("url", "")
            if isinstance(req_url, str) and req_url.startswith(redirect_scheme):
                captured_url.append(req_url)
            redirect_resp = params.get("redirectResponse", {})
            headers = redirect_resp.get("headers", {})
            for k, v in headers.items():
                if k.lower() == "location" and isinstance(v, str) and v.startswith(redirect_scheme):
                    captured_url.append(v)

        cdp.on("Network.responseReceived", on_cdp_response)
        cdp.on("Network.requestWillBeSent", on_cdp_request)

        def handle_request(request: Any) -> None:
            if request.url.startswith(redirect_scheme):
                captured_url.append(request.url)

        page.on("request", handle_request)
        page.goto(authorize_url)
        while not captured_url:
            page.wait_for_timeout(400)
            if page.is_closed():
                break
        browser.close()
    return captured_url[0] if captured_url else None


def _connection_for_target(session: Any, target: dict[str, int]) -> Any:
    from app.connection_service import ConnectionService
    from app.models import User

    if set(target) != {"connection_id", "budget_id", "user_id"} or any(
        type(value) is not int or value <= 0 for value in target.values()
    ):
        raise ValueError("Specify positive connection_id, budget_id and user_id")
    user = session.get(User, target["user_id"])
    if user is None:
        raise ValueError("Selected user does not exist")
    ConnectionService._require_write_member(session, target["budget_id"], user)
    connection = ConnectionService.get_connection(
        session, target["budget_id"], target["connection_id"], user
    )
    if connection.provider != "lidl":
        raise ValueError("Selected connection is not a Lidl connection")
    return connection


def _validate_target(target: dict[str, int]) -> None:
    from sqlmodel import Session, create_engine

    db_path = PROJECT_ROOT / "data" / "database.db"
    if not db_path.exists():
        raise RuntimeError("Local application database does not exist")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            _connection_for_target(session, target)
    finally:
        engine.dispose()


def _sync_token_to_local_db(token_data: dict[str, Any], target: dict[str, int]) -> None:
    """Update exactly the selected connection after checking household ownership."""
    from sqlmodel import Session, create_engine
    from app.connection_service import ConnectionService

    _validate_target(target)
    # Refuse absent/invalid key configuration; there is no default key.
    get_encryption_service(reload_env=True)
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("Authorization result must include a refresh token")
    engine = create_engine(f"sqlite:///{PROJECT_ROOT / 'data' / 'database.db'}")
    try:
        with Session(engine) as session:
            connection = _connection_for_target(session, target)
            ConnectionService.complete_authorization(
                session, connection, refresh_token=refresh_token,
                consented_scopes=str(token_data.get("scope") or ""),
            )
    finally:
        engine.dispose()
    print("Selected Lidl connection updated; other connections were not changed.")


def run_live_login(
    open_browser: bool = True, callback_input: str | None = None,
    target: dict[str, int] | None = None,
) -> None:
    # Validate key configuration and ownership before opening a browser or contacting Lidl.
    get_encryption_service(reload_env=True).primary_key_id
    if target is not None:
        _validate_target(target)
    client = LidlPoCClient(get_lidl_live_config())
    attempt: AuthorizationAttempt = client.create_authorization_attempt()
    authorize_url = client.build_authorize_url(attempt)

    print("\n=== Lidl Plus OAuth2 PKCE (S256) Interactive Login ===")
    print(f"Authorize URL:\n{authorize_url}\n")

    captured = callback_input
    if not captured and open_browser:
        captured = _try_playwright_login(authorize_url)
        if not captured:
            print("Opening default browser (Playwright not installed; falling back to system browser)...")
            print(
                "Tip: Open DevTools -> Network (Preserve log), sign in, and copy the "
                "`com.lidlplus.app://callback?code=...&state=...` URL (or just the `code`).\n"
            )
            webbrowser.open(authorize_url)

    if not captured:
        captured = input("Paste callback URL (`com.lidlplus.app://callback?code=...`) or raw `code`: ").strip()

    code = client.validate_callback(captured, attempt, allow_raw_code=True)
    token_data = client.exchange_code(code, attempt)
    _save_session(token_data, target)
    if target is not None:
        _sync_token_to_local_db(token_data, target)
    print(f"✅ Token exchange succeeded! Encrypted session saved to {SESSION_FILE} (0600 permissions).")
    print(f"   expires_in={token_data.get('expires_in')}s, has_refresh_token={bool(token_data.get('refresh_token'))}")


def run_live_refresh() -> None:
    session_data = _load_session()
    refresh_token = str(session_data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise RuntimeError("Stored session has no refresh_token")

    target = session_data.get("target")
    if target is not None:
        _validate_target(target)
    client = LidlPoCClient(get_lidl_live_config())
    token_data = client.refresh_access_token(refresh_token)
    # OAuth providers may omit a replacement refresh token or unchanged scopes.
    token_data["refresh_token"] = token_data.get("refresh_token") or refresh_token
    token_data["scope"] = token_data.get("scope") or session_data.get("scope")
    _save_session(token_data, target)
    if target is not None:
        _sync_token_to_local_db(token_data, target)
    rotated = token_data.get("refresh_token") != refresh_token
    print("✅ Token refresh succeeded!")
    print(
        f"   expires_in={token_data.get('expires_in')}s, "
        f"refresh_token_rotated={rotated}, "
        f"scope={token_data.get('scope')}"
    )


def run_live_tickets(limit: int = 3) -> None:
    session_data = _load_session()
    access_token = str(session_data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Stored session has no access_token")

    client = LidlPoCClient(get_lidl_live_config())
    list_payload = client.get_tickets_list(access_token, page_number=1)
    entries = extract_ticket_list_entries(list_payload)
    print(f"✅ Fetched ticket list: {len(entries)} entries on page 1.")

    reports: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        ticket_id = str(entry.get("id") or "").strip()
        if not ticket_id:
            continue
        detail = client.get_ticket_detail(access_token, ticket_id)
        canonical = lidl_ticket_to_canonical(detail)
        diff = abs(canonical.calculated_total - canonical.total_amount)
        status = canonical["validation_status"]
        print(
            f"  • Ticket {ticket_id[:8]}... | date={canonical.date} | "
            f"merchant={canonical.merchant_name} | items={len(canonical.items)} | "
            f"total={canonical.total_amount} PLN | calc={canonical.calculated_total} PLN | "
            f"diff={diff} PLN | status={status}"
        )
        reports.append(
            {
                "ticket_id_prefix": ticket_id[:8],
                "date": canonical.date,
                "merchant_name": canonical.merchant_name,
                "item_count": len(canonical.items),
                "total_amount": str(canonical.total_amount),
                "calculated_total": str(canonical.calculated_total),
                "difference": str(diff),
                "validation_status": status,
                "top_level_keys": sorted(detail.keys()),
            }
        )

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"📄 Redacted verification report saved to {REPORT_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue #255 Lidl Plus PoC & contract harness")
    parser.add_argument("--dry-run", action="store_true", help="validate synthetic mapping only")
    subparsers = parser.add_subparsers(dest="command")

    login_p = subparsers.add_parser("login", help="interactive PKCE S256 login")
    login_p.add_argument("--no-browser", action="store_true", help="do not open browser automatically")
    login_p.add_argument("--callback", type=str, default=None, help="callback URL or code")

    for field in ("connection-id", "budget-id", "user-id"):
        login_p.add_argument(f"--{field}", type=int, help="explicit local connection binding (provide all three)")
    subparsers.add_parser("migrate-session", help="encrypt an existing local plaintext session without network access")
    subparsers.add_parser("refresh", help="refresh access_token using stored refresh_token")

    tickets_p = subparsers.add_parser("tickets", help="fetch tickets list and v3 details")
    tickets_p.add_argument("--limit", type=int, default=3, help="max tickets to inspect")

    args = parser.parse_args()
    if args.command == "login":
        supplied = [args.connection_id, args.budget_id, args.user_id]
        if any(value is not None for value in supplied) and not all(value is not None and value > 0 for value in supplied):
            parser.error("Provide positive --connection-id, --budget-id and --user-id together")
        target: dict[str, int] | None = {"connection_id": args.connection_id, "budget_id": args.budget_id, "user_id": args.user_id} if all(value is not None for value in supplied) else None
        run_live_login(open_browser=not args.no_browser, callback_input=args.callback, target=target)
    elif args.command == "migrate-session":
        _load_session()
        print("Session encrypted successfully; no provider request or database update performed.")
    elif args.command == "refresh":
        run_live_refresh()
    elif args.command == "tickets":
        run_live_tickets(limit=args.limit)
    else:
        run_dry_run()


if __name__ == "__main__":
    main()
