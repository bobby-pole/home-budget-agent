"""Lidl Plus OAuth2 PKCE and ticket adapter for issue #255.

Supports both:
- Strict provider-registered OAuth configuration and synthetic contract validation.
- Live Lidl Plus PoC configuration (LidlPlusNativeClient, S256 PKCE, token exchange,
  token refresh, /api/v2/PL/tickets list, /api/v3/PL/tickets/{id} detail, and
  CanonicalReceipt mapping with ±0.01 PLN sum validation).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_lib
import os
import re
import secrets
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import requests

from app.lidl_parser import LidlReceiptParser
from app.receipt_schema import CanonicalItem, CanonicalReceipt


class OAuthConfigurationError(ValueError):
    """Raised when a PoC is configured with an unsafe or unsupported client."""


class OAuthCallbackError(ValueError):
    """Raised when an OAuth callback cannot be bound to an authorization attempt."""


class MerchantRequestError(RuntimeError):
    """Safe HTTP error: provider response bodies are intentionally not retained."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path


@dataclass(frozen=True)
class MerchantOAuthConfiguration:
    """OAuth2 PKCE and API configuration for a merchant receipt source."""

    authorization_endpoint: str
    token_endpoint: str
    ticket_list_endpoint: str
    ticket_detail_endpoint_template: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "offline_access")
    client_secret: str | None = None
    allow_native_redirect: bool = False
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    default_api_headers: dict[str, str] = field(default_factory=dict)

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
        if callback.scheme.lower() == "com.lidlplus.app" and not self.allow_native_redirect:
            raise OAuthConfigurationError(
                "A Lidl Plus native-app redirect URI cannot be used by Rachownik"
            )
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise OAuthConfigurationError("at least one non-empty scope is required")


