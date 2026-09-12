from __future__ import annotations

from decimal import Decimal

import pytest

from digikey_list_mcp.config import Settings
from digikey_list_mcp.errors import PreviewError
from digikey_list_mcp.procurement.models import (
    MyListDetail,
    MyListLine,
    Part,
    PartVariation,
    PriceBreak,
    RequestedLine,
)
from digikey_list_mcp.procurement.plan_mylist import MyListPlanner, OperationJournal


class FakeProducts:
    def __init__(self, part: Part) -> None:
        self.part = part

    async def get_part(self, _: str) -> Part:
        return self.part


class FakeLists:
    def __init__(self) -> None:
        self.created = 0
        self.added = []
        self.lines: list[MyListLine] = []

    async def find_by_name(self, name: str):
        return None

    async def create_list(self, name: str) -> str:
        self.created += 1
        return "new-list"

    async def get_list(self, list_id: str) -> MyListDetail:
        return MyListDetail(list_id=list_id, name="project", lines=self.lines)

    async def add_lines(self, list_id: str, lines: list) -> list[str]:
        self.added.extend(lines)
        return ["new-line"]


def sample_part() -> Part:
    return Part(
        manufacturer="Yageo",
        manufacturer_product_number="RC0603",
        description="resistor",
        quantity_available=1000,
        datasheet_url="https://example.com/data.pdf",
        variations=[
            PartVariation(
                digikey_product_number="REEL-ND",
                package_type="Tape & Reel (TR)",
                quantity_available=10000,
                minimum_order_quantity=5000,
                pricing=[PriceBreak(quantity=5000, unit_price=Decimal("0.01"))],
            ),
            PartVariation(
                digikey_product_number="CUT-ND",
                package_type="Cut Tape (CT)",
                quantity_available=1000,
                minimum_order_quantity=1,
                pricing=[
                    PriceBreak(quantity=1, unit_price=Decimal("0.10")),
                    PriceBreak(quantity=10, unit_price=Decimal("0.05")),
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_preview_selects_cut_tape_and_exposes_quantity_math(memory_store, tmp_path) -> None:
    planner = MyListPlanner(
        FakeProducts(sample_part()),  # type: ignore[arg-type]
        FakeLists(),  # type: ignore[arg-type]
        Settings(preview_ttl_seconds=300),
        memory_store,
        journal=OperationJournal(tmp_path / "journal.json"),
    )
    result = await planner.preview(
        [
            RequestedLine(
                part_number="RC0603",
                quantity=2,
                per_assembly=True,
                attrition_percent=Decimal("10"),
            )
        ],
        list_name="project",
        assembly_count=5,
    )
    line = result.plan.lines[0]
    assert line.requested_quantity == 10
    assert line.attrition_adjusted_quantity == 11
    assert line.final_quantity == 11
    assert line.digikey_product_number == "CUT-ND"
    assert line.unit_price == Decimal("0.05")
    assert result.plan.estimated_total == Decimal("0.55")


@pytest.mark.asyncio
async def test_tampered_preview_is_rejected(memory_store, tmp_path) -> None:
    planner = MyListPlanner(
        FakeProducts(sample_part()),  # type: ignore[arg-type]
        FakeLists(),  # type: ignore[arg-type]
        Settings(),
        memory_store,
        journal=OperationJournal(tmp_path / "journal.json"),
    )
    result = await planner.preview(
        [RequestedLine(part_number="CUT-ND", quantity=1)], list_name="project"
    )
    token = result.preview_token
    with pytest.raises(PreviewError, match=r"malformed|not issued"):
        planner.codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))


@pytest.mark.asyncio
async def test_apply_is_idempotent(memory_store, tmp_path) -> None:
    lists = FakeLists()
    planner = MyListPlanner(
        FakeProducts(sample_part()),  # type: ignore[arg-type]
        lists,  # type: ignore[arg-type]
        Settings(),
        memory_store,
        journal=OperationJournal(tmp_path / "journal.json"),
    )
    preview = await planner.preview(
        [RequestedLine(part_number="CUT-ND", quantity=3)], list_name="project"
    )
    first = await planner.apply(preview.preview_token)
    second = await planner.apply(preview.preview_token)
    assert first.added_product_numbers == ["CUT-ND"]
    assert second.already_applied is True
    assert lists.created == 1
    assert len(lists.added) == 1


@pytest.mark.asyncio
async def test_apply_skips_equivalent_existing_line(memory_store, tmp_path) -> None:
    lists = FakeLists()
    lists.lines = [
        MyListLine(
            digikey_product_number="CUT-ND",
            quantity=3,
            package_type="Cut Tape (CT)",
        )
    ]
    planner = MyListPlanner(
        FakeProducts(sample_part()),  # type: ignore[arg-type]
        lists,  # type: ignore[arg-type]
        Settings(),
        memory_store,
        journal=OperationJournal(tmp_path / "journal.json"),
    )
    preview = await planner.preview(
        [RequestedLine(part_number="CUT-ND", quantity=3)], list_id="existing"
    )
    result = await planner.apply(preview.preview_token)
    assert result.skipped_existing_product_numbers == ["CUT-ND"]
    assert lists.added == []
