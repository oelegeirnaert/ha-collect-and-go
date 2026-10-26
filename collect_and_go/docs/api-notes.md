# API notes (reverse engineered)

Since v2.0.0 the add-on talks **only** to the Collect&Go backend: the HCL/WCS
commerce gateway behind www.collectandgo.be. No official public API exists;
these are the endpoints the web app calls itself. Sources:
docs/api-collect-and-go-notes.md (live DevTools analysis) +
github.com/ddvlamin/xtra-mcp. The old Colruyt/Xtra BFF endpoints
(`latest-shopping-list`, `product-search-prs`, `most-bought-products`) were
used up to v1.x and are kept at the bottom for reference only.

## Auth (verified against the live site, docs/curl/product_display.example)

- Login is Azure AD B2C at `login.myxtra.be` (`B2C_1A_signin`) **with SMS
  verification** → not sanely automatable → the add-on reuses the session
  instead of logging in.
- A working request needs **both**:
  - the ``wcauthtoken`` request header — its value is the
    ``WC_AUTHENTICATION_<userId>`` cookie value verbatim
    (``<userId>%2C<token>``); and
  - the session cookies: ``WC_AUTHENTICATION_<userId>``,
    ``WC_USERACTIVITY_<userId>``, ``WC_ACTIVEPOINTER`` (``<langId>%2C90004``),
    ``WC_SESSION_ESTABLISHED=true`` (plus ``priceMode``).
  The header alone → 500; the cookies alone → 500. Together → 200.
- Every gateway request also needs the static header
  `x-cg-apikey: 502b657c-624c-11eb-8024-f4d06b721e80` (the site's
  `apiGatewayKey`), and `content-type: application/json` on writes.
- Expired/invalid session → **500** on the gateway (not a clean 401).
- Expect Imperva-style bot protection (`reese84` cookie, time-sensitive,
  cannot be reused): bursts can get answered with **HTTP 456** → the app
  caches and backs off.

## Endpoints

Base: `https://apip.collectandgo.be/gateway`
Constants: store `90004`, catalogId `10429`, shopType `CLPBE`,
langId `-1001` (nl) / `-1002` (fr).

| Endpoint | Method | Notes |
| --- | --- | --- |
| `/ecomfoodb2c.eshop.wcsproductviewsearchsvc/v1/store/90004/productview/bySearchTerm/{term}` | GET | Assortment search. Products in `catalogEntryView[]`; id = `partNumber`. Prices in `price[]` (`usage: Display/Offer`, string `value`). Images are relative asset paths → prepend `https://static.colruytgroup.com/images` and drop the `JPG/` prefix. |
| `/ecomfoodb2c.eshop.wcscartsvcv2/v2/store/90004/cart/@self` | GET | Live cart: `orderItem[]` (each with `orderItemId`, `partNumber`, `quantity`), totals in `grandTotal`. |
| `/ecomfoodb2c.eshop.wcscartsvcv2/v2/store/90004/cart` | POST | **Add to cart (verified live, docs/curl/add_to_cart.example):** body `{"orderItem": [{"productId": "<numeric uniqueID>", "quantity": "1", "xitem_field2": "P|1|st"}]}` — `productId` = the product's numeric `uniqueID`, `xitem_field2` = unit marker `P|<qty>|st`. ⚠️ `catalogId` must be the **store catalog** (e.g. `10646`, from the `COL_SHOP` cookie `CLPBE_10646`), not the generic `10429`. |
| `…/cart/@self/update_order_item` | PUT | Update a line: `{"orderItem": [{"orderItemId": "...", "quantity": "3", "xitem_field2": "P|3|st", "partNumber": "<numeric uniqueID>"}], …}`. |
| `…/cart/@self/delete_order_item?orderItemId=…` | DELETE | Remove a cart line. |
| `/ecomfoodb2c.eshop.wcsordersvcv2/v2/store/90004/order/@history` | GET | Past orders in `Order[]` (`orderId`, `status`, `placedDate`, `grandTotal`). |
| `/ecomfoodb2c.eshop.wcslistsvc/v1/store/90004/list/@self/type/CUSTOMER` | GET | Named lists ("mijnlijstjes"). |
| `…/wcslistsvc/v1/store/90004/list/{listId}/item` | POST | Add to named list, body `{"productIds": ["<partNumber>"]}` (best effort). |

## Direct WCS resource endpoints (docs/api-collect-and-go-notes-v2.md)

The web app also talks straight to HCL Commerce resources on
`https://www.collectandgo.be/wcs/resources/store/{storeId}` — same session
cookies, no gateway prefix. The add-on uses them as a fallback when the
gateway returns a 5xx (observed on cart writes).

| Endpoint | Method | Notes |
| --- | --- | --- |
| `/wcs/resources/store/{storeId}/cart/@self` | GET | Live cart (same shape as the gateway) |
| `/wcs/resources/store/{storeId}/cart` | POST | Add item, body `{"orderItem": [{"partNumber", "quantity"}]}` |
| `/wcs/resources/store/{storeId}/cart/item/{orderItemId}` | DELETE | Remove a cart line |
| `/wcs/resources/store/V2/loginidentity` (+ `/refresh`) | POST | Login/token refresh — needs SMS 2FA, **not** automatable |

Checkout from that world (`POST cart/@self/checkout`, `PUT
shipping_info`, `POST /order`) stays in the official app: it needs the
time-sensitive `reese84` bot cookie plus `addressId`/`shipModeId` payloads.

## Checkout

Checkout is a multi-step state machine: `PUT` the handover service (e.g.
`COLLECTNEXTDAY`) onto the cart/order, then a final `POST` to submit. Time
slot and payment stay in the official app/website — deliberately out of
scope; the panel deep-links to the cart page instead.

## Reference only: the old Xtra BFF (≤ v1.x)

Base `https://apix.colruyt.be/gateway/emec.colruyt.bffsvc/cg`, auth via
`clpbff_session` cookie + `x-cg-apikey: a8ylmv13-b285-4788-9e14-0f79b7ed2411`.
Endpoints used: `/latest-shopping-list`, `/add-items-to-list`,
`/remove-item-from-list/{uuid}`, `/most-bought-products`, plus the
session-less search at
`https://apip.colruyt.be/gateway/emec.colruyt.protected.bffsvc/cg/{lang}/api/product-search-prs`
(productId = `technicalArticleNumber`). **No longer called by the add-on.**
