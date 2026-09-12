---
name: digikey-list-mcp
description: Search live DigiKey data and prepare or validate private DigiKey MyLists for electronics projects. Use for part discovery, exact SKU comparisons, BOM pricing, stock checks, packaging choices, substitutions, and MyList preparation. Never use it to place an order or perform checkout.
---

# DigiKey list procurement

Use the bundled MCP tools to move from requirements to a reviewable DigiKey MyList.

## Workflow

1. Search for candidates with `digikey_search_parts`.
2. Use `digikey_get_part` on exact candidates before making price, stock, lifecycle, or packaging claims.
3. Compare all electrically and mechanically relevant constraints. Treat substitutions and recommendations as candidates, never guaranteed equivalents.
4. Call `digikey_preview_mylist_changes` with exact quantities, references, notes, packaging preference, and attrition.
5. Show the user the exact SKU, adjusted quantity, warnings, and estimated total. Apply only after the user approves that preview.
6. Call `digikey_apply_mylist_changes` with the unchanged preview token.
7. Use `digikey_validate_mylist` immediately before the user orders.

Always attribute live product data to DigiKey and include the returned check time. Keep requested, attrition-adjusted, MOQ-adjusted, and final quantities distinct. Never place an order or claim checkout has occurred.

