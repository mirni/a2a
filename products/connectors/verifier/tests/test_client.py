"""Tests for VerifierClient — Lambda invocation with mocked backends."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from products.connectors.verifier.src.client import VerifierClient, VerifierError

# ---------------------------------------------------------------------------
# HTTP mode tests
# ---------------------------------------------------------------------------


class TestHTTPMode:
    @pytest.mark.asyncio
    async def test_invoke_http_success(self):
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
            shared_secret="test-secret",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job_id": "vj-test",
            "status": "completed",
            "result": "satisfied",
            "property_results": [],
            "proof_data": "{}",
            "proof_hash": "abc",
            "duration_ms": 10,
        }

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        result = await client.invoke({"job_id": "vj-test", "properties": []})

        assert result["result"] == "satisfied"
        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        assert call_args[1]["headers"]["X-Verifier-Secret"] == "test-secret"

    @pytest.mark.asyncio
    async def test_invoke_http_error(self):
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with pytest.raises(VerifierError, match="Verifier returned 500"):
            await client.invoke({"job_id": "vj-test", "properties": []})

    @pytest.mark.asyncio
    async def test_invoke_http_no_url(self):
        client = VerifierClient(auth_mode="shared_secret", function_url="")

        with pytest.raises(VerifierError, match="VERIFIER_FUNCTION_URL is not configured"):
            await client.invoke({"job_id": "vj-test"})


# ---------------------------------------------------------------------------
# IAM mode tests
# ---------------------------------------------------------------------------


class TestIAMMode:
    @pytest.mark.asyncio
    async def test_invoke_iam_success(self):
        client = VerifierClient(
            auth_mode="iam",
            function_name="z3-verifier",
            region="us-east-1",
        )

        result_payload = json.dumps(
            {
                "job_id": "vj-test",
                "status": "completed",
                "result": "satisfied",
                "property_results": [],
                "proof_data": "{}",
                "proof_hash": "abc",
                "duration_ms": 10,
            }
        ).encode()

        mock_payload = MagicMock()
        mock_payload.read.return_value = result_payload

        mock_boto = MagicMock()
        mock_boto.invoke.return_value = {
            "Payload": mock_payload,
            "StatusCode": 200,
        }
        client._boto_client = mock_boto

        result = await client.invoke({"job_id": "vj-test", "properties": []})
        assert result["result"] == "satisfied"
        mock_boto.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_iam_function_error(self):
        client = VerifierClient(
            auth_mode="iam",
            function_name="z3-verifier",
            region="us-east-1",
        )

        mock_payload = MagicMock()
        mock_payload.read.return_value = b'{"errorMessage": "timeout"}'

        mock_boto = MagicMock()
        mock_boto.invoke.return_value = {
            "Payload": mock_payload,
            "StatusCode": 200,
            "FunctionError": "Unhandled",
        }
        client._boto_client = mock_boto

        with pytest.raises(VerifierError, match="Lambda function error"):
            await client.invoke({"job_id": "vj-test"})


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_http(self):
        client = VerifierClient(auth_mode="shared_secret")
        mock_http = AsyncMock()
        client._http_client = mock_http

        await client.close()
        mock_http.aclose.assert_called_once()
        assert client._http_client is None

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        client = VerifierClient(auth_mode="shared_secret")
        await client.close()  # Should not raise


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_values(self):
        client = VerifierClient()
        assert client.function_name == "z3-verifier"
        assert client.region == "us-east-1"
        assert client.auth_mode == "iam"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("VERIFIER_LAMBDA_FUNCTION", "custom-fn")
        monkeypatch.setenv("VERIFIER_LAMBDA_REGION", "eu-west-1")
        monkeypatch.setenv("VERIFIER_AUTH_MODE", "shared_secret")

        client = VerifierClient()
        assert client.function_name == "custom-fn"
        assert client.region == "eu-west-1"
        assert client.auth_mode == "shared_secret"
