"""Shared fixtures for sandbox parity tests (v1.2.4 audit T-3).

These tests run against the *live* sandbox at
``sandbox.greenhelix.net`` so they exercise the same stack the
external auditors probe. They intentionally do **not** run with
the in-process FastAPI TestClient — the whole point is to catch
things that only break behind Cloudflare / nginx / TLS / proxy.

Secret plumbing
===============

The tests require 3 API keys with distinct tiers, provisioned
manually on the sandbox (see ``tasks/backlog/sandbox-audit-keys.md``
for the step-by-step). Each key is injected via an environment
variable:

* ``SANDBOX_AUDIT_FREE_KEY`` — a FREE-tier key with a funded wallet.
* ``SANDBOX_AUDIT_PRO_KEY`` — a PRO-tier key with a funded wallet.
* ``SANDBOX_AUDIT_ADMIN_KEY`` — an admin-scoped key.

When **any** of these are absent, the whole suite skips with a
loud marker so developers can run ``pytest tests/sandbox/``
locally without setting up credentials. In CI the
``sandbox-parity`` job uses GitHub secrets to populate them and
fails if the tests don't run.

Base URL
========

Defaults to ``https://sandbox.greenhelix.net``. Override with
``A2A_SANDBOX_URL`` for smoke-testing against a local uvicorn or
a staging alternate.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.asyncio


_DEFAULT_SANDBOX_URL = "https://sandbox.greenhelix.net"


def _sandbox_base_url() -> str:
    return os.environ.get("A2A_SANDBOX_URL", _DEFAULT_SANDBOX_URL)


def _required_keys_missing() -> list[str]:
    return [
        var
        for var in (
            "SANDBOX_AUDIT_FREE_KEY",
            "SANDBOX_AUDIT_PRO_KEY",
            "SANDBOX_AUDIT_ADMIN_KEY",
        )
        if not os.environ.get(var)
    ]


@pytest.fixture(scope="session", autouse=True)
def _require_sandbox_keys():
    """Skip the whole module if audit keys aren't in the env.

    We keep this as ``autouse`` so developers don't need to add
    a decorator to every test; running ``pytest tests/sandbox/``
    locally simply reports the skipped-for-missing-secrets count.
    """
    missing = _required_keys_missing()
    if missing:
        pytest.skip(
            f"sandbox parity tests require env vars: {missing}. "
            f"See tasks/backlog/sandbox-audit-keys.md for how to "
            f"provision these on the sandbox and wire them into "
            f"GitHub Actions secrets."
        )


@pytest.fixture(scope="session")
def sandbox_base_url() -> str:
    return _sandbox_base_url()


@pytest.fixture(scope="session")
def free_key() -> str:
    return os.environ["SANDBOX_AUDIT_FREE_KEY"]


@pytest.fixture(scope="session")
def pro_key() -> str:
    return os.environ["SANDBOX_AUDIT_PRO_KEY"]


@pytest.fixture(scope="session")
def admin_key() -> str:
    return os.environ["SANDBOX_AUDIT_ADMIN_KEY"]


@pytest.fixture()
async def sandbox_client(sandbox_base_url: str):
    """HTTPX async client pointed at the real sandbox.

    No API key is attached here — tests pick which tier to use
    by setting the ``Authorization`` header per-call. That makes
    cross-tenant probes readable.
    """
    async with httpx.AsyncClient(
        base_url=sandbox_base_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    ) as client:
        yield client
