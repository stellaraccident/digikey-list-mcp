from __future__ import annotations

import pytest
from conftest import FakeDigiKeyClient

from digikey_list_mcp.digikey.product_information import ProductInformationAPI


@pytest.mark.asyncio
async def test_search_uses_v4_shape_and_filters() -> None:
    client = FakeDigiKeyClient([{"ProductsCount": 0, "Products": []}])
    api = ProductInformationAPI(client)  # type: ignore[arg-type]
    result = await api.search("10k 0603", limit=500)
    call = client.calls[0]
    assert call["path"] == "/products/v4/search/keyword"
    assert call["json_body"]["Limit"] == 50
    assert call["json_body"]["FilterOptionsRequest"] == {
        "MinimumQuantityAvailable": 1,
        "MarketPlaceFilter": "ExcludeMarketPlace",
    }
    assert result.source == "DigiKey"


@pytest.mark.asyncio
async def test_product_number_is_url_encoded() -> None:
    client = FakeDigiKeyClient([{"Product": {}}])
    api = ProductInformationAPI(client)  # type: ignore[arg-type]
    await api.get_part("ABC/123")
    assert client.calls[0]["path"].endswith("ABC%2F123/productdetails")
