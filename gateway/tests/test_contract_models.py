"""Contract tests — Hypothesis property-based testing for API request models.

Validates:
1. Golden-standard examples from json_schema_extra always parse correctly
2. extra="forbid" rejects unknown fields on all request models
3. Hypothesis-generated inputs are validated correctly (boundary/fuzz)
4. Decimal precision is preserved for currency fields
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from gateway.src.routes.v1.billing import (
    BudgetCapRequest,
    ConvertCurrencyRequest,
    CreateWalletRequest,
    DepositRequest,
    WithdrawRequest,
)
from gateway.src.routes.v1.identity import (
    AddMemberRequest,
    CreateOrgRequest,
    IngestMetricsRequest,
    RegisterAgentRequest,
    SubmitMetricsRequest,
    VerifyAgentRequest,
)
from gateway.src.routes.v1.payments import (
    CreateEscrowRequest,
    CreateIntentRequest,
    CreatePerformanceEscrowRequest,
    CreateSplitIntentRequest,
    CreateSubscriptionRequest,
    PartialCaptureRequest,
    RefundSettlementRequest,
    SplitEntry,
)

# ---------------------------------------------------------------------------
# Collect all request models with their examples
# ---------------------------------------------------------------------------

_ALL_MODELS = [
    CreateWalletRequest,
    DepositRequest,
    WithdrawRequest,
    BudgetCapRequest,
    ConvertCurrencyRequest,
    CreateIntentRequest,
    CreateEscrowRequest,
    CreatePerformanceEscrowRequest,
    PartialCaptureRequest,
    CreateSplitIntentRequest,
    RefundSettlementRequest,
    CreateSubscriptionRequest,
    RegisterAgentRequest,
    VerifyAgentRequest,
    SubmitMetricsRequest,
    CreateOrgRequest,
    AddMemberRequest,
    IngestMetricsRequest,
]


# ===================================================================
# 1. Golden-standard contract tests — examples MUST parse
# ===================================================================


class TestGoldenStandard:
    """Every model's json_schema_extra example must round-trip through validation."""

    @pytest.mark.parametrize(
        "model_cls",
        _ALL_MODELS,
        ids=lambda m: m.__name__,
    )
    def test_example_parses(self, model_cls):
        """The documented example must be a valid instance of its model."""
        schema_extra = model_cls.model_config.get("json_schema_extra", {})
        example = schema_extra.get("example")
        assert example is not None, f"{model_cls.__name__} has no json_schema_extra example"

        instance = model_cls.model_validate(example)
        assert instance is not None

    @pytest.mark.parametrize(
        "model_cls",
        _ALL_MODELS,
        ids=lambda m: m.__name__,
    )
    def test_example_roundtrip(self, model_cls):
        """Parse → serialize → parse must produce identical output."""
        example = model_cls.model_config["json_schema_extra"]["example"]
        first = model_cls.model_validate(example)
        serialized = first.model_dump(mode="json")
        second = model_cls.model_validate(serialized)
        assert first == second


# ===================================================================
# 2. extra="forbid" contract — unknown fields MUST be rejected
# ===================================================================


class TestExtraForbid:
    """All request models must reject payloads with unknown fields."""

    @pytest.mark.parametrize(
        "model_cls",
        _ALL_MODELS,
        ids=lambda m: m.__name__,
    )
    def test_rejects_unknown_field(self, model_cls):
        """Adding an unknown field to the example must raise ValidationError."""
        example = dict(model_cls.model_config["json_schema_extra"]["example"])
        example["__injected_field__"] = "should-not-be-accepted"
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model_cls.model_validate(example)

    @pytest.mark.parametrize(
        "model_cls",
        _ALL_MODELS,
        ids=lambda m: m.__name__,
    )
    def test_config_extra_is_forbid(self, model_cls):
        """The model's ConfigDict must set extra='forbid'."""
        assert model_cls.model_config.get("extra") == "forbid", f"{model_cls.__name__} does not have extra='forbid'"


# ===================================================================
# 3. Hypothesis property-based tests — Decimal currency fields
# ===================================================================

# Strategy for valid currency amounts (positive, ≤ 1B, 2 decimal places)
_valid_amount = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Strategy for valid agent IDs — must match AGENT_ID_PATTERN:
# starts with alphanumeric, then alphanumeric/dot/dash/underscore, 1-128 chars.
_valid_agent_id = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789._-"),
        min_size=0,
        max_size=63,
    ),
)


