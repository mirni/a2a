"""Tests for P2-16: Batch Execution endpoint (POST /v1/batch)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


class TestBatchExecution:
    """Tests for the POST /v1/batch endpoint."""

    async def test_batch_endpoint_exists(self, client, api_key):
        """The /v1/batch endpoint should exist and accept POST."""
        resp = await client.post(
            "/v1/batch",
            json={"calls": [{"tool": "get_balance", "params": {"agent_id": "test-agent"}}]},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should not be 404 or 405
        assert resp.status_code != 404, "Batch endpoint must exist"
        assert resp.status_code != 405, "Batch endpoint must accept POST"

    async def test_single_call_batch(self, client, api_key):
        """A batch with a single call should work correctly."""
        resp = await client.post(
            "/v1/batch",
            json={"calls": [{"tool": "get_balance", "params": {"agent_id": "test-agent"}}]},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["success"] is True
        assert "result" in data["results"][0]

    async def test_multiple_calls_batch(self, client, api_key, app):
        """A batch with multiple calls should execute all of them sequentially."""
        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
                    {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
                ]
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert all(r["success"] for r in data["results"])

    async def test_batch_with_error_in_one_call(self, client, api_key):
        """If one call in a batch fails, others should still succeed."""
        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
                    {"tool": "get_balance", "params": {"agent_id": "nonexistent-wallet-agent"}},
                    {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
                ]
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 3
        # First and third should succeed, second may fail (wallet not found)
        assert data["results"][0]["success"] is True

    async def test_batch_max_10_calls(self, client, api_key):
        """Should reject batches with more than 10 calls."""
        calls = [{"tool": "get_balance", "params": {"agent_id": "test-agent"}} for _ in range(11)]
        resp = await client.post(
            "/v1/batch",
            json={"calls": calls},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    async def test_batch_empty_calls(self, client, api_key):
        """Should handle empty calls list."""
        resp = await client.post(
            "/v1/batch",
            json={"calls": []},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    async def test_batch_requires_auth(self, client):
        """Should require authentication."""
        resp = await client.post(
            "/v1/batch",
            json={"calls": [{"tool": "get_balance", "params": {"agent_id": "test-agent"}}]},
        )
        assert resp.status_code == 401

    async def test_batch_invalid_json(self, client, api_key):
        """Should return 400 for invalid JSON body."""
        resp = await client.post(
            "/v1/batch",
            content=b"not json",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400

    async def test_batch_missing_calls_field(self, client, api_key):
        """Should return 400 when calls field is missing."""
        resp = await client.post(
            "/v1/batch",
            json={"something": "else"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400

    async def test_batch_unknown_tool(self, client, api_key):
        """A call with an unknown tool should return an error entry."""
        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "nonexistent_tool_xyz", "params": {}},
                ]
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["success"] is False
        assert "error" in data["results"][0]
