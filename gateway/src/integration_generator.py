"""Integration package generator — produces LangChain and CrewAI wrappers.

Reads the tool catalog (catalog.json) and generates typed Python code
that wraps each tool for use with LangChain or CrewAI frameworks.
"""

from __future__ import annotations

import json
import os
from typing import Any


def to_class_name(snake: str) -> str:
    """Convert snake_case tool name to PascalCase class name."""
    return "".join(word.capitalize() for word in snake.split("_"))


def schema_to_python_type(schema: dict[str, Any]) -> str:
    """Convert JSON Schema type to Python type annotation string."""
    type_map = {
        "string": "str",
        "number": "float",
        "integer": "int",
        "boolean": "bool",
        "object": "dict",
    }
    json_type = schema.get("type", "")
    if json_type == "array":
        items = schema.get("items", {})
        inner = schema_to_python_type(items)
        return f"list[{inner}]"
    return type_map.get(json_type, "Any")


def load_catalog(service: str | None = None) -> list[dict[str, Any]]:
    """Load tool definitions from catalog.json.

    Args:
        service: Optional filter by service name.

    Returns:
        List of tool definition dicts.
    """
    catalog_path = os.path.join(os.path.dirname(__file__), "catalog.json")
    with open(catalog_path) as f:
        tools = json.load(f)
    if service:
        tools = [t for t in tools if t.get("service") == service]
    return tools


def _generate_fields(input_schema: dict[str, Any]) -> list[tuple[str, str, str, bool]]:
    """Extract (name, type, description, required) tuples from input_schema."""
    props = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    fields = []
    for name, prop in props.items():
        py_type = schema_to_python_type(prop)
        desc = prop.get("description", "")
        is_required = name in required
        fields.append((name, py_type, desc, is_required))
    return fields


def generate_langchain_tool(tool_def: dict[str, Any]) -> str:
    """Generate LangChain StructuredTool code for a single tool."""
    name = tool_def["name"]
    desc = tool_def["description"]
    class_name = to_class_name(name)
    input_class = f"{class_name}Input"

    fields = _generate_fields(tool_def.get("input_schema", {}))

    lines = []
    lines.append(f"class {input_class}(BaseModel):")
    lines.append(f'    """Input for {name}."""')
    for fname, ftype, fdesc, freq in fields:
        if freq:
            lines.append(f'    {fname}: {ftype} = Field(description="{fdesc}")')
        else:
            lines.append(f'    {fname}: Optional[{ftype}] = Field(default=None, description="{fdesc}")')
    if not fields:
        lines.append("    pass")
    lines.append("")

    lines.append(f"async def _{name}_func(**kwargs) -> dict:")
    lines.append(f'    """Call {name} via A2A gateway."""')
    lines.append(f'    return await _call_gateway("{name}", kwargs)')
    lines.append("")

    lines.append(f"{name}_tool = StructuredTool.from_function(")
    lines.append(f"    coroutine=_{name}_func,")
    lines.append(f'    name="{name}",')
    lines.append(f'    description="""{desc}""",')
    lines.append(f"    args_schema={input_class},")
    lines.append(")")
    return "\n".join(lines)


def generate_langchain_module(tools: list[dict[str, Any]]) -> str:
    """Generate a complete LangChain integration module."""
    header = '''"""A2A Platform — LangChain Integration (auto-generated).

Tools for interacting with the A2A Commerce Platform via LangChain.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

A2A_BASE_URL = "http://localhost:8000"


async def _call_gateway(tool_name: str, params: dict[str, Any]) -> dict:
    """Call the A2A gateway API."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{A2A_BASE_URL}/tools/{tool_name}",
            json=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

'''
    tool_blocks = []
    tool_names = []
    for t in tools:
        tool_blocks.append(generate_langchain_tool(t))
        tool_names.append(f"{t['name']}_tool")

    footer = "\n\nA2A_TOOLS = [\n"
    for tn in tool_names:
        footer += f"    {tn},\n"
    footer += "]\n"

    return header + "\n\n".join(tool_blocks) + footer


def generate_crewai_tool(tool_def: dict[str, Any]) -> str:
    """Generate CrewAI BaseTool subclass code for a single tool."""
    name = tool_def["name"]
    desc = tool_def["description"]
    class_name = to_class_name(name)
    tool_class = f"{class_name}Tool"
    input_class = f"{class_name}Input"

    fields = _generate_fields(tool_def.get("input_schema", {}))

    lines = []
    lines.append(f"class {input_class}(BaseModel):")
    lines.append(f'    """Input for {name}."""')
    for fname, ftype, fdesc, freq in fields:
        if freq:
            lines.append(f'    {fname}: {ftype} = Field(description="{fdesc}")')
        else:
            lines.append(f'    {fname}: Optional[{ftype}] = Field(default=None, description="{fdesc}")')
    if not fields:
        lines.append("    pass")
    lines.append("")

    lines.append(f"class {tool_class}(BaseTool):")
    lines.append(f'    name: str = "{name}"')
    lines.append(f'    description: str = """{desc}"""')
    lines.append(f"    args_schema: type[BaseModel] = {input_class}")
    lines.append("")
    lines.append("    def _run(self, **kwargs) -> str:")
    lines.append(f'        return _call_gateway_sync("{name}", kwargs)')
    lines.append("")
    lines.append("    async def _arun(self, **kwargs) -> str:")
    lines.append(f'        return await _call_gateway_async("{name}", kwargs)')
    return "\n".join(lines)


def generate_crewai_module(tools: list[dict[str, Any]]) -> str:
    """Generate a complete CrewAI integration module."""
    header = '''"""A2A Platform — CrewAI Integration (auto-generated).

Tools for interacting with the A2A Commerce Platform via CrewAI.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

A2A_BASE_URL = "http://localhost:8000"


def _call_gateway_sync(tool_name: str, params: dict[str, Any]) -> str:
    """Call the A2A gateway API synchronously."""
    with httpx.Client() as client:
        resp = client.post(
            f"{A2A_BASE_URL}/tools/{tool_name}",
            json=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        return json.dumps(resp.json())


async def _call_gateway_async(tool_name: str, params: dict[str, Any]) -> str:
    """Call the A2A gateway API asynchronously."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{A2A_BASE_URL}/tools/{tool_name}",
            json=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        return json.dumps(resp.json())

'''
    tool_blocks = []
    tool_names = []
    for t in tools:
        tool_blocks.append(generate_crewai_tool(t))
        class_name = to_class_name(t["name"])
        tool_names.append(f"{class_name}Tool")

    footer = "\n\nA2A_TOOLS = [\n"
    for tn in tool_names:
        footer += f"    {tn}(),\n"
    footer += "]\n"

    return header + "\n\n".join(tool_blocks) + footer
