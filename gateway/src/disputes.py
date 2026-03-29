"""Dispute resolution engine — bridges payments (escrow) and identity (trust).

Disputes are opened against escrows. Resolution can be:
- "refund": return funds to payer (calls escrow.refund_escrow)
- "release": release funds to payee (calls escrow.release_escrow)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import aiosqlite


class DisputeNotFoundError(Exception):
    """Raised when a dispute ID is not found."""

    pass


class DisputeStateError(Exception):
    """Raised when a dispute operation is invalid for the current state."""

    pass


class DisputeEngine:
    """Manages dispute lifecycle: open → respond → resolve."""

    def __init__(self, dsn: str, payment_engine: Any):
        self.dsn = dsn.replace("sqlite:///", "")
        self.payment_engine = payment_engine
        self.db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        from shared_src.db_security import harden_connection

        self.db = await aiosqlite.connect(self.dsn)
        self.db.row_factory = aiosqlite.Row
        await harden_connection(self.db)
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS disputes (
                id            TEXT PRIMARY KEY,
                escrow_id     TEXT NOT NULL,
                opener        TEXT NOT NULL,
                respondent    TEXT,
                reason        TEXT NOT NULL DEFAULT '',
                response      TEXT,
                status        TEXT NOT NULL DEFAULT 'open',
                resolution    TEXT,
                resolved_by   TEXT,
                notes         TEXT,
                created_at    REAL NOT NULL,
                responded_at  REAL,
                resolved_at   REAL
            );
            CREATE INDEX IF NOT EXISTS idx_dispute_escrow ON disputes(escrow_id);
            CREATE INDEX IF NOT EXISTS idx_dispute_status ON disputes(status);
            """
        )

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def open_dispute(self, escrow_id: str, opener: str, reason: str = "") -> dict[str, Any]:
        """Open a dispute against an escrow."""
        # Verify escrow exists and is held
        escrow = await self.payment_engine.get_escrow(escrow_id)
        if escrow.status.value != "held":
            raise DisputeStateError(f"Cannot dispute escrow in '{escrow.status.value}' state")

        dispute_id = uuid.uuid4().hex
        now = time.time()
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO disputes (id, escrow_id, opener, respondent, reason, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?)",
            (dispute_id, escrow_id, opener, escrow.payee if opener == escrow.payer else escrow.payer, reason, now),
        )
        await self.db.commit()
        return {
            "id": dispute_id,
            "escrow_id": escrow_id,
            "opener": opener,
            "status": "open",
            "reason": reason,
            "created_at": now,
        }

    async def respond_to_dispute(self, dispute_id: str, respondent: str, response: str) -> dict[str, Any]:
        """Respondent adds their response to the dispute."""
        dispute = await self._get_dispute(dispute_id)
        if dispute["status"] != "open":
            raise DisputeStateError(f"Cannot respond to dispute in '{dispute['status']}' state")

        now = time.time()
        assert self.db is not None
        await self.db.execute(
            "UPDATE disputes SET response = ?, responded_at = ?, status = 'responded' WHERE id = ?",
            (response, now, dispute_id),
        )
        await self.db.commit()
        return {
            "id": dispute_id,
            "status": "responded",
            "respondent": respondent,
            "response": response,
            "responded_at": now,
        }

    async def resolve_dispute(
        self,
        dispute_id: str,
        resolution: str,
        resolved_by: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Resolve a dispute: 'refund' returns funds to payer, 'release' pays the payee."""
        dispute = await self._get_dispute(dispute_id)
        if dispute["status"] not in ("open", "responded"):
            raise DisputeStateError(f"Cannot resolve dispute in '{dispute['status']}' state")

        if resolution not in ("refund", "release"):
            raise ValueError(f"Invalid resolution: {resolution}. Must be 'refund' or 'release'.")

        # Execute the resolution
        escrow_id = dispute["escrow_id"]
        if resolution == "refund":
            await self.payment_engine.refund_escrow(escrow_id)
        else:
            await self.payment_engine.release_escrow(escrow_id)

        now = time.time()
        assert self.db is not None
        await self.db.execute(
            "UPDATE disputes SET status = 'resolved', resolution = ?, resolved_by = ?, "
            "notes = ?, resolved_at = ? WHERE id = ?",
            (resolution, resolved_by, notes, now, dispute_id),
        )
        await self.db.commit()
        return {
            "id": dispute_id,
            "status": "resolved",
            "resolution": resolution,
            "resolved_by": resolved_by,
            "notes": notes,
            "resolved_at": now,
        }

    async def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Public getter for a dispute."""
        return await self._get_dispute(dispute_id)

    async def _get_dispute(self, dispute_id: str) -> dict[str, Any]:
        assert self.db is not None
        cursor = await self.db.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,))
        row = await cursor.fetchone()
        if row is None:
            raise DisputeNotFoundError(f"Dispute not found: {dispute_id}")
        return dict(row)
