# digikey-list-mcp

> Status: working local MVP. Offline tests pass, and production OAuth, Product Information V4,
> and read-only MyLists access were verified on 2026-09-12.

A personal, agent-friendly interface for finding electronic parts and preparing order-ready DigiKey MyLists. The agent does the tedious catalog work; the human reviews the resulting list and completes checkout on DigiKey.

The project is named **`digikey-list-mcp`** to distinguish its MyLists-centered scope from the existing community project named `digikey-mcp`.

The working name says “MCP,” but MCP is the service boundary, not the product goal. The deliverable should be a turnkey personal plugin that works in ChatGPT and Codex and remains usable by other MCP clients.

## What is implemented

- Python 3.12+ package with no Node.js or npm dependency.
- Product Information V4 search, exact details, substitutions, and recommendations.
- MyLists list/read/create/add/update/remove operations, including paginated list reads.
- Exact-SKU normalization, quantity/attrition/MOQ calculations, pricing, and warnings.
- Signed, expiring preview tokens and retry-safe add operations.
- Automatic OAuth refresh-token rotation with Keychain/keyring storage and a mode-`0600` fallback.
- Eleven MCP tools over local stdio or streamable HTTP, with read/write/destructive annotations.
- A validated Codex personal-plugin bundle under `plugin/digikey-list-mcp`.
- Offline HTTP, auth, normalization, planning, CLI, pagination, and MCP discovery tests.

No tool can place an order or check out.

## Quick start

Prerequisites are Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). `direnv` is optional.

```bash
uv sync --extra dev
uv run digikey-list-mcp --help
uv run pytest
```

For optional `direnv` defaults, copy `.envrc.example` to `.envrc` and run `direnv allow`.
The example deliberately contains no credentials.

