"""Tests for handle_product_exception logging of unknown exceptions (audit C2).

The error handler must LOG the full exception details (message, type, traceback)
for unknown exceptions while returning a sanitized 500 to the client.  Without
this, production OperationalErrors are impossible to diagnose remotely.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3

import pytest

pytestmark = pytest.mark.asyncio


async def test_unknown_exception_is_logged_with_full_details():
    """handle_product_exception must log unknown exceptions at ERROR level."""
    from unittest.mock import MagicMock

    from gateway.src.errors import handle_product_exception

    request = MagicMock()
    request.url.path = "/v1/payments/intents/abc123/capture"

    # Simulate the OperationalError that occurs on production
    exc = sqlite3.OperationalError("no such column: source_type")

    logger = logging.getLogger("a2a.errors")
    handler = logging.StreamHandler(io.StringIO())
    handler.setLevel(logging.ERROR)
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    try:
        resp = await handle_product_exception(request, exc)
        log_output = handler.stream.getvalue()
    finally:
        logger.removeHandler(handler)

    # Response must be sanitized (no raw SQL error in response body)
    assert resp.status_code == 500
    body_bytes = resp.body
    body = json.loads(body_bytes)
    assert body["detail"] == "Internal error: OperationalError"

    # But the FULL error message must appear in logs
    assert "no such column: source_type" in log_output
    assert "OperationalError" in log_output


async def test_known_exception_is_not_logged_as_error():
    """Known exceptions (e.g. IntentNotFoundError) should NOT be logged at ERROR."""
    from unittest.mock import MagicMock

    from payments_src.engine import IntentNotFoundError

    from gateway.src.errors import handle_product_exception

    request = MagicMock()
    request.url.path = "/v1/payments/intents/abc123"

    exc = IntentNotFoundError("Intent abc123 not found")

    logger = logging.getLogger("a2a.errors")
    handler = logging.StreamHandler(io.StringIO())
    handler.setLevel(logging.ERROR)
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    try:
        resp = await handle_product_exception(request, exc)
        log_output = handler.stream.getvalue()
    finally:
        logger.removeHandler(handler)

    assert resp.status_code == 404
    # Known exceptions should NOT appear in error logs
    assert log_output == ""
