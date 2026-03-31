"""A2A Toolkit for LangChain — loads tools dynamically from the catalog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool, BaseToolkit

from a2a_langchain._base import create_tool


class A2AToolkit(BaseToolkit):
    """LangChain toolkit that dynamically generates tools from the A2A catalog.

    Usage::

        toolkit = await A2AToolkit.from_client(client)
        tools = toolkit.get_tools()
        # Pass tools to an agent
    """

    tools: list[BaseTool] = []

    def get_tools(self) -> list[BaseTool]:
        return self.tools

    @classmethod
    async def from_client(
        cls,
        client: Any,
        services: Sequence[str] | None = None,
    ) -> A2AToolkit:
        """Create a toolkit from an A2AClient.

        Args:
            client: An A2AClient instance.
            services: Optional list of service names to filter tools by.
                      If None, all tools from the catalog are included.
        """
        catalog = await client.pricing()

        if services is not None:
            service_set = set(services)
            catalog = [entry for entry in catalog if entry.get("service") in service_set]

        tools = [create_tool(client, entry) for entry in catalog]

        return cls(tools=tools)
