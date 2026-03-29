"""Tests for the ReputationPipeline."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from products.reputation.src.aggregator import Aggregator
from products.reputation.src.models import PipelineConfig, ProbeSchedule, ScanSchedule
from products.reputation.src.pipeline import ReputationPipeline
from products.reputation.src.probe_worker import ProbeWorker
from products.reputation.src.scan_worker import ScanWorker
from products.reputation.src.storage import ReputationStorage
from products.trust.src.models import (
    Server,
    TransportType,
)
from products.trust.src.storage import StorageBackend as TrustStorageBackend


@pytest_asyncio.fixture
async def pipeline_deps(tmp_path):
    """Create real storage backends and mock workers for pipeline testing."""
    trust_db = str(tmp_path / "trust.db")
    rep_db = str(tmp_path / "rep.db")

    trust_storage = TrustStorageBackend(dsn=f"sqlite:///{trust_db}")
    await trust_storage.connect()

    rep_storage = ReputationStorage(dsn=f"sqlite:///{rep_db}")
    await rep_storage.connect()

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({})
    mock_client.get = AsyncMock(return_value=mock_response)

    probe_worker = ProbeWorker(trust_storage=trust_storage, client=mock_client)
    scan_worker = ScanWorker(trust_storage=trust_storage, client=mock_client)
    aggregator = Aggregator(trust_storage=trust_storage)

    config = PipelineConfig(
        probe_schedule=ProbeSchedule(interval_seconds=60.0),
        scan_schedule=ScanSchedule(interval_seconds=300.0),
        cycle_interval=0.1,
    )

    pipeline = ReputationPipeline(
        trust_storage=trust_storage,
        reputation_storage=rep_storage,
        probe_worker=probe_worker,
        scan_worker=scan_worker,
        aggregator=aggregator,
        config=config,
    )

    yield pipeline, trust_storage, rep_storage

    await trust_storage.close()
    await rep_storage.close()


class TestPipelineAddTarget:
    @pytest.mark.asyncio
    async def test_add_target(self, pipeline_deps):
        pipeline, trust_storage, rep_storage = pipeline_deps

        target = await pipeline.add_target(url="https://example.com", server_id="svc-1")
        assert target.server_id == "svc-1"
        assert target.url == "https://example.com"
        assert target.probe_interval == 60.0

        stored = await rep_storage.get_target("svc-1")
        assert stored is not None

        server = await trust_storage.get_server("svc-1")
        assert server is not None
        assert server.url == "https://example.com"

    @pytest.mark.asyncio
    async def test_add_target_custom_intervals(self, pipeline_deps):
        pipeline, _, rep_storage = pipeline_deps

        target = await pipeline.add_target(
            url="https://example.com",
            server_id="svc-1",
            probe_interval=30.0,
            scan_interval=120.0,
        )
        assert target.probe_interval == 30.0
        assert target.scan_interval == 120.0

    @pytest.mark.asyncio
    async def test_add_target_existing_server(self, pipeline_deps):
        pipeline, trust_storage, _ = pipeline_deps

        server = Server(
            id="svc-1",
            name="existing",
            url="https://old.com",
            transport_type=TransportType.HTTP,
            registered_at=time.time(),
        )
        await trust_storage.register_server(server)

        target = await pipeline.add_target(url="https://example.com", server_id="svc-1")
        assert target.server_id == "svc-1"

    @pytest.mark.asyncio
    async def test_add_multiple_targets(self, pipeline_deps):
        pipeline, _, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.add_target(url="https://b.com", server_id="svc-2")
        await pipeline.add_target(url="https://c.com", server_id="svc-3")

        targets = await pipeline.list_targets()
        assert len(targets) == 3


class TestPipelineRemoveTarget:
    @pytest.mark.asyncio
    async def test_remove_existing(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        await pipeline.add_target(url="https://example.com", server_id="svc-1")
        removed = await pipeline.remove_target("svc-1")
        assert removed is True

        target = await pipeline.get_target("svc-1")
        assert target is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps
        removed = await pipeline.remove_target("nonexistent")
        assert removed is False


class TestPipelineRunOnce:
    @pytest.mark.asyncio
    async def test_run_once_probes_due_targets(self, pipeline_deps):
        pipeline, trust_storage, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.add_target(url="https://b.com", server_id="svc-2")

        now = time.time()
        result = await pipeline.run_once(now=now)

        assert result["probed"] == 2
        assert result["scanned"] == 2
        assert result["scored"] == 2

    @pytest.mark.asyncio
    async def test_run_once_skips_recently_probed(self, pipeline_deps):
        pipeline, _, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        now = time.time()
        await rep_storage.update_last_probed("svc-1", now)
        await rep_storage.update_last_scanned("svc-1", now)

        result = await pipeline.run_once(now=now)
        assert result["probed"] == 0
        assert result["scanned"] == 0
        assert result["scored"] == 0

    @pytest.mark.asyncio
    async def test_run_once_empty_targets(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps
        result = await pipeline.run_once()
        assert result["probed"] == 0
        assert result["scanned"] == 0
        assert result["scored"] == 0

    @pytest.mark.asyncio
    async def test_run_once_probe_failure_continues(self, pipeline_deps):
        pipeline, trust_storage, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.add_target(url="https://b.com", server_id="svc-2")

        original_probe = pipeline.probe_worker.probe

        async def failing_probe(server_id, url):
            if server_id == "svc-1":
                raise Exception("Probe failed")
            return await original_probe(server_id, url)

        pipeline.probe_worker.probe = failing_probe

        result = await pipeline.run_once()
        assert result["probed"] == 1

    @pytest.mark.asyncio
    async def test_run_once_updates_last_probed(self, pipeline_deps):
        pipeline, _, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        now = time.time()
        await pipeline.run_once(now=now)

        target = await rep_storage.get_target("svc-1")
        assert target.last_probed == now

    @pytest.mark.asyncio
    async def test_run_once_updates_last_scanned(self, pipeline_deps):
        pipeline, _, rep_storage = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        now = time.time()
        await pipeline.run_once(now=now)

        target = await rep_storage.get_target("svc-1")
        assert target.last_scanned == now


class TestPipelineRecomputeScores:
    @pytest.mark.asyncio
    async def test_recompute_specific_server(self, pipeline_deps):
        pipeline, trust_storage, _ = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.run_once()

        scores = await pipeline.recompute_scores(server_id="svc-1")
        assert len(scores) == 1
        assert scores[0].server_id == "svc-1"

    @pytest.mark.asyncio
    async def test_recompute_all(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.add_target(url="https://b.com", server_id="svc-2")
        await pipeline.run_once()

        scores = await pipeline.recompute_scores()
        assert len(scores) == 2


class TestPipelineStartStop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        assert pipeline.is_running is False
        await pipeline.start()
        assert pipeline.is_running is True
        await asyncio.sleep(0.05)
        await pipeline.stop()
        assert pipeline.is_running is False

    @pytest.mark.asyncio
    async def test_double_start(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        await pipeline.start()
        await pipeline.start()
        assert pipeline.is_running is True
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_runs_cycles(self, pipeline_deps):
        pipeline, trust_storage, _ = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.start()
        await asyncio.sleep(0.3)
        await pipeline.stop()

        probes = await trust_storage.get_probe_results("svc-1")
        assert len(probes) >= 1


class TestPipelineListGetTargets:
    @pytest.mark.asyncio
    async def test_list_targets(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        await pipeline.add_target(url="https://b.com", server_id="svc-2")

        targets = await pipeline.list_targets()
        assert len(targets) == 2

    @pytest.mark.asyncio
    async def test_get_target(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps

        await pipeline.add_target(url="https://a.com", server_id="svc-1")
        target = await pipeline.get_target("svc-1")
        assert target is not None
        assert target.url == "https://a.com"

    @pytest.mark.asyncio
    async def test_get_nonexistent_target(self, pipeline_deps):
        pipeline, _, _ = pipeline_deps
        target = await pipeline.get_target("nonexistent")
        assert target is None
