"""Async client for the unofficial Colruyt / Collect&Go (Xtra) API.

The endpoints below are the ones the official Colruyt website and Xtra app
use themselves (reverse engineered, see docs/api-notes.md). There is no
public API, so this can break or get rate-limited at any time.

Authentication
--------------
Two things are needed for the account endpoints:

* the ``clpbff_session`` cookie (an UUID created after logging in with your
  Xtra account on www.colruyt.be — login includes SMS verification, which is
  why this add-on reuses the cookie instead of logging in itself);
* the public ``x-cg-apikey`` header that the website sends along.

Product search works with only the API key, no session required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

# Public API key used by www.colruyt.be / www.collectandgo.be web apps.
API_KEY = "a8ylmv13-b285-4788-9e14-0f79b7ed2411"

BASE_URL = "https://apix.colruyt.be/gateway/emec.colruyt.bffsvc/cg"
SEARCH_URL = (
    "https://apip.colruyt.be/gateway/emec.colruyt.protected.bffsvc"
    "/cg/{lang}/api/product-search-prs"
)

# Link to the real cart for the checkout step (language dependent).
CART_URLS = {
    "nl": "https://www.collectandgo.be/nl/winkelwagen",
    "fr": "https://www.collectandgo.be/fr/chariot",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 20.0


class ColruytError(Exception):
    """Base error for API failures."""


class AuthError(ColruytError):
    """The session cookie is missing, invalid or expired."""


class RateLimited(ColruytError):
    """The API is rate-limiting / bot-challenging us (HTTP 429 or 456)."""


class UpstreamError(ColruytError):
    """Unexpected response from the Colruyt servers."""


def _check_response(resp: httpx.Response) -> None:
    """Translate HTTP status codes into meaningful exceptions."""
    if resp.status_code in (401, 403):
        raise AuthError(f"session rejected ({resp.status_code})")
    if resp.status_code in (429, 456):
        raise RateLimited(f"rate limited ({resp.status_code})")
    if resp.status_code >= 400:
        raise UpstreamError(f"unexpected status {resp.status_code}")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def normalize_product(p: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw API product to the fields the UI needs."""
    price = p.get("price") or {}
    return {
        "product_id": str(p.get("technicalArticleNumber") or ""),
        "name": p.get("LongName") or p.get("name") or "",
        "short_name": p.get("name") or "",
        "brand": p.get("brand") or "",
        "content": p.get("content") or "",
        "image": p.get("thumbNail") or p.get("fullImage") or "",
        "category": p.get("topCategoryName") or "",
        "price": price.get("basicPrice"),
        "unit": price.get("measurementUnit") or "",
        "unit_price": price.get("measurementUnitPrice"),
        "available": bool(p.get("isAvailable", True)),
        "is_weight_article": bool(p.get("IsWeightArticle", False)),
    }


def normalize_list_item(i: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw shopping-list entry to the fields the UI needs."""
    data = i.get("productData") or {}
    return {
        "id": i.get("id"),
        "description": i.get("description") or "",
        "product_id": data.get("productId"),
        "quantity": data.get("quantity", 1),
        "unit_code": data.get("unitCode") or "P",
        "completed": bool(i.get("completedAt")),
        "created_at": i.get("createdAt"),
    }


def parse_list_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The list endpoint has used several shapes over time; handle them all."""
    raw_items = (
        (data.get("getListItems") or {}).get("data")
        or (data.get("data") or {}).get("items")
        or data.get("items")
        or []
    )
    return [normalize_list_item(i) for i in raw_items]


class ColruytClient:
    """Minimal async client for the Xtra shopping-list + product search."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        place_id: str = "2643",
        lang: str = "nl",
        api_key: str = API_KEY,
    ) -> None:
        self.session_id = session_id or None
        self.place_id = place_id or "2643"
        self.lang = lang if lang in ("nl", "fr") else "nl"
        self.api_key = api_key

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-cg-apikey": self.api_key,
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
            "Origin": "https://www.colruyt.be",
            "Referer": "https://www.colruyt.be/",
        }

    @property
    def _cookies(self) -> dict[str, str]:
        return {"clpbff_session": self.session_id} if self.session_id else {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers=self._headers,
            cookies=self._cookies,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # session
    # ------------------------------------------------------------------
    async def validate_session(self) -> bool:
        """Return True when the session cookie is accepted by the API."""
        if not self.session_id:
            return False
        try:
            await self.get_list(limit=1)
            return True
        except AuthError:
            return False

    # ------------------------------------------------------------------
    # shopping list
    # ------------------------------------------------------------------
    async def get_list(
        self, limit: int = 255, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Fetch the active shopping list of the account."""
        params = {
            "limit": limit,
            "offset": offset,
            "sort": "createdAt desc",
            "placeId": self.place_id,
            "lang": self.lang,
            "prs": "true",
        }
        async with self._client() as client:
            resp = await client.get(f"{BASE_URL}/latest-shopping-list", params=params)
            _check_response(resp)
            return parse_list_response(resp.json())

    async def add_items(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add items to the shopping list. Returns the full updated list.

        Each item: {"product_id": str|None, "description": str, "quantity": int}
        Free-text items (no product_id) are supported too.
        """
        now = _utcnow_iso()
        payload_items: list[dict[str, Any]] = []
        for item in items:
            entry: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "createdAt": now,
                "updatedAt": now,
                "completedAt": None,
                "description": item["description"],
            }
            if item.get("product_id"):
                entry["productData"] = {
                    "productId": str(item["product_id"]),
                    "quantity": max(1, int(item.get("quantity", 1))),
                    "unitCode": "P",
                }
            payload_items.append(entry)

        async with self._client() as client:
            resp = await client.post(
                f"{BASE_URL}/add-items-to-list", json={"items": payload_items}
            )
            _check_response(resp)
            return parse_list_response(resp.json())

    async def remove_item(self, item_id: str) -> bool:
        """Remove a shopping-list item by its UUID."""
        async with self._client() as client:
            resp = await client.delete(f"{BASE_URL}/remove-item-from-list/{item_id}")
            _check_response(resp)
            return resp.status_code in (200, 204)

    # ------------------------------------------------------------------
    # products
    # ------------------------------------------------------------------
    async def search_products(
        self, query: str, size: int = 24
    ) -> dict[str, Any]:
        """Search the assortment. Works without a session cookie."""
        params = {
            "searchTerm": query,
            "placeId": self.place_id,
            "size": size,
            "sort": "relevancy desc",
            "isAvailable": "true",
            "skip": 0,
        }
        async with self._client() as client:
            resp = await client.get(
                SEARCH_URL.format(lang=self.lang), params=params
            )
            _check_response(resp)
            data = resp.json()
            return {
                "total": data.get("productsFound", 0),
                "products": [
                    normalize_product(p) for p in data.get("products", [])
                ],
            }

    async def most_bought(self, size: int = 24) -> list[dict[str, Any]]:
        """Products the account buys most (requires a valid session)."""
        params = {"lang": self.lang, "placeId": self.place_id, "prs": "true"}
        async with self._client() as client:
            resp = await client.get(f"{BASE_URL}/most-bought-products", params=params)
            _check_response(resp)
            data = resp.json()
            products = data if isinstance(data, list) else data.get("products", [])
            return [normalize_product(p) for p in products[:size]]
