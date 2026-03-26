"""Workflow: Trading Agent — discover, price check, execute.

Demonstrates a trading agent that:
1. Discovers available services via the marketplace
2. Checks pricing for tools it needs
3. Executes billing and payment operations

Usage:
    # Start the gateway first:
    python gateway/main.py

    # Then run this example:
    python examples/workflow_trading_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.src.a2a_client import A2AClient


async def main() -> None:
    base_url = os.environ.get("A2A_GATEWAY_URL", "http://localhost:8000")
    api_key = os.environ.get("A2A_API_KEY", "")

    if not api_key:
        print("Set A2A_API_KEY environment variable first.")
        print("Create a key via the gateway's key management.")
        return

    async with A2AClient(base_url=base_url, api_key=api_key) as client:
        # Step 1: Health check
        print("=== Step 1: Health Check ===")
        health = await client.health()
        print(f"Gateway status: {health.status}, version: {health.version}")
        print(f"Available tools: {health.tools}")

        # Step 2: Browse pricing catalog
        print("\n=== Step 2: Pricing Catalog ===")
        tools = await client.pricing()
        for tool in tools[:5]:
            cost = tool.pricing.get("per_call", 0)
            print(f"  {tool.name} ({tool.service}) - {cost} credits/call [{tool.tier_required}]")

        # Step 3: Check wallet balance
        print("\n=== Step 3: Check Balance ===")
        try:
            balance = await client.get_balance("trading-agent-1")
            print(f"Balance: {balance} credits")
        except Exception as e:
            print(f"Balance check: {e}")

        # Step 4: Search marketplace for services
        print("\n=== Step 4: Search Marketplace ===")
        services = await client.search_services(query="data")
        print(f"Found {len(services)} services matching 'data'")
        for svc in services[:3]:
            print(f"  - {svc['name']}: {svc['description']}")

        # Step 5: Get usage summary
        print("\n=== Step 5: Usage Summary ===")
        try:
            usage = await client.get_usage_summary("trading-agent-1")
            print(f"Total cost: {usage.get('total_cost', 0)} credits")
            print(f"Total calls: {usage.get('total_calls', 0)}")
        except Exception as e:
            print(f"Usage summary: {e}")

        print("\n=== Workflow Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
