"""Shared fixtures for Stripe connector tests."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from src.client import StripeClient
from src.rate_limiter import RateLimiter
from src.retry import RetryConfig


def make_stripe_response(
    data: dict[str, Any],
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response that looks like a Stripe API reply."""
    return httpx.Response(
        status_code=status_code,
        json=data,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.stripe.com/v1/test"),
    )


def make_error_response(
    status_code: int,
    error_type: str = "invalid_request_error",
    message: str = "Something went wrong",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake Stripe error response."""
    return httpx.Response(
        status_code=status_code,
        json={"error": {"type": error_type, "message": message}},
        headers=headers or {},
        request=httpx.Request("POST", "https://api.stripe.com/v1/test"),
    )


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport for httpx that returns pre-configured responses."""

    def __init__(self) -> None:
        self.responses: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []

    def add_response(self, response: httpx.Response) -> None:
        self.responses.append(response)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("No mock responses remaining")
        resp = self.responses.pop(0)
        # Patch the request on the response so raise_for_status works
        resp._request = request
        return resp


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def fast_retry_config() -> RetryConfig:
    """Retry config with zero delays for tests."""
    return RetryConfig(
        max_retries=2,
        base_delay=0.0,
        max_delay=0.0,
        exponential_base=1.0,
    )


@pytest.fixture
def fast_rate_limiter() -> RateLimiter:
    """Rate limiter that never blocks in tests."""
    return RateLimiter(max_requests=10000, window_seconds=1.0)


@pytest.fixture
def stripe_client(
    mock_transport: MockTransport,
    fast_retry_config: RetryConfig,
    fast_rate_limiter: RateLimiter,
) -> StripeClient:
    """StripeClient wired to mock transport with fast retry/rate-limit."""
    http_client = httpx.AsyncClient(transport=mock_transport, base_url="https://api.stripe.com/v1")
    return StripeClient(
        http_client=http_client,
        retry_config=fast_retry_config,
        rate_limiter=fast_rate_limiter,
    )


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure STRIPE_API_KEY is always set in tests."""
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake_key_for_testing")
