"""Tests for the Stripe API client wrapper."""

import httpx
import pytest
from src.client import StripeClient, _flatten_dict, _get_api_key, _translate_error
from src.errors import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
    UpstreamError,
)
from src.retry import RetryConfig

from .conftest import make_error_response, make_stripe_response


class TestFlattenDict:
    def test_simple(self):
        assert _flatten_dict({"a": "1", "b": "2"}) == {"a": "1", "b": "2"}

    def test_nested(self):
        result = _flatten_dict({"metadata": {"key1": "val1", "key2": "val2"}})
        assert result == {"metadata[key1]": "val1", "metadata[key2]": "val2"}

    def test_none_values_excluded(self):
        result = _flatten_dict({"a": "1", "b": None})
        assert result == {"a": "1"}

    def test_deep_nested(self):
        result = _flatten_dict({"items": {"0": {"price": "p_1"}}})
        assert result == {"items[0][price]": "p_1"}

    def test_empty(self):
        assert _flatten_dict({}) == {}


class TestGetApiKey:
    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("STRIPE_API_KEY", raising=False)
        with pytest.raises(AuthenticationError):
            _get_api_key()

    def test_present_returns(self, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_abc")
        assert _get_api_key() == "sk_test_abc"


class TestTranslateError:
    def test_401_becomes_auth_error(self):
        resp = make_error_response(401, message="Invalid API Key")
        exc = httpx.HTTPStatusError("401", request=resp.request, response=resp)
        translated = _translate_error(exc)
        assert isinstance(translated, AuthenticationError)

    def test_429_becomes_rate_limit_error(self):
        resp = make_error_response(429, headers={"retry-after": "2.5"})
        exc = httpx.HTTPStatusError("429", request=resp.request, response=resp)
        translated = _translate_error(exc)
        assert isinstance(translated, RateLimitError)
        assert translated.details["retry_after"] == 2.5

    def test_500_becomes_retryable_upstream(self):
        resp = make_error_response(500, message="Internal Server Error")
        exc = httpx.HTTPStatusError("500", request=resp.request, response=resp)
        translated = _translate_error(exc)
        assert isinstance(translated, UpstreamError)
        assert translated.retryable is True

    def test_400_becomes_non_retryable(self):
        resp = make_error_response(400, message="Bad request")
        exc = httpx.HTTPStatusError("400", request=resp.request, response=resp)
        translated = _translate_error(exc)
        assert isinstance(translated, UpstreamError)
        assert translated.retryable is False

    def test_timeout_becomes_timeout_error(self):
        exc = httpx.ReadTimeout("timed out")
        translated = _translate_error(exc)
        assert translated.code == "TIMEOUT"
        assert translated.retryable is True

    def test_generic_exception(self):
        exc = RuntimeError("unknown")
        translated = _translate_error(exc)
        assert isinstance(translated, UpstreamError)
        assert translated.retryable is False


class TestStripeClientRequest:
    async def test_successful_get(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "bal_1", "object": "balance"}))
        result = await stripe_client.get("balance")
        assert result["id"] == "bal_1"
        # Verify auth header was sent
        req = mock_transport.requests[0]
        assert req.headers.get("authorization") is not None

    async def test_successful_post_with_idempotency(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "cus_123", "object": "customer"}))
        result = await stripe_client.post(
            "customers",
            {"email": "test@example.com"},
            idempotency_key="idem-key-1",
        )
        assert result["id"] == "cus_123"
        req = mock_transport.requests[0]
        assert req.headers.get("idempotency-key") == "idem-key-1"

    async def test_stripe_version_header(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "x"}))
        await stripe_client.get("balance")
        req = mock_transport.requests[0]
        assert "stripe-version" in req.headers

    async def test_retry_on_500(self, mock_transport, fast_rate_limiter):
        """Client retries on 500, succeeds on second attempt."""
        mock_transport.add_response(make_error_response(500))
        mock_transport.add_response(make_stripe_response({"id": "cus_ok"}))
        retry_cfg = RetryConfig(max_retries=2, base_delay=0.0, max_delay=0.0)
        http = httpx.AsyncClient(transport=mock_transport, base_url="https://api.stripe.com/v1")
        client = StripeClient(
            http_client=http,
            retry_config=retry_cfg,
            rate_limiter=fast_rate_limiter,
        )
        result = await client.get("customers")
        assert result["id"] == "cus_ok"
        assert len(mock_transport.requests) == 2

    async def test_non_retryable_error_raises_immediately(self, mock_transport, fast_rate_limiter):
        """400 errors are not retried and raise ConnectorError."""
        mock_transport.add_response(make_error_response(400, message="Invalid param"))
        retry_cfg = RetryConfig(max_retries=2, base_delay=0.0, max_delay=0.0)
        http = httpx.AsyncClient(transport=mock_transport, base_url="https://api.stripe.com/v1")
        client = StripeClient(
            http_client=http,
            retry_config=retry_cfg,
            rate_limiter=fast_rate_limiter,
        )
        with pytest.raises(ConnectorError) as exc_info:
            await client.get("customers")
        assert exc_info.value.code == "UPSTREAM_ERROR"
        assert len(mock_transport.requests) == 1

    async def test_all_retries_exhausted(self, mock_transport, fast_rate_limiter):
        """When all retries fail, raises ConnectorError."""
        for _ in range(3):
            mock_transport.add_response(make_error_response(500))
        retry_cfg = RetryConfig(max_retries=2, base_delay=0.0, max_delay=0.0)
        http = httpx.AsyncClient(transport=mock_transport, base_url="https://api.stripe.com/v1")
        client = StripeClient(
            http_client=http,
            retry_config=retry_cfg,
            rate_limiter=fast_rate_limiter,
        )
        with pytest.raises(ConnectorError):
            await client.get("customers")
        assert len(mock_transport.requests) == 3

    async def test_post_flattens_nested_data(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "sub_1"}))
        await stripe_client.post(
            "subscriptions",
            {
                "customer": "cus_1",
                "items": {"0": {"price": "price_1"}},
            },
            idempotency_key="sub-key",
        )
        req = mock_transport.requests[0]
        body = req.content.decode()
        assert "items%5B0%5D%5Bprice%5D=price_1" in body or "items[0][price]=price_1" in body

    async def test_close(self, stripe_client):
        await stripe_client.close()
        # Should not raise on double close