def get_lidl_live_config(country: str = "PL") -> MerchantOAuthConfiguration:
    """Return the live Lidl Plus OAuth2 PKCE configuration for Poland."""
    country_clean = country.strip().upper() or "PL"
    device_id = os.getenv("LIDL_POC_DEVICE_ID") or str(uuid.uuid4())
    app_version = os.getenv("LIDL_POC_APP_VERSION", "16.40.20")
    return MerchantOAuthConfiguration(
        authorization_endpoint="https://accounts.lidl.com/connect/authorize",
        token_endpoint="https://accounts.lidl.com/connect/token",
        ticket_list_endpoint=f"https://tickets.lidlplus.com/api/v2/{country_clean}/tickets",
        ticket_detail_endpoint_template=f"https://tickets.lidlplus.com/api/v3/{country_clean}/tickets/{{ticket_id}}",
        client_id=os.getenv("LIDL_CLIENT_ID", "LidlPlusNativeClient"),
        client_secret=os.getenv("LIDL_CLIENT_SECRET", "secret"),
        redirect_uri=os.getenv("LIDL_REDIRECT_URI", "com.lidlplus.app://callback"),
        scopes=("openid", "profile", "offline_access", "lpprofile", "lpapis"),
        allow_native_redirect=True,
        extra_authorize_params={
            "Country": country_clean,
            "language": f"{country_clean.lower()}-{country_clean}",
            "track": "true",
        },
        default_api_headers={
            "User-Agent": (
                f"LidlSocialInternacional/{app_version} "
                "(com.lidl.eci.lidl.plus; build:1378; iOS 17.3.1) Alamofire/5.10.2"
            ),
            "App-Version": app_version,
            "Operating-System": "iOS",
            "App": "com.lidl.eci.lidl.plus",
            "Deviceid": device_id,
            "Accept-Language": "pl",
        },
    )


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
    """OAuth PKCE and ticket client for Lidl Plus."""

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
        params: dict[str, str] = {
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
        if self.config.extra_authorize_params:
            params.update(self.config.extra_authorize_params)
        return f"{self.config.authorization_endpoint}?{urllib.parse.urlencode(params)}"

    def validate_callback(
        self,
        callback_url_or_code: str,
        attempt: AuthorizationAttempt,
        *,
        allow_raw_code: bool = False,
    ) -> str:
        """Return a code when redirect target and state both match (or raw code when explicitly allowed)."""
        cleaned = callback_url_or_code.strip()
        if not cleaned:
            raise OAuthCallbackError("callback cannot be empty")

        if allow_raw_code and "://" not in cleaned and "code=" not in cleaned and "?" not in cleaned:
            return cleaned

        if cleaned.startswith("?") or (cleaned.startswith("code=") and "://" not in cleaned):
            cleaned = f"{self.config.redirect_uri}?{cleaned.lstrip('?')}"

        parsed = urllib.parse.urlsplit(cleaned)
        if _callback_origin(cleaned) != _callback_origin(self.config.redirect_uri):
            raise OAuthCallbackError("callback redirect URI does not match the registered URI")

        parameters = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if parameters.get("error"):
            raise OAuthCallbackError("provider returned an OAuth error")
        codes = parameters.get("code", [])
        states = parameters.get("state", [])
        if len(codes) != 1 or not codes[0]:
            raise OAuthCallbackError("callback must contain exactly one authorization code")
        if states:
            if len(states) != 1 or not hmac.compare_digest(states[0], attempt.state):
                raise OAuthCallbackError("callback state does not match the authorization attempt")
        else:
            raise OAuthCallbackError("callback state does not match the authorization attempt")
        return codes[0]

    @staticmethod
    def _raise_for_status(response: HttpResponse, operation: str) -> None:
        if response.status_code < 200 or response.status_code >= 300:
            raise MerchantRequestError(
                f"{operation} failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )

    @staticmethod
    def _parse_json(response: HttpResponse, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise MerchantRequestError(f"{operation} returned invalid JSON") from error
        if isinstance(payload, list):
            return {"tickets": payload}
        if not isinstance(payload, dict):
            raise MerchantRequestError(f"{operation} returned an unexpected JSON shape")
        return payload

    def _token_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        if self.config.client_secret:
            raw_basic = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
            b64_basic = base64.b64encode(raw_basic).decode("ascii")
            headers["Authorization"] = f"Basic {b64_basic}"
        return headers

    def exchange_code(self, code: str, attempt: AuthorizationAttempt) -> dict[str, Any]:
        """Exchange a verified code using PKCE; never log or persist the response here."""
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "code_verifier": attempt.code_verifier,
        }
        if not self.config.client_secret:
            data["client_id"] = self.config.client_id
        try:
            response = self._session.post(
                self.config.token_endpoint,
                headers=self._token_headers(),
                data=data,
                timeout=15,
            )
        except requests.RequestException as error:
            raise MerchantRequestError("token exchange request failed") from error
        self._raise_for_status(response, "token exchange")
        return self._parse_json(response, "token exchange")

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh a token without emitting it to logs or exception messages."""
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if not self.config.client_secret:
            data["client_id"] = self.config.client_id
        try:
            response = self._session.post(
                self.config.token_endpoint,
                headers=self._token_headers(),
                data=data,
                timeout=15,
            )
        except requests.RequestException as error:
            raise MerchantRequestError("token refresh request failed") from error
        self._raise_for_status(response, "token refresh")
        return self._parse_json(response, "token refresh")

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Rachownik-research/0.1",
        }
        if self.config.default_api_headers:
            headers.update(self.config.default_api_headers)
        return headers

    def get_tickets_list(self, access_token: str, page_number: int = 1) -> dict[str, Any]:
        url = self.config.ticket_list_endpoint
        if self.config.allow_native_redirect and "?" not in url:
            url = f"{url}?pageNumber={page_number}&onlyFavorite=false"
        try:
            response = self._session.get(
                url, headers=self._auth_headers(access_token), timeout=15
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
        result = Decimal(str(value).replace("−", "-").replace(",", ".").strip())
    except (InvalidOperation, ValueError) as error:
        raise TicketMappingError(f"{field_name} must be a decimal") from error
    if not result.is_finite():
        raise TicketMappingError(f"{field_name} must be a finite decimal")
    return result


def _optional_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return _required_decimal(value, field_name)


def _ticket_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TicketMappingError("date is required")
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError as error:
        raise TicketMappingError("date must be ISO-8601") from error


def extract_ticket_list_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract ticket metadata objects from v2 ticket list response variants."""
    for key in ("tickets", "items", "records", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [entry for entry in candidate if isinstance(entry, dict)]
    return []


def _parse_html_printed_receipt(
    ticket_obj: dict[str, Any], raw_html: str
) -> CanonicalReceipt:
    """Parse Polish Lidl Plus v3 HTML receipt (`ticketType == 'HTML'`, `htmlPrintedReceipt`)
    deterministically using `LidlReceiptParser` and enrich with tax/weight metadata from `data-*` spans.
    """
    pre_match = re.search(r"<pre>(.*?)</pre>", raw_html, re.DOTALL | re.IGNORECASE)
    pre_content = pre_match.group(1) if pre_match else raw_html
    plain_lines = [
        html_lib.unescape(re.sub(r"<[^>]+>", "", line)).strip()
        for line in pre_content.splitlines()
    ]
    parsed = LidlReceiptParser().parse(plain_lines)
    if not parsed.items:
        raise TicketMappingError("htmlPrintedReceipt produced no line items")

    # Enrich tax letters & weighted flags from span attributes where available
    tax_map: dict[str, str] = {}
    for m_vat in re.finditer(
        r'data-tax-type="([A-E])"\s+data-tax-percentage="([^"]+)"', raw_html
    ):
        tax_map[m_vat.group(1)] = m_vat.group(2).replace(",", ".")

    article_meta: list[tuple[str, str | None, bool]] = []
    seen_span_pair = False
    for m_art in re.finditer(r"<span[^>]*class=\"article\"[^>]*>", raw_html):
        tag_str = m_art.group(0)
        desc_m = re.search(r'data-art-description="([^"]+)"', tag_str)
        tax_m = re.search(r'data-tax-type="([A-E])"', tag_str)
        qty_m = re.search(r'data-art-quantity="([^"]+)"', tag_str)
        # Each article spans two lines (name line + price line) in Lidl HTML
        if not seen_span_pair:
            seen_span_pair = True
            desc = html_lib.unescape(desc_m.group(1)).strip() if desc_m else ""
            tax_letter = tax_m.group(1) if tax_m else None
            is_weight = bool(qty_m and ("," in qty_m.group(1) or "." in qty_m.group(1)))
            article_meta.append((desc, tax_letter, is_weight))
        else:
            seen_span_pair = False

    meta_idx = 0
    for item in parsed.items:
        if item.is_adjustment:
            item["is_weighted"] = False
            continue
        if meta_idx < len(article_meta):
            _, tax_letter, is_weight = article_meta[meta_idx]
            item["is_weighted"] = is_weight or (item.quantity % 1 != 0)
            if tax_letter:
                item["tax_letter"] = tax_letter
                if tax_letter in tax_map:
                    item["tax_rate"] = tax_map[tax_letter]
            meta_idx += 1
        else:
            item["is_weighted"] = item.quantity % 1 != 0

    store_info = ticket_obj.get("store") if isinstance(ticket_obj.get("store"), dict) else {}
    raw_store = (
        ticket_obj.get("storeCode")
        or (store_info or {}).get("locality")
        or (store_info or {}).get("name")
        or (store_info or {}).get("id")
        or ""
    )
    merchant_name = f"Lidl {str(raw_store).strip()}".strip() or "Lidl"
    raw_total = (
        ticket_obj.get("totalAmount")
        if ticket_obj.get("totalAmount") is not None
        else ticket_obj.get("totalAmountNumeric")
    )
    total_amount = (
        _required_decimal(raw_total, "totalAmount")
        if raw_total is not None
        else parsed.total_amount
    )
    ticket_date = (
        _ticket_date(ticket_obj.get("date"))
        if ticket_obj.get("date")
        else (parsed.date or date.today().isoformat())
    )

    receipt = CanonicalReceipt(
        merchant_name=merchant_name,
        date=ticket_date,
        total_amount=total_amount,
        currency="PLN",
        items=parsed.items,
    )
    difference = abs(receipt.calculated_total - receipt.total_amount)
    receipt["validation_status"] = "verified" if difference <= Decimal("0.01") else "needs_review"
    if difference > Decimal("0.01"):
        receipt["validation_error"] = (
            f"Różnica sumy pozycji ({receipt.calculated_total}) i nagłówka "
            f"({receipt.total_amount}): {difference} PLN"
        )
    if ticket_obj.get("id"):
        receipt["source_receipt_id"] = str(ticket_obj["id"])
    return receipt


def lidl_ticket_to_canonical(raw_ticket: dict[str, Any]) -> CanonicalReceipt:
    """Map a Lidl Plus v3 ticket payload into a CanonicalReceipt without retaining raw PII."""
    if not isinstance(raw_ticket, dict):
        raise TicketMappingError("ticket payload must be an object")

    # Unwrap nested {"ticket": {...}} if returned by specific API versions
    ticket_obj = raw_ticket.get("ticket") if isinstance(raw_ticket.get("ticket"), dict) else raw_ticket
    assert isinstance(ticket_obj, dict)

    raw_lines = ticket_obj.get("itemsLine")
    html_receipt = ticket_obj.get("htmlPrintedReceipt")
    if (not isinstance(raw_lines, list) or not raw_lines) and isinstance(html_receipt, str) and html_receipt.strip():
        return _parse_html_printed_receipt(ticket_obj, html_receipt)

    if not isinstance(raw_lines, list) or not raw_lines:
        raise TicketMappingError("itemsLine must be a non-empty list")

    items: list[CanonicalItem] = []
    for index, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            raise TicketMappingError(f"itemsLine[{index}] must be an object")
        name = str(
            line.get("name")
            or line.get("description")
            or line.get("extendedAmount")
            or ""
        ).strip()
        if not name:
            raise TicketMappingError(f"itemsLine[{index}].name is required")

        raw_unit_price = (
            line.get("currentUnitPrice")
            if line.get("currentUnitPrice") is not None
            else line.get("unitPrice")
        )
        if raw_unit_price is None and line.get("originalAmount") is not None:
            raw_unit_price = line.get("originalAmount")

        unit_price = _required_decimal(raw_unit_price, f"itemsLine[{index}].currentUnitPrice")

        raw_qty = line.get("quantity")
        if raw_qty is None:
            raw_qty = "1" if "currentUnitPrice" not in line and "unitPrice" in line else None
        quantity = _required_decimal(raw_qty, f"itemsLine[{index}].quantity")
        if quantity <= 0:
            raise TicketMappingError(f"itemsLine[{index}].quantity must be positive")

        discounts = line.get("discounts")
        if discounts is None:
            discounts = []
        if not isinstance(discounts, list):
            raise TicketMappingError(f"itemsLine[{index}].discounts must be a list")
        if any(not isinstance(discount, dict) for discount in discounts):
            raise TicketMappingError(f"itemsLine[{index}].discounts entries must be objects")
        discount_total = -sum(
            (
                abs(
                    _required_decimal(
                        discount.get("amount") if discount.get("amount") is not None else discount.get("discountAmount"),
                        f"itemsLine[{index}].discounts.amount",
                    )
                )
                for discount in discounts
            ),
            Decimal("0"),
        )

        # Handle explicit deposit sub-object returned by Lidl v3 on beverages
        deposit_obj = line.get("deposit")

        item = CanonicalItem(
            name=name,
            unit_price=unit_price,
            quantity=quantity,
            discount_total=discount_total,
            original_price=(
                _required_decimal(line["originalUnitPrice"], f"itemsLine[{index}].originalUnitPrice")
                if line.get("originalUnitPrice") is not None
                else None
            ),
            is_adjustment=bool(
                line.get("isDeposit", False)
                or line.get("isAdjustment", False)
                or "kaucja" in name.lower()
                or "opakowania zwrotne" in name.lower()
            ),
        )
        item["is_weighted"] = bool(line.get("isWeight", False))
        tax_rate = line.get("taxRate") if line.get("taxRate") is not None else line.get("taxGroupName")
        if tax_rate is not None:
            item["tax_rate"] = str(tax_rate)
        tax_letter = line.get("taxLetter") if line.get("taxLetter") is not None else line.get("taxGroup")
        if tax_letter is not None:
            item["tax_letter"] = str(tax_letter)
        items.append(item)

        if isinstance(deposit_obj, dict) and deposit_obj.get("unitPrice") is not None:
            dep_unit = _required_decimal(deposit_obj.get("unitPrice"), f"itemsLine[{index}].deposit.unitPrice")
            dep_qty = _optional_decimal(deposit_obj.get("quantity"), f"itemsLine[{index}].deposit.quantity") or quantity
            dep_name = str(deposit_obj.get("description") or f"Kaucja ({name})").strip()
            items.append(
                CanonicalItem(
                    name=dep_name,
                    unit_price=dep_unit,
                    quantity=dep_qty,
                    discount_total=Decimal("0"),
                    is_adjustment=True,
                )
            )

    # Map returned deposits / coupons if present at ticket root
    coupons_used = ticket_obj.get("couponsUsed")
    if isinstance(coupons_used, list):
        for idx, coupon in enumerate(coupons_used):
            if not isinstance(coupon, dict):
                continue
            disc_val = _optional_decimal(coupon.get("discountAmount"), f"couponsUsed[{idx}].discountAmount")
            if disc_val and disc_val != Decimal("0"):
                # Only add if not already reflected in item discounts
                pass

    raw_store = (
        ticket_obj.get("storeCode")
        or (ticket_obj.get("store", {}) or {}).get("id")
        or (ticket_obj.get("store", {}) or {}).get("name")
        or ""
    )
    merchant_name = f"Lidl {str(raw_store).strip()}".strip() or "Lidl"

    raw_total = (
        ticket_obj.get("totalAmount")
        if ticket_obj.get("totalAmount") is not None
        else ticket_obj.get("totalAmountNumeric")
    )

    receipt = CanonicalReceipt(
        merchant_name=merchant_name,
        date=_ticket_date(ticket_obj.get("date")),
        total_amount=_required_decimal(raw_total, "totalAmount"),
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
    if ticket_obj.get("id"):
        receipt["source_receipt_id"] = str(ticket_obj["id"])
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
