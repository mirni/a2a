"""Identity, claims, reputation, and org tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tools._validators import check_caller_owns_agent_id as _check_caller_owns_agent_id


async def _register_agent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Register an agent identity.

    v1.2.2 audit HIGH-8: API key provisioning auto-creates the
    identity record, so ``IdentityAPI.register_agent`` is idempotent
    when the caller omits ``public_key`` or passes the already-stored
    key. A caller that supplies a *different* public key after the
    auto-bind still gets the old conflict (surfaced as 409), so we
    rotate the stored key here so the integrator's signing keypair
    becomes the active one.
    """
    from identity_src.api import AgentAlreadyExistsError
    from identity_src.models import AgentIdentity

    agent_id = params["agent_id"]
    requested_public_key = params.get("public_key")
    try:
        identity = await ctx.identity_api.register_agent(
            agent_id=agent_id,
            public_key=requested_public_key,
        )
    except AgentAlreadyExistsError:
        existing = await ctx.identity_api.get_identity(agent_id)
        if existing is None or requested_public_key is None:
            raise
        # Rotate in the caller-supplied key so downstream signature
        # verification succeeds.
        updated = AgentIdentity(
            agent_id=existing.agent_id,
            public_key=requested_public_key,
            created_at=existing.created_at,
            org_id=existing.org_id,
        )
        await ctx.identity_api.storage.store_identity(updated)
        return {
            "agent_id": updated.agent_id,
            "public_key": updated.public_key,
            "created_at": updated.created_at,
        }
    return {
        "agent_id": identity.agent_id,
        "public_key": identity.public_key,
        "created_at": identity.created_at,
    }


async def _verify_agent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    message = params["message"].encode() if isinstance(params["message"], str) else params["message"]
    valid = await ctx.identity_api.verify_agent(
        agent_id=params["agent_id"],
        message=message,
        signature_hex=params["signature"],
    )
    return {"valid": valid}


async def _submit_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    _check_caller_owns_agent_id(params)
    attestation = await ctx.identity_api.submit_metrics(
        agent_id=params["agent_id"],
        metrics=params["metrics"],
        data_source=params.get("data_source", "self_reported"),
    )
    return {
        "agent_id": attestation.agent_id,
        "commitment_hashes": attestation.commitment_hashes,
        "verified_at": attestation.verified_at,
        "valid_until": attestation.valid_until,
        "data_source": attestation.data_source,
        "signature": attestation.signature,
    }


