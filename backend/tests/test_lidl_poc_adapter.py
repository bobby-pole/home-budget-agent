"""Safety and contract tests for the Issue #255 Lidl research harness."""

from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.lidl_poc_client import (
    LidlPoCClient,
    MerchantOAuthConfiguration,
    MerchantRequestError,
    OAuthCallbackError,
    OAuthConfigurationError,
    TicketMappingError,
    get_lidl_live_config,
    lidl_ticket_to_canonical,
)


def _config() -> MerchantOAuthConfiguration:
    return MerchantOAuthConfiguration(
        authorization_endpoint="https://merchant.example/connect/authorize",
        token_endpoint="https://merchant.example/connect/token",
        ticket_list_endpoint="https://tickets.merchant.example/api/v2/tickets",
        ticket_detail_endpoint_template="https://tickets.merchant.example/api/v3/tickets/{ticket_id}",
        client_id="rachownik-research-client",
        redirect_uri="https://rachownik.example/oauth/lidl/callback",
        scopes=("openid", "offline_access", "receipts.read"),
    )


def _ticket(total: str = "15.27") -> dict:
    return {
        "id": "synthetic-ticket-101",
        "date": "2026-09-18T10:30:00Z",
        "storeCode": "PL1234",
        "totalAmount": total,
        "itemsLine": [
            {"name": "Chleb żytni", "currentUnitPrice": "4.29", "quantity": "1", "discounts": []},
            {"name": "Mleko 3.2%", "currentUnitPrice": "3.49", "quantity": "2", "discounts": []},
            {"name": "Kajzerka", "currentUnitPrice": "0.50", "quantity": "8", "discounts": []},
        ],
    }


def test_pkce_rfc7636_test_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert LidlPoCClient.generate_code_challenge(verifier) == expected


