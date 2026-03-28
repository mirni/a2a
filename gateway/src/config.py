"""Gateway configuration — centralizes hardcoded values.

All tunable parameters are defined here as a frozen dataclass,
loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayConfig:
    """Central configuration for the gateway."""

    # --- Batch endpoint ---
    max_batch_size: int = 10

    # --- Stripe/pricing ---
    credits_per_dollar: int = 100
    min_credits_purchase: int = 100
    max_credits_per_transaction: int = 1_000_000

    # --- Webhook delivery ---
    webhook_max_attempts: int = 3
    webhook_timeout_seconds: float = 10.0

    # --- MCP proxy ---
    mcp_process_timeout: float = 30.0
    mcp_shutdown_timeout: float = 5.0

    # --- Health monitor ---
    health_check_interval: int = 300
    health_check_timeout: float = 10.0

    # --- Subscription scheduler ---
    scheduler_interval: int = 300

    # --- Metrics middleware ---
    max_latency_samples: int = 1000

    # --- Tool defaults ---
    default_page_limit: int = 100
    budget_alert_threshold: float = 0.8
    volume_discount_tiers: dict[int, int] = field(default_factory=lambda: {
        100: 5,
        500: 10,
        1000: 15,
    })

    # --- x402 Protocol ---
    x402_enabled: bool = False
    x402_merchant_address: str = ""
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_supported_networks: str = "base,polygon"

    # --- Stripe checkout ---
    stripe_timeout: float = 15.0

    # --- Stripe packages (credits, price in cents) ---
    stripe_packages: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "starter": (1000, 1000),
        "growth": (5000, 4500),
        "scale": (25000, 20000),
        "enterprise": (100000, 75000),
    })

    @classmethod
    def from_env(cls) -> GatewayConfig:
        """Load configuration from environment variables with defaults."""
        return cls(
            max_batch_size=int(os.environ.get("A2A_MAX_BATCH_SIZE", "10")),
            credits_per_dollar=int(os.environ.get("A2A_CREDITS_PER_DOLLAR", "100")),
            min_credits_purchase=int(os.environ.get("A2A_MIN_CREDITS", "100")),
            max_credits_per_transaction=int(os.environ.get("A2A_MAX_CREDITS", "1000000")),
            webhook_max_attempts=int(os.environ.get("A2A_WEBHOOK_MAX_ATTEMPTS", "3")),
            webhook_timeout_seconds=float(os.environ.get("A2A_WEBHOOK_TIMEOUT", "10.0")),
            mcp_process_timeout=float(os.environ.get("A2A_MCP_TIMEOUT", "30.0")),
            health_check_interval=int(os.environ.get("A2A_HEALTH_INTERVAL", "300")),
            scheduler_interval=int(os.environ.get("A2A_SCHEDULER_INTERVAL", "300")),
            x402_enabled=os.environ.get("X402_ENABLED", "").lower() in ("1", "true", "yes"),
            x402_merchant_address=os.environ.get("X402_MERCHANT_ADDRESS", ""),
            x402_facilitator_url=os.environ.get(
                "X402_FACILITATOR_URL", "https://x402.org/facilitator"
            ),
            x402_supported_networks=os.environ.get("X402_SUPPORTED_NETWORKS", "base,polygon"),
        )
