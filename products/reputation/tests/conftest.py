"""Shared test fixtures for the reputation pipeline tests."""

from __future__ import annotations

import os
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Register shared_src so cross-product imports (db_security) resolve
_shared_src_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src")
)
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

from products.reputation.src.models import (
    PipelineConfig,
    ProbeErrorType,
    ProbeSchedule,
    ProbeTarget,
    ScanResult,
    ScanSchedule,
    SecurityHeaders,
    TLSInfo,
)
from products.reputation.src.storage import ReputationStorage
from products.reputation.src.probe_worker import ProbeWorker
from products.reputation.src.scan_worker import ScanWorker
from products.reputation.src.aggregator import Aggregator
from products.reputation.src.pipeline import ReputationPipeline

from products.trust.src.storage import StorageBackend as TrustStorageBackend
from products.trust.src.models import (
    ProbeResult as TrustProbeResult,
    SecurityScan as TrustSecurityScan,
    Server as TrustServer,
    TransportType,
    TrustScore,
    Window,
)


@pytest_asyncio.fixture
async def trust_storage(tmp_path):
    """Create a real trust StorageBackend with a temp DB."""
    db_path = str(tmp_path / "trust_test.db")
    storage = TrustStorageBackend(dsn=f"sqlite:///{db_path}")
    await storage.connect()
    yield storage
    await storage.close()


@pytest_asyncio.fixture
async def reputation_storage(tmp_path):
    """Create a real ReputationStorage with a temp DB."""
    db_path = str(tmp_path / "reputation_test.db")
    storage = ReputationStorage(dsn=f"sqlite:///{db_path}")
    await storage.connect()
    yield storage
    await storage.close()


@pytest.fixture
def mock_trust_storage():
    """Create a mock trust storage with all required async methods."""
    mock = AsyncMock()
    mock.store_probe_result = AsyncMock(return_value=1)
    mock.store_security_scan = AsyncMock(return_value=1)
    mock.store_trust_score = AsyncMock(return_value=1)
    mock.get_probe_results = AsyncMock(return_value=[])
    mock.get_security_scans = AsyncMock(return_value=[])
    mock.get_server = AsyncMock(return_value=None)
    mock.register_server = AsyncMock()
    mock.update_server_last_probed = AsyncMock()
    mock.get_latest_trust_score = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def sample_probe_target():
    """Create a sample ProbeTarget."""
    return ProbeTarget(
        server_id="svc-test",
        url="https://example.com/health",
        probe_interval=300.0,
        scan_interval=3600.0,
    )


@pytest.fixture
def sample_trust_probe_result():
    """Create a sample trust ProbeResult."""
    return TrustProbeResult(
        server_id="svc-test",
        timestamp=time.time(),
        latency_ms=50.0,
        status_code=200,
        error=None,
    )


@pytest.fixture
def sample_trust_security_scan():
    """Create a sample trust SecurityScan."""
    return TrustSecurityScan(
        server_id="svc-test",
        timestamp=time.time(),
        tls_enabled=True,
        auth_required=True,
        input_validation_score=80.0,
        cve_count=0,
    )


@pytest.fixture
def pipeline_config():
    """Create a PipelineConfig for testing."""
    return PipelineConfig(
        probe_schedule=ProbeSchedule(interval_seconds=60.0, timeout_seconds=5.0),
        scan_schedule=ScanSchedule(interval_seconds=300.0, timeout_seconds=10.0),
        cycle_interval=1.0,
    )
