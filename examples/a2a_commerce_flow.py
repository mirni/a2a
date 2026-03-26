"""Example: Full agent-to-agent commerce flow.

Demonstrates the complete transaction lifecycle:
1. Agent B registers a service on the marketplace
2. Agent A discovers the service
3. Agent A pays Agent B via payment intent
4. Agent A uses the metered connector
5. Trust scores are computed from usage data

This is the wedge use case from our strategy:
"A trading agent discovers and pays for external services autonomously"
"""

import asyncio
import os
import sys

# Add package paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "products", "billing"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "products", "marketplace"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "products", "payments"))

from src.tracker import UsageTracker
from src.wallet import Wallet
from src.storage import StorageBackend as BillingStorage

# Marketplace imports use full module path
from src.marketplace import Marketplace
from src.storage import MarketplaceStorage
from src.models import (
    MatchPreference,
    PricingModel,
    PricingModelType,
    SLA,
    ServiceCreate,
)


async def main():
    # ========================================
    # 1. Initialize infrastructure
    # ========================================
    print("=== Initializing infrastructure ===")

    # Billing layer
    tracker = UsageTracker(storage="sqlite:///a2a_demo.db")
    await tracker.connect()
    wallet = Wallet(tracker.storage)

    # Marketplace
    mp_storage = MarketplaceStorage("sqlite:///a2a_marketplace.db")
    await mp_storage.connect()
    marketplace = Marketplace(storage=mp_storage)

    # Create agent wallets
    try:
        await wallet.create("trading-bot", initial_balance=500.0)
        await wallet.create("data-provider", initial_balance=0.0)
    except ValueError:
        pass

    print(f"  trading-bot balance: {await wallet.get_balance('trading-bot')} credits")
    print(f"  data-provider balance: {await wallet.get_balance('data-provider')} credits")

    # ========================================
    # 2. Provider registers a service
    # ========================================
    print("\n=== Provider registers service ===")

    service = await marketplace.register_service(ServiceCreate(
        provider_id="data-provider",
        name="Crypto Market Data",
        description="Real-time price feeds for BTC, ETH, SOL",
        category="market-data",
        tools=["get_price", "get_orderbook"],
        pricing=PricingModel(model=PricingModelType.PER_CALL, cost=2.0),
        sla=SLA(uptime=99.9, max_latency_ms=200),
        tags=["crypto", "real-time", "market-data"],
        endpoint="https://data-provider.example.com/mcp",
    ))
    print(f"  Registered: {service.name} (id={service.id})")
    print(f"  Pricing: {service.pricing.cost} credits/{service.pricing.model.value}")

    # ========================================
    # 3. Consumer discovers services
    # ========================================
    print("\n=== Consumer discovers services ===")

    matches = await marketplace.best_match(
        query="crypto price data",
        budget=5.0,
        prefer=MatchPreference.COST,
    )

    for i, m in enumerate(matches):
        print(f"  Match {i+1}: {m.service.name}")
        print(f"    Cost: {m.service.pricing.cost} credits/call")
        print(f"    Score: {m.rank_score:.1f}")
        print(f"    Reasons: {', '.join(m.match_reasons)}")

    selected = matches[0].service
    print(f"\n  Selected: {selected.name} @ {selected.endpoint}")

    # ========================================
    # 4. Consumer uses the metered service
    # ========================================
    print("\n=== Consumer uses metered service ===")

    @tracker.metered(cost=2, require_balance=True)
    async def get_price(agent_id: str, symbol: str) -> dict:
        """Simulated price query — 2 credits per call."""
        prices = {"BTC": 67420.50, "ETH": 3280.75, "SOL": 142.30}
        return {"symbol": symbol, "price": prices.get(symbol, 0.0), "provider": "data-provider"}

    # Trading bot makes 5 queries
    for symbol in ["BTC", "ETH", "SOL", "BTC", "ETH"]:
        result = await get_price(agent_id="trading-bot", symbol=symbol)
        print(f"  {result['symbol']}: ${result['price']:,.2f}")

    # ========================================
    # 5. Check balances after usage
    # ========================================
    print("\n=== Final balances ===")
    bot_balance = await wallet.get_balance("trading-bot")
    print(f"  trading-bot: {bot_balance} credits (spent {500.0 - bot_balance})")

    # Usage summary
    summary = await tracker.get_usage_summary("trading-bot")
    print(f"  trading-bot usage: {summary}")

    # ========================================
    # 6. Browse marketplace categories
    # ========================================
    print("\n=== Marketplace stats ===")
    count = await marketplace.count_services()
    categories = await marketplace.list_categories()
    print(f"  Active services: {count}")
    for cat in categories:
        print(f"  Category '{cat['category']}': {cat['count']} services")

    # Cleanup
    await tracker.close()
    await mp_storage.close()
    for f in ["a2a_demo.db", "a2a_marketplace.db"]:
        if os.path.exists(f):
            os.remove(f)


if __name__ == "__main__":
    asyncio.run(main())
