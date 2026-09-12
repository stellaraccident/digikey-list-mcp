from __future__ import annotations

from typing import Any
from urllib.parse import quote

from digikey_list_mcp.digikey.client import DigiKeyClient
from digikey_list_mcp.procurement.models import MyListDetail, MyListSummary, PlannedLine
from digikey_list_mcp.procurement.normalize import normalize_list_detail, normalize_list_summary


class MyListsAPI:
    def __init__(self, client: DigiKeyClient) -> None:
        self.client = client

    async def list_lists(self, *, limit: int = 50, start_index: int = 0) -> list[MyListSummary]:
        payload = await self.client.request_json(
            "GET",
            "/mylists/v1/lists",
            params={"startIndex": max(0, start_index), "limit": max(1, min(limit, 100))},
        )
        rows = payload if isinstance(payload, list) else payload.get("Lists", [])
        return [normalize_list_summary(row) for row in rows]

    async def find_by_name(self, name: str) -> MyListSummary | None:
        for item in await self.list_lists(limit=100):
            if item.name.casefold() == name.casefold():
                return item
        return None

    async def get_list(self, list_id: str) -> MyListDetail:
        encoded = quote(list_id, safe="")
        metadata = await self.client.request_json("GET", f"/mylists/v1/lists/{encoded}")
        start_index = 0
        rows: list[dict[str, Any]] = []
        total = 0
        while True:
            page = await self.client.request_json(
                "GET",
                f"/mylists/v1/lists/{encoded}/parts",
                params={
                    "startIndex": start_index,
                    "limit": 100,
                    "assemblies": 1,
                    "includeAttrition": True,
                },
            )
            if isinstance(page, list):
                page_rows = page
                total = max(total, start_index + len(page_rows))
            else:
                page_rows = page.get("PartsList") or []
                total = int(page.get("TotalParts", start_index + len(page_rows)))
            rows.extend(page_rows)
            if not page_rows or len(rows) >= total or len(page_rows) < 100:
                break
            start_index += len(page_rows)
        parts = {"PartsList": rows, "TotalParts": max(total, len(rows))}
        return normalize_list_detail(list_id, metadata, parts)

    async def create_list(self, name: str, *, created_by: str = "digikey-list-mcp") -> str:
        payload = {
            "ListName": name,
            "CreatedBy": created_by,
            "Tags": ["digikey-list-mcp"],
            "Source": "other",
            "ListSettings": {
                "Visibility": "Private",
                "PackagePreference": "CutTapeOrTR",
                "ColumnPreferences": [],
                "AutoCorrectQuantities": True,
                "AttritionEnabled": True,
                "AutoPopulateCref": True,
            },
        }
        result = await self.client.request_json("POST", "/mylists/v1/lists", json_body=payload)
        list_id = result.get("ListId") if isinstance(result, dict) else result
        if list_id in (None, ""):
            raise ValueError("DigiKey did not return an ID for the newly created MyList.")
        return str(list_id).strip('"')

    async def delete_list(self, list_id: str) -> None:
        await self.client.request_json(
            "DELETE",
            f"/mylists/v1/lists/{quote(list_id, safe='')}",
            expected_status={200, 204},
        )

    async def add_lines(self, list_id: str, lines: list[PlannedLine]) -> list[str]:
        body = [self._requested_part(line) for line in lines]
        result = await self.client.request_json(
            "POST",
            f"/mylists/v1/lists/{quote(list_id, safe='')}/parts",
            params={"index": 0},
            json_body=body,
        )
        return [str(item) for item in (result or [])]

    async def update_line(self, list_id: str, unique_id: str, line: PlannedLine) -> None:
        await self.client.request_json(
            "PUT",
            f"/mylists/v1/lists/{quote(list_id, safe='')}/parts/{quote(unique_id, safe='')}",
            json_body=self._requested_part(line),
            expected_status={200, 204},
        )

    async def remove_line(self, list_id: str, unique_id: str) -> None:
        await self.client.request_json(
            "DELETE",
            f"/mylists/v1/lists/{quote(list_id, safe='')}/parts/{quote(unique_id, safe='')}",
            expected_status={200, 204},
        )

    @staticmethod
    def _requested_part(line: PlannedLine) -> dict[str, Any]:
        return {
            "RequestedPartNumber": line.digikey_product_number,
            "OriginalPartNumber": line.requested_part_number,
            "ManufacturerName": line.manufacturer,
            "CustomerReference": line.customer_reference,
            "ReferenceDesignator": line.reference_designator,
            "Notes": line.notes,
            "SelectedQuantityIndex": 0,
            "Attrition": float(line.attrition_percent),
            "AlternateParts": [],
            "Quantities": [
                {
                    "SelectedPackType": line.package_type,
                    "SelectedSubPackType": None,
                    "Quantity": line.final_quantity,
                    "TargetPrice": (
                        float(line.target_price) if line.target_price is not None else None
                    ),
                }
            ],
        }