async def _get_agent_identity(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from gateway.src.tool_errors import ToolNotFoundError

    identity = await ctx.identity_api.get_identity(params["agent_id"])
    if identity is None:
        raise ToolNotFoundError(
            f"Agent not found: {params['agent_id']}. "
            f'Register identity first: POST /v1/identity/agents {{"agent_id": "{params["agent_id"]}"}}'
        )
    return {
        "agent_id": identity.agent_id,
        "public_key": identity.public_key,
        "created_at": identity.created_at,
        "org_id": identity.org_id,
        "found": True,
    }


async def _get_verified_claims(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    claims = await ctx.identity_api.get_verified_claims(params["agent_id"])
    return {
        "claims": [
            {
                "agent_id": c.agent_id,
                "metric_name": c.metric_name,
                "claim_type": c.claim_type,
                "bound_value": c.bound_value,
                "valid_until": c.valid_until,
            }
            for c in claims
        ]
    }


async def _search_agents_by_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    agents = await ctx.identity_api.search_agents_by_metrics(
        metric_name=params["metric_name"],
        min_value=params.get("min_value"),
        max_value=params.get("max_value"),
        limit=params.get("limit", 50),
    )
    return {"agents": agents}


async def _get_agent_reputation(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from gateway.src.tool_errors import ToolNotFoundError

    reputation = await ctx.identity_api.get_reputation(params["agent_id"])
    if reputation is None:
        raise ToolNotFoundError(
            f"Agent reputation not found: {params['agent_id']}. Register identity first: POST /v1/identity/agents"
        )
    return {
        "agent_id": reputation.agent_id,
        "payment_reliability": reputation.payment_reliability,
        "data_source_quality": reputation.data_source_quality,
        "transaction_volume_score": reputation.transaction_volume_score,
        "composite_score": reputation.composite_score,
        "confidence": reputation.confidence,
        "found": True,
    }


# ---------------------------------------------------------------------------
# Historical claim chains
# ---------------------------------------------------------------------------


async def _build_claim_chain(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.identity_api.build_claim_chain(params["agent_id"])


async def _get_claim_chains(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    chains = await ctx.identity_api.storage.get_claim_chains(params["agent_id"], limit=params.get("limit", 10))
    return {"chains": chains}


# ---------------------------------------------------------------------------
# Org/Team (P3-23)
# ---------------------------------------------------------------------------


async def _create_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a new organization."""
    import time as _time
    import uuid as _uuid

    org_name = params["org_name"]
    owner_agent_id = params.get("agent_id", "")
    org_id = f"org-{_uuid.uuid4().hex[:12]}"
    now = _time.time()

    db = ctx.identity_api.storage.db
    await db.execute(
        "INSERT INTO orgs (id, name, owner_agent_id, created_at, metadata) VALUES (?, ?, ?, ?, ?)",
        (org_id, org_name, owner_agent_id, now, "{}"),
    )
    # Auto-add the owner as a member with role='owner'
    if owner_agent_id:
        await db.execute(
            "INSERT OR IGNORE INTO org_memberships (org_id, agent_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (org_id, owner_agent_id, now),
        )
    await db.commit()

    return {
        "org_id": org_id,
        "name": org_name,
        "created_at": now,
    }


async def _get_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get organization details and members."""
    org_id = params["org_id"]
    db = ctx.identity_api.storage.db

    cursor = await db.execute("SELECT * FROM orgs WHERE id = ?", (org_id,))
    row = await cursor.fetchone()
    if row is None:
        return {"error": f"Org not found: {org_id}"}

    cursor2 = await db.execute("SELECT agent_id FROM agent_identities WHERE org_id = ?", (org_id,))
    members = [{"agent_id": r["agent_id"]} for r in await cursor2.fetchall()]

    return {
        "org_id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "members": members,
    }


async def _ingest_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Ingest time-series metric data for an agent."""
    _check_caller_owns_agent_id(params)
    result = await ctx.identity_api.ingest_timeseries(
        agent_id=params["agent_id"],
        metrics=params["metrics"],
        data_source=params.get("data_source", "self_reported"),
        signature=params.get("signature"),
        nonce=params.get("nonce"),
    )
    return result


async def _query_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Query time-series metrics for an agent."""
    rows = await ctx.identity_api.query_agent_timeseries(
        agent_id=params["agent_id"],
        metric_name=params["metric_name"],
        since=params.get("since"),
        limit=params.get("limit", 100),
    )
    return {"data": rows}


async def _get_metric_deltas(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get metric deltas (current vs previous) for an agent."""
    deltas = await ctx.identity_api.get_metric_deltas(
        agent_id=params["agent_id"],
        metric_name=params.get("metric_name"),
    )
    return {"deltas": deltas}


async def _get_metric_averages(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get pre-computed metric averages for an agent."""
    avgs = await ctx.identity_api.get_metric_averages(
        agent_id=params["agent_id"],
        period=params.get("period", "30d"),
    )
    return {"averages": avgs}


async def _remove_agent_from_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Remove an agent from an organization (with last-owner guard)."""
    from gateway.src.tool_errors import ToolNotFoundError, ToolValidationError

    org_id = params["org_id"]
    agent_id = params["agent_id"]
    db = ctx.identity_api.storage.db

    # Verify org exists
    cursor = await db.execute("SELECT id FROM orgs WHERE id = ?", (org_id,))
    if await cursor.fetchone() is None:
        raise ToolNotFoundError(f"Org not found: {org_id}")

    # Check if target is an owner and the last one
    cursor = await db.execute(
        "SELECT role FROM org_memberships WHERE org_id = ? AND agent_id = ?",
        (org_id, agent_id),
    )
    membership_row = await cursor.fetchone()
    if membership_row is None:
        raise ToolNotFoundError(f"Agent {agent_id} is not a member of {org_id}")

    if membership_row["role"] == "owner":
        cursor = await db.execute(
            "SELECT COUNT(*) FROM org_memberships WHERE org_id = ? AND role = 'owner'",
            (org_id,),
        )
        owner_count = (await cursor.fetchone())[0]
        if owner_count <= 1:
            raise ToolValidationError(f"Cannot remove agent {agent_id}: they are the last owner of {org_id}")

    await db.execute(
        "DELETE FROM org_memberships WHERE org_id = ? AND agent_id = ?",
        (org_id, agent_id),
    )
    await db.commit()

    return {
        "org_id": org_id,
        "agent_id": agent_id,
        "removed": True,
    }


async def _add_agent_to_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Add an agent to an organization."""
    import time as _time

    org_id = params["org_id"]
    agent_id = params["agent_id"]
    role = params.get("role", "member")
    db = ctx.identity_api.storage.db

    cursor = await db.execute("SELECT id FROM orgs WHERE id = ?", (org_id,))
    if await cursor.fetchone() is None:
        return {"error": f"Org not found: {org_id}"}

    await db.execute(
        "UPDATE agent_identities SET org_id = ? WHERE agent_id = ?",
        (org_id, agent_id),
    )
    await db.execute(
        "INSERT OR IGNORE INTO org_memberships (org_id, agent_id, role, joined_at) VALUES (?, ?, ?, ?)",
        (org_id, agent_id, role, _time.time()),
    )
    await db.commit()

    return {
        "agent_id": agent_id,
        "org_id": org_id,
    }
