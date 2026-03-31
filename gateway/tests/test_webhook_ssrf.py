"""Tests for webhook URL SSRF validation (P0-4).

Ensures that webhook registration rejects URLs targeting private networks,
localhost, link-local addresses (cloud metadata), and non-HTTP(S) schemes.
"""

from __future__ import annotations

import pytest

from gateway.src.url_validator import validate_webhook_url


class TestValidWebhookURLs:
    """URLs that should pass validation."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/webhook",
            "https://api.stripe.com/v1/events",
            "http://hooks.external.io:8080/callback",
            "https://my-app.herokuapp.com/webhook",
        ],
    )
    def test_valid_urls_pass(self, url: str) -> None:
        assert validate_webhook_url(url) is None


class TestBlockedSchemes:
    """Non-HTTP(S) schemes must be blocked."""

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/file",
            "file:///etc/passwd",
            "gopher://evil.com",
        ],
    )
    def test_non_http_schemes_blocked(self, url: str) -> None:
        result = validate_webhook_url(url)
        assert result is not None
        assert "scheme" in result.lower() or "Unsupported" in result


class TestBlockedPrivateIPs:
    """RFC 1918 private IP ranges must be blocked."""

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "192.168.0.100",
        ],
        ids=[
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "192.168.0.100",
        ],
    )
    def test_rfc1918_blocked(self, ip: str) -> None:
        result = validate_webhook_url(f"https://{ip}/webhook")
        assert result is not None
        assert "Blocked" in result


class TestBlockedLocalhost:
    """Localhost addresses must be blocked."""

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "127.0.0.2",
            "localhost",
            "[::1]",
        ],
        ids=["127.0.0.1", "127.0.0.2", "localhost", "ipv6-loopback"],
    )
    def test_localhost_blocked(self, host: str) -> None:
        result = validate_webhook_url(f"https://{host}/webhook")
        assert result is not None


class TestBlockedLinkLocal:
    """Link-local and cloud metadata IPs must be blocked."""

    @pytest.mark.parametrize(
        "ip",
        [
            "169.254.0.1",
            "169.254.169.254",
        ],
        ids=["link-local", "cloud-metadata"],
    )
    def test_link_local_blocked(self, ip: str) -> None:
        result = validate_webhook_url(f"http://{ip}/latest/meta-data/")
        assert result is not None
        assert "Blocked" in result

    def test_metadata_google_internal_blocked(self) -> None:
        result = validate_webhook_url("http://metadata.google.internal/computeMetadata/v1/")
        assert result is not None


class TestPortBypass:
    """Private/loopback IPs with port numbers must still be rejected."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1:80/webhook",
            "https://127.0.0.1:443/webhook",
            "https://10.0.0.1:8080/webhook",
            "https://192.168.1.1:3000/webhook",
        ],
        ids=["loopback-80", "loopback-443", "private-8080", "private-3000"],
    )
    def test_ip_with_port_blocked(self, url: str) -> None:
        result = validate_webhook_url(url)
        assert result is not None
        assert "Blocked" in result


class TestURLWithUserInfo:
    """URLs with @ sign attempts to bypass hostname parsing."""

    def test_url_with_at_sign_metadata_blocked(self) -> None:
        result = validate_webhook_url("https://attacker.com@169.254.169.254/latest/meta-data/")
        assert result is not None

    def test_url_with_at_sign_localhost_blocked(self) -> None:
        result = validate_webhook_url("https://legit.example.com@127.0.0.1/webhook")
        assert result is not None


class TestIPv6:
    """IPv6 private ranges must be blocked."""

    def test_ipv6_unique_local_blocked(self) -> None:
        result = validate_webhook_url("https://[fc00::1]/webhook")
        assert result is not None

    def test_ipv6_link_local_blocked(self) -> None:
        result = validate_webhook_url("https://[fe80::1]/webhook")
        assert result is not None


class TestEdgeCases:
    """Edge cases and malformed URLs."""

    def test_empty_url(self) -> None:
        result = validate_webhook_url("")
        assert result is not None

    def test_missing_hostname(self) -> None:
        result = validate_webhook_url("https:///path")
        assert result is not None

    def test_zero_ip_blocked(self) -> None:
        result = validate_webhook_url("https://0.0.0.0/webhook")
        assert result is not None
        assert "Blocked" in result
