"""Tests for v1.3.0 audit findings (SDK fixes).

Covers:
- P6.3: import a2a_greenhelix_sdk shim
- P6.4: create_payment_intent amount type (str | Decimal, not float)
- P6.5: currency kwarg on create_payment_intent
- P6.6: PermissionDeniedError exported
"""

from __future__ import annotations

import inspect
import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ---------------------------------------------------------------------------
# P6.3 — import a2a_greenhelix_sdk shim
# ---------------------------------------------------------------------------


class TestImportShim:
    """The PyPI package name is a2a-greenhelix-sdk, so users expect
    ``import a2a_greenhelix_sdk`` to work as an alias for ``a2a_client``."""

    def test_import_a2a_greenhelix_sdk(self):
        import a2a_greenhelix_sdk  # noqa: F401

    def test_shim_reexports_client(self):
        import a2a_greenhelix_sdk

        assert hasattr(a2a_greenhelix_sdk, "A2AClient")

    def test_shim_reexports_errors(self):
        import a2a_greenhelix_sdk

        assert hasattr(a2a_greenhelix_sdk, "A2AError")
        assert hasattr(a2a_greenhelix_sdk, "AuthenticationError")

    def test_shim_reexports_models(self):
        import a2a_greenhelix_sdk

        assert hasattr(a2a_greenhelix_sdk, "BalanceResponse")
        assert hasattr(a2a_greenhelix_sdk, "PaymentIntentResponse")


# ---------------------------------------------------------------------------
# P6.4 — amount type should accept str/Decimal, not just float
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    from sdk.src.a2a_client import A2AClient

    client = A2AClient.__new__(A2AClient)
    client.base_url = "http://test"
    client.api_key = "test-key"
    client.max_retries = 0
    client._rest = AsyncMock()
    return client


class TestAmountType:
    """create_payment_intent.amount should accept str | Decimal (not just float)."""

    def test_amount_annotation_not_float(self):
        from sdk.src.a2a_client import A2AClient

        sig = inspect.signature(A2AClient.create_payment_intent)
        ann = sig.parameters["amount"].annotation
        # Must NOT be plain float
        assert ann is not float, f"amount annotation is still float: {ann}"
        # Should accept str or Decimal
        ann_str = str(ann)
        assert "str" in ann_str or "Decimal" in ann_str, f"amount annotation {ann} doesn't include str/Decimal"

    @pytest.mark.asyncio
    async def test_amount_accepts_string(self, mock_client):
        from sdk.src.a2a_client.models import PaymentIntentResponse

        mock_client._rest.return_value = {
            "id": "pi_1",
            "status": "pending",
            "amount": "10.50",
            "payer": "a",
            "payee": "b",
        }
        result = await mock_client.create_payment_intent("a", "b", "10.50")
        assert isinstance(result, PaymentIntentResponse)
        # The amount sent to _rest should be the string, not converted to float
        call_json = mock_client._rest.call_args.kwargs.get("json") or mock_client._rest.call_args[1].get("json", {})
        assert call_json["amount"] == "10.50"

    @pytest.mark.asyncio
    async def test_amount_accepts_decimal(self, mock_client):
        from sdk.src.a2a_client.models import PaymentIntentResponse

        mock_client._rest.return_value = {
            "id": "pi_1",
            "status": "pending",
            "amount": "10.50",
            "payer": "a",
            "payee": "b",
        }
        result = await mock_client.create_payment_intent("a", "b", Decimal("10.50"))
        assert isinstance(result, PaymentIntentResponse)


# ---------------------------------------------------------------------------
# P6.5 — currency kwarg on create_payment_intent
# ---------------------------------------------------------------------------


class TestCurrencyKwarg:
    """create_payment_intent should accept an optional currency kwarg."""

    def test_currency_param_exists(self):
        from sdk.src.a2a_client import A2AClient

        sig = inspect.signature(A2AClient.create_payment_intent)
        assert "currency" in sig.parameters, "create_payment_intent missing 'currency' parameter"

    @pytest.mark.asyncio
    async def test_currency_sent_in_body(self, mock_client):
        mock_client._rest.return_value = {
            "id": "pi_1",
            "status": "pending",
            "amount": "10.50",
            "payer": "a",
            "payee": "b",
        }
        await mock_client.create_payment_intent("a", "b", "10.50", currency="USD")
        call_json = mock_client._rest.call_args.kwargs.get("json") or mock_client._rest.call_args[1].get("json", {})
        assert call_json["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_currency_default_credits(self, mock_client):
        mock_client._rest.return_value = {
            "id": "pi_1",
            "status": "pending",
            "amount": "10.50",
            "payer": "a",
            "payee": "b",
        }
        await mock_client.create_payment_intent("a", "b", "10.50")
        call_json = mock_client._rest.call_args.kwargs.get("json") or mock_client._rest.call_args[1].get("json", {})
        assert call_json.get("currency") == "CREDITS"


# ---------------------------------------------------------------------------
# P6.6 — PermissionDeniedError exported
# ---------------------------------------------------------------------------


class TestPermissionDeniedError:
    """SDK must export PermissionDeniedError for 403 responses."""

    def test_error_class_exists(self):
        from sdk.src.a2a_client.errors import PermissionDeniedError  # noqa: F401

    def test_exported_from_package(self):
        from sdk.src.a2a_client import PermissionDeniedError  # noqa: F401

    def test_inherits_a2a_error(self):
        from sdk.src.a2a_client.errors import A2AError, PermissionDeniedError

        assert issubclass(PermissionDeniedError, A2AError)

    def test_raise_for_status_403(self):
        from sdk.src.a2a_client.errors import PermissionDeniedError, raise_for_status

        with pytest.raises(PermissionDeniedError):
            raise_for_status(
                403,
                {
                    "type": "https://api.greenhelix.net/errors/forbidden",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "Forbidden: you do not have access",
                },
            )
