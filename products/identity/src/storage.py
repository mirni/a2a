"""SQLite storage layer for the Agent Identity system.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from .models import (
    AgentIdentity,
    AgentReputation,
    AuditorAttestation,
    MetricCommitment,
    VerifiedClaim,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_identities (
    agent_id    TEXT PRIMARY KEY,
    public_key  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    org_id      TEXT NOT NULL DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS metric_commitments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    commitment_hash TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    window_days     INTEGER NOT NULL DEFAULT 30
);

CREATE INDEX IF NOT EXISTS idx_commitment_agent ON metric_commitments(agent_id);
CREATE INDEX IF NOT EXISTS idx_commitment_ts    ON metric_commitments(timestamp);

CREATE TABLE IF NOT EXISTS attestations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          TEXT NOT NULL,
    auditor_id        TEXT NOT NULL DEFAULT 'platform_auditor_v1',
    commitment_hashes TEXT NOT NULL,
    verified_at       REAL NOT NULL,
    valid_until       REAL NOT NULL,
    data_source       TEXT NOT NULL,
    signature         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attestation_agent ON attestations(agent_id);
CREATE INDEX IF NOT EXISTS idx_attestation_valid ON attestations(valid_until);

CREATE TABLE IF NOT EXISTS verified_claims (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id              TEXT NOT NULL,
    metric_name           TEXT NOT NULL,
    claim_type            TEXT NOT NULL,
    bound_value           REAL NOT NULL,
    attestation_id        INTEGER NOT NULL,
    valid_until           REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claim_agent ON verified_claims(agent_id);
CREATE INDEX IF NOT EXISTS idx_claim_valid ON verified_claims(valid_until);

CREATE TABLE IF NOT EXISTS agent_reputation (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id                 TEXT NOT NULL,
    timestamp                REAL NOT NULL,
    payment_reliability      REAL NOT NULL DEFAULT 0.0,
    dispute_rate             REAL NOT NULL DEFAULT 0.0,
    transaction_volume_score REAL NOT NULL DEFAULT 0.0,
    composite_score          REAL NOT NULL DEFAULT 0.0,
    confidence               REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_reputation_agent ON agent_reputation(agent_id);
CREATE INDEX IF NOT EXISTS idx_reputation_ts    ON agent_reputation(timestamp);

CREATE TABLE IF NOT EXISTS claim_chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    leaf_hashes TEXT NOT NULL,
    chain_length INTEGER NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chain_agent ON claim_chains(agent_id);
"""