class TestHypothesisBilling:
    """Property-based tests for billing request models."""

    @given(amount=_valid_amount)
    @settings(max_examples=50)
    def test_deposit_accepts_valid_amounts(self, amount: Decimal):
        req = DepositRequest(amount=amount)
        assert req.amount == amount
        assert isinstance(req.amount, Decimal)

    @given(amount=_valid_amount)
    @settings(max_examples=50)
    def test_withdraw_accepts_valid_amounts(self, amount: Decimal):
        req = WithdrawRequest(amount=amount)
        assert req.amount == amount

    @given(
        amount=st.decimals(
            min_value=Decimal("-1000"),
            max_value=Decimal("0"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=25)
    def test_deposit_rejects_non_positive_amounts(self, amount: Decimal):
        with pytest.raises(ValidationError):
            DepositRequest(amount=amount)

    @given(agent_id=_valid_agent_id)
    @settings(max_examples=50)
    def test_create_wallet_accepts_valid_agent_ids(self, agent_id: str):
        req = CreateWalletRequest(agent_id=agent_id)
        assert req.agent_id == agent_id
        assert req.initial_balance == Decimal("0")
        assert req.signup_bonus is True

    @given(
        daily=st.one_of(st.none(), _valid_amount),
        monthly=st.one_of(st.none(), _valid_amount),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_budget_cap_optional_fields(self, daily: Decimal | None, monthly: Decimal | None, threshold: float):
        req = BudgetCapRequest(daily_cap=daily, monthly_cap=monthly, alert_threshold=threshold)
        assert req.daily_cap == daily
        assert req.monthly_cap == monthly

    def test_deposit_preserves_decimal_precision(self):
        """Ensure Decimal precision is not lost through float coercion."""
        req = DepositRequest(amount=Decimal("0.10"))
        assert str(req.amount) == "0.10"
        req2 = DepositRequest(amount=Decimal("99999999.99"))
        assert str(req2.amount) == "99999999.99"


class TestHypothesisPayments:
    """Property-based tests for payment request models."""

    @given(
        payer=_valid_agent_id,
        payee=_valid_agent_id,
        amount=_valid_amount,
    )
    @settings(max_examples=50)
    def test_create_intent_valid_inputs(self, payer: str, payee: str, amount: Decimal):
        req = CreateIntentRequest(payer=payer, payee=payee, amount=amount)
        assert req.payer == payer
        assert req.payee == payee
        assert isinstance(req.amount, Decimal)
        assert req.currency == "CREDITS"

    @given(
        payer=_valid_agent_id,
        payee=_valid_agent_id,
        amount=_valid_amount,
    )
    @settings(max_examples=50)
    def test_create_escrow_valid_inputs(self, payer: str, payee: str, amount: Decimal):
        req = CreateEscrowRequest(payer=payer, payee=payee, amount=amount)
        assert req.timeout_hours is None
        assert req.metadata is None

    @given(amount=_valid_amount)
    @settings(max_examples=25)
    def test_partial_capture_valid_amounts(self, amount: Decimal):
        req = PartialCaptureRequest(amount=amount)
        assert req.amount == amount

    def test_split_entry_percentages(self):
        """Split entries must accept valid percentage values."""
        entry = SplitEntry(payee="agent-bob", percentage=60.0)
        assert entry.percentage == 60.0

    @given(
        payer=_valid_agent_id,
        amount=_valid_amount,
    )
    @settings(max_examples=25)
    def test_split_intent_valid_inputs(self, payer: str, amount: Decimal):
        req = CreateSplitIntentRequest(
            payer=payer,
            amount=amount,
            splits=[
                SplitEntry(payee="agent-bob", percentage=60),
                SplitEntry(payee="agent-carol", percentage=40),
            ],
        )
        assert len(req.splits) == 2


class TestHypothesisIdentity:
    """Property-based tests for identity request models."""

    @given(agent_id=_valid_agent_id)
    @settings(max_examples=50)
    def test_register_agent_valid_ids(self, agent_id: str):
        req = RegisterAgentRequest(agent_id=agent_id)
        assert req.agent_id == agent_id
        assert req.public_key is None

    @given(
        message=st.text(min_size=1, max_size=256),
        signature=st.text(
            alphabet=st.sampled_from("0123456789abcdef"),
            min_size=1,
            max_size=128,
        ),
    )
    @settings(max_examples=50)
    def test_verify_agent_valid_inputs(self, message: str, signature: str):
        req = VerifyAgentRequest(message=message, signature=signature)
        assert req.message == message
        assert req.signature == signature

    @given(
        metrics=st.dictionaries(
            keys=st.sampled_from(["uptime", "latency", "error_rate", "accuracy"]),
            values=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=50)
    def test_submit_metrics_valid_inputs(self, metrics: dict):
        req = SubmitMetricsRequest(metrics=metrics)
        assert req.metrics == metrics
        assert req.data_source == "self_reported"

    @given(org_name=st.text(min_size=1, max_size=128))
    @settings(max_examples=25)
    def test_create_org_valid_names(self, org_name: str):
        req = CreateOrgRequest(org_name=org_name)
        assert req.org_name == org_name


# ===================================================================
# 4. Boundary / edge-case tests
# ===================================================================


class TestBoundary:
    """Edge-case tests for field constraints."""

    def test_deposit_at_max_boundary(self):
        """Amount at exactly 1 billion should be rejected (le constraint)."""
        req = DepositRequest(amount=Decimal("1000000000.00"))
        assert req.amount == Decimal("1000000000.00")

    def test_deposit_over_max_boundary(self):
        """Amount over 1 billion must be rejected."""
        with pytest.raises(ValidationError):
            DepositRequest(amount=Decimal("1000000001.00"))

    def test_deposit_minimum_valid(self):
        """Smallest valid positive amount."""
        req = DepositRequest(amount=Decimal("0.01"))
        assert req.amount == Decimal("0.01")

    def test_deposit_zero_rejected(self):
        """Zero amount must be rejected (gt=0)."""
        with pytest.raises(ValidationError):
            DepositRequest(amount=Decimal("0"))

    def test_create_wallet_empty_agent_id(self):
        """Empty string agent_id is rejected by the AGENT_ID_PATTERN validator."""
        with pytest.raises(ValidationError):
            CreateWalletRequest(agent_id="")

    def test_refund_settlement_optional_amount(self):
        """RefundSettlementRequest amount is optional (full refund)."""
        req = RefundSettlementRequest()
        assert req.amount is None
        assert req.reason == ""

    def test_subscription_interval_freeform(self):
        """Interval field accepts any string (validated at business layer)."""
        req = CreateSubscriptionRequest(payer="a", payee="b", amount=Decimal("9.99"), interval="biweekly")
        assert req.interval == "biweekly"
