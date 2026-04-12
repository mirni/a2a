"""Shared Pydantic validators for gateway request models."""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")

#: Agent ID pattern — alphanumeric start, then alphanumeric/dot/dash/underscore, 1-128 chars.
AGENT_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"


def sanitize_text(v: str) -> str:
    """Strip HTML tags from a string to prevent stored XSS."""
    return _TAG_RE.sub("", v)
