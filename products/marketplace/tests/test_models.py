"""Tests for marketplace data models."""

from src.models import (
    MatchPreference,
    PricingModel,
    PricingModelType,
    SLA,
    Service,
    ServiceCreate,
    ServiceMatch,
    ServiceSearchParams,
    ServiceStatus,
    SortBy,
)


class TestPricingModel:
    def test_defaults(self):
        p = PricingModel(model=PricingModelType.PER_CALL)
        assert p.cost == 0.0
        assert p.currency == "credits"

    def test_to_dict(self):
        p = PricingModel(model=PricingModelType.PER_CALL, cost=5.0, currency="usd")
        d = p.to_dict()
        assert d == {"model": "per_call", "cost": 5.0, "currency": "usd"}

    def test_from_dict(self):
        p = PricingModel.from_dict({"model": "subscription", "cost": 100.0, "currency": "credits"})
        assert p.model == PricingModelType.SUBSCRIPTION
        assert p.cost == 100.0

    def test_from_dict_defaults(self):
        p = PricingModel.from_dict({"model": "free"})
        assert p.cost == 0.0
        assert p.currency == "credits"

    def test_frozen(self):
        p = PricingModel(model=PricingModelType.FREE)
        try:
            p.cost = 10.0  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestSLA:
    def test_defaults(self):
        sla = SLA()
        assert sla.uptime == 99.0
        assert sla.max_latency_ms == 1000

    def test_to_dict(self):
        sla = SLA(uptime=99.99, max_latency_ms=50)
        d = sla.to_dict()
        assert d == {"uptime": 99.99, "max_latency_ms": 50}

    def test_from_dict(self):
        sla = SLA.from_dict({"uptime": 99.5, "max_latency_ms": 300})
        assert sla.uptime == 99.5
        assert sla.max_latency_ms == 300

    def test_from_dict_defaults(self):
        sla = SLA.from_dict({})
        assert sla.uptime == 99.0
        assert sla.max_latency_ms == 1000


class TestServiceStatus:
    def test_values(self):
        assert ServiceStatus.ACTIVE.value == "active"
        assert ServiceStatus.INACTIVE.value == "inactive"
        assert ServiceStatus.SUSPENDED.value == "suspended"


class TestPricingModelType:
    def test_values(self):
        assert PricingModelType.PER_CALL.value == "per_call"
        assert PricingModelType.PER_TOKEN.value == "per_token"
        assert PricingModelType.SUBSCRIPTION.value == "subscription"
        assert PricingModelType.FREE.value == "free"


class TestSortBy:
    def test_values(self):
        assert SortBy.TRUST_SCORE.value == "trust_score"
        assert SortBy.COST.value == "cost"
        assert SortBy.CREATED_AT.value == "created_at"
        assert SortBy.NAME.value == "name"


class TestMatchPreference:
    def test_values(self):
        assert MatchPreference.COST.value == "cost"
        assert MatchPreference.TRUST.value == "trust"
        assert MatchPreference.LATENCY.value == "latency"


class TestServiceCreate:
    def test_defaults(self):
        sc = ServiceCreate(
            provider_id="a", name="N", description="D", category="C"
        )
        assert sc.tools == []
        assert sc.pricing.model == PricingModelType.FREE
        assert sc.tags == []
        assert sc.endpoint == ""

    def test_full(self):
        sc = ServiceCreate(
            provider_id="a",
            name="N",
            description="D",
            category="C",
            tools=["t1"],
            pricing=PricingModel(model=PricingModelType.PER_CALL, cost=2.0),
            tags=["x"],
            endpoint="https://example.com",
        )
        assert sc.tools == ["t1"]
        assert sc.pricing.cost == 2.0


class TestService:
    def test_creation(self):
        svc = Service(
            id="svc-1",
            provider_id="a",
            name="N",
            description="D",
            category="C",
            tools=["t"],
            pricing=PricingModel(model=PricingModelType.FREE),
            sla=SLA(),
            tags=["tag"],
            status=ServiceStatus.ACTIVE,
        )
        assert svc.trust_score is None
        assert svc.metadata == {}


class TestServiceSearchParams:
    def test_defaults(self):
        p = ServiceSearchParams()
        assert p.query is None
        assert p.status == ServiceStatus.ACTIVE
        assert p.sort_by == SortBy.TRUST_SCORE
        assert p.limit == 20
        assert p.offset == 0

    def test_custom(self):
        p = ServiceSearchParams(
            query="test", category="data", min_trust_score=50.0
        )
        assert p.query == "test"
        assert p.min_trust_score == 50.0


class TestServiceMatch:
    def test_creation(self):
        svc = Service(
            id="x",
            provider_id="a",
            name="N",
            description="D",
            category="C",
            tools=[],
            pricing=PricingModel(model=PricingModelType.FREE),
            sla=SLA(),
            tags=[],
            status=ServiceStatus.ACTIVE,
        )
        m = ServiceMatch(service=svc, rank_score=85.5, match_reasons=["name_match"])
        assert m.rank_score == 85.5
        assert "name_match" in m.match_reasons