def test_authorization_url_binds_attempt_state_and_pkce() -> None:
    client = LidlPoCClient(_config())
    attempt = client.create_authorization_attempt()
    query = parse_qs(urlsplit(client.build_authorize_url(attempt)).query)

    assert query["client_id"] == ["rachownik-research-client"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [attempt.state]
    assert query["nonce"] == [attempt.nonce]
    assert query["redirect_uri"] == ["https://rachownik.example/oauth/lidl/callback"]


def test_callback_requires_exact_redirect_and_state() -> None:
    client = LidlPoCClient(_config())
    attempt = client.create_authorization_attempt()
    callback = f"https://rachownik.example/oauth/lidl/callback?code=one-time-code&state={attempt.state}"

    assert client.validate_callback(callback, attempt) == "one-time-code"
    with pytest.raises(OAuthCallbackError, match="state"):
        client.validate_callback(
            "https://rachownik.example/oauth/lidl/callback?code=one-time-code&state=wrong", attempt
        )
    with pytest.raises(OAuthCallbackError, match="redirect URI"):
        client.validate_callback(
            f"https://attacker.example/callback?code=one-time-code&state={attempt.state}", attempt
        )


def test_native_lidl_redirect_is_explicitly_rejected() -> None:
    with pytest.raises(OAuthConfigurationError, match="native-app redirect"):
        MerchantOAuthConfiguration(
            authorization_endpoint="https://merchant.example/connect/authorize",
            token_endpoint="https://merchant.example/connect/token",
            ticket_list_endpoint="https://tickets.merchant.example/api/v2/tickets",
            ticket_detail_endpoint_template="https://tickets.merchant.example/api/v3/tickets/{ticket_id}",
            client_id="unknown-client",
            redirect_uri="com.lidlplus.app://callback",
        )


def test_mapping_uses_decimal_and_preserves_tax_without_raw_payload() -> None:
    ticket = _ticket()
    ticket["itemsLine"][0]["taxRate"] = 5
    ticket["itemsLine"][0]["taxLetter"] = "A"
    receipt = lidl_ticket_to_canonical(ticket)

    assert receipt.total_amount == Decimal("15.27")
    assert receipt.calculated_total == Decimal("15.27")
    assert receipt["validation_status"] == "verified"
    assert receipt.items[0]["tax_rate"] == "5"
    assert "raw_data" not in receipt


def test_discounts_weights_and_deposits_are_mapped() -> None:
    ticket = {
        "date": "2026-09-18",
        "totalAmount": "30.62",
        "itemsLine": [
            {
                "name": "Ser Gouda",
                "currentUnitPrice": "11.99",
                "quantity": "2",
                "discounts": [{"amount": "4.50"}],
            },
            {
                "name": "Banany",
                "currentUnitPrice": "6.99",
                "quantity": "1.45",
                "isWeight": True,
                "discounts": [],
            },
            {
                "name": "Kaucja butelka zwrotna",
                "currentUnitPrice": "1.00",
                "quantity": "1",
                "isDeposit": True,
                "discounts": [],
            },
        ],
    }
    receipt = lidl_ticket_to_canonical(ticket)

    assert receipt.items[0].discount_total == Decimal("-4.50")
    assert receipt.items[1]["is_weighted"] is True
    assert receipt.items[2].is_adjustment is True
    assert receipt.calculated_total == Decimal("30.62")


def test_mapping_rejects_missing_or_ambiguous_contract_fields() -> None:
    with pytest.raises(TicketMappingError, match="date is required"):
        lidl_ticket_to_canonical({"totalAmount": "1.00", "itemsLine": [{"name": "x", "currentUnitPrice": "1", "quantity": "1"}]})
    with pytest.raises(TicketMappingError, match="quantity must be positive"):
        lidl_ticket_to_canonical({"date": "2026-09-18", "totalAmount": "1.00", "itemsLine": [{"name": "x", "currentUnitPrice": "1", "quantity": "0"}]})


def test_sum_mismatch_marks_needs_review() -> None:
    receipt = lidl_ticket_to_canonical(_ticket(total="50.00"))
    assert receipt["validation_status"] == "needs_review"
    assert receipt.calculated_total == Decimal("15.27")


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    "field", ["totalAmount", "currentUnitPrice", "quantity", "originalUnitPrice", "discount_amount"]
)
def test_mapping_rejects_non_finite_numbers(field: str, value: str) -> None:
    ticket = _ticket()
    if field == "totalAmount":
        ticket[field] = value
    elif field == "discount_amount":
        ticket["itemsLine"][0]["discounts"] = [{"amount": value}]
    else:
        ticket["itemsLine"][0][field] = value

    with pytest.raises(TicketMappingError, match="must be a finite decimal"):
        lidl_ticket_to_canonical(ticket)


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.response

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_token_exchange_uses_public_client_pkce_without_basic_secret() -> None:
    session = _Session(_Response(200, {"access_token": "not-logged"}))
    client = LidlPoCClient(_config(), session=session)
    attempt = client.create_authorization_attempt()

    assert client.exchange_code("one-time-code", attempt) == {"access_token": "not-logged"}
    call = session.calls[0]
    assert "Authorization" not in call["headers"]
    assert call["data"]["client_id"] == "rachownik-research-client"
    assert call["data"]["code_verifier"] == attempt.code_verifier


def test_http_errors_do_not_expose_provider_body() -> None:
    session = _Session(_Response(401, {"access_token": "sensitive-value"}))
    client = LidlPoCClient(_config(), session=session)

    with pytest.raises(MerchantRequestError) as error:
        client.get_tickets_list("also-sensitive")
    assert "sensitive-value" not in str(error.value)
    assert "also-sensitive" not in str(error.value)


