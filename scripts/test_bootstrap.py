#!/usr/bin/env python3
"""Bootstrap import-order smoke test (P2-2).

Imports the gateway bootstrap module and then verifies that all
expected virtual packages are registered in sys.modules. This catches
regressions on the sys.modules registration chain that wires up
product packages for the gateway.

Usage:
    python scripts/test_bootstrap.py          # exits 0 on success, 1 on failure

Run as part of CI quality job.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Expected virtual package prefixes registered by bootstrap()
_EXPECTED_PREFIXES = [
    "shared_src",
    "billing_src",
    "paywall_src",
    "payments_src",
    "marketplace_src",
    "trust_src",
    "identity_src",
    "messaging_src",
    "gatekeeper_src",
]

# Gateway modules that exercise the full dependency chain
_GATEWAY_IMPORTS = [
    "gateway.src.app",
    "gateway.src.catalog",
    "gateway.src.tools",
]


def main() -> int:
    # Ensure repo root is on sys.path
    root_str = str(REPO_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    errors: list[str] = []

    # 1. Import bootstrap (triggers the full product registration chain)
    try:
        import gateway.src.bootstrap  # noqa: F401
    except (ImportError, ModuleNotFoundError) as e:
        print(f"FATAL: bootstrap import failed: {e}", file=sys.stderr)
        return 1

    # 2. Check all expected virtual packages are registered
    for prefix in _EXPECTED_PREFIXES:
        if prefix not in sys.modules:
            errors.append(f"Missing virtual package: {prefix}")

    # 3. Import gateway modules to verify the chain works end-to-end
    import importlib

    for mod_name in _GATEWAY_IMPORTS:
        try:
            importlib.import_module(mod_name)
        except (ImportError, ModuleNotFoundError) as e:
            errors.append(f"{mod_name}: {type(e).__name__}: {e}")

    if errors:
        print(f"Bootstrap smoke test FAILED ({len(errors)} errors):", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    registered = sum(1 for p in _EXPECTED_PREFIXES if p in sys.modules)
    print(f"Bootstrap smoke test OK — {registered} virtual packages, {len(_GATEWAY_IMPORTS)} gateway modules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
