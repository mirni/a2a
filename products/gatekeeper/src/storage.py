"""SQLite storage layer for the Formal Gatekeeper system.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import aiosqlite

from .models import (
    ProofArtifact,
    VerificationJob,
    VerificationResult,
    VerificationStatus,
)

# Monetary scale: 1 credit = 10^8 atomic units
SCALE = 10**8


# Register Decimal adapter for SQLite
import sqlite3

sqlite3.register_adapter(Decimal, lambda d: int(d * SCALE))

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verification_jobs (
    id                TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    scope             TEXT NOT NULL DEFAULT 'economic',
    status            TEXT NOT NULL DEFAULT 'pending',
    properties        TEXT NOT NULL DEFAULT '[]',
    timeout_seconds   INTEGER NOT NULL DEFAULT 300,
    result            TEXT,
    proof_artifact_id TEXT,
    webhook_url       TEXT,
    idempotency_key   TEXT,
    cost              INTEGER NOT NULL DEFAULT 0,
    metadata          TEXT NOT NULL DEFAULT '{}',
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vj_agent ON verification_jobs(agent_id);
CREATE INDEX IF NOT EXISTS idx_vj_status ON verification_jobs(status);
CREATE INDEX IF NOT EXISTS idx_vj_created ON verification_jobs(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vj_idempotency
    ON verification_jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS proof_artifacts (
    id                TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    result            TEXT NOT NULL,
    proof_hash        TEXT NOT NULL,
    proof_data        TEXT NOT NULL,
    signature         TEXT NOT NULL DEFAULT '',
    signer_public_key TEXT NOT NULL DEFAULT '',
    counterexample    TEXT,
    property_results  TEXT NOT NULL DEFAULT '[]',
    valid_until       REAL NOT NULL,
    created_at        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proof_job ON proof_artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_proof_agent ON proof_artifacts(agent_id);
CREATE INDEX IF NOT EXISTS idx_proof_hash ON proof_artifacts(proof_hash);
"""


