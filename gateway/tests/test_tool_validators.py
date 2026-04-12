"""Tests for gateway/src/tools/_validators.py.

P2-1: shared tool-handler validators extracted from identity.py,
gatekeeper.py, and payments.py. This module centralises ownership
checks and money formatting so tool modules import rather than
copy-paste.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


def test_check_caller_owns_agent_id_admin_passes():
    from gateway.src.tools._validators import check_caller_owns_agent_id

    # Admin tier bypasses the check
    params = {"_caller_agent_id": "admin-1", "_caller_tier": "admin", "agent_id": "other-agent"}
    check_caller_owns_agent_id(params)  # should not raise


def test_check_caller_owns_agent_id_same_agent_passes():
    from gateway.src.tools._validators import check_caller_owns_agent_id

    params = {"_caller_agent_id": "agent-a", "_caller_tier": "pro", "agent_id": "agent-a"}
    check_caller_owns_agent_id(params)  # should not raise


def test_check_caller_owns_agent_id_different_agent_raises():
    from gateway.src.tools._validators import check_caller_owns_agent_id
    from gateway.src.tool_errors import ToolForbiddenError

    params = {"_caller_agent_id": "agent-a", "_caller_tier": "pro", "agent_id": "agent-b"}
    with pytest.raises(ToolForbiddenError, match="Forbidden"):
        check_caller_owns_agent_id(params)


def test_check_caller_owns_agent_id_no_caller_passes():
    from gateway.src.tools._validators import check_caller_owns_agent_id

    params = {"_caller_tier": "pro", "agent_id": "agent-b"}
    check_caller_owns_agent_id(params)  # should not raise


def test_check_caller_owns_job_admin_passes():
    from gateway.src.tools._validators import check_caller_owns_job

    params = {"_caller_agent_id": "admin-1", "_caller_tier": "admin"}
    check_caller_owns_job("other-agent", params)  # should not raise


def test_check_caller_owns_job_owner_passes():
    from gateway.src.tools._validators import check_caller_owns_job

    params = {"_caller_agent_id": "agent-a", "_caller_tier": "pro"}
    check_caller_owns_job("agent-a", params)  # should not raise


def test_check_caller_owns_job_non_owner_raises():
    from gateway.src.tools._validators import check_caller_owns_job
    from gateway.src.tool_errors import ToolForbiddenError

    params = {"_caller_agent_id": "agent-a", "_caller_tier": "pro"}
    with pytest.raises(ToolForbiddenError, match="Forbidden"):
        check_caller_owns_job("agent-b", params)


def test_format_money_two_decimal_places():
    from gateway.src.tools._validators import format_money

    assert format_money(Decimal("1.23")) == "1.23"
    assert format_money(Decimal("5.0")) == "5.00"
    assert format_money(Decimal("0.0246")) == "0.02"
    assert format_money(Decimal("0.025")) == "0.03"  # ROUND_HALF_UP


def test_format_money_accepts_float_and_str():
    from gateway.src.tools._validators import format_money

    assert format_money(5.0) == "5.00"
    assert format_money("1.23") == "1.23"


def test_check_intent_ownership_admin_passes():
    from gateway.src.tools._validators import check_intent_ownership
    from types import SimpleNamespace

    intent = SimpleNamespace(payer="agent-a", payee="agent-b")
    check_intent_ownership("admin-1", "admin", intent)  # should not raise


def test_check_intent_ownership_payer_passes():
    from gateway.src.tools._validators import check_intent_ownership
    from types import SimpleNamespace

    intent = SimpleNamespace(payer="agent-a", payee="agent-b")
    check_intent_ownership("agent-a", "pro", intent)  # should not raise


def test_check_intent_ownership_payee_passes():
    from gateway.src.tools._validators import check_intent_ownership
    from types import SimpleNamespace

    intent = SimpleNamespace(payer="agent-a", payee="agent-b")
    check_intent_ownership("agent-b", "pro", intent)  # should not raise


def test_check_intent_ownership_outsider_raises():
    from gateway.src.tools._validators import check_intent_ownership
    from gateway.src.tool_errors import ToolForbiddenError
    from types import SimpleNamespace

    intent = SimpleNamespace(payer="agent-a", payee="agent-b")
    with pytest.raises(ToolForbiddenError, match="Forbidden"):
        check_intent_ownership("agent-c", "pro", intent)


def test_check_intent_ownership_payer_only_rejects_payee():
    from gateway.src.tools._validators import check_intent_ownership
    from gateway.src.tool_errors import ToolForbiddenError
    from types import SimpleNamespace

    intent = SimpleNamespace(payer="agent-a", payee="agent-b")
    with pytest.raises(ToolForbiddenError, match="payer"):
        check_intent_ownership("agent-b", "pro", intent, payer_only=True)
