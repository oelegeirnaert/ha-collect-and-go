# API notes (reverse engineered, verified 2026-10-22)

No official public API exists. These are the endpoints the Colruyt web apps
call themselves. Traffic credits: github.com/ddvlamin/xtra-mcp
(docs/api-call-dumps) + own probing.

## Auth

- Login is Azure AD B2C at `login.myxtra.be` (`B2C_1A_signin`) **with SMS
  verification** → not sanely automatable → the add-on reuses the session.
- Session cookie: `clpbff_session` (UUID), domain `.colruyt.be`.
- Every API call also needs the public header
  `x-cg-apikey: a8ylmv13-b285-4788-9e14-0f79b7ed2411` (hardcoded in the web
  apps).
- There is Imperva-style bot protection (`reese84` cookie). Bursts of
  unauthenticated requests get answered with **HTTP 456** → the app caches
  and backs off.

## Endpoints

Base: `https://apix.colruyt.be/gateway/emec.colruyt.bffsvc/cg`
(session cookie required; 401 without)

| Endpoint | Method | Notes |
| --- | --- | --- |
| `/latest-shopping-list` | GET | params: `limit, offset, sort=createdAt desc, placeId, lang, prs=true` → JSON with items under `getListItems.data` **or** `data.items` **or** `items` |
| `/add-items-to-list` | POST | body `{"items":[{id: uuid, createdAt, updatedAt, completedAt: null, description, productData: {productId, quantity, unitCode: "P"}}]}` → returns the **full** updated list. `productData` optional for free-text items. |
| `/remove-item-from-list/{uuid}` | DELETE | 200/204 |
| `/most-bought-products` | GET | params `lang, placeId, prs=true` → array of products |

Product search (**no session needed**, only the api key):

```
GET https://apip.colruyt.be/gateway/emec.colruyt.protected.bffsvc/cg/{lang}/api/product-search-prs
    ?searchTerm=melk&placeId=2643&size=25&sort=relevancy desc&isAvailable=true&skip=0
```

Product fields used: `technicalArticleNumber` (= productId), `name`,
`LongName`, `brand`, `content`, `thumbNail`, `topCategoryName`,
`price.basicPrice`, `price.measurementUnit`, `price.measurementUnitPrice`,
`isAvailable`, `IsWeightArticle`, `GTIN`.

## Collect&Go WCS gateway (cart, orders, shop search)

The Collect&Go shop itself runs on an HCL/WCS commerce backend with its own
gateways under `https://apip.collectandgo.be/gateway` (see
docs/api-collect-and-go-notes.md).

Auth for these endpoints: the public `x-cg-apikey` header **plus** a dynamic
`wcauthtoken` header (session token, copied from a logged-in
collectandgo.be browser session), and `content-type: application/json`.

| Endpoint | Method | Notes |
| --- | --- | --- |
| `/ecomfoodb2c.eshop.wcsproductviewsearchsvc/v1/store/90004/productview/bySearchTerm/{term}` | GET | Shop search; products in `catalogEntryView`, id = `partNumber` |
| `/ecomfoodb2c.eshop.wcscartsvcv2/v2/store/90004/cart/@self` | GET | Live cart contents (`orderItem` array) |
| `/ecomfoodb2c.eshop.wcscartsvcv2/v2/store/90004/cart/@self/update_order_item` | PUT | Add to cart, body `{"orderItem": [{"partNumber", "quantity"}], "catalogId", "langId"}` |
| `/ecomfoodb2c.eshop.wcsordersvcv2/v2/store/90004/order/@history` | GET | Past orders (`Order` array) |

Store id `90004`, catalogId `10429`, langId `-1001` (nl) / `-1002` (fr),
apiGatewayKey `502b657c-624c-11eb-8024-f4d06b721e80`.

Checkout is a multi-step state machine (PUT the handover service, e.g.
`COLLECTNEXTDAY`, on the cart, then a final POST to submit) and stays in the
official app/website. Token refresh would go through the `/xtra/authentication`
endpoints, but login needs SMS 2FA, so the add-on just stores a pasted token.

## List vs. cart

The Xtra **shopping list** (above) is shared account-wide and shows up in the
Xtra app, colruyt.be and Collect&Go ("Mijn lijstje"). The actual Collect&Go
**cart** (`www.collectandgo.be/nl/winkelwagen`) runs on a separate HCL/WCS
commerce backend (`orderItem`, `calculateBasket`, …) — reverse engineering it
is possible but unverified without an account; deliberately out of scope for
v1. Checkout (time slot, payment) stays in the official app anyway.
