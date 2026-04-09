"""Shared fixtures for verifier connector tests."""

from __future__ import annotations

import os
import sys

# Ensure project root is importable
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
