#!/usr/bin/env python3
"""Provision an admin API key for stress testing.

Usage:
    scripts/ci/provision_admin_key.py --data-dir /tmp/a2a
    scripts/ci/provision_admin_key.py --agent-id my-agent --balance 500000

Prints only the API key to stdout (capturable via $()).
"""

import argparse
import asyncio
import os
import sys

# Add repo root to path so gateway imports work
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)


async def main(data_dir: str, agent_id: str, balance: float) -> str:
    os.environ["A2A_DATA_DIR"] = data_dir

    import gateway.src.bootstrap  # noqa: F401, I001 — must run first to register namespace packages

    # isort: split
    from billing_src.tracker import UsageTracker
    from paywall_src.keys import KeyManager
    from paywall_src.storage import PaywallStorage

    ps = PaywallStorage(f"sqlite:///{data_dir}/paywall.db")
    await ps.connect()
    km = KeyManager(ps)

    tracker = UsageTracker(f"sqlite:///{data_dir}/billing.db")
    await tracker.connect()

    await tracker.wallet.create(agent_id, initial_balance=balance)
    info = await km.create_key(agent_id, tier="enterprise")

    await ps.close()
    await tracker.close()

    return info["key"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Provision an admin API key")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("A2A_DATA_DIR", ""),
        help="Path to A2A data directory (default: $A2A_DATA_DIR)",
    )
    parser.add_argument(
        "--agent-id",
        default="stress-admin",
        help="Agent ID to create (default: stress-admin)",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=999999.0,
        help="Initial wallet balance (default: 999999.0)",
    )
    args = parser.parse_args()

    if not args.data_dir:
        print("Error: --data-dir or $A2A_DATA_DIR required", file=sys.stderr)
        sys.exit(1)

    key = asyncio.run(main(args.data_dir, args.agent_id, args.balance))
    print(key)
