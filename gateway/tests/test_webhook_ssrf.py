"""Tests for webhook URL SSRF validation.

Ensures that webhook registration rejects URLs targeting private networks,
localhost, link-local addresses (cloud metadata), and non-HTTPS schemes.
"""

from __future__ import annotations

import pytest

from gateway.src.webhooks import WebhookManager

# ---------------------------------------------------------------------------
# Unit tests for _validate_webhook_url
# ---------------------------------------------------------------------------


class TestValidateWebhookUrl:
    """Unit tests for WebhookManager._validate_webhook_url."""

    # -- Public HTTPS URLs should be allowed --------------------------------

    def test_public_https_url_allowed(self):
        """A standard public HTTPS URL must pass validation."""
        WebhookManager._validate_webhook_url("https://example.com/webhook")

    def test_public_https_url_with_path_allowed(self):
        """HTTPS URL with path segments must be allowed."""
        WebhookManager._validate_webhook_url("https://hooks.example.com/v1/callback")

    # -- Private IPs (RFC 1918) must be blocked -----------------------------

    @pytest.mark.parametrize(
        "url",
        [
            "https://10.0.0.1/webhook",
            "https://10.255.255.255/webhook",
            "https://172.16.0.1/webhook",
            "https://172.31.255.255/webhook",
            "https://192.168.1.1/webhook",
            "https://192.168.0.100/webhook",
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
    def test_private_ips_blocked(self, url: str):
        """RFC 1918 private IP addresses must be rejected."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(url)

    # -- Localhost must be blocked ------------------------------------------

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/webhook",
            "https://127.0.0.2/webhook",
            "https://[::1]/webhook",
        ],
        ids=["127.0.0.1", "127.0.0.2", "ipv6-loopback"],
    )
    def test_localhost_blocked(self, url: str):
        """Loopback addresses (127.0.0.0/8, ::1) must be rejected."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(url)

    # -- Link-local / cloud metadata must be blocked ------------------------

    @pytest.mark.parametrize(
        "url",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://169.254.0.1/webhook",
        ],
        ids=["cloud-metadata", "link-local"],
    )
    def test_link_local_blocked(self, url: str):
        """Link-local addresses (169.254.0.0/16) must be rejected."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(url)

    # -- Non-HTTP(S) schemes must be blocked --------------------------------

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://evil.com/payload",
            "gopher://evil.com/",
            "http://example.com/webhook",
        ],
        ids=["file", "ftp", "gopher", "http-plain"],
    )
    def test_non_https_schemes_blocked(self, url: str):
        """Only https:// scheme is allowed; http://, file://, ftp://, etc. must be rejected."""
        with pytest.raises(ValueError, match=r"HTTPS|scheme"):
            WebhookManager._validate_webhook_url(url)

    # -- Port bypass attempts must be blocked -------------------------------

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
    def test_ip_with_port_blocked(self, url: str):
        """Private/loopback IPs with port numbers must still be rejected."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(url)

    # -- URL with userinfo (@) must be handled safely -----------------------

    def test_url_with_at_sign_metadata_blocked(self):
        """URL with @ that resolves hostname to cloud metadata IP must be blocked.

        https://attacker.com@169.254.169.254/ parses as:
          username = attacker.com
          hostname = 169.254.169.254
        The validator must check the actual hostname, not the full URL string.
        """
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(
                "https://attacker.com@169.254.169.254/latest/meta-data/"
            )

    def test_url_with_at_sign_localhost_blocked(self):
        """URL with @ that resolves hostname to localhost must be blocked."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url(
                "https://legit.example.com@127.0.0.1/webhook"
            )

    # -- Edge cases ---------------------------------------------------------

    def test_empty_url_rejected(self):
        """An empty URL string must be rejected."""
        with pytest.raises(ValueError):
            WebhookManager._validate_webhook_url("")

    def test_no_hostname_rejected(self):
        """A URL with no hostname must be rejected."""
        with pytest.raises(ValueError):
            WebhookManager._validate_webhook_url("https:///path")

    def test_ipv6_private_blocked(self):
        """IPv6 unique-local (fc00::/7) addresses must be blocked."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url("https://[fc00::1]/webhook")

    def test_ipv6_link_local_blocked(self):
        """IPv6 link-local (fe80::/10) addresses must be blocked."""
        with pytest.raises(ValueError, match=r"private|loopback|link-local|reserved"):
            WebhookManager._validate_webhook_url("https://[fe80::1]/webhook")


# ---------------------------------------------------------------------------
# Integration test via the API endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_webhook_ssrf_blocked_via_api(client, pro_api_key):
    """Registering a webhook with a private IP via the API must return an error."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://169.254.169.254/latest/meta-data/",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # The request should fail with a validation error, not succeed
    data = resp.json()
    assert data.get("success") is False or resp.status_code >= 400


@pytest.mark.asyncio
async def test_register_webhook_public_url_via_api(client, pro_api_key):
    """Registering a webhook with a public HTTPS URL via the API must succeed."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/webhook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
