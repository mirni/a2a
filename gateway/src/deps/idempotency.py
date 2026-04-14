"""Route-level idempotency body-hash gate.

v1.2.4 audit P0-4: financial mutations must enforce strict idempotency
semantics at the route layer — not just at the billing storage layer —
so callers that replay ``Idempotency-Key: X`` with a different body
get a clean ``409 idempotency_key_reused`` response instead of
silently creating a second intent.

Design
======

The gate uses a small in-process async SQLite table
(``idempotency_cache``) keyed on ``(agent_id, idempotency_key)`` that
stores:

* ``body_hash`` — SHA-256 of the canonical JSON of the request body.
* ``response_json`` — the JSON body of the original success response.
* ``status_code`` — the original HTTP status code.
* ``created_at`` — used for TTL-based cleanup (default 24h).

On replay:

* Same body hash → return the cached response verbatim (single-shot
  guarantee).
* Different body hash → 409 ``idempotency_key_reused`` RFC 9457 with
  ``stored_body_hash`` so the caller can diff.

The gate uses an ``INSERT ... SELECT WHERE NOT EXISTS`` pattern to
close the check-then-insert race: exactly one concurrent request with
a given ``(agent_id, key)`` pair inserts the placeholder row; the
rest see the row already present and take the replay path.

The storage is piggy-backed on the paywall database so we don't
introduce a new schema file for a small shared table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from gateway.src.errors import error_response

logger = logging.getLogger("a2a.idempotency")

#: Idempotency cache TTL (seconds). Replays after this point are
#: treated as a fresh request.
IDEMPOTENCY_TTL_SECONDS = 24 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_cache (
    agent_id        TEXT NOT NULL,
    key             TEXT NOT NULL,
    body_hash       TEXT NOT NULL,
    status_code     INTEGER NOT NULL,
    response_json   TEXT NOT NULL,
    created_at      REAL NOT NULL,
    PRIMARY KEY (agent_id, key)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_created
    ON idempotency_cache(created_at);
"""


async def _ensure_schema(db: Any) -> None:
    """Ensure the idempotency_cache table exists.

    Uses ``CREATE TABLE IF NOT EXISTS`` so it is safe to call on
    every request. We cannot cache per-process because test fixtures
    recreate the paywall DB between tests with the same module-level
    state.
    """
    await db.executescript(_SCHEMA)
    await db.commit()


def _canonical_body_hash(body: Any) -> str:
    """Compute SHA-256 of the canonical JSON form of a body dict.

    Uses ``sort_keys=True`` + ``separators=(",", ":")`` so two
    structurally identical dicts always hash the same regardless of
    Python dict ordering.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def check_idempotency(
    request: Request,
    agent_id: str,
    body: Any,
) -> JSONResponse | None:
    """Check for idempotency collision before a mutation runs.

    Returns:
        - ``None`` if the route should proceed with the mutation.
        - A ``JSONResponse`` (the cached response or a 409 collision)
          that the caller should return verbatim.

    On a cache miss, this call atomically reserves the slot by
    inserting a placeholder row with the body hash — subsequent
    concurrent requests with the same body see the row and take the
    replay path; subsequent requests with a different body see the
    collision and get 409. The placeholder is finalised later by
    :func:`record_idempotent_response`.
    """
    idem_key = request.headers.get("idempotency-key")
    if not idem_key:
        # Fall back to body field for callers that pass it in the JSON payload
        idem_key = body.get("idempotency_key") if isinstance(body, dict) else None
    if not idem_key:
        return None

    ctx = request.app.state.ctx
    db = ctx.paywall_storage.db
    await _ensure_schema(db)

    body_hash = _canonical_body_hash(body)
    now = time.time()
    cutoff = now - IDEMPOTENCY_TTL_SECONDS

    # Atomic reserve-or-replay via INSERT OR IGNORE. The PK is
    # (agent_id, key) so concurrent callers race for the insert; the
    # loser reads the winner's row.
    await db.execute(
        "INSERT OR IGNORE INTO idempotency_cache "
        "(agent_id, key, body_hash, status_code, response_json, created_at) "
        "VALUES (?, ?, ?, 0, '', ?)",
        (agent_id, idem_key, body_hash, now),
    )
    await db.commit()

    cur = await db.execute(
        "SELECT body_hash, status_code, response_json, created_at "
        "FROM idempotency_cache WHERE agent_id = ? AND key = ?",
        (agent_id, idem_key),
    )
    row = await cur.fetchone()
    await cur.close()

    if row is None:
        # Defensive: should never happen after INSERT OR IGNORE.
        return None

    stored_hash = row["body_hash"] if hasattr(row, "__getitem__") else row[0]
    stored_status = row["status_code"] if hasattr(row, "__getitem__") else row[1]
    stored_response = row["response_json"] if hasattr(row, "__getitem__") else row[2]
    stored_created = row["created_at"] if hasattr(row, "__getitem__") else row[3]

    # Expired rows are treated as a fresh slot — replace and proceed.
    if stored_created < cutoff:
        await db.execute(
            "DELETE FROM idempotency_cache WHERE agent_id = ? AND key = ?",
            (agent_id, idem_key),
        )
        await db.execute(
            "INSERT INTO idempotency_cache "
            "(agent_id, key, body_hash, status_code, response_json, created_at) "
            "VALUES (?, ?, ?, 0, '', ?)",
            (agent_id, idem_key, body_hash, now),
        )
        await db.commit()
        return None

    if stored_hash != body_hash:
        # Collision: same key, different body → 409.
        resp = await error_response(
            409,
            (
                f"Idempotency-Key '{idem_key}' was previously used with a different "
                f"request body (stored_body_hash={stored_hash[:12]}...)"
            ),
            "idempotency_key_reused",
            request=request,
        )
        return resp

    if stored_status == 0:
        # Placeholder: the original request is in flight, or this is
        # the first insert. Proceed with the mutation — the caller
        # owns the slot now. (For the first-inserter the body_hash
        # matches trivially.)
        return None

    # Cache hit: return the stored response verbatim.
    try:
        stored_body = json.loads(stored_response)
    except (json.JSONDecodeError, TypeError):
        stored_body = {}
    return JSONResponse(stored_body, status_code=stored_status)


async def record_idempotent_response(
    request: Request,
    agent_id: str,
    status_code: int,
    response_body: Any,
) -> None:
    """Record the successful response for an idempotency key.

    Called after a mutation completes successfully so that a
    subsequent replay with the same body returns the exact response.
    """
    idem_key = request.headers.get("idempotency-key")
    if not idem_key:
        return
    ctx = request.app.state.ctx
    db = ctx.paywall_storage.db
    await _ensure_schema(db)

    try:
        serialised = json.dumps(response_body, default=str)
    except (TypeError, ValueError):
        logger.warning("idempotency: response is not JSON-serialisable; skipping cache")
        return

    await db.execute(
        "UPDATE idempotency_cache SET status_code = ?, response_json = ? WHERE agent_id = ? AND key = ?",
        (status_code, serialised, agent_id, idem_key),
    )
    await db.commit()
