"""Observability middleware package.

This package is the post-P1-2 split of the legacy
``gateway/src/middleware.py`` 800-LOC god-module. Each concern lives
in its own submodule (``correlation``, ``security_headers``, …) and
must stay under 200 LOC; see
``gateway/tests/test_middleware_package_structure.py`` for the pin.

The entire public surface of the old module is re-exported here so
downstream importers (``gateway.src.app``, ``gateway.src.routes.*``,
tests, mutants, …) keep working unchanged:

    from gateway.src.middleware import (
        CorrelationIDMiddleware,
        MetricsMiddleware,
        ...
    )

When adding a new middleware submodule, also update ``__all__`` so
the structural test passes and external consumers can rely on
``dir(gateway.src.middleware)``.
"""

from __future__ import annotations

from .body_size import DEFAULT_MAX_BODY_BYTES, BodySizeLimitMiddleware
from .client_ip import ClientIpResolutionMiddleware
from .correlation import CorrelationIDMiddleware
from .https import HttpsEnforcementMiddleware
from .logging import JSONFormatter, setup_structured_logging
from .metrics import Metrics, MetricsMiddleware, metrics_handler
from .rate_limit import PublicRateLimitMiddleware
from .security_headers import SecurityHeadersMiddleware
from .timeout import DEFAULT_REQUEST_TIMEOUT_SECONDS, RequestTimeoutMiddleware
from .validation import AgentIdLengthMiddleware, EncodedPathRejectionMiddleware

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "AgentIdLengthMiddleware",
    "BodySizeLimitMiddleware",
    "ClientIpResolutionMiddleware",
    "CorrelationIDMiddleware",
    "EncodedPathRejectionMiddleware",
    "HttpsEnforcementMiddleware",
    "JSONFormatter",
    "Metrics",
    "MetricsMiddleware",
    "PublicRateLimitMiddleware",
    "RequestTimeoutMiddleware",
    "SecurityHeadersMiddleware",
    "metrics_handler",
    "setup_structured_logging",
]
