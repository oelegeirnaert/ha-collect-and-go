"""Collect & Go — shared Collect&Go cart add-on.

FastAPI server that exposes a small REST API and serves the single-file web
UI. Designed to run behind Home Assistant ingress (relative URL handling),
with optional direct port access for automations.

All product/cart/order traffic goes through the Collect&Go (HCL/WCS)
gateway — see collectandgo.py and docs/api-notes.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from collectandgo import (
    API_KEY,
    CART_PAGE_URLS,
    AuthError,
    CollectAndGoClient,
    CollectAndGoError,
    RateLimited,
    UpstreamError,
)
from session_store import SessionStore, extract_session_cookies

APP_VERSION = "2.3.0"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OPTIONS_FILE = DATA_DIR / "options.json"
INDEX_FILE = Path(__file__).parent / "static" / "index.html"

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s: %(message)s"
)
_LOGGER = logging.getLogger("collect-and-go")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def _load_options() -> dict[str, Any]:
    defaults: dict[str, Any] = {"language": "nl"}
    try:
        data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update({k: v for k, v in data.items() if v is not None})
    except (OSError, ValueError):
        _LOGGER.warning("No add-on options found at %s, using defaults", OPTIONS_FILE)
    defaults["language"] = defaults.get("language") if defaults.get("language") in ("nl", "fr") else "nl"
    return defaults


OPTIONS = _load_options()
SESSIONS = SessionStore(DATA_DIR / "session.json")


def get_client() -> CollectAndGoClient:
    """Build a client with the best available session cookies.

    Precedence: cookies saved via the panel (/data/session.json) — usually
    the most recent — falling back to the optional ``session_cookies``
    add-on option (a pasted cookie header works there too).
    """
    cookies = SESSIONS.load()
    if not cookies and OPTIONS.get("session_cookies"):
        cookies = extract_session_cookies(str(OPTIONS["session_cookies"]))
    return CollectAndGoClient(
        session=cookies,
        lang=OPTIONS.get("language") or "nl",
    )


# ---------------------------------------------------------------------------
# tiny TTL cache — the Collect&Go API rate-limits aggressively (HTTP 456)
# ---------------------------------------------------------------------------

class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float) -> Optional[Any]:
        hit = self._data.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl:
            return hit[1]
        return None

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.monotonic(), value)

    def invalidate(self, prefix: str) -> None:
        for key in [k for k in self._data if k.startswith(prefix)]:
            del self._data[key]

    def clear(self) -> None:
        self._data.clear()


CACHE = TTLCache()
CART_CACHE_TTL = 8.0
SEARCH_CACHE_TTL = 30.0
ORDER_CACHE_TTL = 300.0
LIST_CACHE_TTL = 60.0


# ---------------------------------------------------------------------------
# app + error mapping
# ---------------------------------------------------------------------------

app = FastAPI(title="Collect & Go", version=APP_VERSION, docs_url=None, redoc_url=None)


@app.exception_handler(AuthError)
async def auth_error_handler(_, exc: AuthError):
    return JSONResponse(status_code=401, content={"error": "auth", "detail": str(exc)})


@app.exception_handler(RateLimited)
async def rate_limit_handler(_, exc: RateLimited):
    return JSONResponse(status_code=429, content={"error": "rate_limited", "detail": str(exc)})


@app.exception_handler(CollectAndGoError)
async def upstream_error_handler(_, exc: CollectAndGoError):
    return JSONResponse(status_code=502, content={"error": "upstream", "detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def network_error_handler(_, exc: httpx.HTTPError):
    _LOGGER.warning("Network error talking to Collect&Go: %s", exc)
    return JSONResponse(status_code=502, content={"error": "network", "detail": str(exc)})


class SessionIn(BaseModel):
    cookies: str = Field(min_length=1)


class AddToCartIn(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1, le=99)
    entry_id: Optional[str] = None


class UpdateCartItemIn(BaseModel):
    quantity: int = Field(ge=1, le=99)
    part_number: Optional[str] = None


class AddToNamedListIn(BaseModel):
    list_id: str = Field(min_length=1)
    product_ids: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# state & session
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
async def state() -> dict[str, Any]:
    client = get_client()
    configured = client.has_session
    return {
        "version": APP_VERSION,
        "configured": configured,
        "language": client.lang,
        "cart_url": CART_PAGE_URLS.get(client.lang, CART_PAGE_URLS["nl"]),
        "session_source": "panel" if SESSIONS.load() else ("options" if configured else None),
    }


@app.get("/api/session/check")
async def session_check() -> dict[str, Any]:
    client = get_client()
    if not client.has_session:
        return {"configured": False, "valid": False}
    valid = await client.validate_session()
    return {"configured": True, "valid": valid}


@app.post("/api/session")
async def session_save(body: SessionIn) -> dict[str, Any]:
    """Save a new session. Accepts anything the user can copy: a whole
    cookie header, the DevTools cookie-table rows, a single
    ``WC_AUTHENTICATION_…=…`` pair, or just its value. Validated against
    the live cart before storing — so a wrong paste is caught immediately."""
    cookies = extract_session_cookies(body.cookies)
    if not cookies:
        raise HTTPException(
            status_code=400,
            detail="Could not find the WC_AUTHENTICATION cookie in what you pasted.",
        )
    client = CollectAndGoClient(
        session=cookies,
        lang=OPTIONS.get("language") or "nl",
    )
    valid = await client.validate_session()
    if not valid:
        raise HTTPException(status_code=401, detail="Session was rejected by Collect&Go.")
    SESSIONS.save(cookies)
    CACHE.clear()
    _LOGGER.info(
        "New Collect&Go session saved and validated (%d cookies: %s).",
        len(cookies),
        ", ".join(sorted(cookies)),
    )
    return {"configured": True, "valid": True}


@app.delete("/api/session")
async def session_clear() -> dict[str, bool]:
    SESSIONS.clear()
    CACHE.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# cart ("winkelmand") — the shared object this add-on is built around
# ---------------------------------------------------------------------------

@app.get("/api/cart")
async def view_cart(force: bool = False) -> dict[str, Any]:
    """Live contents of the Collect&Go cart.

    Cart lines only carry the numeric partNumber, so we enrich them with the
    product's name, image and price via a batched catalog lookup
    (best-effort — a lookup failure never breaks the cart).
    """
    if not force:
        cached = CACHE.get("cart", CART_CACHE_TTL)
        if cached is not None:
            return {**cached, "cached": True}
    cart = await get_client().get_cart()
    await _enrich_cart(cart)
    CACHE.set("cart", cart)
    return {**cart, "cached": False}


async def _enrich_cart(cart: dict[str, Any]) -> None:
    """Fill in name/image/price for cart lines that only have an id."""
    items = cart.get("items") or []
    # ids that still look "bare" (description is just the partNumber)
    need = [
        i.get("entry_id")
        for i in items
        if i.get("entry_id") and (not i.get("description") or i.get("description") == i.get("entry_id") or not i.get("image"))
    ]
    need = [n for n in dict.fromkeys(need) if n]
    if not need:
        return
    lookup = await get_client().get_products_by_ids(need)
    if not lookup:
        return
    for item in items:
        product = lookup.get(item.get("entry_id") or "")
        if not product:
            continue
        if not item.get("description") or item["description"] == item.get("entry_id"):
            item["description"] = product.get("name") or item["description"]
        if not item.get("image"):
            item["image"] = product.get("image") or ""
        item["brand"] = product.get("brand") or ""
        item["content"] = product.get("content") or ""
        if item.get("price") is None and product.get("price") is not None:
            # per-unit catalog price × quantity as a fallback line price
            item["unit_price"] = product["price"]
            item["price"] = round(product["price"] * (item.get("quantity") or 1), 2)
        elif item.get("price") is not None and item.get("quantity"):
            item["unit_price"] = round(item["price"] / item["quantity"], 2)
        item["product_id"] = product.get("product_id") or item.get("product_id")


@app.post("/api/cart/items")
async def add_to_cart(body: AddToCartIn) -> dict[str, Any]:
    """Add a product to the cart. Also usable from HASS automations:

    rest_command payload: {"product_id": "14507", "entry_id": "3074…", "quantity": 2}
    — ``entry_id`` (the numeric uniqueID) is what the cart actually needs;
    both come straight from /api/search results.
    """
    result = await get_client().add_to_cart(
        body.product_id, body.quantity, entry_id=body.entry_id
    )
    CACHE.invalidate("cart")
    return {"added": True, "result": result}


@app.put("/api/cart/items/{order_item_id}")
async def update_cart_item(order_item_id: str, body: UpdateCartItemIn) -> dict[str, Any]:
    result = await get_client().update_cart_item(
        order_item_id, body.quantity, part_number=body.part_number
    )
    CACHE.invalidate("cart")
    return {"updated": True, "result": result}


@app.delete("/api/cart/items/{order_item_id}")
async def remove_cart_item(order_item_id: str) -> dict[str, Any]:
    ok = await get_client().remove_cart_item(order_item_id)
    CACHE.invalidate("cart")
    return {"removed": ok}


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------

@app.get("/api/orders")
async def order_history() -> dict[str, Any]:
    """Past Collect&Go orders of the account."""
    cached = CACHE.get("orders", ORDER_CACHE_TTL)
    if cached is not None:
        return {"orders": cached}
    orders = await get_client().get_order_history()
    CACHE.set("orders", orders)
    return {"orders": orders}


# ---------------------------------------------------------------------------
# named lists (Collect&Go "mijnlijstjes")
# ---------------------------------------------------------------------------

@app.get("/api/lists")
async def named_lists() -> dict[str, Any]:
    cached = CACHE.get("lists", LIST_CACHE_TTL)
    if cached is not None:
        return {"lists": cached}
    try:
        lists = await get_client().get_lists()
    except AuthError:
        raise
    except CollectAndGoError:
        lists = []
    CACHE.set("lists", lists)
    return {"lists": lists}


@app.post("/api/lists/items")
async def add_to_named_list(body: AddToNamedListIn) -> dict[str, Any]:
    ok = await get_client().add_products_to_named_list(body.list_id, body.product_ids)
    return {"added": ok, "list_id": body.list_id}


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search(q: str = "", size: int = 24) -> dict[str, Any]:
    """Search the Collect&Go assortment. Results carry the WCS ``partNumber``
    (``product_id``) that the cart endpoints accept."""
    q = q.strip()
    if len(q) < 2:
        return {"total": 0, "products": []}
    size = max(1, min(size, 50))
    key = f"search:{q.lower()}:{size}"
    cached = CACHE.get(key, SEARCH_CACHE_TTL)
    if cached is not None:
        return cached
    result = await get_client().search_products(q, size=size)
    CACHE.set(key, result)
    return result


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

async def _startup_check() -> None:
    client = get_client()
    if not client.has_session:
        _LOGGER.info("No session configured yet — open the panel to connect Collect&Go.")
        return
    try:
        valid = await client.validate_session()
        if valid:
            _LOGGER.info("Collect&Go session valid. Language=%s.", client.lang)
        else:
            _LOGGER.warning("Collect&Go session expired or invalid — reconnect via the panel.")
    except CollectAndGoError as exc:
        _LOGGER.warning("Could not validate session at startup: %s", exc)


@app.on_event("startup")
async def on_startup() -> None:
    _LOGGER.info("Collect & Go add-on v%s starting (api key …%s)", APP_VERSION, API_KEY[-8:])
    asyncio.create_task(_startup_check())


def main() -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8099,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
