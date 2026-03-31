"""Tests that the OpenAPI ErrorResponse schema matches the live API error format.

The live API returns errors like:
    {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

The OpenAPI spec must document this exact shape.
"""

from __future__ import annotations

import jsonschema
import pytest

from gateway.src.openapi import generate_openapi_spec


@pytest.mark.asyncio
async def test_error_response_schema_has_correct_structure():
    """ErrorResponse schema must have success (bool), error (object with code+message), request_id."""
    spec = generate_openapi_spec()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]

    # Top-level must be an object with success, error, request_id
    assert error_schema["type"] == "object"
    props = error_schema["properties"]

    # success field
    assert "success" in props, "ErrorResponse must have a 'success' field"
    assert props["success"]["type"] == "boolean"

    # error field must be an object with code and message
    assert "error" in props, "ErrorResponse must have an 'error' field"
    assert props["error"]["type"] == "object"
    error_props = props["error"]["properties"]
    assert "code" in error_props, "error object must have a 'code' field"
    assert error_props["code"]["type"] == "string"
    assert "message" in error_props, "error object must have a 'message' field"
    assert error_props["message"]["type"] == "string"

    # request_id field
    assert "request_id" in props, "ErrorResponse must have a 'request_id' field"
    assert props["request_id"]["type"] == "string"

    # required fields: success and error are always present
    assert "success" in error_schema["required"]
    assert "error" in error_schema["required"]


@pytest.mark.asyncio
async def test_error_response_schema_must_not_have_legacy_fields():
    """ErrorResponse must NOT have the old flat 'detail' field."""
    spec = generate_openapi_spec()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]
    props = error_schema["properties"]

    # The old schema had 'detail' as a top-level string -- must be gone
    assert "detail" not in props, "Legacy 'detail' field must be removed from ErrorResponse"


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
