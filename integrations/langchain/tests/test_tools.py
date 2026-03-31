"""TDD RED: Tests for tools.py — pre-built A2A tool classes."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool

from tests.conftest import _make_exec_response


class TestA2AGetBalance:
    def test_is_base_tool(self, mock_client):
        from a2a_langchain.tools import A2AGetBalance
        tool = A2AGetBalance(client=mock_client)
        assert isinstance(tool, BaseTool)

    def test_name(self, mock_client):
        from a2a_langchain.tools import A2AGetBalance
        tool = A2AGetBalance(client=mock_client)
        assert tool.name == "get_balance"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2AGetBalance
        mock_client.execute.return_value = _make_exec_response({"balance": "100.00"})
        tool = A2AGetBalance(client=mock_client)
        result = await tool._arun(agent_id="a1")
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "a1"})
        assert json.loads(result)["balance"] == "100.00"


class TestA2ADeposit:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ADeposit
        tool = A2ADeposit(client=mock_client)
        assert tool.name == "deposit"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2ADeposit
        mock_client.execute.return_value = _make_exec_response({"new_balance": "200.00"})
        tool = A2ADeposit(client=mock_client)
        result = await tool._arun(agent_id="a1", amount=100)
        params = mock_client.execute.call_args[0][1]
        assert params["agent_id"] == "a1"
        assert params["amount"] == 100


class TestA2ACreatePaymentIntent:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ACreatePaymentIntent
        tool = A2ACreatePaymentIntent(client=mock_client)
        assert tool.name == "create_intent"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2ACreatePaymentIntent
        mock_client.execute.return_value = _make_exec_response(
            {"id": "i1", "status": "pending", "amount": "25.00"}
        )
        tool = A2ACreatePaymentIntent(client=mock_client)
        result = await tool._arun(payer="a", payee="b", amount=25)
        params = mock_client.execute.call_args[0][1]
        assert params["payer"] == "a"
        assert params["payee"] == "b"


class TestA2ACapturePayment:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ACapturePayment
        tool = A2ACapturePayment(client=mock_client)
        assert tool.name == "capture_intent"


class TestA2ACreateEscrow:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ACreateEscrow
        tool = A2ACreateEscrow(client=mock_client)
        assert tool.name == "create_escrow"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2ACreateEscrow
        mock_client.execute.return_value = _make_exec_response(
            {"id": "e1", "status": "held", "amount": "50.00"}
        )
        tool = A2ACreateEscrow(client=mock_client)
        result = await tool._arun(payer="a", payee="b", amount=50)
        params = mock_client.execute.call_args[0][1]
        assert params["payer"] == "a"


class TestA2AReleaseEscrow:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2AReleaseEscrow
        tool = A2AReleaseEscrow(client=mock_client)
        assert tool.name == "release_escrow"


class TestA2ASearchServices:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ASearchServices
        tool = A2ASearchServices(client=mock_client)
        assert tool.name == "search_services"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2ASearchServices
        mock_client.execute.return_value = _make_exec_response({"services": []})
        tool = A2ASearchServices(client=mock_client)
        result = await tool._arun(query="analytics")
        mock_client.execute.assert_called_once_with(
            "search_services", {"query": "analytics"}
        )


class TestA2AGetTrustScore:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2AGetTrustScore
        tool = A2AGetTrustScore(client=mock_client)
        assert tool.name == "get_trust_score"


class TestA2ARegisterAgent:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ARegisterAgent
        tool = A2ARegisterAgent(client=mock_client)
        assert tool.name == "register_agent"

    @pytest.mark.asyncio
    async def test_arun_with_optional(self, mock_client):
        from a2a_langchain.tools import A2ARegisterAgent
        mock_client.execute.return_value = _make_exec_response(
            {"agent_id": "a1", "public_key": "pk", "created_at": 100.0}
        )
        tool = A2ARegisterAgent(client=mock_client)
        result = await tool._arun(agent_id="a1", public_key="pk")
        params = mock_client.execute.call_args[0][1]
        assert params["public_key"] == "pk"


class TestA2ASendMessage:
    def test_name(self, mock_client):
        from a2a_langchain.tools import A2ASendMessage
        tool = A2ASendMessage(client=mock_client)
        assert tool.name == "send_message"

    @pytest.mark.asyncio
    async def test_arun(self, mock_client):
        from a2a_langchain.tools import A2ASendMessage
        mock_client.execute.return_value = _make_exec_response(
            {"id": "m1", "sender": "a", "recipient": "b", "thread_id": "t1"}
        )
        tool = A2ASendMessage(client=mock_client)
        result = await tool._arun(
            sender="a", recipient="b", message_type="text", body="hello"
        )
        params = mock_client.execute.call_args[0][1]
        assert params["sender"] == "a"
        assert params["body"] == "hello"


class TestAllToolsReturnJSON:
    """All pre-built tools return valid JSON strings."""

    @pytest.mark.asyncio
    async def test_all_return_json(self, mock_client):
        from a2a_langchain.tools import (
            A2AGetBalance, A2ADeposit, A2ACreatePaymentIntent,
            A2ACapturePayment, A2ACreateEscrow, A2AReleaseEscrow,
            A2ASearchServices, A2AGetTrustScore, A2ARegisterAgent,
            A2ASendMessage,
        )
        mock_client.execute.return_value = _make_exec_response({"ok": True})

        tools_and_args = [
            (A2AGetBalance(client=mock_client), {"agent_id": "a1"}),
            (A2ADeposit(client=mock_client), {"agent_id": "a1", "amount": 10}),
            (A2ACreatePaymentIntent(client=mock_client), {"payer": "a", "payee": "b", "amount": 10}),
            (A2ACapturePayment(client=mock_client), {"intent_id": "i1"}),
            (A2ACreateEscrow(client=mock_client), {"payer": "a", "payee": "b", "amount": 10}),
            (A2AReleaseEscrow(client=mock_client), {"escrow_id": "e1"}),
            (A2ASearchServices(client=mock_client), {"query": "test"}),
            (A2AGetTrustScore(client=mock_client), {"server_id": "s1"}),
            (A2ARegisterAgent(client=mock_client), {"agent_id": "a1"}),
            (A2ASendMessage(client=mock_client), {"sender": "a", "recipient": "b", "message_type": "text", "body": "hi"}),
        ]
        for tool, kwargs in tools_and_args:
            result = await tool._arun(**kwargs)
            parsed = json.loads(result)
            assert isinstance(parsed, dict), f"{tool.name} did not return dict"
