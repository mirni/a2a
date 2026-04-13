#!/usr/bin/env python3
"""Provision stress-test agents with wallets + API keys (DB-level).

Usage:
    python scripts/ci/provision_stress_agents.py --data-dir /tmp/a2a --count 20

Creates agents stress-agent-0000 through stress-agent-{count-1} with pro-tier
API keys and funded wallets.  Prints a JSON object mapping agent_id → api_key
to stdout.
"""

import argparse
import asyncio
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)


async def main(data_dir: str, count: int, balance: float) -> dict[str, str]:
    os.environ["A2A_DATA_DIR"] = data_dir

    import gateway.src.bootstrap  # noqa: F401, I001

    # isort: split
    from billing_src.tracker import UsageTracker
    from paywall_src.keys import KeyManager
    from paywall_src.storage import PaywallStorage

    ps = PaywallStorage(f"sqlite:///{data_dir}/paywall.db")
    await ps.connect()
    km = KeyManager(ps)

    tracker = UsageTracker(f"sqlite:///{data_dir}/billing.db")
    await tracker.connect()

    agents: dict[str, str] = {}
    for i in range(count):
        agent_id = f"stress-agent-{i:04d}"
        await tracker.wallet.create(agent_id, initial_balance=balance)
        info = await km.create_key(agent_id, tier="pro")
        agents[agent_id] = info["key"]

    await ps.close()
    await tracker.close()
    return agents


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Provision stress test agents")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("A2A_DATA_DIR", ""),
        help="Path to A2A data directory",
    )
    parser.add_argument("--count", type=int, default=20, help="Number of agents")
    parser.add_argument("--balance", type=float, default=100000.0, help="Wallet balance per agent")
    args = parser.parse_args()

    if not args.data_dir:
        print("Error: --data-dir or $A2A_DATA_DIR required", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(main(args.data_dir, args.count, args.balance))
    print(json.dumps(result))
