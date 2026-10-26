# Changelog

All notable changes to the Collect & Go add-on. This project follows
[Semantic Versioning](https://semver.org/): **MAJOR** for breaking changes,
**MINOR** for new features, **PATCH** for fixes.

## [2.3.0] — 2026-10-26

### Added

- **Richer cart:** cart lines are enriched via a batched
  `productview/byId` lookup — each line now shows the product **image,
  name, brand/content and price** (per-unit and line total) instead of a
  bare product id. New `productview/byId` client method; `xprice` shape
  (`basePrice`, comma decimals) parsed.
- Quantity steppers send the line's numeric `partNumber` along (some WCS
  builds reject updates without it).

## [2.2.0] — 2026-10-26

### Changed (breaking)

- **Auth = cookies + header, exactly like the site** (verified via
  `docs/curl/product_display.example`): the ``wcauthtoken`` request header carries the
  `WC_AUTHENTICATION_<userId>` cookie value verbatim, and the session
  cookies (`WC_AUTHENTICATION_…`, `WC_USERACTIVITY_…`, `WC_ACTIVEPOINTER`,
  `WC_SESSION_ESTABLISHED`, `priceMode`, `COL_SHOP`) go along. The
  v2.0/v2.1 token fields are gone.
- **Add to cart = the real call** (verified via
  `docs/curl/add_to_cart.example`): `POST …/v2/store/90004/cart` with
  `{"productId": <uniqueID>, "quantity": "n", "xitem_field2": "P|n|st"}`
  and the **store catalog id** (`10646`, from `COL_SHOP`) instead of the
  generic one.
- **Login is now one paste:** the panel accepts a whole **Copy-as-cURL**
  command (DevTools → Network), a cookie header, the DevTools cookie-table
  rows, a single `WC_AUTHENTICATION_…=…` pair, or just its value — and
  validates against the live cart before saving. A rejected session now
  shows a clear message instead of a 502, and validation falls back to the
  order-history endpoint when Imperva throttles the cart read (405 → clean
  429 in the UI).
- Options `wcauthtoken`/`wctoken`/`wctrustedtoken` replaced by a single
  `session_cookies` option.
- Cart add/remove fall back to the direct WCS resource endpoints
  (`/wcs/resources/store/…`) when the gateway answers 5xx.

## [2.1.0] — 2026-10-26

### Added

- **Direct WCS cart endpoints** (`/wcs/resources/store/…`, see
  `docs/api-collect-and-go-notes-v2.md`): with the optional `WCToken` +
  `WCTrustedToken` pair (new *Advanced* section in the setup panel, or the
  matching add-on options) cart view/add/remove use the faster direct
  endpoints, with the standard gateway as automatic fallback. The session
  cookies `WC_SESSION_ESTABLISHED` / `WC_ACTIVEPOINTER` are sent along.
- `/api/state` now reports `wcs_tokens` so the panel can show which
  transport is active.
- Product images now resolve correctly (WCS asset paths are mapped to the
  `static.colruytgroup.com` CDN).

### Changed

- The panel got the Collect&Go look: brand palette (dark-blue header, red
  accents, orange badges), rounded cards and buttons.

## [2.0.0] — 2026-10-26

### Changed (breaking)

- The add-on now talks **only** to the Collect&Go (HCL/WCS) gateway; the
  old Colruyt/Xtra endpoints (the shared "Mijn lijstje" list, the
  `product-search-prs` search and "most bought") are no longer used.
- **Simpler login:** one token instead of two cookies. Paste the
  `wcauthtoken` from collectandgo.be (bare value or whole cookie string) —
  the add-on validates it against your live cart before saving, and an
  expired token immediately shows the reconnect flow.
- The panel is now **cart-centric**: live cart with quantity steppers,
  remove buttons and total; search results add straight into the cart.
- REST API: `/api/list*` is gone in favour of `/api/cart` (GET),
  `/api/cart/items` (POST) and `/api/cart/items/{orderItemId}`
  (PUT/DELETE); `/api/search` uses the WCS shop catalog; `/api/orders`
  is new.
- Options `place_id` and `session_cookie` removed — the store comes from
  your Collect&Go session; use `wcauthtoken` instead.

### Removed

- Free-text items (the WCS cart only accepts real products / partNumbers).
- "Most bought" suggestions (Xtra-only endpoint).

## [1.2.0] — 2026-10-26

### Added

- Collect&Go WCS gateway integration (see `docs/api-collect-and-go-notes.md`):
  - View the **live Collect&Go cart** (`GET /api/cart`) and your **order
    history** (`GET /api/orders`) straight from the panel.
  - New `wcauthtoken` support: paste the token from collectandgo.be in the
    setup panel (or the `wcauthtoken` add-on option); it is stored with the
    session and sent as a header to the cart/order gateways.
  - New `source=wcs` search backend (`/api/search?q=...&source=wcs`) using
    the Collect&Go shop catalog — results carry the `partNumber` that the
    cart endpoints accept.
- Direct add-to-cart now sends the WCS `partNumber`/`quantity` payload and
  uses the stored `wcauthtoken`.

## [1.0.1] — 2026-10-22

### Fixed

- Adding an item to the list no longer returns a generic *500 Internal Server
  Error* when the Colruyt API answers with a non-JSON or error-shaped body
  (plain-text "OK", WAF block page, …). The API client now validates and
  tolerates those responses and returns a clean, readable error instead.
- Hardened all list/search parsing against unexpected response shapes and
  non-object entries, so one malformed product or item can no longer break
  the whole view.

## [1.0.0] — 2026-10-22

### Added

- Initial release: shared Collect&Go / Xtra shopping list in the Home
  Assistant sidebar.
- Connect your Xtra account with the `clpbff_session` cookie (no password
  stored); session kept in the add-on's data folder.
- View the shared list, search the Colruyt assortment (images + prices),
  add items with quantity, remove items, free-text items.
- "Frequently bought" quick-add section and deep link to the real
  Collect&Go cart for checkout.
- UI in English, Nederlands and Français.
- Optional REST API on port 8099 for automations (`rest_command`).
