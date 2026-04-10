"""Verifier client — invokes AWS Lambda Z3 function for formal verification.

Supports three auth modes:
  - IAM (boto3 Lambda invoke with SigV4 signing)
  - Shared secret (httpx POST to Function URL with X-Verifier-Secret header)
  - Mock (calls handler.lambda_handler directly — for CI/testing)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("a2a.verifier")

_VALID_AUTH_MODES = frozenset({"iam", "shared_secret"})


class VerifierError(Exception):
    """Raised when the verifier backend returns an error."""

    pass


class VerifierClient:
    """Client for the Z3 verifier Lambda function.

    Implements the VerifierBackend protocol expected by GatekeeperAPI.
    """

    def __init__(
        self,
        function_name: str | None = None,
        region: str | None = None,
        auth_mode: str | None = None,
        function_url: str | None = None,
        shared_secret: str | None = None,
        fallback_region: str | None = None,
    ):
        self.function_name = function_name or os.environ.get("VERIFIER_LAMBDA_FUNCTION", "z3-verifier")
        self.region = region or os.environ.get("VERIFIER_LAMBDA_REGION", "us-east-1")
        self.auth_mode = auth_mode or os.environ.get("VERIFIER_AUTH_MODE", "iam")
        self.function_url = function_url or os.environ.get("VERIFIER_FUNCTION_URL", "")
        self.shared_secret = shared_secret or os.environ.get("VERIFIER_SHARED_SECRET", "")
        # v1.2.4 P1 (arch audit): opt-in regional failover for IAM mode.
        # When set, a failed primary Lambda invoke triggers exactly one
        # retry in the fallback region with a freshly created boto client.
        # Ignored for shared_secret / HTTP mode.
        self.fallback_region = fallback_region or os.environ.get("VERIFIER_LAMBDA_FALLBACK_REGION") or None

        if self.auth_mode not in _VALID_AUTH_MODES:
            raise ValueError(f"Invalid auth_mode '{self.auth_mode}'. Must be one of: {sorted(_VALID_AUTH_MODES)}")

        if self.auth_mode == "shared_secret" and self.function_url and not self.function_url.startswith("https://"):
            raise ValueError("function_url must use HTTPS")

        if self.fallback_region is not None and self.fallback_region == self.region:
            raise ValueError(
                f"fallback_region must differ from primary region "
                f"(both set to '{self.region}')"
            )

        self._boto_client: Any = None
        self._fallback_boto_client: Any = None
        self._http_client: Any = None

    async def invoke(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Invoke the Z3 verifier and return the result.

        This method satisfies the VerifierBackend protocol.
        """
        if self.auth_mode == "iam":
            return await self._invoke_boto(job_spec)
        else:
            return await self._invoke_http(job_spec)

    def _ensure_boto_client(self) -> None:
        """Lazily create the boto3 Lambda client if not already set."""
        if self._boto_client is None:
            import boto3

            self._boto_client = boto3.client("lambda", region_name=self.region)

    def _ensure_fallback_boto_client(self) -> None:
        """Lazily create the fallback-region boto3 Lambda client."""
        if self._fallback_boto_client is None:
            import boto3

            self._fallback_boto_client = boto3.client("lambda", region_name=self.fallback_region)

    async def _invoke_boto(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Invoke Lambda via boto3 (synchronous, wrapped in executor).

        v1.2.4 P1: if ``fallback_region`` is configured and the primary
        invoke raises any exception, re-create the boto client in the
        fallback region and retry exactly once. On a second failure the
        fallback error is raised (primary error is logged).
        """
        import asyncio

        self._ensure_boto_client()
        loop = asyncio.get_running_loop()
        payload_bytes = json.dumps(job_spec).encode()

        def _sync_invoke(boto_client: Any) -> dict[str, Any]:
            response = boto_client.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=payload_bytes,
            )

            payload = response["Payload"].read()
            if response.get("FunctionError"):
                raise VerifierError(f"Lambda function error: {payload.decode()}")
            try:
                return json.loads(payload)
            except json.JSONDecodeError as e:
                raise VerifierError(f"Lambda returned invalid JSON: {e}") from e

        try:
            return await loop.run_in_executor(None, _sync_invoke, self._boto_client)
        except Exception as primary_exc:
            if self.fallback_region is None:
                raise
            logger.warning(
                "verifier primary region %s failed (%s); retrying in fallback region %s",
                self.region,
                primary_exc,
                self.fallback_region,
            )
            self._ensure_fallback_boto_client()
            return await loop.run_in_executor(None, _sync_invoke, self._fallback_boto_client)

    async def _invoke_http(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Invoke Lambda via Function URL with shared secret."""
        import httpx

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=330.0)

        if not self.function_url:
            raise VerifierError("VERIFIER_FUNCTION_URL is not configured")

        headers = {}
        if self.shared_secret:
            headers["X-Verifier-Secret"] = self.shared_secret

        try:
            response = await self._http_client.post(
                self.function_url,
                json=job_spec,
                headers=headers,
            )
        except httpx.TransportError as e:
            raise VerifierError(f"Connection error: {e}") from e

        if response.status_code != 200:
            raise VerifierError(f"Verifier returned {response.status_code}: {response.text}")

        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise VerifierError(f"Verifier returned invalid JSON: {e}") from e

    async def close(self) -> None:
        """Clean up HTTP client resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


class MockVerifierClient:
    """In-process mock that calls the Lambda handler directly.

    Used when VERIFIER_AUTH_MODE=mock (CI and local testing).
    Requires z3-solver to be installed.
    """

    async def invoke(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        import asyncio
        import importlib
        import sys

        # Import the handler from the lambda directory
        handler_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "lambda", "z3-verifier")
        handler_path = os.path.normpath(handler_path)

        if handler_path not in sys.path:
            sys.path.insert(0, handler_path)

        handler_mod = importlib.import_module("handler")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, handler_mod.lambda_handler, job_spec, None)

    async def close(self) -> None:
        pass
