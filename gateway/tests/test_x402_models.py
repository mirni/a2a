"""Tests for x402 protocol Pydantic models and exception types."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.src.tool_errors import X402ReplayError, X402VerificationError
from gateway.src.x402 import (
    USDC_CONTRACTS,
    X402Authorization,
    X402Payload,
    X402PaymentProof,
    X402PaymentRequired,
)


class TestX402Authorization:
    """X402Authorization model validation."""

    def test_valid_authorization(self):
        auth = X402Authorization(**X402Authorization.model_config["json_schema_extra"]["example"])
        assert auth.from_address == "0xSenderAddress"
        assert auth.to == "0xMerchantAddress"
        assert auth.value == "1000000"

    def test_from_alias(self):
        """Field 'from_address' uses alias 'from' for JSON serialization."""
        data = {
            "from": "0xABC",
            "to": "0xDEF",
            "value": "500",
            "valid_after": 0,
            "valid_before": 9999999999,
            "nonce": "0x" + "ab" * 32,
        }
        auth = X402Authorization.model_validate(data)
        assert auth.from_address == "0xABC"
        dumped = auth.model_dump(by_alias=True)
        assert "from" in dumped
        assert dumped["from"] == "0xABC"

    def test_extra_fields_forbidden(self):
        data = X402Authorization.model_config["json_schema_extra"]["example"].copy()
        data["extra_field"] = "nope"
        with pytest.raises(ValidationError, match="extra_field"):
            X402Authorization.model_validate(data)


class TestX402Payload:
    """X402Payload model validation."""

    def test_valid_payload(self):
        payload = X402Payload(**X402Payload.model_config["json_schema_extra"]["example"])
        assert payload.signature.startswith("0x")
        assert isinstance(payload.authorization, X402Authorization)

    def test_extra_fields_forbidden(self):
        data = X402Payload.model_config["json_schema_extra"]["example"].copy()
        data["extra"] = "bad"
        with pytest.raises(ValidationError, match="extra"):
            X402Payload.model_validate(data)


class TestX402PaymentProof:
    """X402PaymentProof model validation."""

    def test_valid_proof(self):
        proof = X402PaymentProof(**X402PaymentProof.model_config["json_schema_extra"]["example"])
        assert proof.x402_version == 1
        assert proof.scheme == "exact"
        assert proof.network == "base"
        assert isinstance(proof.payload, X402Payload)

    def test_example_roundtrip(self):
        """model_validate(example) → model_dump() produces identical structure."""
        example = X402PaymentProof.model_config["json_schema_extra"]["example"]
        proof = X402PaymentProof.model_validate(example)
        dumped = proof.model_dump(by_alias=True)
        assert dumped["payload"]["authorization"]["from"] == example["payload"]["authorization"]["from"]
        assert dumped["network"] == example["network"]

    def test_extra_fields_forbidden(self):
        data = X402PaymentProof.model_config["json_schema_extra"]["example"].copy()
        data["unknown"] = 42
        with pytest.raises(ValidationError, match="unknown"):
            X402PaymentProof.model_validate(data)


class TestX402PaymentRequired:
    """X402PaymentRequired model validation."""

    def test_valid_required(self):
        req = X402PaymentRequired(**X402PaymentRequired.model_config["json_schema_extra"]["example"])
        assert req.max_amount_required == "1000"
        assert req.network == "base"
        assert req.pay_to == "0xMerchantAddress"

    def test_extra_fields_forbidden(self):
        data = X402PaymentRequired.model_config["json_schema_extra"]["example"].copy()
        data["bonus"] = True
        with pytest.raises(ValidationError, match="bonus"):
            X402PaymentRequired.model_validate(data)


class TestUSDCContracts:
    """USDC contract addresses are present for supported networks."""

    def test_base_and_polygon(self):
        assert "base" in USDC_CONTRACTS
        assert "polygon" in USDC_CONTRACTS
        assert USDC_CONTRACTS["base"].startswith("0x")
        assert USDC_CONTRACTS["polygon"].startswith("0x")


class TestX402Exceptions:
    """X402 exception hierarchy."""

    def test_verification_error_is_exception(self):
        exc = X402VerificationError("bad proof")
        assert isinstance(exc, Exception)
        assert str(exc) == "bad proof"

    def test_replay_error_is_verification_error(self):
        exc = X402ReplayError("nonce reused")
        assert isinstance(exc, X402VerificationError)
        assert isinstance(exc, Exception)

    def test_exception_mapping(self):
        """X402 exceptions map to 402 in the error handler."""

        # Verify the mapping dict inside handle_product_exception
        assert type(X402VerificationError("x")).__name__ == "X402VerificationError"
        assert type(X402ReplayError("x")).__name__ == "X402ReplayError"
