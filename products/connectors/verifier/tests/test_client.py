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

from products.connectors.verifier.src.client import MockVerifierClient, VerifierClient, VerifierError

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

    @pytest.mark.asyncio
    async def test_invoke_http_no_secret_header(self):
        """When no shared_secret is configured, no auth header is sent."""
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
            shared_secret="",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "satisfied"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        await client.invoke({"job_id": "vj-test"})
        call_args = mock_http.post.call_args
        assert "X-Verifier-Secret" not in call_args[1]["headers"]

    @pytest.mark.asyncio
    async def test_invoke_http_transport_error(self):
        """Transport errors are wrapped in VerifierError."""
        import httpx

        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
        )

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        client._http_client = mock_http

        with pytest.raises(VerifierError, match="Connection error"):
            await client.invoke({"job_id": "vj-test"})

    @pytest.mark.asyncio
    async def test_invoke_http_invalid_json_response(self):
        """Invalid JSON response is wrapped in VerifierError."""
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("bad", "", 0)

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with pytest.raises(VerifierError, match="invalid JSON"):
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

    @pytest.mark.asyncio
    async def test_invoke_iam_invalid_json(self):
        """Lambda returns invalid JSON payload."""
        client = VerifierClient(auth_mode="iam", function_name="z3-verifier")

        mock_payload = MagicMock()
        mock_payload.read.return_value = b"not json at all"

        mock_boto = MagicMock()
        mock_boto.invoke.return_value = {"Payload": mock_payload, "StatusCode": 200}
        client._boto_client = mock_boto

        with pytest.raises(VerifierError, match="invalid JSON"):
            await client.invoke({"job_id": "vj-test"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_auth_mode(self):
        with pytest.raises(ValueError, match="Invalid auth_mode"):
            VerifierClient(auth_mode="bogus")

    def test_http_url_must_be_https(self):
        with pytest.raises(ValueError, match="HTTPS"):
            VerifierClient(
                auth_mode="shared_secret",
                function_url="http://insecure.example.com/",
            )

    def test_https_url_accepted(self):
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://secure.example.com/",
        )
        assert client.function_url == "https://secure.example.com/"

    def test_empty_url_accepted(self):
        """Empty URL is allowed at construction (fails at invoke time)."""
        client = VerifierClient(auth_mode="shared_secret", function_url="")
        assert client.function_url == ""


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
        # v1.2.4 P1: fallback region is opt-in; default is no fallback.
        assert client.fallback_region is None

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("VERIFIER_LAMBDA_FUNCTION", "custom-fn")
        monkeypatch.setenv("VERIFIER_LAMBDA_REGION", "eu-west-1")
        monkeypatch.setenv("VERIFIER_AUTH_MODE", "shared_secret")

        client = VerifierClient()
        assert client.function_name == "custom-fn"
        assert client.region == "eu-west-1"
        assert client.auth_mode == "shared_secret"


# ---------------------------------------------------------------------------
# Multi-region failover (v1.2.4 P1: arch audit)
# ---------------------------------------------------------------------------


class TestMultiRegionFailover:
    """Multi-region failover for IAM-mode Lambda invoke.

    When ``VERIFIER_LAMBDA_FALLBACK_REGION`` is set (or ``fallback_region`` is
    passed to the constructor), a failed primary invoke triggers a single
    retry in the fallback region with a freshly created boto3 client. This
    hedges against regional Lambda outages without requiring client-side
    orchestration.
    """

    def test_fallback_region_from_env(self, monkeypatch):
        monkeypatch.setenv("VERIFIER_LAMBDA_FALLBACK_REGION", "us-west-2")
        client = VerifierClient(auth_mode="iam", region="us-east-1")
        assert client.fallback_region == "us-west-2"

    def test_fallback_region_from_constructor(self):
        client = VerifierClient(
            auth_mode="iam",
            region="us-east-1",
            fallback_region="us-west-2",
        )
        assert client.fallback_region == "us-west-2"

    def test_fallback_same_as_primary_rejected(self):
        """Defensive: fallback region equal to primary is a config error."""
        with pytest.raises(ValueError, match="fallback_region must differ"):
            VerifierClient(
                auth_mode="iam",
                region="us-east-1",
                fallback_region="us-east-1",
            )

    @pytest.mark.asyncio
    async def test_no_fallback_propagates_primary_error(self):
        """Without fallback config, primary errors propagate unchanged."""
        client = VerifierClient(auth_mode="iam", region="us-east-1")

        mock_boto = MagicMock()
        mock_boto.invoke.side_effect = RuntimeError("boom")
        client._boto_client = mock_boto

        with pytest.raises(RuntimeError, match="boom"):
            await client.invoke({"job_id": "vj-test", "properties": []})
        assert mock_boto.invoke.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_not_used_when_primary_succeeds(self):
        """Fallback client is never constructed on primary success."""
        client = VerifierClient(
            auth_mode="iam",
            region="us-east-1",
            fallback_region="us-west-2",
        )

        payload = MagicMock()
        payload.read.return_value = json.dumps({"result": "satisfied"}).encode()
        mock_primary = MagicMock()
        mock_primary.invoke.return_value = {"Payload": payload, "StatusCode": 200}
        client._boto_client = mock_primary

        # Stub ensure_fallback so any lazy construction raises loudly.
        def _fail():
            raise AssertionError("fallback client must not be constructed on primary success")

        client._ensure_fallback_boto_client = _fail  # type: ignore[method-assign]

        result = await client.invoke({"job_id": "vj-test", "properties": []})
        assert result["result"] == "satisfied"
        assert mock_primary.invoke.call_count == 1
        assert client._fallback_boto_client is None

    @pytest.mark.asyncio
    async def test_fallback_region_invoked_on_primary_error(self):
        """Primary raises → fallback region retried → success returned."""
        client = VerifierClient(
            auth_mode="iam",
            region="us-east-1",
            fallback_region="us-west-2",
        )

        mock_primary = MagicMock()
        mock_primary.invoke.side_effect = RuntimeError("primary region down")
        client._boto_client = mock_primary

        # Pre-seed fallback client (equivalent to what _ensure_fallback_boto_client
        # would lazily create via boto3.client("lambda", region_name="us-west-2")).
        payload = MagicMock()
        payload.read.return_value = json.dumps({"result": "satisfied"}).encode()
        mock_fallback = MagicMock()
        mock_fallback.invoke.return_value = {"Payload": payload, "StatusCode": 200}
        client._fallback_boto_client = mock_fallback

        result = await client.invoke({"job_id": "vj-test", "properties": []})
        assert result["result"] == "satisfied"
        assert mock_primary.invoke.call_count == 1
        assert mock_fallback.invoke.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_region_failure_raises_fallback_error(self):
        """Both regions fail → error from fallback region is raised."""
        client = VerifierClient(
            auth_mode="iam",
            region="us-east-1",
            fallback_region="us-west-2",
        )

        mock_primary = MagicMock()
        mock_primary.invoke.side_effect = RuntimeError("primary region down")
        client._boto_client = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.invoke.side_effect = RuntimeError("fallback region also down")
        client._fallback_boto_client = mock_fallback

        with pytest.raises(RuntimeError, match="fallback region also down"):
            await client.invoke({"job_id": "vj-test", "properties": []})
        assert mock_primary.invoke.call_count == 1
        assert mock_fallback.invoke.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_retries_only_once(self):
        """Fallback region is retried at most once (no infinite loop)."""
        client = VerifierClient(
            auth_mode="iam",
            region="us-east-1",
            fallback_region="us-west-2",
        )

        mock_primary = MagicMock()
        mock_primary.invoke.side_effect = RuntimeError("down")
        client._boto_client = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.invoke.side_effect = RuntimeError("also down")
        client._fallback_boto_client = mock_fallback

        with pytest.raises(RuntimeError):
            await client.invoke({"job_id": "vj-test", "properties": []})
        assert mock_primary.invoke.call_count == 1
        assert mock_fallback.invoke.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_ignored_in_shared_secret_mode(self):
        """Fallback only applies to IAM mode; HTTP path is unchanged."""
        client = VerifierClient(
            auth_mode="shared_secret",
            function_url="https://test.lambda-url.on.aws/",
            fallback_region="us-west-2",
        )
        # Fallback is stored but HTTP invoke path never consults it.
        assert client.fallback_region == "us-west-2"

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "boom"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with pytest.raises(VerifierError, match="Verifier returned 500"):
            await client.invoke({"job_id": "vj-test"})
        # No retry — HTTP path does exactly one POST.
        assert mock_http.post.call_count == 1


# ---------------------------------------------------------------------------
# MockVerifierClient tests
# ---------------------------------------------------------------------------


class TestMockVerifierClient:
    @pytest.mark.asyncio
    async def test_import_failure_raises_verifier_error(self):
        """When handler import fails, MockVerifierClient raises VerifierError with diagnostic message."""
        from unittest.mock import patch

        client = MockVerifierClient()

        with patch("importlib.import_module", side_effect=ImportError("No module named 'z3'")):
            with pytest.raises(VerifierError, match="cannot import handler"):
                await client.invoke({"job_id": "vj-test", "properties": []})

    @pytest.mark.asyncio
    async def test_import_failure_mentions_z3_solver(self):
        """Error message should mention z3-solver installation."""
        from unittest.mock import patch

        client = MockVerifierClient()

        with patch("importlib.import_module", side_effect=ImportError("No module named 'z3'")):
            with pytest.raises(VerifierError, match="z3-solver"):
                await client.invoke({"job_id": "vj-test", "properties": []})

    @pytest.mark.asyncio
    async def test_successful_invocation(self):
        """MockVerifierClient invokes handler and returns result with status completed."""
        from unittest.mock import patch

        client = MockVerifierClient()

        mock_handler = MagicMock()
        mock_handler.lambda_handler.return_value = {
            "job_id": "vj-test",
            "status": "completed",
            "result": "satisfied",
            "property_results": [],
            "proof_data": "{}",
            "proof_hash": "abc",
            "duration_ms": 5,
        }

        mock_module = MagicMock()
        mock_module.lambda_handler = mock_handler.lambda_handler

        with patch("importlib.import_module", return_value=mock_module):
            result = await client.invoke({"job_id": "vj-test", "properties": []})

        assert result["status"] == "completed"
        assert result["result"] == "satisfied"
        mock_handler.lambda_handler.assert_called_once()


# ---------------------------------------------------------------------------
# Package lambda/ symlink tests
# ---------------------------------------------------------------------------


class TestPackageSymlinks:
    """Verify lambda/ symlinks exist in package trees for deployed Z3 verifier."""

    def test_gateway_test_lambda_symlink_exists(self):
        """package/a2a-gateway-test must include lambda/ symlink."""
        link = os.path.join(
            _project_root,
            "package", "a2a-gateway-test", "opt", "a2a-test", "lambda",
        )
        assert os.path.islink(link), f"Expected symlink at {link}"

    def test_gateway_sandbox_lambda_symlink_exists(self):
        """package/a2a-gateway-sandbox must include lambda/ symlink."""
        link = os.path.join(
            _project_root,
            "package", "a2a-gateway-sandbox", "opt", "a2a-sandbox", "lambda",
        )
        assert os.path.islink(link), f"Expected symlink at {link}"

    def test_gateway_test_lambda_symlink_resolves(self):
        """Symlink must resolve to the actual lambda/ directory."""
        link = os.path.join(
            _project_root,
            "package", "a2a-gateway-test", "opt", "a2a-test", "lambda",
        )
        resolved = os.path.realpath(link)
        expected = os.path.realpath(os.path.join(_project_root, "lambda"))
        assert resolved == expected, f"Symlink resolves to {resolved}, expected {expected}"

    def test_gateway_sandbox_lambda_symlink_resolves(self):
        """Symlink must resolve to the actual lambda/ directory."""
        link = os.path.join(
            _project_root,
            "package", "a2a-gateway-sandbox", "opt", "a2a-sandbox", "lambda",
        )
        resolved = os.path.realpath(link)
        expected = os.path.realpath(os.path.join(_project_root, "lambda"))
        assert resolved == expected, f"Symlink resolves to {resolved}, expected {expected}"
