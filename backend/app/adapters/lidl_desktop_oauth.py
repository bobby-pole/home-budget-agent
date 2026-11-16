"""Desktop Playwright + CDP callback capture helper for Lidl Plus OAuth2 PKCE (#264).

Runs exclusively inside the owner's trusted local desktop environment.
Never bypasses CAPTCHA/MFA or logs callback URLs, authorization codes, or tokens.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from typing import Any

from app.config import settings
from app.import_scheduler import is_trusted_worker_environment


class DesktopOAuthUnavailableError(RuntimeError):
    """Raised when interactive desktop browser capture cannot run on this host."""


class DesktopOAuthCancelledError(RuntimeError):
    """Raised when the interactive login window closes or times out before redirect."""


def is_desktop_oauth_available() -> bool:
    """Return True when trusted_local desktop Playwright capture can launch a GUI browser."""
    if settings.DEMO_MODE or not is_trusted_worker_environment():
        return False
    if os.getenv("RACHOWNIK_DISABLE_DESKTOP_BROWSER", "").strip().lower() == "true":
        return False
    if importlib.util.find_spec("playwright") is None:
        return False
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def capture_lidl_oauth_callback(
    authorize_url: str,
    *,
    redirect_scheme: str = "com.lidlplus.app://",
    timeout_seconds: int = 300,
) -> str:
    """Open an interactive Chromium window and capture the custom-scheme OAuth callback URL."""
    if not is_trusted_worker_environment() or settings.DEMO_MODE:
        raise DesktopOAuthUnavailableError(
            "Desktop OAuth capture is restricted to the trusted local environment."
        )
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DesktopOAuthUnavailableError(
            "Playwright is not installed on this host."
        ) from exc

    if sys.platform not in ("darwin", "win32") and not (
        os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")
    ):
        raise DesktopOAuthUnavailableError(
            "No graphical display (DISPLAY/WAYLAND_DISPLAY) is available for desktop browser login."
        )

    captured_url: list[str] = []
    deadline = time.monotonic() + max(10, timeout_seconds)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(locale="pl-PL")
                page = context.new_page()
                page.set_default_timeout(60_000)

                cdp = context.new_cdp_session(page)
                cdp.send("Network.enable")

                def _record_callback(url: str) -> None:
                    if not captured_url and url.startswith(redirect_scheme):
                        captured_url.append(url)

                def on_cdp_response(params: dict[str, Any]) -> None:
                    headers = params.get("response", {}).get("headers", {})
                    for key, value in headers.items():
                        if str(key).lower() == "location" and isinstance(value, str):
                            _record_callback(value)

                def on_cdp_request(params: dict[str, Any]) -> None:
                    req_url = params.get("request", {}).get("url", "")
                    if isinstance(req_url, str):
                        _record_callback(req_url)
                    headers = params.get("redirectResponse", {}).get("headers", {})
                    for key, value in headers.items():
                        if str(key).lower() == "location" and isinstance(value, str):
                            _record_callback(value)

                cdp.on("Network.responseReceived", on_cdp_response)
                cdp.on("Network.requestWillBeSent", on_cdp_request)

                def handle_request(request: Any) -> None:
                    if isinstance(request.url, str):
                        _record_callback(request.url)

                page.on("request", handle_request)
                page.goto(authorize_url)

                while not captured_url:
                    if time.monotonic() >= deadline:
                        raise DesktopOAuthCancelledError(
                            "Lidl desktop login timed out before completing authorization."
                        )
                    if page.is_closed():
                        break
                    page.wait_for_timeout(400)
            finally:
                browser.close()
    except DesktopOAuthCancelledError:
        raise
    except Exception as exc:
        if "timeout" in type(exc).__name__.lower():
            raise DesktopOAuthCancelledError(
                "Lidl desktop login timed out while loading the authorization page."
            ) from exc
        raise DesktopOAuthUnavailableError(
            f"Unable to launch desktop browser for Lidl OAuth ({type(exc).__name__})."
        ) from exc

    if not captured_url:
        raise DesktopOAuthCancelledError(
            "Lidl desktop login window was closed before receiving the authorization callback."
        )
    return captured_url[0]
