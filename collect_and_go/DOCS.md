# Collect & Go — Shared Cart

Manage your Collect&Go cart ("winkelmand") together, straight from the Home
Assistant sidebar.

Everyone who opens this panel sees **the same cart** — it *is* the cart of
your Collect&Go account. Search the assortment, add products with a
quantity, adjust amounts, remove items — the other person sees it within
seconds. When the week is done, tap **🧺 Checkout** to open the cart in the
official Collect&Go app/website and finish there (pick-up point, time slot
and payment stay in the official app).

## Setup (one time, ±1 minute)

1. Start the add-on and open **Collect & Go** in the sidebar.
2. The panel asks you to connect Collect&Go:
   - Open [collectandgo.be](https://www.collectandgo.be) **in a new tab**,
     log in with your Xtra account (SMS code, as usual) and pick your store.
   - Stay on collectandgo.be and open the developer tools with **F12**.
   - Go to **Application** (Chrome/Edge) or **Storage** (Firefox) →
     **Cookies** → `https://www.collectandgo.be`.
   - Find the cookie that starts with **`WC_AUTHENTICATION_`** and copy its
     **name and value** (e.g. `WC_AUTHENTICATION_1234567=1234567%2C…`).
   - Paste it in the add-on panel and save.
3. The add-on validates the session against your live cart immediately — a
   wrong value is rejected with a clear message. Done — both you and your
   partner can now use the panel.

> Only the session cookies are stored (in the add-on's own data folder,
> `/data/session.json`). Your password is never stored. Pasting a whole
> cookie header (or several cookies at once) works too — the add-on picks
> out what it needs (`WC_AUTHENTICATION_…`, `WC_USERACTIVITY_…`,
> `WC_ACTIVEPOINTER`, `WC_SESSION_ESTABLISHED`). You can also store the
> cookies in the add-on **configuration** (`session_cookies` option) if you
> prefer configuration-as-code; a session saved via the panel takes
> precedence.

### Session expired?

Tokens don't last forever (days to weeks). When it expires, the panel shows
a warning — just repeat the steps above.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| `language` | `nl` | Language for product data: `nl` or `fr`. |
| `session_cookies` | _(empty)_ | Optional: the session cookies (see above). |

> Upgrading from v2.0/v2.1? The `wcauthtoken`, `wctoken` and
> `wctrustedtoken` options were replaced by a single `session_cookies`
> paste — there is no `wcauthtoken` on collectandgo.be; the session is the
> `WC_AUTHENTICATION_…` cookie (+ friends).

> Upgrading from v1.x? The `place_id` and `session_cookie` options no longer
> exist — the store is taken from your Collect&Go session and the old Xtra
> cookie is not used anymore. You can remove both from the configuration.

## Using the REST API from automations

Enable port `8099` on the add-on's *Network* section (or use the ingress
URL). First find the product ids via search:

`GET /api/search?q=melk` → `products[].product_id` (+ `products[].entry_id`)

Then add it to the cart:

```yaml
rest_command:
  cg_add_item:
    url: "http://local-collect-and-go:8099/api/cart/items"
    method: POST
    headers:
      Content-Type: application/json
    payload: '{"product_id": "{{ product_id }}", "entry_id": "{{ entry_id }}", "quantity": {{ qty | default(1) }}}'
```

### API overview

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/state` | GET | Add-on + session configuration state |
| `/api/session/check` | GET | Validate the stored session against the live cart |
| `/api/session` | POST / DELETE | Save / clear the session (`{cookies}` — paste anything) |
| `/api/cart` | GET | Live cart contents (items, quantities, total) |
| `/api/cart/items` | POST | Add a product `{product_id, entry_id, quantity}` — both ids from search |
| `/api/cart/items/{orderItemId}` | PUT | Change a cart line's quantity `{quantity}` |
| `/api/cart/items/{orderItemId}` | DELETE | Remove a cart line |
| `/api/orders` | GET | Past Collect&Go orders |
| `/api/search?q=...` | GET | Search the Collect&Go assortment |
| `/api/lists` | GET | Named lists ("mijnlijstjes") |
| `/api/lists/items` | POST | Add products to a named list `{list_id, product_ids}` |

## Notes & limitations

- Not affiliated with Colruyt Group. The API is unofficial and may change.
- The Collect&Go API rate-limits: the add-on caches briefly and tells you
  when to slow down instead of failing silently.
- Everything happens in the real cart of the account — the same cart you
  see in the Collect&Go app/website.
- Free-text items no longer exist (that was v1's Xtra list): the cart only
  accepts real products.
- Checkout (time slot, payment) stays in the official Collect&Go
  app/website.
