"""Base tool class and factory for A2A LangChain integration."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model


# JSON-schema type → Python type mapping
_JSON_TYPE_MAP = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
}


class A2ABaseTool(BaseTool):
    """Base tool that delegates to an A2AClient.execute() call."""

    client: Any = Field(exclude=True)
    tool_name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.execute(self.tool_name, kwargs)
        return json.dumps(result.result, default=str)

    def _run(self, **kwargs: Any) -> str:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self._arun(**kwargs)
                ).result()
        return asyncio.run(self._arun(**kwargs))


def _build_args_schema(tool_def: dict) -> Type[BaseModel]:
    """Dynamically build a Pydantic model from a catalog entry's JSON schema."""
    schema = tool_def.get("schema", {})
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
                Optional[py_type],
                Field(default=None, description=description),
            )

    model_name = f"{tool_def['tool']}_input"
    return create_model(model_name, **fields)


def create_tool(client: Any, tool_def: dict) -> BaseTool:
    """Factory: build a LangChain StructuredTool from an A2A catalog entry."""

    args_schema = _build_args_schema(tool_def)
    tool_name = tool_def["tool"]

    async def _arun_impl(**kwargs: Any) -> str:
        result = await client.execute(tool_name, kwargs)
        return json.dumps(result.result, default=str)

    def _run_impl(**kwargs: Any) -> str:
        return asyncio.run(_arun_impl(**kwargs))

    return StructuredTool(
        name=tool_name,
        description=tool_def.get("description", ""),
        args_schema=args_schema,
        func=_run_impl,
        coroutine=_arun_impl,
    )
