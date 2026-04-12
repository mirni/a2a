"""WAL2.10 regression — budget caps PUT must accept aliased fields.

The v1.2.9 audit sends ``{"daily": 100, "monthly": 2000}`` which the
current ``BudgetCapRequest`` rejects (422) because fields are named
``daily_cap`` / ``monthly_cap``.  Both forms should be accepted.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_budget_cap_with_canonical_fields(client, api_key):
    """PUT with daily_cap/monthly_cap (canonical names) succeeds."""
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily_cap": "100.00", "monthly_cap": "2000.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


async def test_budget_cap_with_aliased_fields(client, api_key):
    """PUT with daily/monthly (short aliases) succeeds."""
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily": "100.00", "monthly": "2000.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"Expected 200 for aliased fields, got {resp.status_code}: {resp.text}"


async def test_budget_cap_mixed_alias_and_canonical(client, api_key):
    """PUT with a mix of alias + canonical name succeeds."""
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily": "50.00", "monthly_cap": "1000.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"Expected 200 for mixed fields, got {resp.status_code}: {resp.text}"


async def test_budget_cap_unknown_field_rejected(client, api_key):
    """PUT with unknown field still returns 422 (extra=forbid)."""
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily_cap": "100.00", "unknown_field": "bad"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_budget_cap_alert_threshold(client, api_key):
    """Alert threshold is accepted alongside caps."""
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily": "200.00", "alert_threshold": 0.9},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
