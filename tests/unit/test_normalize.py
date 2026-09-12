from decimal import Decimal

from digikey_list_mcp.procurement.normalize import normalize_list_detail, normalize_product


def product_payload() -> dict:
    return {
        "Product": {
            "Description": {"ProductDescription": "10 kOhm resistor"},
            "Manufacturer": {"Id": 1, "Name": "Yageo"},
            "ManufacturerProductNumber": "RC0603FR-0710KL",
            "ProductUrl": "https://www.digikey.com/example",
            "DatasheetUrl": "https://example.com/datasheet.pdf",
            "QuantityAvailable": 5000,
            "ProductStatus": {"Status": "Active", "Name": "Active"},
            "Parameters": [
                {"ParameterText": "Resistance", "ValueText": "10 kOhms"},
            ],
            "ProductVariations": [
                {
                    "DigiKeyProductNumber": "311-10.0KHRCT-ND",
                    "PackageType": {"Name": "Cut Tape (CT)"},
                    "QuantityAvailableforPackageType": 2000,
                    "MinimumOrderQuantity": 1,
                    "StandardPackage": 1,
                    "StandardPricing": [
                        {"BreakQuantity": 1, "UnitPrice": 0.10},
                        {"BreakQuantity": 10, "UnitPrice": 0.05},
                    ],
                }
            ],
        }
    }


def test_normalizes_product_and_price_breaks() -> None:
    part = normalize_product(product_payload())
    assert part.manufacturer == "Yageo"
    assert part.description == "10 kOhm resistor"
    assert part.parameters == {"Resistance": "10 kOhms"}
    variation = part.variations[0]
    assert variation.package_type == "Cut Tape (CT)"
    assert variation.unit_price_for(25) == Decimal("0.05")


def test_normalizes_mylist_line() -> None:
    detail = normalize_list_detail(
        "list-1",
        {"ListName": "project"},
        {
            "TotalParts": 1,
            "PartsList": [
                {
                    "UniqueId": "line-1",
                    "DigiKeyPartNumber": "311-10.0KHRCT-ND",
                    "ReferenceDesignator": "R1,R2",
                    "SelectedQuantityIndex": 0,
                    "Quantities": [{"Quantity": 10, "SelectedPackType": "Cut Tape (CT)"}],
                }
            ],
        },
    )
    assert detail.name == "project"
    assert detail.lines[0].quantity == 10
    assert detail.lines[0].reference_designator == "R1,R2"


def test_normalizes_production_mylist_quantity_and_selected_price() -> None:
    detail = normalize_list_detail(
        "list-1",
        {"ListName": "project"},
        {
            "TotalParts": 1,
            "PartsList": [
                {
                    "UniqueId": "line-1",
                    "DigiKeyPartNumber": "P5555-ND",
                    "SelectedQuantityIndex": 0,
                    "Quantities": [
                        {
                            "QuantityRequested": 1,
                            "CalculatedQuantity": 1,
                            "SelectedPackType": "Bulk",
                            "SelectedPackOptionIndex": 0,
                            "PackOptions": [{"CalculatedUnitPrice": 1.41}],
                        }
                    ],
                }
            ],
        },
    )

    line = detail.lines[0]
    assert line.quantity == 1
    assert line.package_type == "Bulk"
    assert line.unit_price == Decimal("1.41")
