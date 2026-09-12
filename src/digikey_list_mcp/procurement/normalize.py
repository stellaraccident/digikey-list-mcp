from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from digikey_list_mcp.procurement.models import (
    MyListDetail,
    MyListLine,
    MyListSummary,
    Part,
    PartVariation,
    PriceBreak,
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in (
            "Name",
            "Status",
            "ProductDescription",
            "DetailedDescription",
            "Text",
            "Value",
        ):
            if value.get(key) is not None:
                return str(value[key])
        return None
    return str(value)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_price_breaks(rows: list[dict[str, Any]]) -> list[PriceBreak]:
    result: list[PriceBreak] = []
    for row in rows:
        quantity = _int(row.get("BreakQuantity") or row.get("Quantity"), 1)
        unit_price = _decimal(row.get("UnitPrice"))
        if unit_price is None:
            continue
        result.append(
            PriceBreak(
                quantity=max(1, quantity),
                unit_price=unit_price,
                total_price=_decimal(row.get("TotalPrice")),
            )
        )
    return sorted(result, key=lambda item: item.quantity)


def normalize_product(payload: dict[str, Any]) -> Part:
    product = payload.get("Product", payload)
    manufacturer = _text(product.get("Manufacturer"))
    status = _text(product.get("ProductStatus"))
    parameters: dict[str, str] = {}
    for item in product.get("Parameters") or []:
        name = _text(item.get("Parameter")) or _text(item.get("ParameterText"))
        value = _text(item.get("Value")) or _text(item.get("ValueText"))
        if name and value:
            parameters[name] = value

    variations: list[PartVariation] = []
    for item in product.get("ProductVariations") or []:
        sku = _text(item.get("DigiKeyProductNumber"))
        if not sku:
            continue
        account_pricing = normalize_price_breaks(item.get("MyPricing") or [])
        standard_pricing = normalize_price_breaks(item.get("StandardPricing") or [])
        variations.append(
            PartVariation(
                digikey_product_number=sku,
                package_type=_text(item.get("PackageType")),
                quantity_available=_int(
                    item.get("QuantityAvailableforPackageType") or item.get("QuantityAvailable")
                ),
                minimum_order_quantity=max(1, _int(item.get("MinimumOrderQuantity"), 1)),
                standard_package=(
                    _int(item.get("StandardPackage"))
                    if item.get("StandardPackage") is not None
                    else None
                ),
                marketplace=bool(item.get("MarketPlace", False)),
                tariff_active=bool(item.get("TariffActive", False)),
                pricing=account_pricing or standard_pricing,
                pricing_source=(
                    "account" if account_pricing else "standard" if standard_pricing else "unknown"
                ),
            )
        )

    return Part(
        manufacturer=manufacturer,
        manufacturer_product_number=_text(product.get("ManufacturerProductNumber")),
        description=_text(product.get("Description")),
        product_url=_text(product.get("ProductUrl")),
        datasheet_url=_text(product.get("DatasheetUrl")),
        quantity_available=_int(product.get("QuantityAvailable")),
        product_status=status,
        discontinued=bool(product.get("Discontinued", False)),
        end_of_life=bool(product.get("EndOfLife", False)),
        normally_stocking=product.get("NormallyStocking"),
        ncnr=bool(product.get("Ncnr", False)),
        parameters=parameters,
        variations=variations,
    )


def normalize_list_summary(payload: dict[str, Any]) -> MyListSummary:
    list_id = _text(payload.get("ListId") or payload.get("Id")) or ""
    name = _text(payload.get("ListName") or payload.get("Name")) or list_id
    return MyListSummary(
        list_id=list_id,
        name=name,
        date_modified=_text(payload.get("DateModified")),
        can_edit=payload.get("CanEdit"),
    )


def normalize_list_line(payload: dict[str, Any]) -> MyListLine:
    quantities = payload.get("Quantities") or payload.get("RequestedQuantities") or []
    selected_index = _int(payload.get("SelectedQuantityIndex"), 0)
    selected = quantities[selected_index] if 0 <= selected_index < len(quantities) else {}
    quantity = (
        selected.get("CalculatedQuantity")
        or selected.get("QuantityRequested")
        or selected.get("Quantity")
        or payload.get("Quantity")
        or payload.get("RequestedQuantity")
    )
    pack = selected.get("SelectedPackType") or payload.get("PackType") or payload.get("PackageType")
    pack_options = selected.get("PackOptions") or []
    selected_pack_index = _int(selected.get("SelectedPackOptionIndex"), 0)
    selected_pack = (
        pack_options[selected_pack_index] if 0 <= selected_pack_index < len(pack_options) else {}
    )
    return MyListLine(
        unique_id=_text(payload.get("UniqueId")),
        requested_part_number=_text(payload.get("RequestedPartNumber")),
        digikey_product_number=_text(payload.get("DigiKeyPartNumber")),
        manufacturer_product_number=_text(payload.get("ManufacturerPartNumber")),
        manufacturer=_text(payload.get("Manufacturer")),
        description=_text(payload.get("Description")),
        customer_reference=_text(payload.get("CustomerReference")),
        reference_designator=_text(payload.get("ReferenceDesignator")),
        notes=_text(payload.get("Notes")),
        quantity=_int(quantity) if quantity is not None else None,
        package_type=_text(pack),
        quantity_available=(
            _int(payload.get("QuantityAvailable"))
            if payload.get("QuantityAvailable") is not None
            else None
        ),
        minimum_order_quantity=(
            _int(payload.get("MinOrderQty")) if payload.get("MinOrderQty") is not None else None
        ),
        unit_price=_decimal(payload.get("UnitPrice") or selected_pack.get("CalculatedUnitPrice")),
        raw_quantities=quantities,
    )


def normalize_list_detail(
    list_id: str,
    metadata: dict[str, Any] | None,
    parts_payload: dict[str, Any] | list[dict[str, Any]],
) -> MyListDetail:
    if isinstance(parts_payload, list):
        rows = parts_payload
        total = len(rows)
    else:
        rows = parts_payload.get("PartsList") or []
        total = _int(parts_payload.get("TotalParts"), len(rows))
    return MyListDetail(
        list_id=list_id,
        name=_text((metadata or {}).get("ListName") or (metadata or {}).get("Name")),
        lines=[normalize_list_line(row) for row in rows],
        total_parts=total,
    )
