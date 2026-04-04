"""Tests for SQLite DB file permissions.

DB files should have 0o600 (owner read/write only) after startup.
"""

from __future__ import annotations

import os
import stat

import pytest

pytestmark = pytest.mark.asyncio


class TestDBPermissions:
    """SQLite database files should have restricted permissions."""

    async def test_billing_db_permissions(self, app, tmp_data_dir):
        """Billing DB should be owner-only (0o600)."""
        db_path = os.path.join(tmp_data_dir, "billing.db")
        if os.path.isfile(db_path):
            mode = os.stat(db_path).st_mode
            assert mode & stat.S_IRWXG == 0, "Group should have no access"
            assert mode & stat.S_IRWXO == 0, "Others should have no access"
            assert mode & stat.S_IRUSR, "Owner should have read"
            assert mode & stat.S_IWUSR, "Owner should have write"
