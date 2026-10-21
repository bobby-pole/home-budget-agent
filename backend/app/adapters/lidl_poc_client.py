"""Safe research harness for issue #255.

This module deliberately does *not* contain credentials, redirect URIs, headers,
or client identities copied from a merchant's native application. It can only
be used with OAuth configuration explicitly issued to Rachownik by the provider.
Until that configuration exists, the supported mode is fixture-based contract
validation, not live merchant access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import requests

from app.receipt_schema import CanonicalItem, CanonicalReceipt


class OAuthConfigurationError(ValueError):
    """Raised when a PoC is configured with an unsafe or unsupported client."""


class OAuthCallbackError(ValueError):
    """Raised when an OAuth callback cannot be bound to an authorization attempt."""


class MerchantRequestError(RuntimeError):
    """Safe HTTP error: provider response bodies are intentionally not retained."""


class TicketMappingError(ValueError):
    """Raised when a merchant payload cannot be safely mapped to the contract."""


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> HttpResponse: ...

    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...


def _require_https_url(value: str, field_name: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise OAuthConfigurationError(f"{field_name} must be an absolute HTTPS URL")
    return value


def _callback_origin(value: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme, parsed.netloc, parsed.path


@dataclass(frozen=True)
class MerchantOAuthConfiguration:
    """Configuration that must come from a provider-authorized Rachownik client."""

    authorization_endpoint: str
    token_endpoint: str
    ticket_list_endpoint: str
    ticket_detail_endpoint_template: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "offline_access")

    def __post_init__(self) -> None:
        _require_https_url(self.authorization_endpoint, "authorization_endpoint")
        _require_https_url(self.token_endpoint, "token_endpoint")
        _require_https_url(self.ticket_list_endpoint, "ticket_list_endpoint")
        _require_https_url(self.ticket_detail_endpoint_template, "ticket_detail_endpoint_template")
        if "{ticket_id}" not in self.ticket_detail_endpoint_template:
            raise OAuthConfigurationError("ticket_detail_endpoint_template must contain {ticket_id}")
        if not self.client_id.strip():
            raise OAuthConfigurationError("client_id is required")

        callback = urllib.parse.urlsplit(self.redirect_uri)
        if not callback.scheme:
            raise OAuthConfigurationError("redirect_uri must be an absolute registered URI")
        # A copied native-app callback is not a redirect URI registered for Rachownik.
        if callback.scheme.lower() == "com.lidlplus.app":
            raise OAuthConfigurationError(
                "A Lidl Plus native-app redirect URI cannot be used by Rachownik"
            )
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise OAuthConfigurationError("at least one non-empty scope is required")


@dataclass(frozen=True)
class AuthorizationAttempt:
    """Ephemeral values that bind an OAuth callback to one browser login."""

    code_verifier: str
    state: str
    nonce: str


def _new_code_verifier() -> str:
    # RFC 7636 permits 43--128 characters from the URL-safe alphabet.
    return secrets.token_urlsafe(64)[:64]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class LidlPoCClient:
    """OAuth PKCE and ticket client for an explicitly authorized PoC only."""

    def __init__(self, config: MerchantOAuthConfiguration, session: HttpSession | None = None) -> None:
        self.config = config
        self._session = session or requests.Session()

    @staticmethod
    def generate_code_verifier(length: int = 64) -> str:
        if not 43 <= length <= 128:
            raise ValueError("PKCE verifier length must be between 43 and 128")
        return secrets.token_urlsafe(length)[:length]

    @staticmethod
    def generate_code_challenge(verifier: str) -> str:
        if not 43 <= len(verifier) <= 128:
            raise ValueError("PKCE verifier length must be between 43 and 128")
        return _code_challenge(verifier)

    def create_authorization_attempt(self) -> AuthorizationAttempt:
        return AuthorizationAttempt(
            code_verifier=_new_code_verifier(),
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
        )

    def build_authorize_url(
        self, attempt: AuthorizationAttempt, country: str = "PL", language: str = "pl-PL"
    ) -> str:
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "scope": " ".join(self.config.scopes),
            "redirect_uri": self.config.redirect_uri,
            "code_challenge": self.generate_code_challenge(attempt.code_verifier),
            "code_challenge_method": "S256",
            "state": attempt.state,
            "nonce": attempt.nonce,
            "country": country,
            "ui_locales": language,
        }
        return f"{self.config.authorization_endpoint}?{urllib.parse.urlencode(params)}"

    def validate_callback(self, callback_url: str, attempt: AuthorizationAttempt) -> str:
        """Return a code only when redirect target and state both match."""
        parsed = urllib.parse.urlsplit(callback_url)
        if _callback_origin(callback_url) != _callback_origin(self.config.redirect_uri):
            raise OAuthCallbackError("callback redirect URI does not match the registered URI")

        parameters = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if parameters.get("error"):
            raise OAuthCallbackError("provider returned an OAuth error")
        codes = parameters.get("code", [])
        states = parameters.get("state", [])
        if len(codes) != 1 or not codes[0]:
            raise OAuthCallbackError("callback must contain exactly one authorization code")
        if len(states) != 1 or not hmac.compare_digest(states[0], attempt.state):
            raise OAuthCallbackError("callback state does not match the authorization attempt")
        return codes[0]

    @staticmethod
    def _raise_for_status(response: HttpResponse, operation: str) -> None:
        if response.status_code < 200 or response.status_code >= 300:
            raise MerchantRequestError(f"{operation} failed with HTTP {response.status_code}")

    @staticmethod
    def _parse_json(response: HttpResponse, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise MerchantRequestError(f"{operation} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise MerchantRequestError(f"{operation} returned an unexpected JSON shape")
        return payload

    def exchange_code(self, code: str, attempt: AuthorizationAttempt) -> dict[str, Any]:
        """Exchange a verified code using PKCE; never log or persist the response here."""
        try:
            response = self._session.post(
                self.config.token_endpoint,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.config.client_id,
                    "code": code,
                    "redirect_uri": self.config.redirect_uri,
                    "code_verifier": attempt.code_verifier,
                },
                timeout=15,
            )
        except requests.RequestException as error:
            raise MerchantRequestError("token exchange request failed") from error
        self._raise_for_status(response, "token exchange")
        return self._parse_json(response, "token exchange")

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh a token without emitting it to logs or exception messages."""
        try:
            response = self._session.post(
                self.config.token_endpoint,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.config.client_id,
                    "refresh_token": refresh_token,
                },
                timeout=15,
            )
        except requests.RequestException as error:
            raise MerchantRequestError("token refresh request failed") from error
        self._raise_for_status(response, "token refresh")
        return self._parse_json(response, "token refresh")

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Rachownik-research/0.1",
        }

    def get_tickets_list(self, access_token: str) -> dict[str, Any]:
        try:
            response = self._session.get(
                self.config.ticket_list_endpoint, headers=self._auth_headers(access_token), timeout=15
            )
        except requests.RequestException as error:
            raise MerchantRequestError("ticket list request failed") from error
        self._raise_for_status(response, "ticket list")
        return self._parse_json(response, "ticket list")

    def get_ticket_detail(self, access_token: str, ticket_id: str) -> dict[str, Any]:
        if not ticket_id:
            raise ValueError("ticket_id is required")
        url = self.config.ticket_detail_endpoint_template.replace(
            "{ticket_id}", urllib.parse.quote(ticket_id, safe="")
        )
        try:
            response = self._session.get(url, headers=self._auth_headers(access_token), timeout=15)
        except requests.RequestException as error:
            raise MerchantRequestError("ticket detail request failed") from error
        self._raise_for_status(response, "ticket detail")
        return self._parse_json(response, "ticket detail")


