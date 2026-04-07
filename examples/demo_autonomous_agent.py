"""Demo: Autonomous Agent — full loop: register, discover, pay, execute, verify.

Demonstrates an autonomous agent that:
1. Registers its cryptographic identity
2. Discovers services in the marketplace
3. Checks its wallet balance
4. Creates payment intents for services
5. Executes tool calls via the gateway
6. Verifies results and tracks spending

Usage:
    # Start the gateway first:
    python gateway/main.py

    # Then run this demo:
    python examples/demo_autonomous_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.src.a2a_client import A2AClient
from sdk.src.a2a_client.errors import A2AError


async def main() -> None:
    base_url = os.environ.get("A2A_GATEWAY_URL", "http://localhost:8000")
    api_key = os.environ.get("A2A_API_KEY", "")

    if not api_key:
        print("Set A2A_API_KEY environment variable first.")
        print()
        print("Quick start:")
        print("  1. python gateway/main.py  (start gateway)")
        print("  2. Create an API key via the key management system")
        print("  3. export A2A_API_KEY=a2a_free_...")
        print("  4. python examples/demo_autonomous_agent.py")
        return

    agent_id = "autonomous-agent-1"

    async with A2AClient(base_url=base_url, api_key=api_key) as client:
        print("=" * 60)
        print("  Autonomous Agent Demo")
        print("=" * 60)

        # Phase 1: Identity Registration
        print("\n--- Phase 1: Identity Registration ---")
        try:
            identity = await client.register_agent(agent_id)
            print(f"Registered: {identity.agent_id}")
            print(f"Public key: {identity.public_key[:16]}...")
            print("(Save the private key returned on first registration!)")
        except A2AError as e:
            if "already exists" in str(e.message).lower():
                print(f"Agent {agent_id} already registered")
                identity_info = await client.get_agent_identity(agent_id)
                print(f"Public key: {identity_info.public_key[:16]}...")
            else:
                raise

        # Phase 2: Discovery
        print("\n--- Phase 2: Discovery ---")
        health = await client.health()
        print(f"Gateway: {health.status} (v{health.version}, {health.tools} tools)")

        tools = await client.pricing()
        free_tools = [t for t in tools if t.pricing.get("per_call", 0) == 0]
        paid_tools = [t for t in tools if t.pricing.get("per_call", 0) > 0]
        print(f"Free tools: {len(free_tools)}, Paid tools: {len(paid_tools)}")

        # Phase 3: Budget Assessment
        print("\n--- Phase 3: Budget Assessment ---")
        try:
            balance = await client.get_balance(agent_id)
            print(f"Wallet balance: {balance} credits")
        except A2AError:
            print("No wallet found — this agent needs funding first.")
            return

        total_cost_estimate = sum(t.pricing.get("per_call", 0) for t in paid_tools)
        print(f"Estimated cost for all paid tools: {total_cost_estimate} credits")
        print(f"Budget sufficient: {balance >= total_cost_estimate}")

        # Phase 4: Search for services
        print("\n--- Phase 4: Marketplace Search ---")
        services = await client.search_services()
        print(f"Marketplace services: {len(services)}")

        matches = await client.best_match(query="analytics")
        print(f"Best matches for 'analytics': {len(matches)}")
        for m in matches[:3]:
            svc = m["service"]
            print(f"  [{m['rank_score']:.2f}] {svc['name']}: {svc['description']}")

        # Phase 5: Execute operations
        print("\n--- Phase 5: Execute Operations ---")

        # 4a: Get usage summary
        try:
            usage = await client.get_usage_summary(agent_id)
            print(f"Usage - calls: {usage['total_calls']}, cost: {usage['total_cost']}")
        except A2AError as e:
            print(f"Usage check failed: {e.message}")

        # 4b: Create a payment intent
        try:
            intent = await client.create_payment_intent(
                payer=agent_id,
                payee="analytics-service",
                amount=10.0,
                description="Analytics query batch",
                idempotency_key="demo-intent-001",
            )
            print(f"Payment intent: {intent['id']} ({intent['status']})")

            # 4c: Capture the payment
            settlement = await client.capture_payment(intent["id"])
            print(f"Settlement: {settlement['id']} ({settlement['amount']} credits)")
        except A2AError as e:
            print(f"Payment flow: {e.message}")

        # Phase 6: Verify
        print("\n--- Phase 6: Verification ---")
        try:
            final_balance = await client.get_balance(agent_id)
            print(f"Final balance: {final_balance} credits")

            final_usage = await client.get_usage_summary(agent_id)
            print(f"Total API calls: {final_usage['total_calls']}")
            print(f"Total API cost: {final_usage['total_cost']} credits")

            history = await client.get_payment_history(agent_id)
            print(f"Payment records: {len(history)}")
        except A2AError as e:
            print(f"Verification: {e.message}")

        print("\n" + "=" * 60)
        print("  Demo complete.")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
