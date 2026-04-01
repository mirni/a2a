"""Tests that the OpenAPI ErrorResponse schema matches the RFC 9457 Problem Details format.

The live API returns errors like:
    {"type": "https://api.greenhelix.net/errors/xxx", "title": "Bad Request", "status": 400, "detail": "..."}

The OpenAPI spec must document this exact shape.
"""

from __future__ import annotations

import jsonschema
import pytest

from gateway.src.openapi import generate_openapi_spec


@pytest.mark.asyncio
async def test_error_response_schema_has_rfc9457_structure():
    """ErrorResponse schema must have type, title, status, detail (RFC 9457)."""
    spec = generate_openapi_spec()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]

    # Top-level must be an object with RFC 9457 fields
    assert error_schema["type"] == "object"
    props = error_schema["properties"]

    # type field (URI reference)
    assert "type" in props, "ErrorResponse must have a 'type' field"
    assert props["type"]["type"] == "string"

    # title field
    assert "title" in props, "ErrorResponse must have a 'title' field"
    assert props["title"]["type"] == "string"

    # status field (integer HTTP status code)
    assert "status" in props, "ErrorResponse must have a 'status' field"
    assert props["status"]["type"] == "integer"

    # detail field
    assert "detail" in props, "ErrorResponse must have a 'detail' field"
    assert props["detail"]["type"] == "string"

    # required fields
    assert "type" in error_schema["required"]
    assert "title" in error_schema["required"]
    assert "status" in error_schema["required"]


@pytest.mark.asyncio
async def test_error_response_schema_must_not_have_legacy_fields():
    """ErrorResponse must NOT have the old 'success' or nested 'error' fields."""
    spec = generate_openapi_spec()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]
    props = error_schema["properties"]

    # The old schema had 'success' and 'error' as top-level fields -- must be gone
    assert "success" not in props, "Legacy 'success' field must be removed from ErrorResponse"
    assert "error" not in props, "Legacy 'error' field must be removed from ErrorResponse"
    assert "request_id" not in props, "Legacy 'request_id' field must be removed from ErrorResponse"


@pytest.mark.asyncio
async def test_actual_error_response_matches_schema(client):
    """An actual error response from the API must validate against the OpenAPI ErrorResponse schema."""
    # Trigger a real error: execute a tool that doesn't exist
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool_xyz", "params": {}},
        headers={"Authorization": "Bearer fake-key-for-error-test"},
    )
    assert resp.status_code >= 400

    body = resp.json()

    # Fetch the OpenAPI schema for ErrorResponse
    spec = generate_openapi_spec()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]

    # Validate the actual response body against the schema
    jsonschema.validate(instance=body, schema=error_schema)
