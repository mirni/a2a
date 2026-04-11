#!/usr/bin/env python3
"""Dump the gateway's current OpenAPI schema as canonical JSON.

v1.2.4 audit P1 T-5: feeds the schema-diff CI gate at
``reports/openapi-baseline.json``. The baseline is committed;
any removal or type change in a PR trips the gate.

Usage::

    python scripts/dump_openapi.py > /tmp/current.json
    diff -u reports/openapi-baseline.json /tmp/current.json

Exit code is always 0; stdout is the canonical JSON. The
comparison is performed by ``scripts/ci/diff_openapi.py``.
"""

from __future__ import annotations

import json
import os
import sys


def _prepare_env() -> None:
    """Point the gateway at ephemeral databases so we can import it.

    The gateway's app factory needs the product DSNs to be set
    before ``create_app()`` is called. We use an in-memory
    scratch path so that running this script never touches the
    real state.
    """
    tmp = "/tmp/_dump_openapi"
    os.makedirs(tmp, exist_ok=True)
    os.environ.setdefault("A2A_DATA_DIR", tmp)
    for var, name in [
        ("BILLING_DSN", "billing.db"),
        ("PAYWALL_DSN", "paywall.db"),
        ("PAYMENTS_DSN", "payments.db"),
        ("MARKETPLACE_DSN", "marketplace.db"),
        ("TRUST_DSN", "trust.db"),
        ("IDENTITY_DSN", "identity.db"),
        ("EVENT_BUS_DSN", "event_bus.db"),
        ("WEBHOOK_DSN", "webhooks.db"),
        ("DISPUTE_DSN", "disputes.db"),
        ("MESSAGING_DSN", "messaging.db"),
    ]:
        os.environ.setdefault(var, f"sqlite:///{tmp}/{name}")


def main() -> int:
    _prepare_env()

    # Import lazily — before this point, sys.path has to have
    # the repo root. The caller is expected to run the script
    # from the repo root.
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

    import gateway.src.bootstrap  # noqa: F401
    from gateway.src.app import create_app

    app = create_app()
    schema = app.openapi()

    # Canonical serialisation so the diff is stable.
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
