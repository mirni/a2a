"""Example: Multi-agent workflow with billing and rate policies.

Demonstrates a scenario where multiple agents use shared tools
with different rate limits and spend caps, showing how the billing
layer enforces policies per-agent.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "products", "billing"))

from src.policies import RateLimitExceededError, RatePolicyManager, SpendCapExceededError
from src.tracker import UsageTracker
from src.wallet import Wallet


async def main():
    tracker = UsageTracker(storage="sqlite:///multi_agent.db")
    await tracker.connect()

    wallet = Wallet(tracker.storage)
    policies = RatePolicyManager(tracker.storage)

    # Setup: two agents with different tiers
    try:
        await wallet.create("free-agent", initial_balance=10.0)
        await wallet.create("pro-agent", initial_balance=1000.0)
    except ValueError:
        pass

    # Free tier: 5 calls/min, 10 credits/day
    await policies.set_policy("free-agent", max_calls_per_min=5, max_spend_per_day=10)
    # Pro tier: 100 calls/min, 1000 credits/day
    await policies.set_policy("pro-agent", max_calls_per_min=100, max_spend_per_day=1000)

    @tracker.metered(cost=1, require_balance=True)
    async def api_call(agent_id: str, endpoint: str) -> dict:
        """Simulated API call — 1 credit per call."""
        return {"endpoint": endpoint, "status": "ok"}

    # Pro agent: works fine
    print("--- Pro agent (high limits) ---")
    for i in range(10):
        await api_call(agent_id="pro-agent", endpoint=f"/data/{i}")
    print("Pro agent made 10 calls successfully")
    balance = await wallet.get_balance("pro-agent")
    print(f"Pro agent balance: {balance} credits")

    # Free agent: hits rate limit
    print("\n--- Free agent (rate limited) ---")
    calls_made = 0
    for i in range(10):
        try:
            await policies.check_all("free-agent", cost=1)
            await api_call(agent_id="free-agent", endpoint=f"/data/{i}")
            calls_made += 1
        except RateLimitExceededError:
            print(f"  Rate limit hit after {calls_made} calls")
            break
        except SpendCapExceededError:
            print(f"  Spend cap hit after {calls_made} calls")
            break

    balance = await wallet.get_balance("free-agent")
    print(f"Free agent made {calls_made} calls, balance: {balance} credits")

    await tracker.close()
    if os.path.exists("multi_agent.db"):
        os.remove("multi_agent.db")


if __name__ == "__main__":
    asyncio.run(main())
