"""Tests for the Aggregator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from products.reputation.src.aggregator import Aggregator
from products.reputation.src.models import ProbeTarget
from products.reputation.src.storage import ReputationStorage
from products.trust.src.models import (
    ProbeResult as TrustProbeResult,
    SecurityScan as TrustSecurityScan,
    TrustScore,
    Window,
)


def make_probe(server_id: str, timestamp: float, status_code: int = 200,
               latency_ms: float = 50.0) -> TrustProbeResult:
    return TrustProbeResult(
        server_id=server_id,
        timestamp=timestamp,
        latency_ms=latency_ms,
        status_code=status_code,
    )


def make_scan(server_id: str, timestamp: float, tls: bool = True,
              auth: bool = True) -> TrustSecurityScan:
    return TrustSecurityScan(
        server_id=server_id,
        timestamp=timestamp,
        tls_enabled=tls,
        auth_required=auth,
        input_validation_score=80.0,
        cve_count=0,
    )


class TestAggregatorRecomputeScore:
    @pytest.mark.asyncio
    async def test_recompute_with_probes_and_scans(self):
        now = time.time()
        probes = [make_probe("svc-1", now - 100)]
        scans = [make_scan("svc-1", now - 200)]

        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=probes)
        mock_storage.get_security_scans = AsyncMock(return_value=scans)
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        score = await agg.recompute_score("svc-1", now=now)

        assert score.server_id == "svc-1"
        assert score.composite_score >= 0.0
        assert score.confidence > 0.0
        mock_storage.store_trust_score.assert_called_once()

    @pytest.mark.asyncio
    async def test_recompute_with_no_data(self):
        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=[])
        mock_storage.get_security_scans = AsyncMock(return_value=[])
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        score = await agg.recompute_score("svc-empty", now=time.time())

        assert score.server_id == "svc-empty"
        assert score.composite_score == 0.0
        assert score.confidence == 0.0

    @pytest.mark.asyncio
    async def test_recompute_with_window(self):
        now = time.time()
        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=[])
        mock_storage.get_security_scans = AsyncMock(return_value=[])
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        score = await agg.recompute_score("svc-1", window=Window.D7, now=now)

        assert score.window == Window.D7
        call_args = mock_storage.get_probe_results.call_args
        assert call_args[1]["since"] == now - 604800

    @pytest.mark.asyncio
    async def test_recompute_stores_result(self):
        now = time.time()
        probes = [make_probe("svc-1", now - 60, latency_ms=100.0)]

        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=probes)
        mock_storage.get_security_scans = AsyncMock(return_value=[])
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        await agg.recompute_score("svc-1", now=now)

        stored_score = mock_storage.store_trust_score.call_args[0][0]
        assert stored_score.server_id == "svc-1"
        assert stored_score.composite_score > 0.0

    @pytest.mark.asyncio
    async def test_recompute_high_reliability(self):
        now = time.time()
        probes = [make_probe("svc-1", now - i * 60) for i in range(10)]
        scans = [make_scan("svc-1", now - 100)]

        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=probes)
        mock_storage.get_security_scans = AsyncMock(return_value=scans)
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        score = await agg.recompute_score("svc-1", now=now)

        assert score.reliability_score > 50.0
        assert score.confidence == 1.0

    @pytest.mark.asyncio
    async def test_recompute_low_reliability(self):
        now = time.time()
        probes = [make_probe("svc-1", now - i * 60, status_code=500) for i in range(10)]

        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=probes)
        mock_storage.get_security_scans = AsyncMock(return_value=[])
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        score = await agg.recompute_score("svc-1", now=now)

        assert score.reliability_score < 60.0


class TestAggregatorRecomputeScores:
    @pytest.mark.asyncio
    async def test_recompute_multiple(self):
        now = time.time()
        mock_storage = AsyncMock()
        mock_storage.get_probe_results = AsyncMock(return_value=[])
        mock_storage.get_security_scans = AsyncMock(return_value=[])
        mock_storage.store_trust_score = AsyncMock(return_value=1)

        agg = Aggregator(trust_storage=mock_storage)
        scores = await agg.recompute_scores(["svc-1", "svc-2", "svc-3"], now=now)

        assert len(scores) == 3
        assert scores[0].server_id == "svc-1"
        assert scores[1].server_id == "svc-2"
        assert scores[2].server_id == "svc-3"

    @pytest.mark.asyncio
    async def test_recompute_empty_list(self):
        mock_storage = AsyncMock()
        agg = Aggregator(trust_storage=mock_storage)
        scores = await agg.recompute_scores([], now=time.time())
        assert scores == []


class TestAggregatorRecomputeAllActive:
    @pytest.mark.asyncio
    async def test_recompute_all_active(self):
        now = time.time()
        mock_trust_storage = AsyncMock()
        mock_trust_storage.get_probe_results = AsyncMock(return_value=[])
        mock_trust_storage.get_security_scans = AsyncMock(return_value=[])
        mock_trust_storage.store_trust_score = AsyncMock(return_value=1)

        mock_rep_storage = AsyncMock()
        mock_rep_storage.list_targets = AsyncMock(return_value=[
            ProbeTarget(server_id="svc-1", url="https://a.com"),
            ProbeTarget(server_id="svc-2", url="https://b.com"),
        ])

        agg = Aggregator(trust_storage=mock_trust_storage)
        scores = await agg.recompute_all_active(mock_rep_storage, now=now)

        assert len(scores) == 2

    @pytest.mark.asyncio
    async def test_recompute_all_active_empty(self):
        mock_trust_storage = AsyncMock()
        mock_rep_storage = AsyncMock()
        mock_rep_storage.list_targets = AsyncMock(return_value=[])

        agg = Aggregator(trust_storage=mock_trust_storage)
        scores = await agg.recompute_all_active(mock_rep_storage, now=time.time())
        assert scores == []
