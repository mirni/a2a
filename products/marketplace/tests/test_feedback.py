"""Tests for platform feedback / suggestion box (TDD).

Agents can submit suggestions and the platform can retrieve them.
"""

from __future__ import annotations

import pytest

from src.models import ServiceCreate
from src.marketplace import Marketplace, ServiceNotFoundError

pytestmark = pytest.mark.asyncio


class TestRateService:
    """Test service rating via Marketplace.rate_service."""

    async def test_rate_service(self, marketplace: Marketplace):
        svc = await marketplace.register_service(ServiceCreate(
            provider_id="provider-1",
            name="Test Service",
            description="A test service",
            category="testing",
        ))
        await marketplace.rate_service(svc.id, "reviewer-1", 5, "Excellent!")
        ratings = await marketplace.get_service_ratings(svc.id)
        assert ratings["count"] == 1
        assert ratings["average_rating"] == 5.0
        assert ratings["ratings"][0]["review"] == "Excellent!"

    async def test_rate_service_updates_existing(self, marketplace: Marketplace):
        svc = await marketplace.register_service(ServiceCreate(
            provider_id="provider-2",
            name="Update Test",
            description="Update",
            category="testing",
        ))
        await marketplace.rate_service(svc.id, "reviewer-1", 3)
        await marketplace.rate_service(svc.id, "reviewer-1", 5)
        ratings = await marketplace.get_service_ratings(svc.id)
        assert ratings["count"] == 1
        assert ratings["average_rating"] == 5.0

    async def test_rate_service_invalid_rating(self, marketplace: Marketplace):
        svc = await marketplace.register_service(ServiceCreate(
            provider_id="provider-3",
            name="Invalid Test",
            description="Invalid",
            category="testing",
        ))
        with pytest.raises(ValueError, match="between 1 and 5"):
            await marketplace.rate_service(svc.id, "reviewer-1", 6)

    async def test_rate_nonexistent_service(self, marketplace: Marketplace):
        with pytest.raises(ServiceNotFoundError):
            await marketplace.rate_service("nonexistent", "reviewer-1", 5)


class TestSuggestionBox:
    """Test platform suggestion/feedback submission."""

    async def test_submit_suggestion(self, marketplace: Marketplace):
        suggestion_id = await marketplace.submit_suggestion(
            agent_id="agent-fb",
            category="feature",
            message="Add dark mode support",
        )
        assert suggestion_id is not None

    async def test_get_suggestions(self, marketplace: Marketplace):
        await marketplace.submit_suggestion("agent-1", "feature", "Add search")
        await marketplace.submit_suggestion("agent-2", "bug", "Login broken")

        suggestions = await marketplace.get_suggestions()
        assert len(suggestions) == 2

    async def test_get_suggestions_by_category(self, marketplace: Marketplace):
        await marketplace.submit_suggestion("agent-1", "feature", "Add search")
        await marketplace.submit_suggestion("agent-2", "bug", "Login broken")
        await marketplace.submit_suggestion("agent-3", "feature", "Add filters")

        features = await marketplace.get_suggestions(category="feature")
        assert len(features) == 2
        assert all(s["category"] == "feature" for s in features)

    async def test_suggestion_has_required_fields(self, marketplace: Marketplace):
        await marketplace.submit_suggestion("agent-x", "feature", "Better docs")
        suggestions = await marketplace.get_suggestions()
        s = suggestions[0]
        assert "id" in s
        assert s["agent_id"] == "agent-x"
        assert s["category"] == "feature"
        assert s["message"] == "Better docs"
        assert "created_at" in s

    async def test_get_suggestions_respects_limit(self, marketplace: Marketplace):
        for i in range(5):
            await marketplace.submit_suggestion(f"agent-{i}", "feature", f"Idea {i}")
        suggestions = await marketplace.get_suggestions(limit=3)
        assert len(suggestions) == 3
