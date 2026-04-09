"""Verifier client — invokes AWS Lambda Z3 function for formal verification.

Supports two auth modes:
  - IAM (boto3 Lambda invoke with SigV4 signing)
  - Shared secret (httpx POST to Function URL with X-Verifier-Secret header)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("a2a.verifier")


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
    ):
        self.function_name = function_name or os.environ.get(
            "VERIFIER_LAMBDA_FUNCTION", "z3-verifier"
        )
        self.region = region or os.environ.get("VERIFIER_LAMBDA_REGION", "us-east-1")
        self.auth_mode = auth_mode or os.environ.get("VERIFIER_AUTH_MODE", "iam")
        self.function_url = function_url or os.environ.get("VERIFIER_FUNCTION_URL", "")
        self.shared_secret = shared_secret or os.environ.get(
            "VERIFIER_SHARED_SECRET", ""
        )

        self._boto_client = None
        self._http_client = None

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

            self._boto_client = boto3.client(
                "lambda", region_name=self.region
            )

    async def _invoke_boto(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Invoke Lambda via boto3 (synchronous, wrapped in executor)."""
        import asyncio

        self._ensure_boto_client()
        boto_client = self._boto_client
        loop = asyncio.get_running_loop()

        def _sync_invoke():
            response = boto_client.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(job_spec),
            )

            payload = response["Payload"].read()
            if response.get("FunctionError"):
                raise VerifierError(
                    f"Lambda function error: {payload.decode()}"
                )
            return json.loads(payload)

        return await loop.run_in_executor(None, _sync_invoke)

    async def _invoke_http(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Invoke Lambda via Function URL with shared secret."""
        import httpx

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=900.0)

        if not self.function_url:
            raise VerifierError("VERIFIER_FUNCTION_URL is not configured")

        headers = {}
        if self.shared_secret:
            headers["X-Verifier-Secret"] = self.shared_secret

        response = await self._http_client.post(
            self.function_url,
            json=job_spec,
            headers=headers,
        )

        if response.status_code != 200:
            raise VerifierError(
                f"Verifier returned {response.status_code}: {response.text}"
            )

        return response.json()

    async def close(self) -> None:
        """Clean up HTTP client resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
