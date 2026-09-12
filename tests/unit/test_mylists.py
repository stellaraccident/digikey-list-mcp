from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import FakeDigiKeyClient

from digikey_list_mcp.digikey.mylists import MyListsAPI
from digikey_list_mcp.procurement.models import PlannedLine


@pytest.mark.asyncio
async def test_create_list_defaults_private_and_cut_tape_friendly() -> None:
    client = FakeDigiKeyClient(["list-123"])
    api = MyListsAPI(client)  # type: ignore[arg-type]
    assert await api.create_list("project") == "list-123"
    body = client.calls[0]["json_body"]
    assert body["ListSettings"]["Visibility"] == "Private"
    assert body["ListSettings"]["PackagePreference"] == "CutTapeOrTR"


@pytest.mark.asyncio
async def test_add_lines_maps_procurement_fields_to_requested_part() -> None:
    client = FakeDigiKeyClient([["line-id"]])
    api = MyListsAPI(client)  # type: ignore[arg-type]
    line = PlannedLine(
        requested_part_number="MPN",
        digikey_product_number="DK-SKU",
        requested_quantity=10,
        attrition_adjusted_quantity=11,
        final_quantity=11,
        package_type="Cut Tape (CT)",
        quantity_available=100,
        target_price=Decimal("0.15"),
        reference_designator="R1,R2",
        attrition_percent=Decimal("10"),
    )
    await api.add_lines("list/1", [line])
    call = client.calls[0]
    assert "list%2F1" in call["path"]
    requested = call["json_body"][0]
    assert requested["RequestedPartNumber"] == "DK-SKU"
    assert requested["ReferenceDesignator"] == "R1,R2"
    assert requested["Quantities"][0]["Quantity"] == 11


@pytest.mark.asyncio
async def test_get_list_paginates_parts() -> None:
    first_page = {
        "PartsList": [{"UniqueId": str(index)} for index in range(100)],
        "TotalParts": 101,
    }
    second_page = {"PartsList": [{"UniqueId": "100"}], "TotalParts": 101}
    client = FakeDigiKeyClient([{"ListName": "project"}, first_page, second_page])
    api = MyListsAPI(client)  # type: ignore[arg-type]

    result = await api.get_list("list-123")

    assert result.total_parts == 101
    assert len(result.lines) == 101
    assert client.calls[2]["params"]["startIndex"] == 100


@pytest.mark.asyncio
async def test_delete_list_uses_encoded_id() -> None:
    client = FakeDigiKeyClient([None])
    api = MyListsAPI(client)  # type: ignore[arg-type]

    await api.delete_list("list/123")

    assert client.calls[0]["method"] == "DELETE"
    assert client.calls[0]["path"].endswith("list%2F123")
    assert client.calls[0]["expected_status"] == {200, 204}
