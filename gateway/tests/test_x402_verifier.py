"""Tests for X402Verifier — local validation, nonce cache, facilitator calls."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.src.tool_errors import X402ReplayError, X402VerificationError
from gateway.src.x402 import (
    USDC_CONTRACTS,
    X402Authorization,
    X402Payload,
    X402PaymentProof,
    X402PaymentRequired,
    X402Verifier,
)


def _make_proof(
    *,
    to: str = "0xMerchant",
    value: str = "1000",
    valid_after: int = 0,
    valid_before: int | None = None,
    nonce: str = "0x" + "ab" * 32,
    network: str = "base",
) -> X402PaymentProof:
    if valid_before is None:
        valid_before = int(time.time()) + 600
    return X402PaymentProof(
        x402_version=1,
        scheme="exact",
        network=network,
        payload=X402Payload(
            signature="0x" + "ff" * 65,
            authorization=X402Authorization.model_validate(
                {
                    "from": "0xSender",
                    "to": to,
                    "value": value,
                    "valid_after": valid_after,
                    "valid_before": valid_before,
                    "nonce": nonce,
                }
            ),
        ),
    )


@pytest.fixture
def verifier():
    return X402Verifier(
        merchant_address="0xMerchant",
        facilitator_url="https://x402.org/facilitator",
        supported_networks={"base": USDC_CONTRACTS["base"]},
    )


class TestReplayDetection:
    def test_first_use_passes(self, verifier):
        verifier.check_replay("0xabc")  # should not raise

    def test_same_nonce_twice_raises(self, verifier):
        verifier.mark_nonce_used("0xabc")
        with pytest.raises(X402ReplayError, match="already used"):
            verifier.check_replay("0xabc")


class TestValidateProofLocally:
    def test_valid_proof_passes(self, verifier):
        proof = _make_proof()
        verifier.validate_proof_locally(proof, required_value="500")

    def test_wrong_recipient(self, verifier):
        proof = _make_proof(to="0xWrongAddress")
        with pytest.raises(X402VerificationError, match="recipient"):
            verifier.validate_proof_locally(proof, required_value="500")

    def test_insufficient_value(self, verifier):
        proof = _make_proof(value="100")
        with pytest.raises(X402VerificationError, match="Insufficient"):
            verifier.validate_proof_locally(proof, required_value="500")

    def test_expired_proof(self, verifier):
        proof = _make_proof(valid_before=int(time.time()) - 10)
        with pytest.raises(X402VerificationError, match="expired"):
            verifier.validate_proof_locally(proof, required_value="500")

    def test_not_yet_valid(self, verifier):
        proof = _make_proof(valid_after=int(time.time()) + 9999)
        with pytest.raises(X402VerificationError, match="not yet valid"):
            verifier.validate_proof_locally(proof, required_value="500")

    def test_unsupported_network(self, verifier):
        proof = _make_proof(network="ethereum")
        with pytest.raises(X402VerificationError, match="network"):
            verifier.validate_proof_locally(proof, required_value="500")

    def test_replay_nonce(self, verifier):
        proof = _make_proof()
        verifier.mark_nonce_used(proof.payload.authorization.nonce)
        with pytest.raises(X402ReplayError):
            verifier.validate_proof_locally(proof, required_value="500")


class TestBuildPaymentRequired:
    def test_returns_correct_structure(self, verifier):
        req = verifier.build_payment_required(cost_value="2000", resource="/v1/execute", network="base")
        assert isinstance(req, X402PaymentRequired)
        assert req.max_amount_required == "2000"
        assert req.pay_to == "0xMerchant"
        assert req.asset == USDC_CONTRACTS["base"]
        assert req.network == "base"
        assert req.resource == "/v1/execute"


class TestFacilitatorCalls:
    @pytest.mark.asyncio
    async def test_verify_success(self, verifier):
        proof = _make_proof()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"valid": True}

        with patch("gateway.src.x402.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            result = await verifier.verify_with_facilitator(proof)
            assert result == {"valid": True}

    @pytest.mark.asyncio
    async def test_verify_failure(self, verifier):
        proof = _make_proof()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Invalid signature"

        with patch("gateway.src.x402.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            with pytest.raises(X402VerificationError, match="Facilitator"):
                await verifier.verify_with_facilitator(proof)

    @pytest.mark.asyncio
    async def test_settle_success(self, verifier):
        proof = _make_proof()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"settled": True}

        with patch("gateway.src.x402.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            result = await verifier.settle_with_facilitator(proof)
            assert result == {"settled": True}
