"""Example: Metered MCP connector with billing integration.

Demonstrates how to wire the billing layer into an MCP connector
so that every tool call is metered and charged to the calling agent.

This is the pattern for monetizing connectors as a service.
"""

import asyncio
import os
import sys

# Add package paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "products", "billing"))

from src.tracker import UsageTracker
from src.wallet import Wallet


async def main():
    # 1. Initialize billing
    tracker = UsageTracker(storage="sqlite:///example_billing.db")
    await tracker.connect()

    wallet = Wallet(tracker.storage)

    # 2. Create agent wallets
    try:
        await wallet.create("trading-bot-1", initial_balance=100.0)
        print("Created wallet for trading-bot-1 with 100 credits")
    except ValueError:
        print("Wallet already exists for trading-bot-1")

    try:
        await wallet.create("analytics-agent", initial_balance=50.0)
        print("Created wallet for analytics-agent with 50 credits")
    except ValueError:
        print("Wallet already exists for analytics-agent")

    # 3. Define metered tools (these would be your connector tools)
    @tracker.metered(cost=1)
    async def query_database(agent_id: str, sql: str) -> dict:
        """Simulated database query — costs 1 credit per call."""
        return {"rows": [{"id": 1, "name": "Example"}], "row_count": 1}

    @tracker.metered(cost=5, require_balance=True)
    async def create_payment(agent_id: str, amount: int, currency: str) -> dict:
        """Simulated payment creation — costs 5 credits, requires wallet balance."""
        return {"payment_id": "pay_123", "status": "created"}

    # 4. Agents use tools (billing happens automatically)
    print("\n--- Agent calls ---")

    result = await query_database(agent_id="trading-bot-1", sql="SELECT * FROM orders")
    print(f"query_database result: {result}")

    result = await create_payment(agent_id="trading-bot-1", amount=2000, currency="usd")
    print(f"create_payment result: {result}")

    result = await query_database(agent_id="analytics-agent", sql="SELECT COUNT(*) FROM users")
    print(f"query_database result: {result}")

    # 5. Check balances
    print("\n--- Balances ---")
    bal1 = await wallet.get_balance("trading-bot-1")
    bal2 = await wallet.get_balance("analytics-agent")
    print(f"trading-bot-1: {bal1} credits remaining")
    print(f"analytics-agent: {bal2} credits remaining")

    # 6. Check usage summary
    print("\n--- Usage ---")
    summary = await tracker.get_usage_summary("trading-bot-1")
    print(f"trading-bot-1 usage: {summary}")

    summary = await tracker.get_usage_summary("analytics-agent")
    print(f"analytics-agent usage: {summary}")

    # 7. Clean up
    await tracker.close()

    # Remove example database
    if os.path.exists("example_billing.db"):
        os.remove("example_billing.db")


if __name__ == "__main__":
    asyncio.run(main())