Create an organization and production application in the
[DigiKey Developer Portal](https://developer.digikey.com/), subscribe the application to Product
Information V4 and MyLists, and register the callback URI you intend to use. Find your **Account
ID** under your profile information on the main DigiKey website—not in the developer portal. Then:

```bash
uv run digikey-list-mcp configure
uv run digikey-list-mcp auth login
uv run digikey-list-mcp doctor --live
```

The login command opens DigiKey and asks you to paste the full redirected URL. With the default
`https://localhost` callback, the final browser page may fail to load; copy its address-bar URL
anyway. The command verifies OAuth state before saving tokens.

When configuring production, answer `no` to the sandbox prompt. Sandbox is useful for validating
OAuth and response shapes, but its synthetic user may not map to a MyLists account; this can appear
as `MyLists.Api Error` with an internal `AccountId: 0`. Production MyLists requires the real Account
ID described above. Sandbox and production applications have separate credentials and tokens, so
run `auth login` again after switching applications.

Run the MCP server directly with:

```bash
uv run digikey-list-mcp serve --transport stdio
```

The checked-in plugin points at this repository through `uv`, so it does not need a separately
installed executable. It is intentionally not installed into a personal marketplace yet: live
write-path verification should happen first. The streamable-HTTP transport is available for
development, but it must not be exposed beyond localhost until an MCP authentication layer is added.

## Architecture decision

The implementation is a small Python service against DigiKey's official APIs with
workflow-oriented MCP tools and a local personal-plugin bundle.

Version 1 uses:

- **Product Information V4** for search, exact product details, live price and stock, quantity/package pricing, substitutions, recommendations, and product documents.
- **MyLists v1** for listing, creating, reading, and updating private lists.
- **OAuth 2.0 authorization-code flow (three-legged)** for both products. MyLists requires it, and one consistent user-authorized session is simpler than mixing auth modes.

It will **not** manipulate DigiKey's web cart, automate checkout, or place orders. MyLists is the handoff to the human-facing purchasing flow.

This is the best-supported path because DigiKey describes MyLists as external access to the same API used by its My Lists web application. Its API can create lists, add parts, fetch priced list contents, and update or remove lines. By contrast, the official Ordering API places orders directly, requires an active DigiKey Credit account, and solves a problem we do not currently have.

## What the experience should feel like

Example requests to an agent:

- “Find an in-stock 3.3 V, 500 mA LDO in SOT-23-5 with at least 12 V input tolerance. Prefer parts with a healthy stock buffer and a readable datasheet.”
- “Price this BOM for five assemblies, add 10% attrition to passives, and flag every minimum-order or packaging mismatch.”
- “Compare these three regulators at quantities 1, 10, and 25. Include lifecycle status and plausible substitutes.”
- “Create a private list called `soil-sensor-r2`, add the selected parts, and preserve my reference designators and notes.”
- “Revalidate `soil-sensor-r2` against current stock and pricing and tell me what changed before I order.”

The result should contain exact manufacturer and DigiKey part numbers, selected packaging, requested and orderable quantities, unit and extended prices, current stock, lifecycle status, minimum order quantity, datasheet/product links, and a `checked_at` timestamp. Every DigiKey-derived result must identify DigiKey as its source.

## Why this approach

| Option | Verdict | Reason |
| --- | --- | --- |
| Official Product Information + MyLists APIs behind MCP | **Choose** | Covers search through order-ready list creation without browser automation or checkout risk. |
| Existing community `digikey-mcp` | Learn from it, do not adopt as the base | It currently focuses on Product Information V4, offline BOM generation, and two-legged auth; it does not provide the MyLists write workflow that is central here. |
| Browser automation against digikey.com | Fallback only | Fragile, slow, difficult to make idempotent, and unnecessary for the v1 workflow. |
| DigiKey Ordering API | Defer | It queues real orders, uses three-legged OAuth, and requires an active DigiKey Credit account. We explicitly want manual checkout. |
| Quote API | Possible later | Useful for locking pricing, but not needed to build and review a MyList. |
| Cross-distributor aggregator | Later, behind a separate provider adapter | Helpful for Mouser and others, but it should not delay a clean DigiKey implementation or blur data provenance. |

No relevant turnkey DigiKey integration appears in the plugin options available to this workspace, and the community implementation reviewed does not cover MyLists. A purpose-built personal integration is justified.

## Supported workflow

```text
project requirements or BOM
          |
          v
search and shortlist (Product Information V4)
          |
          v
exact-SKU validation: stock, price, MOQ, packaging, lifecycle
          |
          v
preview proposed MyList changes
          |
          v
create/update private MyList (human-confirmed write)
          |
          v
revalidate immediately before purchase
          |
          v
human reviews and checks out on DigiKey
```

Search results are discovery candidates, not purchase-ready facts. DigiKey's keyword search does not return account-specific `MyPricing`; exact product/pricing endpoints do. Before a line is proposed or written, the server must resolve it to an exact DigiKey SKU and refresh its details.

## MCP tools

Tools expose procurement concepts rather than mirroring DigiKey's API one endpoint at a time.

### Discovery and validation (read-only)

- `digikey_search_parts`
  - Input: query, result limit, in-stock flag, and marketplace-exclusion flag.
  - Output: normalized discovery candidates with standard pricing.
- `digikey_get_part`
  - Input: manufacturer or DigiKey part number and optional manufacturer ID.
  - Output: exact product, pricing options, availability, MOQ, packaging, lifecycle, parameters, product URL, and datasheet URL.
- `digikey_compare_parts`
  - Input: two to twelve exact part numbers.
  - Output: normalized current details with an explicit compatibility warning.
- `digikey_find_alternates`
  - Input: exact part number and result limit.
  - Output: DigiKey substitutions/recommendations clearly labeled as candidates requiring compatibility review.
- `digikey_list_mylists`
- `digikey_get_mylist`
- `digikey_validate_mylist`
  - Rechecks every line's current price, stock, MOQ, packaging, and lifecycle; reports shortages and deltas from the previous validation if locally available.

### MyLists changes (writes)

- `digikey_preview_mylist_changes`
  - Input: target list or new list name, assembly count, and lines containing exact part number, per-assembly quantity or total quantity, packaging preference, reference designators, customer reference, notes, target price, and attrition.
  - Output: normalized, orderable lines; warnings; estimated total; and an expiring preview/confirmation token.
- `digikey_apply_mylist_changes`
  - Input: preview token.
  - Applies only the reviewed diff. The token binds the list ID, exact lines, and quantities so a later tool call cannot change the proposal.
- `digikey_update_mylist_line`
  - Update quantity, selected package, references, notes, target price, or attrition for one line.
- `digikey_remove_mylist_line`
  - Destructive; always requires explicit user confirmation.

Creating a list or appending reviewed parts is reversible and low risk, but it still changes the user's DigiKey account. The default workflow is preview then apply. Replacing a list, removing lines, or reducing quantities must never happen as a side effect of an “add” operation.

### MCP safety metadata

The server declares:

- read operations: `readOnlyHint: true`;
- preview: read-only and idempotent;
- create/add/update: not read-only, normally idempotent at our layer;
- remove/replace: `destructiveHint: true`;
- all DigiKey calls: `openWorldHint: true`.

## MyLists mapping

The adapter translates the stable tool schema into DigiKey's current `RequestedPart` structure:

| Our field | DigiKey field |
| --- | --- |
| exact requested SKU | `RequestedPartNumber` |
| project/BOM identity | `CustomerReference` |
| PCB references | `ReferenceDesignator` |
| selection rationale or assembly notes | `Notes` |
| scrap/spares percentage | `Attrition` |
| quantity and target price | `Quantities[].Quantity`, `Quantities[].TargetPrice` |
| package choice | `Quantities[].SelectedPackType`, `SelectedSubPackType` |
| alternate candidates | `AlternateParts` |

The API returns a stable list ID and per-line unique IDs. We should use those IDs for updates rather than matching mutable descriptions or positions. List creation should default to private visibility and a cut-tape-friendly package preference for small projects, while allowing the user to override it.

Important integration detail: DigiKey's published MyLists Swagger describes the API as v1 and exposes it under `/mylists/v1`. We should check the downloaded Swagger into test fixtures only if DigiKey's terms permit redistribution; otherwise, generate a minimal internal client from documented shapes and keep contract snapshots synthetic.

## Authentication and setup

### One-time user setup

1. Create or sign in to a My DigiKey account.
2. Create a developer organization and application in the [DigiKey Developer Portal](https://developer.digikey.com/).
3. Subscribe the production application to **Product Information V4** and **MyLists**.
4. Register the exact callback URL shown by this project.
5. Put the client ID and client secret in the operating system credential store through the setup command—never in `.env` by default, shell history, source control, or plugin metadata.
6. Run `digikey-list-mcp auth login`. It opens DigiKey's authorization page, handles the short-lived authorization code, and stores the resulting rotating tokens securely.

The callback URI sent during login and token exchange must exactly match the registered value, including any trailing slash. DigiKey documents authorization codes as valid for one minute, three-legged access tokens for 30 minutes, and refresh tokens for 90 days. A refresh exchange issues a new refresh token and invalidates the old one, so token replacement must be atomic and safe across concurrent calls.

### Credential storage

Preferred local storage on macOS is Keychain. A portable fallback may use a user-only file outside the repository with mode `0600`. Logs must redact:

- client secret;
- authorization codes;
- access and refresh tokens;
- DigiKey account/customer IDs where not required for diagnosis;
- shipping, contact, or order information if those APIs are added later.

The MCP server itself also needs an authorization boundary. A local stdio process inherits the local user's trust boundary. A remotely reachable streamable-HTTP endpoint must use MCP-compatible user authentication; an unguessable URL is not authentication.

## Packaging and deployment

Implement one shared core with two transports:

- **stdio** for local MCP clients and easy development;
- **streamable HTTP at `/mcp`** for ChatGPT/Codex plugin use.

Recommended stack:

- Python 3.12+ managed with `uv` and a committed `uv.lock`;
- the official Python `mcp` SDK and Pydantic models;
- HTTPX behind a small `DigiKeyClient` protocol;
- Authlib where it simplifies the OAuth authorization-code flow;
- `keyring` for macOS Keychain, behind a credential-store protocol with a secure portable fallback;
- pytest and respx for offline unit and HTTP contract tests;
- structured logs with mandatory secret redaction;
- no database for DigiKey catalog data.

The core server must have no Node.js or npm dependency. If a rich browser UI is added later, keep its frontend optional, isolated, and independently built; the MCP tools and plugin must remain fully useful without it.

The personal plugin should bundle:

```text
plugin.json                 portable plugin manifest
mcp.json                    MCP server connection
skills/digikey-list-mcp/    agent workflow guidance
assets/                     optional icons
```

Current OpenAI plugin architecture treats the plugin as the installable package and the MCP server as its live tools/data component. A custom UI is optional. We should begin headless; a small editable BOM comparison/review panel may be worth adding only after the tool workflow is reliable.

For private development, run the service locally and use the supported secure MCP tunnel or a local MCP client. A ChatGPT-accessible production endpoint needs stable HTTPS and streamable HTTP. We should not expose a temporary unauthenticated tunnel containing DigiKey credentials.

## Safety and procurement rules

The server enforces these rules rather than relying only on model judgment:

1. **No checkout tools.** No payment, shipping, or order-placement surface in v1.
2. **Exact SKU before write.** Never add a fuzzy keyword result directly to a list.
3. **Fresh purchase facts.** Refresh details before preview; include `checked_at` and source on every result.
4. **No false equivalence.** Alternates are candidates. Flag package, pinout, voltage/current, tolerance, temperature, lifecycle, and certification differences.
5. **Quantity transparency.** Return requested, attrition-adjusted, MOQ-adjusted, package-multiple-adjusted, and final list quantities separately.
6. **Idempotent writes.** Retrying a timed-out apply must not duplicate lines. Store only minimal operation IDs/digests needed to achieve this.
7. **Preview-bound mutation.** Applying a preview cannot silently use newer candidates or different quantities.
8. **No destructive convenience.** Append/upsert and replace are distinct operations. Deletes require confirmation.
9. **Budget warnings.** Warn when extended price exceeds the previewed amount by a configurable absolute or percentage threshold.
10. **Manual final review.** The output always reminds the user that price, stock, suitability, taxes, and shipping can change before checkout.

## Data handling and DigiKey terms

This is an internal application for personal purchasing. DigiKey's API agreement expressly includes internal applications that automate and enhance purchasing as a permitted purpose, subject to its approval and terms.

The implementation must:

- clearly attribute DigiKey as the source of DigiKey data;
- preserve DigiKey product links and notices;
- avoid bulk catalog downloads;
- avoid building a persistent local catalog database from API responses;
- keep cross-vendor results clearly separated and attributed when Mouser or other providers are added;
- store durable **user intent** (project name, requested quantities, notes, references, selected SKU, validation timestamps and digests), not a shadow copy of DigiKey's catalog;
- use short-lived in-memory response caching only to control duplicate calls and respect rate limits, pending a final terms review;
- stop and remove retained DigiKey data if API access is terminated, as required by the agreement.

Product Information's published standard quota is 120 calls per minute and 1,000 per day. The client must honor `429`, `Retry-After`, and DigiKey rate-limit headers, coalesce concurrent identical lookups, and never hide stale fallback data as current. Quotas vary by API product, so they should be learned from response headers and configuration rather than hard-coded globally.

This README is technical planning, not legal advice. Re-read the live agreement before production deployment, especially before adding cross-distributor comparison or persistent analytics.

## Repository layout

```text
pyproject.toml
uv.lock
src/
  digikey_list_mcp/
    digikey/
      client.py           HTTP, locale headers, errors, throttling
      auth.py             authorization-code and rotating-token lifecycle
      product_information.py
      mylists.py
    procurement/
      normalize.py        quantities, packaging, money, lifecycle
      plan_mylist.py      preview and idempotent apply
    server/
      app.py              agent-facing tools and both transports
    credentials/
      store.py
tests/
  unit/
plugin/
  digikey-list-mcp/
    .codex-plugin/plugin.json
    .mcp.json
    skills/digikey-list-mcp/SKILL.md
```

Provider-specific wire types must not leak into MCP results. A future `MouserClient` should implement the same internal procurement model while retaining explicit field-level provenance.

## Delivery status

### Live-account verification — create/add/read complete

- Production application registered with Product Information V4 and MyLists subscriptions.
- Three-legged production OAuth completed successfully.
- Exact production product lookup completed successfully.
- Production MyLists listing completed successfully using the Account ID from the main DigiKey
  profile page.
- Created private list `digikey-list-mcp-live-test-20260912-223850`, added quantity 1 of
  `P5555-ND`, and read the line back successfully. It was intentionally left in the account for
  manual inspection.
- Production returns requested and calculated quantities as `QuantityRequested` and
  `CalculatedQuantity`, and returns the selected price under
  `PackOptions[].CalculatedUnitPrice`. The normalizer accepts these observed fields as well as the
  published generic shapes.
- Next: verify update and delete behavior after the retained test list has been inspected.

### Useful local MCP — implemented

- Implement search, exact details, comparison, and alternates.
- Implement list/read/create/add/update with preview-bound, idempotent writes.
- Add `validate_mylist` and human-readable price/stock/MOQ warnings.
- Ship stdio transport and a one-command setup/auth/doctor flow.

### Personal plugin — local bundle implemented; remote deployment deferred

- Add authentication before deploying streamable HTTP beyond localhost.
- Install the bundled MCP server plus procurement skill as a personal plugin after the live check.
- Add install/update scripts and a health check that explains expired login, missing subscriptions, rate limits, and locale/account configuration in plain language.
- Test the same core scenarios in ChatGPT, Codex, and one non-OpenAI MCP inspector/client.

### Phase 3 — procurement assistant features

- Import KiCad BOMs and generic CSVs without losing reference designators.
- Add project-level policies: preferred package sizes, marketplace exclusion, minimum stock buffer, lifecycle preferences, attrition rules, and budget thresholds.
- Add a review UI only if conversational preview is insufficient.
- Add Mouser behind the provider boundary, with unmistakable source attribution and a terms review.

## V1 acceptance criteria

V1 is done when a fresh install can:

1. guide the user through DigiKey developer setup without exposing secrets;
2. authenticate once and refresh tokens without repeated browser interaction;
3. search by requirements and return concise, attributed candidates;
4. turn chosen candidates into exact, currently validated order lines;
5. preview and create/update a private MyList with quantities, packaging, references, and notes;
6. retry writes without duplicate lines;
7. revalidate the completed list and report price, stock, MOQ, packaging, and lifecycle issues;
8. leave checkout entirely to the user;
9. pass offline unit/contract tests without DigiKey credentials;
10. emit no secrets in logs, tool results, test snapshots, or error messages.

## Open questions for write-path verification

- How does MyLists behave when adding the same DigiKey SKU twice with different references or package choices?
- Does the live list endpoint always return current pricing/availability, or should every line be revalidated through Product Information V4?
- Which package strings does MyLists accept in practice for cut tape, tape-and-reel, Digi-Reel, tray, and bulk?
- What are the observed MyLists-specific burst and daily quotas?
- What is the cleanest route from a populated MyList into DigiKey's manual checkout UI?

Production read access required the Product Information V4 and MyLists subscriptions, three-legged
OAuth, and `X-DIGIKEY-Account-ID`. The remaining questions require controlled writes or observations
that the public documentation does not answer precisely enough.

## Sources

Primary sources:

- [DigiKey API products](https://developer.digikey.com/products)
- [Product Information V4 endpoints](https://developer.digikey.com/products/product-information-v4/productsearch)
- [MyLists endpoints](https://developer.digikey.com/products/mylists/mylists)
- [MyLists published Swagger](https://developer.digikey.com/node/2690/oas-download)
- [DigiKey OAuth and rate-limit documentation](https://developer.digikey.com/documentation)
- [DigiKey OAuth FAQ](https://developer.digikey.com/faq)
- [DigiKey API User Agreement](https://developer.digikey.com/api-user-agreement)
- [DigiKey official GitHub organization](https://github.com/Digi-Key)
- [OpenAI plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
- [OpenAI MCP server guidance](https://developers.openai.com/plugins/concepts/mcp-server)
- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

Existing implementation reviewed:

- [`itsyashk/digikey-mcp`](https://github.com/itsyashk/digikey-mcp)
