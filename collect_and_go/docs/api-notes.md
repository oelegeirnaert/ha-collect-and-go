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

## List vs. cart

The Xtra **shopping list** (above) is shared account-wide and shows up in the
Xtra app, colruyt.be and Collect&Go ("Mijn lijstje"). The actual Collect&Go
**cart** (`www.collectandgo.be/nl/winkelwagen`) runs on a separate HCL/WCS
commerce backend (`orderItem`, `calculateBasket`, …) — reverse engineering it
is possible but unverified without an account; deliberately out of scope for
v1. Checkout (time slot, payment) stays in the official app anyway.