@dataclass
class IdentityStorage:
    """Async SQLite storage backend for all agent identity data."""

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)

    async def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        db_path = self.dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("IdentityStorage not connected. Call connect() first.")
        return self._db

    # -----------------------------------------------------------------------
    # Agent identities
    # -----------------------------------------------------------------------

    async def store_identity(self, identity: AgentIdentity) -> AgentIdentity:
        """Insert or replace an agent identity record."""
        await self.db.execute(
            "INSERT OR REPLACE INTO agent_identities (agent_id, public_key, created_at, org_id) "
            "VALUES (?, ?, ?, ?)",
            (identity.agent_id, identity.public_key, identity.created_at, identity.org_id),
        )
        await self.db.commit()
        return identity

    async def get_identity(self, agent_id: str) -> AgentIdentity | None:
        """Retrieve an agent identity by agent_id."""
        cursor = await self.db.execute(
            "SELECT * FROM agent_identities WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return AgentIdentity(
            agent_id=row["agent_id"],
            public_key=row["public_key"],
            created_at=row["created_at"],
            org_id=row["org_id"],
        )

    # -----------------------------------------------------------------------
    # Metric commitments
    # -----------------------------------------------------------------------

    async def store_commitment(self, commitment: MetricCommitment) -> int:
        """Store a metric commitment and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO metric_commitments "
            "(agent_id, metric_name, commitment_hash, timestamp, window_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                commitment.agent_id,
                commitment.metric_name,
                commitment.commitment_hash,
                commitment.timestamp,
                commitment.window_days,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_commitments(
        self, agent_id: str, since: float | None = None, limit: int = 100
    ) -> list[MetricCommitment]:
        """Retrieve metric commitments for an agent."""
        query = "SELECT * FROM metric_commitments WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            MetricCommitment(
                agent_id=r["agent_id"],
                metric_name=r["metric_name"],
                commitment_hash=r["commitment_hash"],
                timestamp=r["timestamp"],
                window_days=r["window_days"],
            )
            for r in rows
        ]

    # -----------------------------------------------------------------------
    # Attestations
    # -----------------------------------------------------------------------

    async def store_attestation(self, attestation: AuditorAttestation) -> int:
        """Store an auditor attestation and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO attestations "
            "(agent_id, auditor_id, commitment_hashes, verified_at, valid_until, "
            "data_source, signature) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                attestation.agent_id,
                attestation.auditor_id,
                json.dumps(attestation.commitment_hashes),
                attestation.verified_at,
                attestation.valid_until,
                attestation.data_source,
                attestation.signature,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_attestations(
        self, agent_id: str, valid_only: bool = True
    ) -> list[AuditorAttestation]:
        """Retrieve attestations for an agent, optionally filtering expired ones."""
        query = "SELECT * FROM attestations WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if valid_only:
            query += " AND valid_until > ?"
            params.append(time.time())
        query += " ORDER BY verified_at DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            AuditorAttestation(
                agent_id=r["agent_id"],
                auditor_id=r["auditor_id"],
                commitment_hashes=json.loads(r["commitment_hashes"]),
                verified_at=r["verified_at"],
                valid_until=r["valid_until"],
                data_source=r["data_source"],
                signature=r["signature"],
            )
            for r in rows
        ]

    async def get_attestation_by_id(self, attestation_id: int) -> AuditorAttestation | None:
        """Retrieve an attestation by its row ID."""
        cursor = await self.db.execute(
            "SELECT * FROM attestations WHERE id = ?", (attestation_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return AuditorAttestation(
            agent_id=row["agent_id"],
            auditor_id=row["auditor_id"],
            commitment_hashes=json.loads(row["commitment_hashes"]),
            verified_at=row["verified_at"],
            valid_until=row["valid_until"],
            data_source=row["data_source"],
            signature=row["signature"],
        )

    # -----------------------------------------------------------------------
    # Verified claims
    # -----------------------------------------------------------------------

    async def store_claim(self, claim: VerifiedClaim, attestation_id: int) -> int:
        """Store a verified claim and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO verified_claims "
            "(agent_id, metric_name, claim_type, bound_value, attestation_id, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                claim.agent_id,
                claim.metric_name,
                claim.claim_type,
                claim.bound_value,
                attestation_id,
                claim.valid_until,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_claims(
        self, agent_id: str, valid_only: bool = True
    ) -> list[VerifiedClaim]:
        """Retrieve verified claims for an agent, optionally filtering expired."""
        query = "SELECT * FROM verified_claims WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if valid_only:
            query += " AND valid_until > ?"
            params.append(time.time())
        query += " ORDER BY valid_until DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            VerifiedClaim(
                agent_id=r["agent_id"],
                metric_name=r["metric_name"],
                claim_type=r["claim_type"],
                bound_value=r["bound_value"],
                attestation_signature="",  # Not stored directly; linked via attestation_id
                valid_until=r["valid_until"],
            )
            for r in rows
        ]

    async def search_claims(
        self,
        metric_name: str,
        claim_type: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 100,
    ) -> list[VerifiedClaim]:
        """Search verified claims across all agents.

        Args:
            metric_name: The metric to search (e.g. "sharpe_30d").
            claim_type: Filter by claim_type ("gte" or "lte"). Optional.
            min_value: Minimum bound_value (agents claiming >= this). Optional.
            max_value: Maximum bound_value (agents claiming <= this). Optional.
            limit: Max results.

        Returns:
            List of matching VerifiedClaim objects (only non-expired).
        """
        query = "SELECT * FROM verified_claims WHERE metric_name = ? AND valid_until > ?"
        params: list[Any] = [metric_name, time.time()]
        if claim_type is not None:
            query += " AND claim_type = ?"
            params.append(claim_type)
        if min_value is not None:
            query += " AND bound_value >= ?"
            params.append(min_value)
        if max_value is not None:
            query += " AND bound_value <= ?"
            params.append(max_value)
        query += " ORDER BY bound_value DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            VerifiedClaim(
                agent_id=r["agent_id"],
                metric_name=r["metric_name"],
                claim_type=r["claim_type"],
                bound_value=r["bound_value"],
                attestation_signature="",
                valid_until=r["valid_until"],
            )
            for r in rows
        ]

    # -----------------------------------------------------------------------
    # Agent reputation
    # -----------------------------------------------------------------------

    async def store_reputation(self, reputation: AgentReputation) -> int:
        """Store a reputation record and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO agent_reputation "
            "(agent_id, timestamp, payment_reliability, dispute_rate, "
            "transaction_volume_score, composite_score, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                reputation.agent_id,
                reputation.timestamp,
                reputation.payment_reliability,
                reputation.dispute_rate,
                reputation.transaction_volume_score,
                reputation.composite_score,
                reputation.confidence,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_latest_reputation(self, agent_id: str) -> AgentReputation | None:
        """Retrieve the most recent reputation record for an agent."""
        cursor = await self.db.execute(
            "SELECT * FROM agent_reputation WHERE agent_id = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return AgentReputation(
            agent_id=row["agent_id"],
            timestamp=row["timestamp"],
            payment_reliability=row["payment_reliability"],
            dispute_rate=row["dispute_rate"],
            transaction_volume_score=row["transaction_volume_score"],
            composite_score=row["composite_score"],
            confidence=row["confidence"],
        )

    # -----------------------------------------------------------------------
    # Claim chains
    # -----------------------------------------------------------------------

    async def store_claim_chain(
        self,
        agent_id: str,
        merkle_root: str,
        leaf_hashes: list[str],
        period_start: float,
        period_end: float,
    ) -> int:
        """Store a claim chain (Merkle tree of attestation hashes).

        Args:
            agent_id: The agent this chain belongs to.
            merkle_root: Hex-encoded Merkle root of the attestation hashes.
            leaf_hashes: List of hex attestation hashes (the leaves).
            period_start: Unix timestamp of the earliest attestation.
            period_end: Unix timestamp of the latest attestation.

        Returns:
            The row ID of the stored claim chain.
        """
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO claim_chains "
            "(agent_id, merkle_root, leaf_hashes, chain_length, "
            "period_start, period_end, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                merkle_root,
                json.dumps(leaf_hashes),
                len(leaf_hashes),
                period_start,
                period_end,
                now,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_claim_chains(
        self, agent_id: str, limit: int = 10
    ) -> list[dict]:
        """Retrieve claim chains for an agent, newest first.

        Args:
            agent_id: The agent to query.
            limit: Maximum number of chains to return.

        Returns:
            List of dicts with keys: id, agent_id, merkle_root, leaf_hashes,
            chain_length, period_start, period_end, created_at.
        """
        cursor = await self.db.execute(
            "SELECT * FROM claim_chains WHERE agent_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "merkle_root": r["merkle_root"],
                "leaf_hashes": r["leaf_hashes"],
                "chain_length": r["chain_length"],
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
