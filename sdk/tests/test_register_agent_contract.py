"""v1.2.4 audit P0-3: SDK ↔ server ``created_at`` type alignment.

The server serialises timestamp fields (``created_at``, ``updated_at``
et al.) as ISO-8601 strings via ``gateway.src.serialization``. The SDK
models used to type them as ``float`` (Unix seconds), which caused the
audit's Python client to crash with a ``ValidationError`` the instant
it tried to parse a live sandbox ``register_agent`` response. The fix:
SDK models accept **both** ISO-8601 strings and POSIX-float timestamps,
emitting a ``datetime`` (or ``str`` kept as-is) so callers can use it
without further conversion.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


class TestRegisterAgentResponseAcceptsIsoString:
    """v1.2.4 audit P0-3: ``RegisterAgentResponse`` must parse a server
    payload where ``created_at`` is an ISO-8601 string (the format the
    gateway's serialisation layer emits today).
    """

    def test_iso_8601_string_parses(self):
        from a2a_client.models import RegisterAgentResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": "2026-04-11T00:00:00+00:00",
        }
        resp = RegisterAgentResponse.model_validate(payload)
        assert resp.agent_id == "audit-agent"
        # Accept either datetime or preserved string — the contract is
        # that *parsing must not fail*. Prefer datetime for ergonomics.
        assert isinstance(resp.created_at, (datetime, str, float, int))

    def test_iso_8601_with_z_suffix_parses(self):
        from a2a_client.models import RegisterAgentResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": "2026-04-11T00:00:00Z",
        }
        resp = RegisterAgentResponse.model_validate(payload)
        assert resp.agent_id == "audit-agent"

    def test_float_timestamp_still_parses(self):
        """Back-compat: old servers emitted float; must keep working."""
        from a2a_client.models import RegisterAgentResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": 1711612800.0,
        }
        resp = RegisterAgentResponse.model_validate(payload)
        assert resp.agent_id == "audit-agent"

    def test_integer_timestamp_parses(self):
        from a2a_client.models import RegisterAgentResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": 1711612800,
        }
        resp = RegisterAgentResponse.model_validate(payload)
        assert resp.agent_id == "audit-agent"

    def test_invalid_string_rejected(self):
        from a2a_client.models import RegisterAgentResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": "not-a-timestamp",
        }
        with pytest.raises(ValidationError):
            RegisterAgentResponse.model_validate(payload)


class TestGetAgentIdentityResponseAcceptsIsoString:
    """The same rule applies to ``GetAgentIdentityResponse`` where
    ``created_at`` is ``Optional``.
    """

    def test_iso_string_parses(self):
        from a2a_client.models import GetAgentIdentityResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": "ed25519_hex_abc...",
            "created_at": "2026-04-11T00:00:00+00:00",
            "org_id": None,
            "found": True,
        }
        resp = GetAgentIdentityResponse.model_validate(payload)
        assert resp.agent_id == "audit-agent"

    def test_none_allowed(self):
        from a2a_client.models import GetAgentIdentityResponse

        payload = {
            "agent_id": "audit-agent",
            "public_key": None,
            "created_at": None,
            "org_id": None,
            "found": False,
        }
        resp = GetAgentIdentityResponse.model_validate(payload)
        assert resp.found is False


class TestTimestampRoundTrip:
    """Property-style: float → validated model → same or equivalent
    timestamp representation.
    """

    def test_float_roundtrip_preserves_timestamp_value(self):
        from a2a_client.models import RegisterAgentResponse

        ts = 1711612800.5
        resp = RegisterAgentResponse.model_validate(
            {"agent_id": "a", "public_key": "k", "created_at": ts}
        )
        if isinstance(resp.created_at, datetime):
            assert abs(resp.created_at.timestamp() - ts) < 1e-3
        elif isinstance(resp.created_at, (int, float)):
            assert abs(float(resp.created_at) - ts) < 1e-3
        elif isinstance(resp.created_at, str):
            # ISO-8601 round-tripped back to timestamp
            parsed = datetime.fromisoformat(resp.created_at.replace("Z", "+00:00"))
            assert abs(parsed.timestamp() - ts) < 1e-3

    def test_iso_roundtrip_preserves_timestamp_value(self):
        from a2a_client.models import RegisterAgentResponse

        dt = datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc)
        iso = dt.isoformat()
        resp = RegisterAgentResponse.model_validate(
            {"agent_id": "a", "public_key": "k", "created_at": iso}
        )
        if isinstance(resp.created_at, datetime):
            assert resp.created_at == dt
        elif isinstance(resp.created_at, (int, float)):
            assert abs(float(resp.created_at) - dt.timestamp()) < 1e-3
