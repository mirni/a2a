"""Base tool class and factory for A2A CrewAI integration."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from crewai.tools import BaseTool
from pydantic import ConfigDict, Field, create_model

from sdk.src.a2a_client.errors import A2AError

# JSON-schema type -> Python type mapping
_JSON_TYPE_MAP = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
}


class A2ACrewTool(BaseTool):
    """Base CrewAI tool that delegates to an A2AClient.execute() call."""

    client: Any = Field(exclude=True)
    tool_name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, **kwargs: Any) -> str:
        try:
            result = asyncio.run(self.client.execute(self.tool_name, kwargs))
        except A2AError as exc:
            return json.dumps(
                {"error": True, "message": str(exc), "code": exc.code, "status": exc.status},
                default=str,
            )
        return json.dumps(result.result, default=str)


def _normalize_tool_def(tool_def: Any) -> dict:
    """Normalize a catalog entry (dict or ToolPricing dataclass) to a dict."""
    if hasattr(tool_def, "__dataclass_fields__"):
        from dataclasses import asdict

        tool_def = asdict(tool_def)
    return dict(tool_def) if not isinstance(tool_def, dict) else tool_def


def _build_args_schema(tool_def: dict) -> type:
    """Dynamically build a Pydantic model from a catalog entry's JSON schema."""
    schema = tool_def.get("input_schema", tool_def.get("schema", {}))
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _JSON_TYPE_MAP.get(prop.get("type", "string"), str)
        description = prop.get("description", "")
        if name in required:
            fields[name] = (py_type, Field(description=description))
        else:
            fields[name] = (
                py_type | None,
                Field(default=None, description=description),
            )

    tool_name = tool_def.get("name", tool_def.get("tool", "unknown"))
    model_name = f"{tool_name}_input"
    return create_model(model_name, **fields)


def create_tool(client: Any, tool_def: Any) -> BaseTool:
    """Factory: build a CrewAI tool from an A2A catalog entry.

    Accepts both dict format and ToolPricing dataclass instances.
    """
    tool_def = _normalize_tool_def(tool_def)
    args_schema = _build_args_schema(tool_def)
    tool_name = tool_def.get("name", tool_def.get("tool"))

    class _DynamicA2ACrewTool(A2ACrewTool):
        pass

    return _DynamicA2ACrewTool(
        client=client,
        tool_name=tool_name,
        name=tool_name,
        description=tool_def.get("description", ""),
        description_updated=True,
        args_schema=args_schema,
    )
