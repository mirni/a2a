"""Tests for gateway.src.anomaly — time-windowed anomaly detection."""

from __future__ import annotations

import logging
from unittest.mock import patch

from gateway.src.anomaly import AnomalyDetector


class TestAuthFailures:
    def test_below_threshold_no_warning(self, caplog):
        det = AnomalyDetector()

        with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
            for _ in range(4):
                det.record_auth_failure("agent-a")

        assert "ANOMALY" not in caplog.text

    def test_at_threshold_triggers_warning(self, caplog):
        det = AnomalyDetector()

        with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
            for _ in range(5):
                det.record_auth_failure("agent-a")

        assert "ANOMALY" in caplog.text
        assert "agent-a" in caplog.text
        assert "auth failures" in caplog.text

    def test_old_events_pruned(self, caplog):
        det = AnomalyDetector()
        base_time = 1000.0

        with patch("gateway.src.anomaly.time.monotonic") as mock_time:
            # Record 4 failures at t=1000
            mock_time.return_value = base_time
            for _ in range(4):
                det.record_auth_failure("agent-a")

            # Advance past 60s window, add 1 more — old ones pruned
            mock_time.return_value = base_time + 61
            with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
                det.record_auth_failure("agent-a")

        # Only 1 event in window — no warning
        assert "ANOMALY" not in caplog.text


class TestRateLimitHits:
    def test_below_threshold_no_warning(self, caplog):
        det = AnomalyDetector()

        with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
            for _ in range(9):
                det.record_rate_limit_hit("agent-b")

        assert "ANOMALY" not in caplog.text

    def test_at_threshold_triggers_warning(self, caplog):
        det = AnomalyDetector()

        with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
            for _ in range(10):
                det.record_rate_limit_hit("agent-b")

        assert "ANOMALY" in caplog.text
        assert "agent-b" in caplog.text
        assert "rate-limit" in caplog.text

    def test_old_events_pruned(self, caplog):
        det = AnomalyDetector()
        base_time = 1000.0

        with patch("gateway.src.anomaly.time.monotonic") as mock_time:
            # Record 9 hits at t=1000
            mock_time.return_value = base_time
            for _ in range(9):
                det.record_rate_limit_hit("agent-b")

            # Advance past 300s window
            mock_time.return_value = base_time + 301
            with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
                det.record_rate_limit_hit("agent-b")

        assert "ANOMALY" not in caplog.text


class TestMultiAgent:
    def test_agents_independent(self, caplog):
        """Agent A's failures don't affect agent B's count."""
        det = AnomalyDetector()

        with caplog.at_level(logging.WARNING, logger="a2a.anomaly"):
            for _ in range(4):
                det.record_auth_failure("agent-a")
            for _ in range(4):
                det.record_auth_failure("agent-b")

        # Neither hits the threshold of 5
        assert "ANOMALY" not in caplog.text