def _job_from_row(row: aiosqlite.Row) -> VerificationJob:
    """Convert a database row to a VerificationJob model."""
    return VerificationJob(
        id=row["id"],
        agent_id=row["agent_id"],
        scope=row["scope"],
        status=row["status"],
        properties=json.loads(row["properties"]),
        timeout_seconds=row["timeout_seconds"],
        result=row["result"],
        proof_artifact_id=row["proof_artifact_id"],
        webhook_url=row["webhook_url"],
        idempotency_key=row["idempotency_key"],
        cost=Decimal(row["cost"]) / SCALE,
        metadata=json.loads(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _proof_from_row(row: aiosqlite.Row) -> ProofArtifact:
    """Convert a database row to a ProofArtifact model."""
    return ProofArtifact(
        id=row["id"],
        job_id=row["job_id"],
        agent_id=row["agent_id"],
        result=row["result"],
        proof_hash=row["proof_hash"],
        proof_data=row["proof_data"],
        signature=row["signature"],
        signer_public_key=row["signer_public_key"],
        counterexample=row["counterexample"],
        property_results=json.loads(row["property_results"]),
        valid_until=row["valid_until"],
        created_at=row["created_at"],
    )


@dataclass
class GatekeeperStorage:
    """Async SQLite storage for verification jobs and proof artifacts."""

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the underlying database connection (for external use)."""
        if self._db is None:
            raise RuntimeError("Storage not connected")
        return self._db

    async def connect(self) -> None:
        db_path = self.dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ----- Verification Jobs -----

    async def create_job(self, job: VerificationJob) -> VerificationJob:
        """Insert a new verification job."""
        await self.db.execute(
            """INSERT INTO verification_jobs
               (id, agent_id, scope, status, properties, timeout_seconds,
                result, proof_artifact_id, webhook_url, idempotency_key,
                cost, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.agent_id,
                job.scope.value,
                job.status.value,
                json.dumps([p.model_dump() for p in job.properties]),
                job.timeout_seconds,
                job.result.value if job.result else None,
                job.proof_artifact_id,
                job.webhook_url,
                job.idempotency_key,
                int(job.cost * SCALE),
                json.dumps(job.metadata),
                job.created_at,
                job.updated_at,
            ),
        )
        await self.db.commit()
        return job

    async def get_job(self, job_id: str) -> VerificationJob | None:
        """Retrieve a verification job by ID."""
        cursor = await self.db.execute("SELECT * FROM verification_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return _job_from_row(row) if row else None

    async def get_job_by_idempotency_key(self, idempotency_key: str) -> VerificationJob | None:
        """Retrieve a job by its idempotency key."""
        cursor = await self.db.execute(
            "SELECT * FROM verification_jobs WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return _job_from_row(row) if row else None

    async def update_job_status(
        self,
        job_id: str,
        status: VerificationStatus,
        result: VerificationResult | None = None,
        proof_artifact_id: str | None = None,
    ) -> VerificationJob | None:
        """Update job status, optionally setting result and proof ID."""
        now = time.time()
        if result is not None and proof_artifact_id is not None:
            await self.db.execute(
                """UPDATE verification_jobs
                   SET status = ?, result = ?, proof_artifact_id = ?, updated_at = ?
                   WHERE id = ?""",
                (status.value, result.value, proof_artifact_id, now, job_id),
            )
        elif result is not None:
            await self.db.execute(
                """UPDATE verification_jobs
                   SET status = ?, result = ?, updated_at = ?
                   WHERE id = ?""",
                (status.value, result.value, now, job_id),
            )
        else:
            await self.db.execute(
                """UPDATE verification_jobs SET status = ?, updated_at = ? WHERE id = ?""",
                (status.value, now, job_id),
            )
        await self.db.commit()
        return await self.get_job(job_id)

    async def update_job_cost(self, job_id: str, cost: Decimal) -> VerificationJob | None:
        """Update a job's cost field.

        v1.2.4 repricing: used by GatekeeperAPI._execute_job to apply the
        heavy-tail solver-time surcharge once the verifier returns the
        observed duration_ms.
        """
        now = time.time()
        await self.db.execute(
            "UPDATE verification_jobs SET cost = ?, updated_at = ? WHERE id = ?",
            (int(cost * SCALE), now, job_id),
        )
        await self.db.commit()
        return await self.get_job(job_id)

    async def list_jobs(
        self,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[VerificationJob]:
        """List verification jobs for an agent with optional filters."""
        query = "SELECT * FROM verification_jobs WHERE agent_id = ?"
        params: list[Any] = [agent_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        if cursor:
            try:
                params.append(float(cursor))
            except (ValueError, TypeError):
                return []
            query += " AND created_at < ?"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(limit, 200))

        cursor_result = await self.db.execute(query, params)
        rows = await cursor_result.fetchall()
        return [_job_from_row(r) for r in rows]

    # ----- Proof Artifacts -----

    async def create_proof(self, proof: ProofArtifact) -> ProofArtifact:
        """Insert a new proof artifact."""
        await self.db.execute(
            """INSERT INTO proof_artifacts
               (id, job_id, agent_id, result, proof_hash, proof_data,
                signature, signer_public_key, counterexample,
                property_results, valid_until, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proof.id,
                proof.job_id,
                proof.agent_id,
                proof.result.value,
                proof.proof_hash,
                proof.proof_data,
                proof.signature,
                proof.signer_public_key,
                proof.counterexample,
                json.dumps(proof.property_results),
                proof.valid_until,
                proof.created_at,
            ),
        )
        await self.db.commit()
        return proof

    async def get_proof(self, proof_id: str) -> ProofArtifact | None:
        """Retrieve a proof artifact by ID."""
        cursor = await self.db.execute("SELECT * FROM proof_artifacts WHERE id = ?", (proof_id,))
        row = await cursor.fetchone()
        return _proof_from_row(row) if row else None

    async def get_proof_by_job(self, job_id: str) -> ProofArtifact | None:
        """Retrieve the proof artifact for a given job."""
        cursor = await self.db.execute("SELECT * FROM proof_artifacts WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        return _proof_from_row(row) if row else None

    async def get_proof_by_hash(self, proof_hash: str) -> ProofArtifact | None:
        """Retrieve a proof by its hash."""
        cursor = await self.db.execute("SELECT * FROM proof_artifacts WHERE proof_hash = ?", (proof_hash,))
        row = await cursor.fetchone()
        return _proof_from_row(row) if row else None