def test_live_lidl_config_uses_basic_auth_and_mobile_headers() -> None:
    cfg = get_lidl_live_config()
    session = _Session(_Response(200, {"access_token": "tok", "refresh_token": "ref"}))
    client = LidlPoCClient(cfg, session=session)
    attempt = client.create_authorization_attempt()

    callback = f"com.lidlplus.app://callback?code=live-code-123&state={attempt.state}"
    code = client.validate_callback(callback, attempt)
    assert code == "live-code-123"

    client.exchange_code(code, attempt)
    token_call = session.calls[0]
    assert token_call["headers"]["Authorization"].startswith("Basic ")
    assert token_call["data"]["code"] == "live-code-123"
    assert token_call["data"]["code_verifier"] == attempt.code_verifier

    session.response = _Response(200, {"tickets": [{"id": "t-1"}]})
    client.get_tickets_list("tok")
    list_call = session.calls[1]
    assert list_call["headers"]["Operating-System"] == "iOS"
    assert list_call["headers"]["App"] == "com.lidl.eci.lidl.plus"
    assert "pageNumber=1" in list_call["url"]


def test_polish_html_printed_receipt_maps_to_verified_canonical() -> None:
    sample_html = """<html><body><pre>
<span class="header"><span id="h1">Lidl sp. z o.o.</span></span>
<span class="purchase_list"><span id="p1" class="currency" data-currency="zł">2026-10-21</span>
<span id="p2" class="article" data-art-id="1" data-art-quantity="0,505" data-unit-price="43,90" data-tax-type="C" data-art-description="Ciasto Sernik">Ciasto Sernik</span>
<span id="p3" class="article" data-art-id="1" data-art-quantity="0,505" data-unit-price="43,90" data-tax-type="C" data-art-description="Ciasto Sernik">0,505kg x 43.9 22.17 C</span>
<span id="p4" class="discount" data-promotion-id="_DISCOUNT1">RABAT 50% -11,09</span>
<span id="p5" class="article" data-art-id="2" data-art-quantity="6" data-unit-price="0,99" data-tax-type="A" data-art-description="Woda lekko gaz.">Woda lekko gaz.</span>
<span id="p6" class="article" data-art-id="2" data-art-quantity="6" data-unit-price="0,99" data-tax-type="A" data-art-description="Woda lekko gaz.">6 * 0.99 5.94 A</span>
</span><span class="vat_info"><span id="v1" data-tax-type="A" data-tax-percentage="23,00">PTU A 5,94</span>
<span id="v2" data-tax-type="C" data-tax-percentage="5,00">PTU C 11,08</span>
</span><span class="purchase_summary"><span id="s1">Suma PLN 17,02</span>
<span id="s2">Opakowania zwrotne wydania</span>
<span id="s3">Kaucja PET 6 * 0.5 3.0</span>
<span id="s4">Opakowania zwrotne suma 3,00</span>
<span id="s5">Suma 20,02</span>
</span></pre></body></html>"""
    ticket = {
        "ticketType": "HTML",
        "id": "240019528420261021332821",
        "date": "2026-10-21T08:51:10",
        "totalAmount": 20.02,
        "store": {"id": "PL1952", "locality": "Rybnik"},
        "htmlPrintedReceipt": sample_html,
    }
    receipt = lidl_ticket_to_canonical(ticket)
    assert receipt.merchant_name == "Lidl Rybnik"
    assert receipt.date == "2026-10-21"
    assert receipt.total_amount == Decimal("20.02")
    assert receipt.calculated_total == Decimal("20.02")
    assert receipt["validation_status"] == "verified"
    assert len(receipt.items) == 3
    assert receipt.items[0].discount_total == Decimal("-11.09")
    assert receipt.items[0]["is_weighted"] is True
    assert receipt.items[0]["tax_letter"] == "C"
    assert receipt.items[0]["tax_rate"] == "5.00"
    assert receipt.items[2].is_adjustment is True
    assert receipt.items[2].final_line_total == Decimal("3.00")


def test_callback_url_requires_state_even_when_raw_codes_are_allowed():
    client = LidlPoCClient(_config())
    attempt = client.create_authorization_attempt()
    with pytest.raises(OAuthCallbackError, match="state"):
        client.validate_callback(
            "https://rachownik.example/oauth/lidl/callback?code=one-time-code",
            attempt, allow_raw_code=True,
        )
