"""Workflow: Data Pipeline — multi-tool chained payments.

Demonstrates a data pipeline agent that:
1. Creates payment intents for data processing services
2. Captures payments after successful processing
3. Tracks all costs via the billing system

Usage:
    # Start the gateway first:
    python gateway/main.py

    # Then run this example:
    python examples/workflow_data_pipeline.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.src.a2a_client import A2AClient


async def main() -> None:
    base_url = os.environ.get("A2A_GATEWAY_URL", "http://localhost:8000")
    api_key = os.environ.get("A2A_API_KEY", "")

    if not api_key:
        print("Set A2A_API_KEY environment variable first.")
        return

    async with A2AClient(base_url=base_url, api_key=api_key) as client:
        agent_id = "pipeline-agent"

        # Step 1: Check balance before starting pipeline
        print("=== Step 1: Pre-flight Balance Check ===")
        try:
            balance = await client.get_balance(agent_id)
            print(f"Starting balance: {balance} credits")
        except Exception as e:
            print(f"Could not check balance: {e}")
            return

        # Step 2: Create payment intent for data extraction
        print("\n=== Step 2: Data Extraction Payment ===")
        try:
            intent = await client.create_payment_intent(
                payer=agent_id,
                payee="data-extraction-service",
                amount=25.0,
                description="Extract customer records batch #42",
            )
            print(f"Intent created: {intent['id']} (status: {intent['status']})")

            # Simulate: extraction succeeds, capture the payment
            settlement = await client.capture_payment(intent["id"])
            print(f"Payment captured: {settlement['id']} (amount: {settlement['amount']})")
        except Exception as e:
            print(f"Payment flow error: {e}")

        # Step 3: Create payment intent for data transformation
        print("\n=== Step 3: Data Transformation Payment ===")
        try:
            intent2 = await client.create_payment_intent(
                payer=agent_id,
                payee="data-transform-service",
                amount=15.0,
                description="Transform and normalize records",
            )
            print(f"Intent created: {intent2['id']} (status: {intent2['status']})")

            settlement2 = await client.capture_payment(intent2["id"])
            print(f"Payment captured: {settlement2['id']} (amount: {settlement2['amount']})")
        except Exception as e:
            print(f"Payment flow error: {e}")

        # Step 4: Check final balance and usage
        print("\n=== Step 4: Post-Pipeline Summary ===")
        try:
            final_balance = await client.get_balance(agent_id)
            print(f"Final balance: {final_balance} credits")

            usage = await client.get_usage_summary(agent_id)
            print(f"Total API cost: {usage.get('total_cost', 0)} credits")
            print(f"Total API calls: {usage.get('total_calls', 0)}")
        except Exception as e:
            print(f"Summary error: {e}")

        # Step 5: Check payment history
        print("\n=== Step 5: Payment History ===")
        try:
            history = await client.get_payment_history(agent_id)
            print(f"Total payments: {len(history)}")
            for entry in history[:5]:
                print(f"  - {entry}")
        except Exception as e:
            print(f"History error: {e}")

        print("\n=== Pipeline Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
