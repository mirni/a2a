"""Tests for gateway.src.url_validator — SSRF protection."""

from __future__ import annotations

from unittest.mock import patch

from gateway.src.url_validator import validate_webhook_url


class TestScheme:
    def test_https_allowed(self):
        # Mock DNS to avoid real resolution
        with patch("gateway.src.url_validator.socket.getaddrinfo", return_value=[]):
            assert validate_webhook_url("https://example.com/hook") is None

    def test_http_allowed(self):
        with patch("gateway.src.url_validator.socket.getaddrinfo", return_value=[]):
            assert validate_webhook_url("http://example.com/hook") is None

    def test_ftp_blocked(self):
        result = validate_webhook_url("ftp://example.com/file")
        assert result is not None
        assert "scheme" in result.lower()

    def test_file_blocked(self):
        result = validate_webhook_url("file:///etc/passwd")
        assert result is not None


class TestBlockedIPs:
    def test_private_10_blocked(self):
        result = validate_webhook_url("https://10.0.0.1/hook")
        assert result is not None
        assert "Blocked" in result

    def test_private_172_blocked(self):
        result = validate_webhook_url("https://172.16.0.1/hook")
        assert result is not None

    def test_private_192_blocked(self):
        result = validate_webhook_url("https://192.168.1.1/hook")
        assert result is not None

    def test_loopback_blocked(self):
        result = validate_webhook_url("https://127.0.0.1/hook")
        assert result is not None

    def test_ipv6_loopback_blocked(self):
        result = validate_webhook_url("https://[::1]/hook")
        assert result is not None

    def test_link_local_blocked(self):
        result = validate_webhook_url("https://169.254.1.1/hook")
        assert result is not None

    def test_cloud_metadata_blocked(self):
        result = validate_webhook_url("https://169.254.169.254/hook")
        assert result is not None


class TestBlockedHostnames:
    def test_localhost_blocked(self):
        result = validate_webhook_url("https://localhost/hook")
        assert result is not None
        assert "Blocked hostname" in result

    def test_metadata_google_blocked(self):
        result = validate_webhook_url("https://metadata.google.internal/computeMetadata")
        assert result is not None

    def test_case_insensitive_hostname(self):
        result = validate_webhook_url("https://LOCALHOST/hook")
        assert result is not None


class TestDNSResolution:
    def test_dns_failure_allowed(self):
        """DNS failure -> allow (delivery will fail naturally)."""
        import socket

        with patch(
            "gateway.src.url_validator.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            assert validate_webhook_url("https://nonexistent.example.com/hook") is None

    def test_valid_external_ip_allowed(self):
        """Public IP -> allowed."""
        result = validate_webhook_url("https://8.8.8.8/hook")
        assert result is None

    def test_hostname_resolving_to_blocked_ip(self):
        """Hostname resolving to private IP -> blocked."""
        with patch(
            "gateway.src.url_validator.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 443))],
        ):
            result = validate_webhook_url("https://evil.example.com/hook")
            assert result is not None
            assert "resolves to blocked" in result


class TestMissingHostname:
    def test_no_hostname(self):
        result = validate_webhook_url("https:///path")
        assert result is not None
