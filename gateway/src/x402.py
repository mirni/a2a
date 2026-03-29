"""x402 Protocol — Internet-native crypto payments via EIP-3009 transfer authorizations.

Models for the x402 payment handshake:
  - Server returns HTTP 402 with X402PaymentRequired in PAYMENT-REQUIRED header
  - Client signs EIP-3009 authorization and retries with X-PAYMENT header
  - Server verifies via Coinbase x402 Facilitator, then fulfills the request
"""

from __future__ import annotations

import base64
import json
import logging
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.tool_errors import X402ReplayError, X402VerificationError

logger = logging.getLogger("a2a.x402")


# USDC contract addresses per network
USDC_CONTRACTS: dict[str, str] = {
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "polygon": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
}


class X402Authorization(BaseModel):
    """EIP-3009 transferWithAuthorization parameters."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "from": "0xSenderAddress",
                "to": "0xMerchantAddress",
                "value": "1000000",
                "valid_after": 0,
                "valid_before": 9999999999,
                "nonce": "0x" + "ab" * 32,
            }
        },
    )

    from_address: str = Field(alias="from")
    to: str
    value: str
    valid_after: int
    valid_before: int
    nonce: str


class X402Payload(BaseModel):
    """Wraps the EIP-712 signature and the authorization it covers."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "signature": "0x" + "ff" * 65,
                "authorization": {
                    "from": "0xSenderAddress",
                    "to": "0xMerchantAddress",
                    "value": "1000000",
                    "valid_after": 0,
                    "valid_before": 9999999999,
                    "nonce": "0x" + "ab" * 32,
                },
            }
        },
    )

    signature: str
    authorization: X402Authorization


class X402PaymentProof(BaseModel):
    """Top-level proof decoded from the X-PAYMENT header (base64 JSON)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "x402_version": 1,
                "scheme": "exact",
                "network": "base",
                "payload": {
                    "signature": "0x" + "ff" * 65,
                    "authorization": {
                        "from": "0xSenderAddress",
                        "to": "0xMerchantAddress",
                        "value": "1000000",
                        "valid_after": 0,
                        "valid_before": 9999999999,
                        "nonce": "0x" + "ab" * 32,
                    },
                },
            }
        },
    )

    x402_version: int = 1
    scheme: str = "exact"
    network: str
    payload: X402Payload


class X402PaymentRequired(BaseModel):
    """Server's payment requirements — encoded into PAYMENT-REQUIRED header."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "max_amount_required": "1000",
                "resource": "/v1/execute",
                "description": "Tool execution payment",
                "pay_to": "0xMerchantAddress",
                "asset": USDC_CONTRACTS["base"],
                "network": "base",
            }
        },
    )

    max_amount_required: str
    resource: str
    description: str
    pay_to: str
    asset: str
    network: str


class X402Verifier:
    """Validates x402 payment proofs locally and via the Coinbase Facilitator."""

    def __init__(
        self,
        merchant_address: str,
        facilitator_url: str,
        supported_networks: dict[str, str],
    ) -> None:
        self._merchant_address = merchant_address
        self._facilitator_url = facilitator_url
        self._supported_networks = supported_networks
        self._used_nonces: set[str] = set()
        self.pending_settlements: list[X402PaymentProof] = []

    def check_replay(self, nonce: str) -> None:
        """Raise X402ReplayError if nonce was already seen."""
        if nonce in self._used_nonces:
            raise X402ReplayError(f"Nonce already used: {nonce}")

    def mark_nonce_used(self, nonce: str) -> None:
        """Record nonce as used."""
        self._used_nonces.add(nonce)

    def validate_proof_locally(self, proof: X402PaymentProof, required_value: str) -> None:
        """Local checks (no network call).

        Raises X402VerificationError on any failure.
        """
        auth = proof.payload.authorization
        now = time.time()

        if auth.to != self._merchant_address:
            raise X402VerificationError(f"Wrong recipient: expected {self._merchant_address}, got {auth.to}")

        if int(auth.value) < int(required_value):
            raise X402VerificationError(f"Insufficient value: {auth.value} < {required_value}")

        if auth.valid_before <= now:
            raise X402VerificationError("Payment authorization has expired")

        if auth.valid_after > now:
            raise X402VerificationError("Payment authorization is not yet valid")

        if proof.network not in self._supported_networks:
            raise X402VerificationError(f"Unsupported network: {proof.network}")

        self.check_replay(auth.nonce)

    async def verify_with_facilitator(self, proof: X402PaymentProof) -> dict:
        """POST base64-encoded proof to facilitator /verify endpoint."""
        proof_json = proof.model_dump(by_alias=True)
        encoded = base64.b64encode(json.dumps(proof_json).encode()).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._facilitator_url}/verify",
                json={"payment": encoded},
            )

        if resp.status_code != 200:
            raise X402VerificationError(f"Facilitator verification failed ({resp.status_code}): {resp.text}")
        return resp.json()

    async def settle_with_facilitator(self, proof: X402PaymentProof) -> dict:
        """POST to facilitator /settle. Fire-and-forget after tool execution."""
        proof_json = proof.model_dump(by_alias=True)
        encoded = base64.b64encode(json.dumps(proof_json).encode()).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._facilitator_url}/settle",
                json={"payment": encoded},
            )

        resp.raise_for_status()
        return resp.json()

    def queue_failed_settlement(self, proof: X402PaymentProof) -> None:
        """Queue a proof whose settlement failed for later retry."""
        self.pending_settlements.append(proof)
        logger.info("Queued failed settlement for retry (nonce=%s)", proof.payload.authorization.nonce)

    async def retry_pending_settlements(self) -> tuple[int, int]:
        """Retry all pending settlements. Returns (settled, failed) counts."""
        settled = 0
        failed = 0
        remaining: list[X402PaymentProof] = []
        for proof in self.pending_settlements:
            try:
                await self.settle_with_facilitator(proof)
                settled += 1
            except Exception:
                logger.warning("Retry settlement failed (nonce=%s)", proof.payload.authorization.nonce, exc_info=True)
                remaining.append(proof)
                failed += 1
        self.pending_settlements = remaining
        return settled, failed

    def build_payment_required(self, cost_value: str, resource: str, network: str = "base") -> X402PaymentRequired:
        """Build the payment requirements object for a 402 response."""
        return X402PaymentRequired(
            max_amount_required=cost_value,
            resource=resource,
            description="Tool execution payment",
            pay_to=self._merchant_address,
            asset=self._supported_networks.get(network, ""),
            network=network,
        )
