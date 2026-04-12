"""Shared fixtures for marketplace tests."""

from __future__ import annotations

import os
import sys

import pytest

# Route shared_src registration through the single base module.
_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "tests"))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from _conftest_base import register_shared_src  # noqa: E402

register_shared_src(__file__)

from src.marketplace import Marketplace  # noqa: E402
from src.models import SLA, PricingModel, PricingModelType, ServiceCreate  # noqa: E402
from src.storage import MarketplaceStorage  # noqa: E402


@pytest.fixture
async def storage():
    s = MarketplaceStorage(dsn="sqlite:///:memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def marketplace(storage):
    return Marketplace(storage=storage)


@pytest.fixture
async def marketplace_with_trust(storage):
    """Marketplace with a mock trust provider."""
    scores = {}

    async def trust_provider(provider_id: str) -> float | None:
        return scores.get(provider_id)

    mp = Marketplace(storage=storage, trust_provider=trust_provider)
    mp._trust_scores = scores  # expose for test manipulation
    return mp


def make_service(
    provider_id: str = "agent-1",
    name: str = "Test Service",
    description: str = "A test service",
    category: str = "testing",
    tools: list[str] | None = None,
    cost: float = 1.0,
    pricing_model: PricingModelType = PricingModelType.PER_CALL,
    tags: list[str] | None = None,
    endpoint: str = "https://example.com/mcp",
    uptime: float = 99.9,
    max_latency_ms: int = 200,
) -> ServiceCreate:
    return ServiceCreate(
        provider_id=provider_id,
        name=name,
        description=description,
        category=category,
        tools=tools or ["tool_a", "tool_b"],
        pricing=PricingModel(model=pricing_model, cost=cost),
        sla=SLA(uptime=uptime, max_latency_ms=max_latency_ms),
        tags=tags or ["test"],
        endpoint=endpoint,
    )
