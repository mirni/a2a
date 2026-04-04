"""Tests for P1 #8: BOLA input reflection sanitization.

Error messages must not echo raw agent_id or reflect oversized input.
"""

from __future__ import annotations

import pytest

from gateway.src.authorization import check_ownership_authorization

pytestmark = pytest.mark.asyncio


class TestBOLASanitization:
    """403 error messages must sanitize reflected input."""

    def test_long_agent_id_truncated_in_error(self):
        """A 1000-char agent_id in params should not appear verbatim in the error."""
        long_id = "x" * 1000
        result = check_ownership_authorization(
            caller_agent_id="real-caller",
            caller_tier="free",
            params={"agent_id": long_id},
        )
        assert result is not None
        status, message, code = result
        assert status == 403
        # The raw long ID must NOT appear in the error message
        assert long_id not in message
        # The caller's real agent_id must NOT appear in the error message
        assert "real-caller" not in message

    def test_normal_mismatch_does_not_leak_caller_id(self):
        """Error message must not include the authenticated caller's agent_id."""
        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"agent_id": "bob"},
        )
        assert result is not None
        status, message, code = result
        assert status == 403
        # Neither alice nor bob should appear in the error message
        assert "alice" not in message
        assert "bob" not in message

    def test_admin_bypasses_check(self):
        """Admin tier should always return None (authorized)."""
        result = check_ownership_authorization(
            caller_agent_id="admin",
            caller_tier="admin",
            params={"agent_id": "anyone"},
        )
        assert result is None
