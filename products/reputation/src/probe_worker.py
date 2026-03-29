"""Probe worker: executes HTTP health probes against registered targets.

Uses httpx for async HTTP requests. Classifies errors into categories
and stores results via the trust storage backend.
"""

from __future__ import annotations

import logging
import ssl
import time
from dataclasses import dataclass, field

import httpx

from .models import ProbeErrorType

# Re-use trust models for storage compatibility
try:
    from src.models import ProbeResult as TrustProbeResult
except ImportError:
    from products.trust.src.models import ProbeResult as TrustProbeResult

logger = logging.getLogger(__name__)


def classify_error(exc: Exception | None, status_code: int | None = None) -> ProbeErrorType:
    """Classify an HTTP error into a ProbeErrorType category.

    Args:
        exc: The exception raised during the HTTP call, or None for success.
        status_code: HTTP status code if a response was received.

    Returns:
        The classified error type.
    """
    if exc is None and status_code is not None:
        if 200 <= status_code < 400:
            return ProbeErrorType.SUCCESS
        if 400 <= status_code < 500:
            return ProbeErrorType.HTTP_4XX
        if 500 <= status_code < 600:
            return ProbeErrorType.HTTP_5XX
    if exc is None:
        return ProbeErrorType.SUCCESS

    exc_str = str(exc).lower()

    # SSL/TLS errors
    if isinstance(exc, ssl.SSLError) or "ssl" in exc_str or "certificate" in exc_str:
        return ProbeErrorType.SSL_ERROR

    # httpx-specific exception types
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        return ProbeErrorType.TIMEOUT
    if isinstance(exc, httpx.TimeoutException):
        return ProbeErrorType.TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        if "name resolution" in exc_str or "dns" in exc_str or "nodename" in exc_str or "getaddrinfo" in exc_str:
            return ProbeErrorType.DNS_ERROR
        if "refused" in exc_str or "connection refused" in exc_str:
            return ProbeErrorType.CONNECTION_REFUSED
        return ProbeErrorType.CONNECTION_REFUSED

    # Generic fallbacks by message content
    if "timeout" in exc_str or "timed out" in exc_str:
        return ProbeErrorType.TIMEOUT
    if "refused" in exc_str:
        return ProbeErrorType.CONNECTION_REFUSED
    if "dns" in exc_str or "name resolution" in exc_str or "getaddrinfo" in exc_str:
        return ProbeErrorType.DNS_ERROR
    if "ssl" in exc_str or "certificate" in exc_str or "tls" in exc_str:
        return ProbeErrorType.SSL_ERROR

    return ProbeErrorType.UNKNOWN


@dataclass
class ProbeWorker:
    """Executes HTTP health probes against registered targets.

    Attributes:
        trust_storage: The trust StorageBackend for persisting probe results.
        timeout: HTTP request timeout in seconds.
        client: Optional pre-configured httpx.AsyncClient (for testing).
    """

    trust_storage: object  # StorageBackend from trust module
    timeout: float = 10.0
    client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def probe(self, server_id: str, url: str) -> tuple[TrustProbeResult, ProbeErrorType]:
        """Execute a single HTTP health probe.

        Makes a GET request to the target URL, measures latency,
        classifies any errors, and stores the result in trust storage.

        Args:
            server_id: Identifier for the server being probed.
            url: The URL to probe.

        Returns:
            Tuple of (ProbeResult stored in trust DB, error classification).
        """
        error_type = ProbeErrorType.SUCCESS
        status_code = 0
        latency_ms = 0.0
        error_msg: str | None = None

        should_close = False
        client = self.client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            should_close = True

        try:
            start = time.time()
            try:
                response = await client.get(url, timeout=self.timeout)
                latency_ms = (time.time() - start) * 1000.0
                status_code = response.status_code
                error_type = classify_error(None, status_code)
                if error_type not in (ProbeErrorType.SUCCESS,):
                    error_msg = f"HTTP {status_code}"
            except Exception as exc:
                latency_ms = (time.time() - start) * 1000.0
                error_type = classify_error(exc)
                error_msg = f"{error_type.value}: {exc}"
                status_code = 0

            now = time.time()
            result = TrustProbeResult(
                server_id=server_id,
                timestamp=now,
                latency_ms=latency_ms,
                status_code=status_code,
                error=error_msg,
            )

            # Store in trust storage
            await self.trust_storage.store_probe_result(result)
            logger.debug(
                "Probe %s: status=%d latency=%.1fms error_type=%s",
                server_id,
                status_code,
                latency_ms,
                error_type.value,
            )
            return result, error_type

        finally:
            if should_close:
                await client.aclose()

    async def probe_batch(self, targets: list[tuple[str, str]]) -> list[tuple[TrustProbeResult, ProbeErrorType]]:
        """Probe a batch of targets sequentially.

        Args:
            targets: List of (server_id, url) tuples.

        Returns:
            List of (ProbeResult, ProbeErrorType) tuples in same order.
        """
        results = []
        for server_id, url in targets:
            result = await self.probe(server_id, url)
            results.append(result)
        return results
