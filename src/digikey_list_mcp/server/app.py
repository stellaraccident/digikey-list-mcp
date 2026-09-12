from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from digikey_list_mcp.procurement.models import PlannedLine, RequestedLine
from digikey_list_mcp.runtime import Runtime

SERVER_INSTRUCTIONS = """
Use DigiKey search results only for discovery. Resolve and refresh an exact DigiKey SKU before
proposing a purchase line. Use preview then apply for MyLists writes. Never imply that alternates
are electrically or mechanically equivalent without checking the relevant constraints. This server
does not place orders or perform checkout. Attribute returned catalog data to DigiKey.
""".strip()


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


def create_server(runtime: Runtime | None = None) -> MCPServer:
    runtime = runtime or Runtime()
    server = MCPServer("digikey-list-mcp", instructions=SERVER_INSTRUCTIONS)

    read_tool = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
    preview_tool = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
    write_tool = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
    )
    destructive_tool = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
    )

    @server.tool(annotations=read_tool)
    async def digikey_search_parts(
        query: str,
        limit: int = 10,
        in_stock: bool = True,
        exclude_marketplace: bool = True,
    ) -> dict[str, Any]:
        """Search DigiKey for discovery candidates using standard pricing."""
        async with runtime.services() as services:
            result = await services.products.search(
                query,
                limit=limit,
                in_stock=in_stock,
                exclude_marketplace=exclude_marketplace,
            )
            return _dump(result)

    @server.tool(annotations=read_tool)
    async def digikey_get_part(
        product_number: str, manufacturer_id: str | None = None
    ) -> dict[str, Any]:
        """Get current exact product, variation, stock, lifecycle, and pricing data from DigiKey."""
        async with runtime.services() as services:
            result = await services.products.get_part(
                product_number, manufacturer_id=manufacturer_id
            )
            return _dump(result)

    @server.tool(annotations=read_tool)
    async def digikey_compare_parts(product_numbers: list[str]) -> dict[str, Any]:
        """Fetch exact current details for two or more parts for an attributed comparison."""
        if not 2 <= len(product_numbers) <= 12:
            raise ValueError("Provide between 2 and 12 product numbers.")
        async with runtime.services() as services:
            parts = await asyncio.gather(
                *(services.products.get_part(number) for number in product_numbers)
            )
            return {
                "source": "DigiKey",
                "parts": _dump(parts),
                "warning": (
                    "Confirm pinout, package, and electrical constraints before substitution."
                ),
            }

    @server.tool(annotations=read_tool)
    async def digikey_find_alternates(product_number: str, limit: int = 10) -> dict[str, Any]:
        """Return DigiKey substitutions and recommendations as unverified candidates."""
        async with runtime.services() as services:
            substitutions, recommendations = await asyncio.gather(
                services.products.substitutions(product_number, limit=limit),
                services.products.recommendations(product_number, limit=limit),
            )
            return {
                "source": "DigiKey",
                "substitutions": _dump(substitutions),
                "recommendations": _dump(recommendations),
                "warning": "Candidates are not guaranteed equivalents; verify every constraint.",
            }

    @server.tool(annotations=read_tool)
    async def digikey_list_mylists(limit: int = 50) -> list[dict[str, Any]]:
        """List the authenticated user's DigiKey MyLists."""
        async with runtime.services() as services:
            return _dump(await services.mylists.list_lists(limit=limit))

    @server.tool(annotations=read_tool)
    async def digikey_get_mylist(list_id: str) -> dict[str, Any]:
        """Read one DigiKey MyList and its current list-line data."""
        async with runtime.services() as services:
            return _dump(await services.mylists.get_list(list_id))

    @server.tool(annotations=read_tool)
    async def digikey_validate_mylist(list_id: str) -> dict[str, Any]:
        """Refresh every MyList line against exact DigiKey product data and report warnings."""
        async with runtime.services() as services:
            return _dump(await services.planner.validate(list_id))

    @server.tool(annotations=preview_tool)
    async def digikey_preview_mylist_changes(
        lines: list[RequestedLine],
        list_id: str | None = None,
        list_name: str | None = None,
        assembly_count: int = 1,
    ) -> dict[str, Any]:
        """Validate exact SKUs and return an expiring, signed preview without changing DigiKey."""
        async with runtime.services() as services:
            result = await services.planner.preview(
                lines,
                list_id=list_id,
                list_name=list_name,
                assembly_count=assembly_count,
            )
            return _dump(result)

    @server.tool(annotations=write_tool)
    async def digikey_apply_mylist_changes(preview_token: str) -> dict[str, Any]:
        """Apply exactly one previously reviewed preview to DigiKey MyLists idempotently."""
        async with runtime.services() as services:
            return _dump(await services.planner.apply(preview_token))

    @server.tool(annotations=write_tool)
    async def digikey_update_mylist_line(
        list_id: str,
        unique_id: str,
        line: RequestedLine,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Preview or explicitly confirm replacement of one existing MyList line."""
        async with runtime.services() as services:
            preview = await services.planner.preview([line], list_id=list_id)
            planned: PlannedLine = preview.plan.lines[0]
            if not confirm:
                return {
                    "confirmed": False,
                    "proposed_line": _dump(planned),
                    "instruction": (
                        "Review this line and call again with confirm=true and identical input."
                    ),
                }
            await services.mylists.update_line(list_id, unique_id, planned)
            return {
                "source": "DigiKey",
                "confirmed": True,
                "list_id": list_id,
                "unique_id": unique_id,
                "updated_line": _dump(planned),
            }

    @server.tool(annotations=destructive_tool)
    async def digikey_remove_mylist_line(
        list_id: str, unique_id: str, confirm: bool = False
    ) -> dict[str, Any]:
        """Delete one MyList line only when the user explicitly confirms the exact IDs."""
        if not confirm:
            return {
                "confirmed": False,
                "list_id": list_id,
                "unique_id": unique_id,
                "instruction": "Deletion was not performed. Call again with confirm=true.",
            }
        async with runtime.services() as services:
            await services.mylists.remove_line(list_id, unique_id)
        return {
            "source": "DigiKey",
            "confirmed": True,
            "list_id": list_id,
            "unique_id": unique_id,
        }

    return server
