"""a2a-reputation: Reputation Data Collection Pipeline.

Continuously monitors registered servers via health probes and security scans,
then aggregates results into trust scores using the trust scoring engine.
"""

from .aggregator import Aggregator
from .models import PipelineConfig, ProbeSchedule, ProbeTarget, ScanSchedule
from .pipeline import ReputationPipeline
from .probe_worker import ProbeWorker
from .scan_worker import ScanWorker
from .storage import ReputationStorage

__all__ = [
    "Aggregator",
    "PipelineConfig",
    "ProbeSchedule",
    "ProbeTarget",
    "ProbeWorker",
    "ReputationPipeline",
    "ReputationStorage",
    "ScanSchedule",
    "ScanWorker",
]

__version__ = "0.1.0"
