"""Retry logic with exponential backoff for production connectors."""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes that are safe to retry
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class RetryExhausted(Exception):
    """All retry attempts failed."""

    def __init__(self, last_error: Exception, attempts: int):
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(f"Failed after {attempts} attempts: {last_error}")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_status_codes: frozenset[int] = RETRYABLE_STATUS_CODES,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    """Compute delay for a given attempt number (0-indexed)."""
    delay = config.base_delay * (config.exponential_base ** attempt)
    return min(delay, config.max_delay)


def is_retryable_error(error: Exception, config: RetryConfig) -> bool:
    """Determine if an error is retryable."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in config.retryable_status_codes
    if isinstance(error, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)):
        return True
    return False


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        func: Async function to call.
        *args: Positional arguments for func.
        config: Retry configuration. Uses defaults if None.
        **kwargs: Keyword arguments for func.

    Returns:
        The return value of func.

    Raises:
        RetryExhausted: If all retry attempts fail.
    """
    if config is None:
        config = RetryConfig()

    last_error: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt == config.max_retries or not is_retryable_error(e, config):
                raise RetryExhausted(e, attempt + 1) from e

            delay = _compute_delay(attempt, config)

            # Check for Retry-After header on rate limit responses
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                retry_after = e.response.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass

            logger.warning(
                "Attempt %d/%d failed: %s. Retrying in %.1fs",
                attempt + 1,
                config.max_retries + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)

    raise RetryExhausted(last_error, config.max_retries + 1)  # type: ignore[arg-type]


def with_retry(config: RetryConfig | None = None) -> Callable:
    """Decorator to add retry logic to an async function."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(func, *args, config=config, **kwargs)

        return wrapper

    return decorator
