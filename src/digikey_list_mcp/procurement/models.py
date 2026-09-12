from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class PriceBreak(BaseModel):
    quantity: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)


class PartVariation(BaseModel):
    digikey_product_number: str
    package_type: str | None = None
    quantity_available: int = 0
    minimum_order_quantity: int = 1
    standard_package: int | None = None
    marketplace: bool = False
    tariff_active: bool = False
    pricing: list[PriceBreak] = Field(default_factory=list)
    pricing_source: Literal["account", "standard", "unknown"] = "unknown"

    def unit_price_for(self, quantity: int) -> Decimal | None:
        eligible = [row for row in self.pricing if row.quantity <= quantity]
        if eligible:
            return max(eligible, key=lambda row: row.quantity).unit_price
        return self.pricing[0].unit_price if self.pricing else None


class Part(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    checked_at: datetime = Field(default_factory=utc_now)
    manufacturer: str | None = None
    manufacturer_product_number: str | None = None
    description: str | None = None
    product_url: str | None = None
    datasheet_url: str | None = None
    quantity_available: int = 0
    product_status: str | None = None
    discontinued: bool = False
    end_of_life: bool = False
    normally_stocking: bool | None = None
    ncnr: bool = False
    parameters: dict[str, str] = Field(default_factory=dict)
    variations: list[PartVariation] = Field(default_factory=list)


class SearchResult(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    checked_at: datetime = Field(default_factory=utc_now)
    query: str
    products_count: int
    products: list[Part]
    note: str = "Discovery results use standard pricing; validate an exact SKU before purchase."


class MyListSummary(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    list_id: str
    name: str
    date_modified: str | None = None
    can_edit: bool | None = None


class MyListLine(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    unique_id: str | None = None
    requested_part_number: str | None = None
    digikey_product_number: str | None = None
    manufacturer_product_number: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    customer_reference: str | None = None
    reference_designator: str | None = None
    notes: str | None = None
    quantity: int | None = None
    package_type: str | None = None
    quantity_available: int | None = None
    minimum_order_quantity: int | None = None
    unit_price: Decimal | None = None
    raw_quantities: list[dict[str, Any]] = Field(default_factory=list)


class MyListDetail(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    checked_at: datetime = Field(default_factory=utc_now)
    list_id: str
    name: str | None = None
    lines: list[MyListLine] = Field(default_factory=list)
    total_parts: int = 0


class RequestedLine(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    part_number: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    per_assembly: bool = False
    package_type: str | None = None
    customer_reference: str | None = None
    reference_designator: str | None = None
    notes: str | None = None
    target_price: Decimal | None = Field(default=None, ge=0)
    attrition_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class PlannedLine(BaseModel):
    requested_part_number: str
    digikey_product_number: str
    manufacturer_product_number: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    requested_quantity: int
    attrition_adjusted_quantity: int
    final_quantity: int
    package_type: str | None = None
    minimum_order_quantity: int = 1
    quantity_available: int = 0
    unit_price: Decimal | None = None
    extended_price: Decimal | None = None
    customer_reference: str | None = None
    reference_designator: str | None = None
    notes: str | None = None
    target_price: Decimal | None = None
    attrition_percent: Decimal = Decimal("0")
    warnings: list[str] = Field(default_factory=list)
    product_url: str | None = None
    datasheet_url: str | None = None


class PreviewPlan(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    list_id: str | None = None
    list_name: str | None = None
    assembly_count: int = 1
    lines: list[PlannedLine]
    estimated_total: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)


class PreviewResult(BaseModel):
    plan: PreviewPlan
    preview_token: str
    instruction: str = "Review the exact SKUs and quantities, then apply this preview token."


class ApplyResult(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    list_id: str
    list_name: str | None = None
    added_product_numbers: list[str] = Field(default_factory=list)
    skipped_existing_product_numbers: list[str] = Field(default_factory=list)
    already_applied: bool = False
    message: str = "MyList updated. Review it on DigiKey before checkout."


class ValidationLine(BaseModel):
    line: MyListLine
    current_part: Part | None = None
    warnings: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    source: Literal["DigiKey"] = "DigiKey"
    checked_at: datetime = Field(default_factory=utc_now)
    list_id: str
    lines: list[ValidationLine]
    warnings: list[str] = Field(default_factory=list)
