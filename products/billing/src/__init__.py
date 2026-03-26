"""a2a_billing: Agent Billing & Usage Tracking Layer for A2A commerce.

Provides usage metering, credit-based wallets, rate policies,
and a billing event stream for MCP server monetization.
"""

from .events import BillingEventStream
from .policies import RateLimitExceededError, RatePolicyManager, SpendCapExceededError
from .storage import StorageBackend
from .tracker import UsageTracker, require_credits
from .wallet import InsufficientCreditsError, Wallet, WalletNotFoundError

__all__ = [
    "BillingEventStream",
    "InsufficientCreditsError",
    "RateLimitExceededError",
    "RatePolicyManager",
    "SpendCapExceededError",
    "StorageBackend",
    "UsageTracker",
    "Wallet",
    "WalletNotFoundError",
    "require_credits",
]

__version__ = "0.1.0"
