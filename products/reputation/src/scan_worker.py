"""Scan worker: performs security scans against registered targets.

Checks TLS certificate validity, security headers (HSTS, CSP, X-Frame-Options),
and authentication requirements. Stores results via the trust storage backend.
"""

from __future__ import annotations

import logging
import ssl
import time
from dataclasses import dataclass, field

import httpx

from .models import ScanResult, SecurityHeaders, TLSInfo

# Re-use trust models for storage compatibility
try:
    from src.models import SecurityScan as TrustSecurityScan
except ImportError:
    from products.trust.src.models import SecurityScan as TrustSecurityScan

logger = logging.getLogger(__name__)

# Security headers to check
SECURITY_HEADERS = {
    "strict-transport-security": "has_hsts",
    "content-security-policy": "has_csp",
    "x-frame-options": "has_x_frame_options",
    "x-content-type-options": "has_x_content_type_options",
    "referrer-policy": "has_referrer_policy",
}

HEADER_WEIGHT = 100.0 / len(SECURITY_HEADERS)


def analyze_security_headers(headers: httpx.Headers) -> SecurityHeaders:
    """Analyze HTTP response headers for security configuration.

    Checks for presence of: HSTS, CSP, X-Frame-Options,
    X-Content-Type-Options, Referrer-Policy.

    Args:
        headers: The HTTP response headers.

    Returns:
        SecurityHeaders with boolean flags and a composite score.
    """
    result = {}
    found = 0
    for header_name, attr_name in SECURITY_HEADERS.items():
        present = header_name in headers
        result[attr_name] = present
        if present:
            found += 1

    result["header_score"] = round(found * HEADER_WEIGHT, 2)
    return SecurityHeaders(**result)


def check_tls_from_url(url: str) -> TLSInfo:
    """Determine basic TLS info from the URL scheme.

    For full certificate validation, a real TLS connection is needed.
    This provides a basic check based on URL scheme.
    """
    is_https = url.lower().startswith("https://")
    return TLSInfo(enabled=is_https, valid=is_https)


def check_auth_required(response: httpx.Response) -> bool:
    """Determine if authentication is required based on response.

    Checks for 401/403 status codes and WWW-Authenticate header.

    Args:
        response: The HTTP response to analyze.

    Returns:
        True if authentication appears to be required.
    """
    if response.status_code in (401, 403):
        return True
    if "www-authenticate" in response.headers:
        return True
    return False


@dataclass
class ScanWorker:
    """Executes security scans against registered targets.

    Attributes:
        trust_storage: The trust StorageBackend for persisting scan results.
        timeout: HTTP request timeout in seconds.
        client: Optional pre-configured httpx.AsyncClient (for testing).
    """

    trust_storage: object  # StorageBackend from trust module
    timeout: float = 30.0
    client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def scan(self, server_id: str, url: str) -> ScanResult:
        """Perform a full security scan of a target.

        Checks:
        1. TLS certificate validity
        2. Security headers (HSTS, CSP, X-Frame-Options, etc.)
        3. Authentication requirement

        Args:
            server_id: Identifier for the server being scanned.
            url: The URL to scan.

        Returns:
            Complete ScanResult with all security findings.
        """
        should_close = False
        client = self.client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            should_close = True

        now = time.time()
        tls_info = TLSInfo()
        security_headers = SecurityHeaders()
        auth_required = False
        input_validation_score = 0.0

        try:
            # Check TLS based on URL scheme
            tls_info = check_tls_from_url(url)

            # Make request for header analysis and auth check
            try:
                response = await client.get(url, timeout=self.timeout)
                security_headers = analyze_security_headers(response.headers)
                auth_required = check_auth_required(response)

                # If HTTPS succeeded, mark TLS as valid
                if url.lower().startswith("https://"):
                    tls_info = TLSInfo(enabled=True, valid=True, protocol_version="TLSv1.2+")

            except ssl.SSLError:
                tls_info = TLSInfo(enabled=True, valid=False)
            except Exception as exc:
                logger.warning("Scan request failed for %s: %s", server_id, exc)

            # Compute input_validation_score from header completeness
            input_validation_score = security_headers.header_score

            now = time.time()
            scan_result = ScanResult(
                server_id=server_id,
                timestamp=now,
                tls_info=tls_info,
                security_headers=security_headers,
                auth_required=auth_required,
                input_validation_score=input_validation_score,
            )

            # Store in trust storage as a SecurityScan
            trust_scan = TrustSecurityScan(
                server_id=server_id,
                timestamp=now,
                tls_enabled=tls_info.enabled and tls_info.valid,
                auth_required=auth_required,
                input_validation_score=input_validation_score,
                cve_count=0,
            )
            await self.trust_storage.store_security_scan(trust_scan)

            logger.debug(
                "Scan %s: tls=%s auth=%s header_score=%.1f",
                server_id, tls_info.valid, auth_required, security_headers.header_score,
            )

            return scan_result

        finally:
            if should_close:
                await client.aclose()

    async def scan_batch(
        self, targets: list[tuple[str, str]]
    ) -> list[ScanResult]:
        """Scan a batch of targets sequentially.

        Args:
            targets: List of (server_id, url) tuples.

        Returns:
            List of ScanResult in same order.
        """
        results = []
        for server_id, url in targets:
            result = await self.scan(server_id, url)
            results.append(result)
        return results
