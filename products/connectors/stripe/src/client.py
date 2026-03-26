"""Stripe API client wrapper with retry, rate-limiting, and structured errors.

Uses httpx to call Stripe REST API directly (no stripe SDK dependency).
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from src.audit_log import log_operation
from src.errors import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
    UpstreamError,
)
from src.rate_limiter import RateLimiter
from src.retry import RetryConfig, RetryExhausted, retry_async

STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_VERSION = "2024-12-18.acacia"
CONNECTOR_NAME = "stripe"


def _get_api_key() -> str:
    """Read Stripe API key from environment."""
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        raise AuthenticationError("STRIPE_API_KEY environment variable is not set")
    return key


class StripeClient:
    """Production Stripe HTTP client with retry + rate-limit."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        retry_config: RetryConfig | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self._http = http_client or httpx.AsyncClient(
            base_url=STRIPE_API_BASE,
            timeout=30.0,
        )
        self._retry_config = retry_config or RetryConfig(
            max_retries=3,
            base_delay=0.5,
            max_delay=30.0,
        )
        self._rate_limiter = rate_limiter or RateLimiter(
            max_requests=100,
            window_seconds=60.0,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Core request method
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Stripe API request with retry and rate-limit.

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: API path relative to /v1/ (e.g. "customers").
            data: Form-encoded body for POST requests.
            params: Query parameters for GET requests.
            idempotency_key: Idempotency key for write operations.

        Returns:
            Parsed JSON response from Stripe.
        """
        api_key = _get_api_key()

        headers: dict[str, str] = {
            "Stripe-Version": STRIPE_API_VERSION,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Clean None values from params and data
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        clean_data = _flatten_dict(data) if data else None

        start = time.monotonic()

        async def _do_request() -> httpx.Response:
            await self._rate_limiter.acquire()
            url = f"{STRIPE_API_BASE}/{path.lstrip('/')}"
            resp = await self._http.request(
                method,
                url,
                data=clean_data,
                params=clean_params or None,
                headers=headers,
                auth=(api_key, ""),
            )
            resp.raise_for_status()
            return resp

        try:
            response = await retry_async(_do_request, config=self._retry_config)
        except RetryExhausted as exc:
            duration_ms = (time.monotonic() - start) * 1000
            error = _translate_error(exc.last_error)
            log_operation(
                operation=f"{method} /{path}",
                connector=CONNECTOR_NAME,
                params=clean_params or (clean_data if clean_data else None),
                error=str(error),
                duration_ms=duration_ms,
            )
            raise error from exc

        duration_ms = (time.monotonic() - start) * 1000
        result: dict[str, Any] = response.json()

        log_operation(
            operation=f"{method} /{path}",
            connector=CONNECTOR_NAME,
            params=clean_params or (clean_data if clean_data else None),
            result_summary=f"id={result.get('id', 'n/a')}",
            duration_ms=duration_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def post(
        self,
        path: str,
        data: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self.request("POST", path, data=data, idempotency_key=idempotency_key)

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.request("GET", path, params=params)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _flatten_dict(
    d: dict[str, Any], parent_key: str = "", sep: str = "[",
) -> dict[str, str]:
    """Flatten nested dicts for Stripe form-encoded POST bodies.

    Stripe expects nested keys like metadata[key1]=value1.
    """
    items: list[tuple[str, str]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}]" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        elif v is not None:
            items.append((new_key, str(v)))
    return dict(items)


def _translate_error(exc: Exception) -> ConnectorError:
    """Translate httpx exceptions into structured ConnectorError types."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.json()
            message = body.get("error", {}).get("message", str(exc))
        except Exception:
            message = str(exc)

        if status == 401:
            return AuthenticationError(message)
        if status == 429:
            retry_after = exc.response.headers.get("retry-after")
            ra = float(retry_after) if retry_after else None
            return RateLimitError(retry_after=ra)
        if status >= 500:
            return UpstreamError(message, status_code=status, retryable=True)
        return UpstreamError(message, status_code=status, retryable=False)

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        from src.errors import TimeoutError as ConnTimeoutError
        return ConnTimeoutError(str(exc))

    return UpstreamError(str(exc), retryable=False)
