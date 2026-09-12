from __future__ import annotations

from urllib.parse import quote

from digikey_list_mcp.digikey.client import DigiKeyClient
from digikey_list_mcp.procurement.models import Part, SearchResult
from digikey_list_mcp.procurement.normalize import normalize_product


class ProductInformationAPI:
    def __init__(self, client: DigiKeyClient) -> None:
        self.client = client

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        in_stock: bool = True,
        exclude_marketplace: bool = True,
    ) -> SearchResult:
        limit = max(1, min(limit, 50))
        filters: dict[str, object] = {}
        if in_stock:
            filters["MinimumQuantityAvailable"] = 1
        if exclude_marketplace:
            filters["MarketPlaceFilter"] = "ExcludeMarketPlace"
        payload = await self.client.request_json(
            "POST",
            "/products/v4/search/keyword",
            json_body={
                "Keywords": query,
                "Limit": limit,
                "Offset": max(0, offset),
                "FilterOptionsRequest": filters,
                "SortOptions": {"Field": "QuantityAvailable", "SortOrder": "Descending"},
            },
        )
        products = []
        seen: set[str] = set()
        for item in (payload.get("ExactMatches") or []) + (payload.get("Products") or []):
            product = normalize_product(item)
            key = product.manufacturer_product_number or repr(item)
            if key.casefold() in seen:
                continue
            seen.add(key.casefold())
            products.append(product)
        return SearchResult(
            query=query,
            products_count=int(payload.get("ProductsCount", len(products))),
            products=products[:limit],
        )

    async def get_part(
        self,
        product_number: str,
        *,
        manufacturer_id: str | None = None,
    ) -> Part:
        params = {"manufacturerId": manufacturer_id} if manufacturer_id else None
        payload = await self.client.request_json(
            "GET",
            f"/products/v4/search/{quote(product_number, safe='')}/productdetails",
            params=params,
        )
        return normalize_product(payload)

    async def substitutions(self, product_number: str, *, limit: int = 10) -> list[Part]:
        payload = await self.client.request_json(
            "GET",
            f"/products/v4/search/{quote(product_number, safe='')}/substitutions",
            params={"limit": max(1, min(limit, 50))},
        )
        rows = payload.get("Substitutions") or payload.get("Products") or []
        return [normalize_product(row) for row in rows]

    async def recommendations(self, product_number: str, *, limit: int = 10) -> list[Part]:
        payload = await self.client.request_json(
            "GET",
            f"/products/v4/search/{quote(product_number, safe='')}/recommendedproducts",
            params={
                "limit": max(1, min(limit, 50)),
                "excludeMarketPlaceProducts": True,
            },
        )
        recommendation = payload.get("Recommendations") or payload.get("RecommendedProducts") or []
        if isinstance(recommendation, dict):
            recommendation = recommendation.get("RecommendedProducts") or []
        return [normalize_product(row) for row in recommendation]
