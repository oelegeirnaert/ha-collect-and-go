"""Collect & Go — shared shopping list add-on.

FastAPI server that exposes a small REST API and serves the single-file web
UI. Designed to run behind Home Assistant ingress (relative URL handling),
with optional direct port access for automations.
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

from colruyt import (
    API_KEY,
    CART_URLS,
    AuthError,
    ColruytClient,
    ColruytError,
    RateLimited,
    UpstreamError,
)
from session_store import SessionStore, extract_session_cookie

APP_VERSION = "1.0.3"
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
    defaults: dict[str, Any] = {"place_id": "2643", "language": "nl"}
    try:
        data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update({k: v for k, v in data.items() if v is not None})
    except (OSError, ValueError):
        _LOGGER.warning("No add-on options found at %s, using defaults", OPTIONS_FILE)
    defaults["language"] = defaults.get("language") if defaults.get("language") in ("nl", "fr") else "nl"
    defaults["place_id"] = str(defaults.get("place_id") or "2643")
    return defaults


OPTIONS = _load_options()
SESSIONS = SessionStore(DATA_DIR / "session.json")


def get_client() -> ColruytClient:
    """Build a client with the best available session.

    Precedence: session saved via the panel (/data/session.json) — that one
    is usually the most recent — falling back to the optional add-on option.
    """
    session = SESSIONS.load() or OPTIONS.get("session_cookie") or None
    if session:
        session = extract_session_cookie(session) or session
    return ColruytClient(
        session_id=session,
        place_id=str(OPTIONS.get("place_id") or "2643"),
        lang=OPTIONS.get("language") or "nl",
    )


# ---------------------------------------------------------------------------
# tiny TTL cache — the Colruyt API rate-limits aggressively (HTTP 456)
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


CACHE = TTLCache()
LIST_CACHE_TTL = 8.0
SEARCH_CACHE_TTL = 30.0
MOST_BOUGHT_CACHE_TTL = 300.0


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


@app.exception_handler(ColruytError)
async def upstream_error_handler(_, exc: ColruytError):
    return JSONResponse(status_code=502, content={"error": "upstream", "detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def network_error_handler(_, exc: httpx.HTTPError):
    _LOGGER.warning("Network error talking to Colruyt: %s", exc)
    return JSONResponse(status_code=502, content={"error": "network", "detail": str(exc)})


class SessionIn(BaseModel):
    cookie: str = Field(min_length=1)


class AddItemIn(BaseModel):
    product_id: Optional[str] = None
    description: Optional[str] = None
    quantity: int = Field(default=1, ge=1, le=99)


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
    configured = bool(client.session_id)
    return {
        "version": APP_VERSION,
        "configured": configured,
        "place_id": client.place_id,
        "language": client.lang,
        "cart_url": CART_URLS.get(client.lang, CART_URLS["nl"]),
        "session_source": "panel" if SESSIONS.load() else ("options" if configured else None),
    }


@app.get("/api/session/check")
async def session_check() -> dict[str, Any]:
    client = get_client()
    if not client.session_id:
        return {"configured": False, "valid": False}
    valid = await client.validate_session()
    return {"configured": True, "valid": valid}


@app.post("/api/session")
async def session_save(body: SessionIn) -> dict[str, Any]:
    session = extract_session_cookie(body.cookie)
    if not session:
        raise HTTPException(
            status_code=400,
            detail="Could not find a clpbff_session value in what you pasted.",
        )
    client = ColruytClient(
        session_id=session,
        place_id=str(OPTIONS.get("place_id") or "2643"),
        lang=OPTIONS.get("language") or "nl",
    )
    valid = await client.validate_session()
    if not valid:
        raise HTTPException(status_code=401, detail="Session was rejected by Colruyt.")
    SESSIONS.save(session)
    CACHE.invalidate("list")
    _LOGGER.info("New session saved and validated.")
    return {"configured": True, "valid": True}


@app.delete("/api/session")
async def session_clear() -> dict[str, bool]:
    SESSIONS.clear()
    CACHE.invalidate("list")
    return {"ok": True}


# ---------------------------------------------------------------------------
# shopping list
# ---------------------------------------------------------------------------

@app.get("/api/list")
async def list_items(force: bool = False) -> dict[str, Any]:
    if not force:
        cached = CACHE.get("list", LIST_CACHE_TTL)
        if cached is not None:
            return {"items": cached, "cached": True}
    items = await get_client().get_list()
    CACHE.set("list", items)
    return {"items": items, "cached": False}


class AddItemsIn(BaseModel):
    items: list[AddItemIn]


@app.post("/api/list/items")
async def add_item(body: AddItemsIn) -> dict[str, Any]:
    """Add one or more items. Also usable from HASS automations:

    rest_command example payload: {"items": [{"description": "Melk", "quantity": 2}]}
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="No items provided.")
    to_add = []
    for item in body.items:
        description = (item.description or "").strip()
        if not description and item.product_id:
            description = f"Product {item.product_id}"
        if not description:
            raise HTTPException(status_code=400, detail="description is required.")
        to_add.append(
            {
                "product_id": item.product_id,
                "description": description,
                "quantity": item.quantity,
            }
        )
    items = await get_client().add_items(to_add)
    CACHE.set("list", items)
    return {"items": items, "added": len(to_add)}


@app.delete("/api/list/items/{item_id}")
async def remove_item(item_id: str) -> dict[str, Any]:
    ok = await get_client().remove_item(item_id)
    CACHE.invalidate("list")
    return {"removed": ok}


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search(q: str = "", size: int = 24) -> dict[str, Any]:
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


@app.get("/api/most-bought")
async def most_bought() -> dict[str, Any]:
    cached = CACHE.get("most-bought", MOST_BOUGHT_CACHE_TTL)
    if cached is not None:
        return {"products": cached}
    products = await get_client().most_bought()
    CACHE.set("most-bought", products)
    return {"products": products}


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

async def _startup_check() -> None:
    client = get_client()
    if not client.session_id:
        _LOGGER.info("No session configured yet — open the panel to connect your Xtra account.")
        return
    try:
        valid = await client.validate_session()
        if valid:
            _LOGGER.info("Session valid. Store placeId=%s, language=%s.", client.place_id, client.lang)
        else:
            _LOGGER.warning("Session expired or invalid — reconnect via the panel.")
    except ColruytError as exc:
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
