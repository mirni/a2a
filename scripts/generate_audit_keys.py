#!/usr/bin/env python3
"""Generate API keys for external security audit.

Creates three agent wallets (free, pro, admin tiers) with funded wallets
and saves the keys to a file for the external auditor.

Usage:
    scripts/generate_audit_keys.py --data-dir /path/to/a2a/data
    scripts/generate_audit_keys.py --data-dir /path/to/a2a/data --output keys.txt
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

AGENTS = [
    {
        "agent_id": "audit-free",
        "tier": "free",
        "balance": 10000.0,
        "scopes": ["read", "write"],
    },
    {
        "agent_id": "audit-pro",
        "tier": "pro",
        "balance": 100000.0,
        "scopes": ["read", "write"],
    },
    {
        "agent_id": "audit-admin",
        "tier": "enterprise",
        "balance": 999999.0,
        "scopes": ["read", "write", "admin"],
    },
]


async def main(data_dir: str, output_path: str) -> None:
    os.environ["A2A_DATA_DIR"] = data_dir

    from billing_src.tracker import UsageTracker
    from paywall_src.keys import KeyManager
    from paywall_src.storage import PaywallStorage

    import gateway.src.bootstrap  # noqa: F401 — triggers side-effects

    ps = PaywallStorage(f"sqlite:///{data_dir}/paywall.db")
    await ps.connect()
    km = KeyManager(ps)

    tracker = UsageTracker(f"sqlite:///{data_dir}/billing.db")
    await tracker.connect()

    keys: list[dict] = []
    for agent in AGENTS:
        try:
            await tracker.wallet.create(
                agent["agent_id"],
                initial_balance=agent["balance"],
                signup_bonus=False,
            )
        except ValueError:
            pass  # wallet already exists

        info = await km.create_key(
            agent["agent_id"],
            tier=agent["tier"],
            scopes=agent["scopes"],
        )
        keys.append(
            {
                "agent_id": agent["agent_id"],
                "tier": agent["tier"],
                "key": info["key"],
                "balance": agent["balance"],
            }
        )

    await ps.close()
    await tracker.close()

    # Write to file
    lines = [
        "# External Security Audit API Keys",
        f"# Generated: {datetime.now(datetime.UTC).isoformat()}",
        "# Target: api.greenhelix.net/v1  (or sandbox.greenhelix.net/v1)",
        "#",
        "# WARNING: These keys grant real access. Do not commit to git.",
        "",
    ]
    for k in keys:
        lines.append(f"# {k['tier']} tier — agent: {k['agent_id']}, balance: {k['balance']}")
        lines.append(f"{k['tier'].upper()}_API_KEY={k['key']}")
        lines.append("")

    # Also write JSON for programmatic consumption
    lines.append("# JSON format:")
    lines.append(f"# {json.dumps(keys)}")

    content = "\n".join(lines) + "\n"

    with open(output_path, "w") as f:
        f.write(content)

    print(f"Keys written to {output_path}", file=sys.stderr)
    for k in keys:
        print(f"  {k['tier']:12s}  {k['key']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate API keys for security audit")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("A2A_DATA_DIR", ""),
        help="Path to A2A data directory (default: $A2A_DATA_DIR)",
    )
    parser.add_argument(
        "--output",
        default="tasks/external/audit-api-keys.env",
        help="Output file path (default: tasks/external/audit-api-keys.env)",
    )
    args = parser.parse_args()

    if not args.data_dir:
        print("Error: --data-dir or $A2A_DATA_DIR required", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main(args.data_dir, args.output))
