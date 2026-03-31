"""URL validator that blocks SSRF attacks on webhook registrations.

Rejects URLs targeting:
- Private/RFC 1918 IPs: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- Localhost: 127.0.0.0/8, [::1]
- Link-local: 169.254.0.0/16, fe80::/10
- Cloud metadata: 169.254.169.254 (AWS/GCP/Azure)
- Non-HTTP(S) schemes
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Networks that must never be targeted by webhooks.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
]

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.google.internal.",
    }
)


def validate_webhook_url(url: str) -> str | None:
    """Validate a URL is safe for webhook delivery.

    Returns:
        None if the URL is safe.
        An error message string if the URL should be blocked.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        return f"Unsupported scheme: {parsed.scheme!r} (must be http or https)"

    hostname = parsed.hostname
    if not hostname:
        return "Missing hostname"

    # Block known dangerous hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return f"Blocked hostname: {hostname}"

    # Try to parse as IP address directly
    try:
        addr = ipaddress.ip_address(hostname)
        return _check_ip(addr)
    except ValueError:
        pass

    # Resolve hostname to check destination IPs
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        # Can't resolve — allow it; delivery will fail naturally
        return None

    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str)
            error = _check_ip(addr)
            if error:
                return f"Hostname {hostname!r} resolves to blocked address: {error}"
        except ValueError:
            continue

    return None


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return an error message if the IP address is in a blocked range."""
    for network in _BLOCKED_NETWORKS:
        if addr in network:
            return f"Blocked IP range ({network}): {addr}"
    return None
