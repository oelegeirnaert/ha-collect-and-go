# Home Assistant add-on: Collect & Go shared cart

Manage **one** Collect&Go cart ("winkelmand") with your household — straight
from the Home Assistant sidebar.

Both you and your partner open the same panel in Home Assistant, search the
Collect&Go assortment and add products. Everything lands in the real cart of
your Collect&Go account — the same cart you see in the official Collect&Go
app/website. From there you pick a time slot and check out as usual
(pick-up point, time slot, payment).

![panel](collect_and_go/icon.png)

## Features

- 🛒 View the live Collect&Go cart in real time (auto-refresh)
- 🔍 Search the full Collect&Go assortment (with pictures and prices)
- ➕ Add products (with quantity) — instantly visible for your partner
- 🔢 Change quantities and ❌ remove items straight from the panel
- 📋 Named lists ("mijnlijstjes") supported as add target
- 🔗 Deep link to checkout in the official Collect&Go app
- 🌐 UI in English, Nederlands and Français
- 🔌 REST API, so you can hook it into automations
  (e.g. *"Hey Google, add milk"* → `rest_command`)

## How it works (important!)

Collect&Go has **no public API**. This add-on uses the same unofficial
endpoints that the Collect&Go website uses itself (the HCL/WCS gateway).
Authentication happens with your **session token** (`wcauthtoken`):

1. You log in once on [collectandgo.be](https://www.collectandgo.be) (with
   SMS verification, as usual) and pick your store.
2. You copy the `wcauthtoken` cookie value into the add-on (via the panel).
3. The add-on validates it against your live cart, stores it securely in its
   own data folder and reuses it until it expires. When it expires, the
   panel tells you and you repeat step 1–2.

Your password is **never** stored. The cart is shared account-wide, so both
you and your partner always see the same cart — also in the official
Collect&Go app.

> ⚠️ Not affiliated with Colruyt Group or Collect&Go. The API can change or
> rate-limit at any time; the add-on handles that gracefully but offers no
> guarantees.

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on store → ⋮ →
   Repositories** and add the URL of this GitHub repository.
2. Install **Collect & Go — Shared Cart**.
3. (Optional) set the **language** in the add-on configuration.
4. Start the add-on and open **Collect & Go** in the sidebar.
5. Follow the on-screen steps to connect your Collect&Go session.

## Documentation

See [collect_and_go/DOCS.md](collect_and_go/DOCS.md) for the full
documentation (also shown in the add-on's *Documentation* tab).

## Automation example

```yaml
rest_command:
  collect_and_go_add:
    url: "http://local-collect-and-go:8099/api/cart/items"
    method: POST
    headers:
      Content-Type: application/json
    payload: '{"product_id": "{{ product_id }}", "entry_id": "{{ entry_id }}", "quantity": {{ quantity | default(1) }}}'
```

Find the ids first via `GET /api/search?q=melk` → `products[].product_id`
and `products[].entry_id`.

> The hostname above works when the add-on exposes port `8099` on the
> *Network* section of the add-on page (or use the ingress URL).

## Contributing / local development

You don't need a Home Assistant instance to hack on this add-on — it runs
standalone. The only requirement is [`just`](https://just.systems)
(`sudo apt install just` / `brew install just` / `snap install just`) plus
Python 3.12+ and optionally Docker.

```bash
just            # list all available tasks
just setup      # one-time: create .venv and install dependencies
just run        # run the app at http://127.0.0.1:8099 (no Docker)
just dev        # same, but with auto-reload on code changes
just check      # syntax-check Python + validate YAML manifests
just docker-run # build & run the real add-on image (closest to HASS)
just docker-stop
```

Data (your session, options) is stored in `/tmp/cg-data` for `just run`/
`just dev` and in `./.dev-data` for `just docker-run` — both git-ignored.
To simulate add-on options locally, write an `options.json` there, e.g.:

```json
{"language": "nl"}
```

### Testing with your Collect&Go account

Open http://127.0.0.1:8099, paste your `wcauthtoken` cookie (see
[DOCS.md](collect_and_go/DOCS.md)) and use the UI as you would in HASS.

### Releasing a new version

```bash
just release patch "Short description of the fix"
```

This bumps `config.yaml` + `APP_VERSION`, prepends to
[CHANGELOG.md](collect_and_go/CHANGELOG.md), commits, tags and pushes.
Use `minor`/`major` for features/breaking changes.

## Credits

API knowledge reverse-engineered from the Colruyt/Collect&Go web apps, with
thanks to the authors of
[xtra-mcp](https://github.com/ddvlamin/xtra-mcp) for documenting the traffic.
