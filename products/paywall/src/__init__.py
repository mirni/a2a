"""a2a_paywall: Connector subscription and paywall middleware for A2A commerce.

Gates MCP tool calls behind API key auth, tier-based access,
rate limits, and wallet-based billing.
"""

from .keys import InvalidKeyError, KeyManager
from .middleware import (
    InsufficientBalanceError,
    PaywallAuthError,
    PaywallError,
    PaywallMiddleware,
    RateLimitError,
    TierInsufficientError,
)
from .storage import PaywallStorage
from .tiers import TIER_CONFIGS, TierConfig, TierName, get_tier_config, tier_has_access
from .usage_api import UsageAPI

__all__ = [
    "PaywallAuthError",
    "TIER_CONFIGS",
    "InsufficientBalanceError",
    "InvalidKeyError",
    "KeyManager",
    "PaywallError",
    "PaywallMiddleware",
    "PaywallStorage",
    "RateLimitError",
    "TierConfig",
    "TierInsufficientError",
    "TierName",
    "UsageAPI",
    "get_tier_config",
    "tier_has_access",
]

__version__ = "0.1.0"
