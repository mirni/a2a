"""Tests for retry logic."""

import httpx
import pytest
from src.retry import RetryConfig, RetryExhausted, _compute_delay, is_retryable_error, retry_async


class TestComputeDelay:
    def test_first_attempt(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)
        assert _compute_delay(0, config) == 1.0

    def test_second_attempt(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)
        assert _compute_delay(1, config) == 2.0

    def test_third_attempt(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)
        assert _compute_delay(2, config) == 4.0

    def test_respects_max_delay(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, max_delay=3.0)
        assert _compute_delay(5, config) == 3.0


class TestIsRetryableError:
    def test_429_is_retryable(self):
        response = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
        error = httpx.HTTPStatusError("rate limit", request=response.request, response=response)
        assert is_retryable_error(error, RetryConfig()) is True

    def test_500_is_retryable(self):
        response = httpx.Response(500, request=httpx.Request("GET", "https://example.com"))
        error = httpx.HTTPStatusError("server error", request=response.request, response=response)
        assert is_retryable_error(error, RetryConfig()) is True

    def test_400_is_not_retryable(self):
        response = httpx.Response(400, request=httpx.Request("GET", "https://example.com"))
        error = httpx.HTTPStatusError("bad request", request=response.request, response=response)
        assert is_retryable_error(error, RetryConfig()) is False

    def test_timeout_is_retryable(self):
        error = httpx.ReadTimeout("timeout")
        assert is_retryable_error(error, RetryConfig()) is True

    def test_connect_error_is_retryable(self):
        error = httpx.ConnectError("refused")
        assert is_retryable_error(error, RetryConfig()) is True

    def test_generic_error_not_retryable(self):
        error = ValueError("bad value")
        assert is_retryable_error(error, RetryConfig()) is False


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        call_count = 0

        async def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(succeeds, config=RetryConfig(max_retries=3))
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self):
        call_count = 0

        async def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                response = httpx.Response(500, request=httpx.Request("GET", "https://example.com"))
                raise httpx.HTTPStatusError("error", request=response.request, response=response)
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=0.01)
        result = await retry_async(fails_then_succeeds, config=config)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        async def always_fails():
            response = httpx.Response(500, request=httpx.Request("GET", "https://example.com"))
            raise httpx.HTTPStatusError("error", request=response.request, response=response)

        config = RetryConfig(max_retries=2, base_delay=0.01)
        with pytest.raises(RetryExhausted) as exc_info:
            await retry_async(always_fails, config=config)
        assert exc_info.value.attempts == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        call_count = 0

        async def bad_request():
            nonlocal call_count
            call_count += 1
            response = httpx.Response(400, request=httpx.Request("GET", "https://example.com"))
            raise httpx.HTTPStatusError("bad", request=response.request, response=response)

        config = RetryConfig(max_retries=3, base_delay=0.01)
        with pytest.raises(RetryExhausted) as exc_info:
            await retry_async(bad_request, config=config)
        assert call_count == 1
        assert exc_info.value.attempts == 1
