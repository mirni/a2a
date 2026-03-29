"""Shared fixtures for marketplace tests."""

from __future__ import annotations

import os
import sys
import types

import pytest

# Register shared_src so cross-product imports (db_security) resolve
_shared_src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src"))
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

from src.marketplace import Marketplace
from src.models import SLA, PricingModel, PricingModelType, ServiceCreate
from src.storage import MarketplaceStorage


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