def _required_decimal(value: Any, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TicketMappingError(f"{field_name} is required")
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as error:
        raise TicketMappingError(f"{field_name} must be a decimal") from error
    if not result.is_finite():
        raise TicketMappingError(f"{field_name} must be a finite decimal")
    return result


def _ticket_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TicketMappingError("date is required")
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError as error:
        raise TicketMappingError("date must be ISO-8601") from error


def lidl_ticket_to_canonical(raw_ticket: dict[str, Any]) -> CanonicalReceipt:
    """Map a documented ticket payload without retaining raw purchase data."""
    if not isinstance(raw_ticket, dict):
        raise TicketMappingError("ticket payload must be an object")

    raw_lines = raw_ticket.get("itemsLine")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise TicketMappingError("itemsLine must be a non-empty list")

    items: list[CanonicalItem] = []
    for index, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            raise TicketMappingError(f"itemsLine[{index}] must be an object")
        name = str(line.get("name") or line.get("description") or "").strip()
        if not name:
            raise TicketMappingError(f"itemsLine[{index}].name is required")
        unit_price = _required_decimal(line.get("currentUnitPrice"), f"itemsLine[{index}].currentUnitPrice")
        quantity = _required_decimal(line.get("quantity"), f"itemsLine[{index}].quantity")
        if quantity <= 0:
            raise TicketMappingError(f"itemsLine[{index}].quantity must be positive")

        discounts = line.get("discounts", [])
        if not isinstance(discounts, list):
            raise TicketMappingError(f"itemsLine[{index}].discounts must be a list")
        if any(not isinstance(discount, dict) for discount in discounts):
            raise TicketMappingError(f"itemsLine[{index}].discounts entries must be objects")
        discount_total = -sum(
            (abs(_required_decimal(discount.get("amount"), f"itemsLine[{index}].discounts.amount"))
             for discount in discounts),
            Decimal("0"),
        )

        item = CanonicalItem(
            name=name,
            unit_price=unit_price,
            quantity=quantity,
            discount_total=discount_total,
            original_price=(
                _required_decimal(line["originalUnitPrice"], f"itemsLine[{index}].originalUnitPrice")
                if line.get("originalUnitPrice") is not None else None
            ),
            is_adjustment=bool(
                line.get("isDeposit", False)
                or line.get("isAdjustment", False)
                or "kaucja" in name.lower()
            ),
        )
        item["is_weighted"] = bool(line.get("isWeight", False))
        if line.get("taxRate") is not None:
            item["tax_rate"] = str(line["taxRate"])
        if line.get("taxLetter") is not None:
            item["tax_letter"] = str(line["taxLetter"])
        items.append(item)

    receipt = CanonicalReceipt(
        merchant_name=(f"Lidl {str(raw_ticket.get('storeCode') or '').strip()}".strip() or "Lidl"),
        date=_ticket_date(raw_ticket.get("date")),
        total_amount=_required_decimal(raw_ticket.get("totalAmount"), "totalAmount"),
        currency="PLN",
        items=items,
    )
    difference = abs(receipt.calculated_total - receipt.total_amount)
    receipt["validation_status"] = "verified" if difference <= Decimal("0.01") else "needs_review"
    if difference > Decimal("0.01"):
        receipt["validation_error"] = (
            f"Różnica sumy pozycji ({receipt.calculated_total}) i nagłówka "
            f"({receipt.total_amount}): {difference} PLN"
        )
    return receipt


# Synthetic fixture only. A production decision requires a separately redacted,
# provenance-recorded payload from a test account; raw account payloads must not
# be committed to the repository.
MOCK_LIDL_V3_TICKET: dict[str, Any] = {
    "id": "synthetic-ticket-001",
    "date": "2026-09-18T14:22:10Z",
    "storeCode": "PL0422",
    "totalAmount": "41.89",
    "itemsLine": [
        {"name": "Chleb żytni 500g", "quantity": "1", "currentUnitPrice": "4.29", "discounts": []},
        {"name": "Mleko 3.2% 1L", "quantity": "2", "currentUnitPrice": "3.49", "discounts": []},
        {"name": "Ser Gouda 400g", "quantity": "2", "currentUnitPrice": "11.99", "discounts": [{"amount": "4.50"}]},
        {"name": "Banany Bio", "quantity": "1.450", "currentUnitPrice": "6.99", "isWeight": True, "discounts": []},
        {"name": "Kaucja butelka zwrotna", "quantity": "1", "currentUnitPrice": "1.00", "isDeposit": True, "discounts": []},
    ],
}
