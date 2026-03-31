"""TDD RED: Tests for _schemas.py — Pydantic input schemas with extra=forbid."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError


class TestGetBalanceInput:
    def test_valid(self):
        from a2a_langchain._schemas import GetBalanceInput
        m = GetBalanceInput(agent_id="agent-1")
        assert m.agent_id == "agent-1"

    def test_extra_forbid(self):
        from a2a_langchain._schemas import GetBalanceInput
        with pytest.raises(ValidationError):
            GetBalanceInput(agent_id="a1", bogus="x")

    def test_required_field(self):
        from a2a_langchain._schemas import GetBalanceInput
        with pytest.raises(ValidationError):
            GetBalanceInput()


class TestDepositInput:
    def test_valid(self):
        from a2a_langchain._schemas import DepositInput
        m = DepositInput(agent_id="a1", amount=Decimal("100.00"))
        assert m.agent_id == "a1"
        assert m.amount == Decimal("100.00")

    def test_extra_forbid(self):
        from a2a_langchain._schemas import DepositInput
        with pytest.raises(ValidationError):
            DepositInput(agent_id="a1", amount=100, extra="bad")


class TestCreatePaymentIntentInput:
    def test_valid(self):
        from a2a_langchain._schemas import CreatePaymentIntentInput
        m = CreatePaymentIntentInput(payer="a", payee="b", amount=Decimal("25.00"))
        assert m.payer == "a"
        assert m.payee == "b"

    def test_extra_forbid(self):
        from a2a_langchain._schemas import CreatePaymentIntentInput
        with pytest.raises(ValidationError):
            CreatePaymentIntentInput(payer="a", payee="b", amount=10, bad="x")


class TestCapturePaymentInput:
    def test_valid(self):
        from a2a_langchain._schemas import CapturePaymentInput
        m = CapturePaymentInput(intent_id="i1")
        assert m.intent_id == "i1"


class TestCreateEscrowInput:
    def test_valid(self):
        from a2a_langchain._schemas import CreateEscrowInput
        m = CreateEscrowInput(payer="a", payee="b", amount=Decimal("50.00"))
        assert m.amount == Decimal("50.00")

    def test_extra_forbid(self):
        from a2a_langchain._schemas import CreateEscrowInput
        with pytest.raises(ValidationError):
            CreateEscrowInput(payer="a", payee="b", amount=50, nope="x")


class TestReleaseEscrowInput:
    def test_valid(self):
        from a2a_langchain._schemas import ReleaseEscrowInput
        m = ReleaseEscrowInput(escrow_id="e1")
        assert m.escrow_id == "e1"


class TestSearchServicesInput:
    def test_valid(self):
        from a2a_langchain._schemas import SearchServicesInput
        m = SearchServicesInput(query="analytics")
        assert m.query == "analytics"


class TestGetTrustScoreInput:
    def test_valid(self):
        from a2a_langchain._schemas import GetTrustScoreInput
        m = GetTrustScoreInput(server_id="s1")
        assert m.server_id == "s1"


class TestRegisterAgentInput:
    def test_valid(self):
        from a2a_langchain._schemas import RegisterAgentInput
        m = RegisterAgentInput(agent_id="a1")
        assert m.agent_id == "a1"

    def test_optional_public_key(self):
        from a2a_langchain._schemas import RegisterAgentInput
        m = RegisterAgentInput(agent_id="a1", public_key="pk")
        assert m.public_key == "pk"


class TestSendMessageInput:
    def test_valid(self):
        from a2a_langchain._schemas import SendMessageInput
        m = SendMessageInput(sender="a", recipient="b", message_type="text", body="hi")
        assert m.sender == "a"
        assert m.body == "hi"

    def test_optional_fields(self):
        from a2a_langchain._schemas import SendMessageInput
        m = SendMessageInput(
            sender="a", recipient="b", message_type="text", body="hi",
            subject="greetings", thread_id="t1"
        )
        assert m.subject == "greetings"
        assert m.thread_id == "t1"

    def test_extra_forbid(self):
        from a2a_langchain._schemas import SendMessageInput
        with pytest.raises(ValidationError):
            SendMessageInput(sender="a", recipient="b", message_type="text", body="hi", extra="x")


class TestAllSchemasHaveExamples:
    """Every schema must include json_schema_extra with examples."""

    def test_all_schemas_have_schema_extra(self):
        from a2a_langchain import _schemas
        schema_classes = [
            _schemas.GetBalanceInput,
            _schemas.DepositInput,
            _schemas.CreatePaymentIntentInput,
            _schemas.CapturePaymentInput,
            _schemas.CreateEscrowInput,
            _schemas.ReleaseEscrowInput,
            _schemas.SearchServicesInput,
            _schemas.GetTrustScoreInput,
            _schemas.RegisterAgentInput,
            _schemas.SendMessageInput,
        ]
        for cls in schema_classes:
            config = cls.model_config
            assert config.get("json_schema_extra") is not None, (
                f"{cls.__name__} missing json_schema_extra"
            )
