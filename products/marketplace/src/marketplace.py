"""Marketplace API — register, discover, and match agent services."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    SLA,
    MatchPreference,
    PricingModel,
    Service,
    ServiceCreate,
    ServiceMatch,
    ServiceSearchParams,
    ServiceStatus,
    SortBy,
)
from .storage import MarketplaceStorage


class ServiceNotFoundError(Exception):
    """Raised when a service ID is not found."""

    def __init__(self, service_id: str) -> None:
        self.service_id = service_id
        super().__init__(f"Service not found: {service_id}")


class DuplicateServiceError(Exception):
    """Raised when provider tries to register a duplicate service name."""

    def __init__(self, provider_id: str, name: str) -> None:
        self.provider_id = provider_id
        self.name = name
        super().__init__(f"Provider '{provider_id}' already has service named '{name}'")


class Marketplace:
    """Agent-native service marketplace for discovery and matching.

    Args:
        storage: MarketplaceStorage instance.
        trust_provider: Optional callable(server_id) -> float|None for trust scores.
    """

    def __init__(
        self,
        storage: MarketplaceStorage,
        trust_provider: Any | None = None,
    ) -> None:
        self._storage = storage
        self._trust_provider = trust_provider

    @property
    def storage(self) -> MarketplaceStorage:
        """Public accessor for the marketplace storage backend."""
        return self._storage

    async def register_service(self, spec: ServiceCreate) -> Service:
        """Register a new service in the marketplace.

        Raises:
            DuplicateServiceError: If provider already has a service with this name.
            ValueError: If required fields are missing.
        """
        if not spec.name or not spec.name.strip():
            raise ValueError("Service name is required")
        if not spec.provider_id or not spec.provider_id.strip():
            raise ValueError("Provider ID is required")
        if not spec.category or not spec.category.strip():
            raise ValueError("Category is required")

        # Check for duplicate name per provider
        existing = await self._storage.get_services_by_provider(spec.provider_id)
        for svc in existing:
            if svc["name"] == spec.name and svc["status"] == "active":
                raise DuplicateServiceError(spec.provider_id, spec.name)

        service_id = await self._storage.insert_service(
            provider_id=spec.provider_id,
            name=spec.name,
            description=spec.description,
            category=spec.category,
            tools=spec.tools,
            pricing=spec.pricing.to_dict(),
            sla=spec.sla.to_dict(),
            tags=spec.tags,
            endpoint=spec.endpoint,
            metadata=spec.metadata,
        )
        raw = await self._storage.get_service(service_id)
        if raw is None:
            raise RuntimeError(f"Failed to retrieve newly created service {service_id}")
        return self._to_service(raw)

    async def get_service(self, service_id: str) -> Service:
        """Get a service by ID.

        Raises:
            ServiceNotFoundError: If service not found.
        """
        raw = await self._storage.get_service(service_id)
        if raw is None:
            raise ServiceNotFoundError(service_id)
        svc = self._to_service(raw)
        svc.trust_score = await self._get_trust_score(svc.provider_id)
        return svc

    async def update_service(
        self,
        service_id: str,
        *,
        requester_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        pricing: PricingModel | None = None,
        sla: SLA | None = None,
        tools: list[str] | None = None,
        tags: list[str] | None = None,
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Service:
        """Update an existing service.

        Args:
            service_id: The service to update.
            requester_id: If provided, verifies caller owns the service.

        Raises:
            ServiceNotFoundError: If service not found.
            PermissionError: If requester_id does not match provider_id.
        """
        if requester_id is not None:
            await self._check_ownership(service_id, requester_id)

        updated = await self._storage.update_service(
            service_id,
            name=name,
            description=description,
            category=category,
            pricing=pricing.to_dict() if pricing else None,
            sla=sla.to_dict() if sla else None,
            tools=tools,
            tags=tags,
            endpoint=endpoint,
            metadata=metadata,
        )
        if not updated:
            raise ServiceNotFoundError(service_id)
        raw = await self._storage.get_service(service_id)
        if raw is None:
            raise RuntimeError(f"Failed to retrieve updated service {service_id}")
        return self._to_service(raw)

    async def deactivate_service(self, service_id: str, *, requester_id: str | None = None) -> Service:
        """Deactivate a service listing.

        Args:
            service_id: The service to deactivate.
            requester_id: If provided, verifies caller owns the service.

        Raises:
            ServiceNotFoundError: If service not found.
            PermissionError: If requester_id does not match provider_id.
        """
        if requester_id is not None:
            await self._check_ownership(service_id, requester_id)

        updated = await self._storage.update_service(service_id, status="inactive")
        if not updated:
            raise ServiceNotFoundError(service_id)
        raw = await self._storage.get_service(service_id)
        if raw is None:
            raise RuntimeError(f"Failed to retrieve deactivated service {service_id}")
        return self._to_service(raw)

    async def _check_ownership(self, service_id: str, requester_id: str) -> None:
        """Verify that requester_id matches the service's provider_id."""
        raw = await self._storage.get_service(service_id)
        if raw is None:
            raise ServiceNotFoundError(service_id)
        if raw["provider_id"] != requester_id:
            raise PermissionError(f"Agent '{requester_id}' is not the owner of service '{service_id}'")

    async def search(self, params: ServiceSearchParams | None = None, **kwargs: Any) -> list[Service]:
        """Search for services with filters.

        Can be called with a ServiceSearchParams or keyword arguments.
        """
        if params is None:
            params = ServiceSearchParams(**kwargs)

        results = await self._storage.search_services(
            query=params.query,
            category=params.category,
            tags=params.tags,
            max_cost=params.max_cost,
            pricing_model=params.pricing_model.value if params.pricing_model else None,
            status=params.status.value,
            limit=params.limit,
            offset=params.offset,
        )

        services = [self._to_service(r) for r in results]

        # Attach trust scores
        for svc in services:
            svc.trust_score = await self._get_trust_score(svc.provider_id)

        # Filter by min_trust_score
        if params.min_trust_score is not None:
            services = [s for s in services if s.trust_score is not None and s.trust_score >= params.min_trust_score]

        # Sort
        services = self._sort_services(services, params.sort_by, params.sort_desc)

        return services

    async def best_match(
        self,
        query: str,
        budget: float | None = None,
        min_trust_score: float | None = None,
        prefer: MatchPreference = MatchPreference.TRUST,
        limit: int = 5,
    ) -> list[ServiceMatch]:
        """Find the best matching services for a query.

        Returns ranked list of matches with scores and reasons.
        """
        params = ServiceSearchParams(
            query=query,
            max_cost=budget,
            min_trust_score=min_trust_score,
            limit=limit * 3,  # over-fetch for ranking
        )
        candidates = await self.search(params)

        matches: list[ServiceMatch] = []
        for svc in candidates:
            score, reasons = self._compute_rank_score(svc, prefer, query)
            matches.append(ServiceMatch(service=svc, rank_score=score, match_reasons=reasons))

        matches.sort(key=lambda m: m.rank_score, reverse=True)
        return matches[:limit]

    async def list_categories(self) -> list[dict[str, Any]]:
        """List all active categories with service counts."""
        return await self._storage.list_categories()

    async def get_provider_services(self, provider_id: str) -> list[Service]:
        """Get all services for a provider."""
        results = await self._storage.get_services_by_provider(provider_id)
        return [self._to_service(r) for r in results]

    async def count_services(self, status: str = "active") -> int:
        """Count services with given status."""
        return await self._storage.count_services(status)

    def _to_service(self, raw: dict[str, Any]) -> Service:
        """Convert a storage dict to a Service model."""
        pricing_data = json.loads(raw.get("pricing_json", "{}"))
        sla_data = json.loads(raw.get("sla_json", "{}"))
        metadata = json.loads(raw.get("metadata_json", "{}"))

        return Service(
            id=raw["id"],
            provider_id=raw["provider_id"],
            name=raw["name"],
            description=raw["description"],
            category=raw["category"],
            tools=raw.get("tools", []),
            pricing=PricingModel.from_dict(pricing_data),
            sla=SLA.from_dict(sla_data),
            tags=raw.get("tags", []),
            status=ServiceStatus(raw["status"]),
            endpoint=raw.get("endpoint", ""),
            metadata=metadata,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )

    async def _get_trust_score(self, provider_id: str) -> float | None:
        """Get trust score for a provider."""
        if self._trust_provider is None:
            return None
        try:
            return await self._trust_provider(provider_id)
        except Exception:
            return None

    def _sort_services(self, services: list[Service], sort_by: SortBy, desc: bool) -> list[Service]:
        """Sort services by the given field."""
        if sort_by == SortBy.TRUST_SCORE:
            key = lambda s: s.trust_score if s.trust_score is not None else -1
        elif sort_by == SortBy.COST:
            key = lambda s: s.pricing.cost
        elif sort_by == SortBy.CREATED_AT:
            key = lambda s: s.created_at
        elif sort_by == SortBy.NAME:
            key = lambda s: s.name.lower()
        else:
            key = lambda s: s.created_at

        return sorted(services, key=key, reverse=desc)

    def _compute_rank_score(self, svc: Service, prefer: MatchPreference, query: str) -> tuple[float, list[str]]:
        """Compute a ranking score for best_match.

        Returns (score, reasons).
        """
        score = 0.0
        reasons: list[str] = []

        # Text relevance: name/description match
        q = query.lower()
        if q in svc.name.lower():
            score += 30.0
            reasons.append("name_match")
        if q in svc.description.lower():
            score += 15.0
            reasons.append("description_match")
        for tag in svc.tags:
            if q in tag.lower():
                score += 10.0
                reasons.append(f"tag_match:{tag}")
                break

        # Trust score component
        if svc.trust_score is not None:
            trust_weight = 2.0 if prefer == MatchPreference.TRUST else 1.0
            score += svc.trust_score * 0.3 * trust_weight
            if svc.trust_score >= 80:
                reasons.append("high_trust")

        # Cost component (lower cost = higher score)
        if svc.pricing.cost > 0:
            cost_weight = 2.0 if prefer == MatchPreference.COST else 1.0
            # Inverse cost scoring: max 20 points, decays with cost
            cost_score = max(0, 20.0 - svc.pricing.cost * 5.0) * cost_weight
            score += cost_score
            if svc.pricing.cost < 1.0:
                reasons.append("low_cost")
        else:
            score += 20.0  # Free is great
            reasons.append("free")

        # Latency component (lower = better)
        if prefer == MatchPreference.LATENCY:
            latency_score = max(0, 20.0 - svc.sla.max_latency_ms / 100.0)
            score += latency_score
            if svc.sla.max_latency_ms <= 200:
                reasons.append("low_latency")

        return score, reasons
