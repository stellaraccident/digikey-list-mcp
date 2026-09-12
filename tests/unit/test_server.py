from __future__ import annotations

import pytest
from mcp import Client

from digikey_list_mcp.server import create_server


@pytest.mark.asyncio
async def test_mcp_client_discovers_tools_and_safety_annotations() -> None:
    async with Client(create_server()) as client:
        result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}
    assert len(tools) == 11
    assert tools["digikey_search_parts"].annotations.read_only_hint is True
    assert tools["digikey_apply_mylist_changes"].annotations.read_only_hint is False
    assert tools["digikey_remove_mylist_line"].annotations.destructive_hint is True
