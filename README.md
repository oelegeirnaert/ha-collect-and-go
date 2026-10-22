# Home Assistant add-on: Collect & Go shared shopping list

Share **one** Colruyt Collect&Go / Xtra shopping list ("Mijn lijstje") with your
household — straight from the Home Assistant sidebar.

Both you and your partner open the same panel in Home Assistant, search the
Colruyt assortment and add products. Everything lands on the single shopping
list tied to your Xtra account — the same list you see in the Collect&Go
app/website and on colruyt.be. From there you add the items to your Collect&Go
cart ("winkelmand") and check out as usual (pick-up point, time slot, payment).

![panel](collect_and_go/icon.png)

## Features

- 🛒 View the shared shopping list in real time (auto-refresh)
- 🔍 Search the full Colruyt assortment (with pictures and prices)
- ➕ Add products (with quantity) — instantly visible for your partner
- ❌ Remove items from the list
- ⭐ "Most bought" quick-add suggestions
- 🔗 Deep link to your Collect&Go cart for checkout
- 🌐 UI in English, Nederlands and Français
- 🔌 REST API, so you can hook it into automations
  (e.g. *"Hey Google, add milk"* → `rest_command`)

## How it works (important!)

Collect&Go has **no public API**. This add-on uses the same unofficial
endpoints that the Colruyt website/app use. Authentication happens with your
**Xtra session cookie** (`clpbff_session`):

1. You log in once on [colruyt.be](https://www.colruyt.be) (with SMS
   verification, as usual).
2. You copy the `clpbff_session` cookie value into the add-on (via the panel).
3. The add-on stores it securely in its own data folder and reuses it until it
   expires. When it expires, the panel tells you and you repeat step 1–2.

Your password is **never** stored. The session is shared account-wide, so both
you and your girlfriend always see the same list — also in the official
Collect&Go app.

> ⚠️ Not affiliated with Colruyt Group or Collect&Go. The API can change or
> rate-limit at any time; the add-on handles that gracefully but offers no
> guarantees.

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on store → ⋮ →
   Repositories** and add the URL of this GitHub repository.
2. Install **Collect & Go — Shared Shopping List**.
3. (Optional) set your **Store ID** and **language** in the add-on
   configuration.
4. Start the add-on and open **Collect & Go** in the sidebar.
5. Follow the on-screen steps to connect your Xtra session.

## Documentation

See [collect_and_go/DOCS.md](collect_and_go/DOCS.md) for the full
documentation (also shown in the add-on's *Documentation* tab).

## Automation example

```yaml
rest_command:
  collect_and_go_add:
    url: "http://local-collect-and-go:8099/api/list/items"
    method: POST
    headers:
      Content-Type: application/json
    payload: '{"description": "{{ description }}", "quantity": {{ quantity | default(1) }}}'
```

> The hostname above works when the add-on exposes port `8099` on the
> *Network* section of the add-on page (or use the ingress URL).

## Credits

API knowledge reverse-engineered from the Colruyt/Collect&Go web apps, with
thanks to the authors of
[xtra-mcp](https://github.com/ddvlamin/xtra-mcp) for documenting the traffic.
