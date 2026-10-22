# Collect & Go — Shared Shopping List

Share one Colruyt Collect&Go / Xtra shopping list ("Mijn lijstje") with your
household, straight from the Home Assistant sidebar.

Everyone who opens this panel sees **the same list** (it lives on your Xtra
account). Search products, add them with a quantity, remove them again — the
other person sees it within seconds. When the week is done, open your
Collect&Go cart via the 🧺 button, add the list to the cart and check out as
usual (pick-up point, time slot and payment stay in the official
app/website).

## Setup (one time, ±1 minute)

1. Start the add-on and open **Collect & Go** in the sidebar.
2. The panel asks you to connect your Xtra account:
   - Open [colruyt.be](https://www.colruyt.be) **in a new tab** and log in
     (with the SMS code, as usual).
   - Stay on colruyt.be and open the developer tools with **F12**.
   - Go to **Application** (Chrome/Edge) or **Storage** (Firefox) →
     **Cookies** → `https://www.colruyt.be`.
   - Copy the **value** of the cookie named `clpbff_session`
     (an UUID like `61c33aee-cb24-…`).
   - Paste it in the add-on panel and save.
3. Done — both you and your partner can now use the panel.

> Only the session id is stored (in the add-on's own data folder,
> `/data/session.json`). Your password is never stored. You can also store
> the cookie in the add-on **configuration** (`session_cookie` option) if you
> prefer; a session saved via the panel takes precedence.

### Session expired?

Sessions don't last forever (days to weeks). When it expires, the panel shows
a warning — just repeat the steps above.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| `place_id` | `2643` | Numeric id of your Colruyt store (used for store-specific prices/availability). |
| `language` | `nl` | Language for product data: `nl` or `fr`. |
| `session_cookie` | _(empty)_ | Optional: the `clpbff_session` value (see above). |

### Finding your own store id

The default works for searching, but prices and availability are store
specific. To find your store's id: on
[collectandgo.be](https://www.collectandgo.be), pick your store, then open the
developer tools → **Network** → filter on `placeId`. The numeric value in any
API request is your store id.

## Using the REST API from automations

Enable port `8099` on the add-on's *Network* section (or use the ingress URL).
Then for example:

```yaml
rest_command:
  cg_add_item:
    url: "http://local-collect-and-go:8099/api/list/items"
    method: POST
    headers:
      Content-Type: application/json
    payload: '{"items": [{"description": "{{ item }}", "quantity": {{ qty | default(1) }}}]}'
```

Add a searched product by id for a precise match:

```json
{"items": [{"product_id": "2318063", "description": "Volle melk brik", "quantity": 2}]}
```

### API overview

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/state` | GET | Add-on + session configuration state |
| `/api/session/check` | GET | Validate the stored session |
| `/api/session` | POST / DELETE | Save / clear the session cookie |
| `/api/list` | GET | Current shopping list |
| `/api/list/items` | POST | Add item(s) `{items: [...]}` |
| `/api/list/items/{id}` | DELETE | Remove an item |
| `/api/search?q=...` | GET | Search the assortment |
| `/api/most-bought` | GET | Frequently bought products |

## Notes & limitations

- Not affiliated with Colruyt Group. The API is unofficial and may change.
- The Colruyt API rate-limits: the add-on caches briefly and tells you when to
  slow down instead of failing silently.
- The list is shared account-wide: it also appears in the Xtra app and in the
  Collect&Go app/website under "Mijn lijstje".
- Changing the quantity of an existing list item = remove + add again.
