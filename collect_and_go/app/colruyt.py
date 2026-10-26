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

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

# Public API key used by www.colruyt.be / www.collectandgo.be web apps.
API_KEY = "a8ylmv13-b285-4788-9e14-0f79b7ed2411"

BASE_URL = "https://apix.colruyt.be/gateway/emec.colruyt.bffsvc/cg"
SEARCH_URL = (
    "https://apip.colruyt.be/gateway/emec.colruyt.protected.bffsvc"
    "/cg/{lang}/api/product-search-prs"
)

# The Collect&Go shop itself runs on the HCL/WCS commerce backend with its
# own gateways (extracted from the live site's WCParamJS config).
WCS_STORE_ID = "90004"
WCS_CATALOG_ID = "10429"
WCS_SHOP_TYPE = "CLPBE"
WCS_LANG_IDS = {"nl": "-1001", "fr": "-1002"}
WCS_API_KEY = "502b657c-624c-11eb-8024-f4d06b721e80"  # apiGatewayKey, public
WCS_BASE = "https://apip.collectandgo.be/gateway"
WCS_LIST_URL = f"{WCS_BASE}/ecomfoodb2c.eshop.wcslistsvc/v1"
WCS_CART_URL = f"{WCS_BASE}/ecomfoodb2c.eshop.wcscartsvcv2/v2"
WCS_SEARCH_URL = f"{WCS_BASE}/ecomfoodb2c.eshop.wcsproductviewsearchsvc/v1"
WCS_ORDER_URL = f"{WCS_BASE}/ecomfoodb2c.eshop.wcsordersvcv2/v2"

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


def _json(resp: httpx.Response) -> Any:
    """Parse a response body as JSON, tolerating empty/non-JSON bodies.

    The Colruyt BFF sometimes answers 201 with a plain-text body, and the
    WAF in front of it can answer with an HTML page — neither parses.
    """
    try:
        return resp.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        preview = resp.text[:200] if resp.text else "(empty body)"
        raise UpstreamError(
            f"non-JSON response (HTTP {resp.status_code}): {preview}"
        ) from None


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


def parse_list_response(data: Any) -> list[dict[str, Any]]:
    """The list endpoint has used several shapes over time; handle them all."""
    if not isinstance(data, dict):
        return []
    raw_items = (
        (data.get("getListItems") or {}).get("data")
        or (data.get("data") or {}).get("items")
        or data.get("items")
        or []
    )
    if not isinstance(raw_items, list):
        return []
    return [normalize_list_item(i) for i in raw_items if isinstance(i, dict)]


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if value is None:
            continue
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            continue
    return None


def _wcs_price(prices: Any) -> Optional[float]:
    """WCS returns price as a list like [{'usage': 'Display', 'value': '2.59'}]."""
    if not isinstance(prices, list):
        return _first_number(prices)
    preferred = None
    for entry in prices:
        if not isinstance(entry, dict):
            continue
        value = _first_number(entry.get("value"), entry.get("price"))
        if value is None:
            continue
        if entry.get("usage") == "Display":
            return value
        if preferred is None:
            preferred = value
    return preferred


def normalize_wcs_product(p: dict[str, Any]) -> dict[str, Any]:
    """Reduce a WCS ``catalogEntryView`` product to the fields the UI needs.

    ``partNumber`` is the identifier the Collect&Go cart endpoints expect.
    """
    return {
        "product_id": _first_str(p.get("partNumber"), str(p.get("uniqueID") or "")),
        "name": _first_str(p.get("name"), p.get("shortDescription")),
        "short_name": _first_str(p.get("shortDescription"), p.get("name")),
        "brand": _first_str(p.get("manufacturer"), p.get("brand")),
        "content": _first_str(p.get("content"), p.get("packaging")),
        "image": _first_str(p.get("thumbnail"), p.get("fullImage")),
        "category": "",
        "price": _wcs_price(p.get("price")),
        "unit": "",
        "unit_price": None,
        "available": bool(p.get("buyable", p.get("available", True))),
        "is_weight_article": False,
    }


def normalize_cart_item(i: dict[str, Any]) -> dict[str, Any]:
    """Reduce a WCS cart ``orderItem`` to the fields the UI needs."""
    entry = i.get("catalogEntry") if isinstance(i.get("catalogEntry"), dict) else {}
    quantity = _first_number(i.get("quantity"))
    return {
        "id": _first_str(i.get("orderItemId"), i.get("itemId")),
        "product_id": _first_str(i.get("partNumber"), str(i.get("productId") or "")),
        "description": _first_str(
            i.get("productName"),
            i.get("description"),
            entry.get("name"),
            i.get("partNumber"),
        ),
        "quantity": int(quantity) if quantity is not None else 1,
        "price": _first_number(
            i.get("orderItemPrice"), i.get("price"), i.get("unitPrice")
        ),
    }


def parse_cart_response(data: Any) -> dict[str, Any]:
    """Normalize the WCS ``cart/@self`` response."""
    if not isinstance(data, dict):
        return {"items": [], "total": None, "order_id": None}
    raw_items = data.get("orderItem") or data.get("orderItems") or []
    if not isinstance(raw_items, list):
        raw_items = []
    return {
        "items": [normalize_cart_item(i) for i in raw_items if isinstance(i, dict)],
        "total": _first_number(
            data.get("grandTotal"), data.get("totalProductPrice")
        ),
        "order_id": _first_str(data.get("orderId"), str(data.get("orderID") or "")),
    }


def parse_order_history(data: Any) -> list[dict[str, Any]]:
    """Normalize the WCS ``order/@history`` response."""
    if not isinstance(data, dict):
        return []
    raw = data.get("Order") or data.get("orders") or data.get("order") or []
    if not isinstance(raw, list):
        return []
    orders = []
    for o in raw:
        if not isinstance(o, dict):
            continue
        orders.append(
            {
                "order_id": _first_str(o.get("orderId"), str(o.get("orderID") or "")),
                "status": _first_str(o.get("status"), o.get("orderStatus")),
                "placed_at": _first_str(o.get("placedDate"), o.get("lastUpdate")),
                "total": _first_number(o.get("grandTotal"), o.get("totalPrice")),
            }
        )
    return orders


class ColruytClient:
    """Minimal async client for the Xtra shopping-list + product search."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        place_id: str = "2643",
        lang: str = "nl",
        api_key: str = API_KEY,
        wcauthtoken: Optional[str] = None,
    ) -> None:
        self.session_id = session_id or None
        self.place_id = place_id or "2643"
        self.lang = lang if lang in ("nl", "fr") else "nl"
        self.api_key = api_key
        self.wcauthtoken = wcauthtoken or None

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
            return parse_list_response(_json(resp))

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
            return parse_list_response(_json(resp))

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
            data = _json(resp)
            if not isinstance(data, dict):
                raise UpstreamError("unexpected search response shape")
            return {
                "total": data.get("productsFound", 0),
                "products": [
                    normalize_product(p)
                    for p in data.get("products", [])
                    if isinstance(p, dict)
                ],
            }

    async def most_bought(self, size: int = 24) -> list[dict[str, Any]]:
        """Products the account buys most (requires a valid session)."""
        params = {"lang": self.lang, "placeId": self.place_id, "prs": "true"}
        async with self._client() as client:
            resp = await client.get(f"{BASE_URL}/most-bought-products", params=params)
            _check_response(resp)
            data = _json(resp)
            products = data if isinstance(data, list) else data.get("products", [])
            return [
                normalize_product(p) for p in products[:size] if isinstance(p, dict)
            ]

    # ------------------------------------------------------------------
    # named shopping lists (Collect&Go WCS list service)
    # ------------------------------------------------------------------
    @property
    def _wcs_headers(self) -> dict[str, str]:
        headers = {
            "X-CG-APIKey": WCS_API_KEY,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": "https://www.collectandgo.be",
            "Referer": "https://www.collectandgo.be/",
        }
        # Dynamic WCS session token (from the Collect&Go site, see
        # docs/api-collect-and-go-notes.md). Cart/order endpoints reject
        # calls without it.
        if self.wcauthtoken:
            headers["wcauthtoken"] = self.wcauthtoken
        return headers

    @property
    def _wcs_lang_id(self) -> str:
        return WCS_LANG_IDS.get(self.lang, WCS_LANG_IDS["nl"])

    def _wcs_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers=self._wcs_headers,
            cookies=self._cookies,
            follow_redirects=True,
        )

    async def get_lists(self) -> list[dict[str, Any]]:
        """All named customer lists of the account (Collect&Go "mijnlijstjes")."""
        url = f"{WCS_LIST_URL}/store/{WCS_STORE_ID}/list/@self/type/CUSTOMER"
        params = {
            "catalogId": WCS_CATALOG_ID,
            "shopType": WCS_SHOP_TYPE,
            "langId": self._wcs_lang_id,
        }
        async with self._wcs_client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            data = _json(resp)
            raw = data.get("list") or data.get("lists") or []
            if not isinstance(raw, list):
                return []
            lists = []
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                lists.append(
                    {
                        "id": str(
                            entry.get("listId")
                            or entry.get("identifier")
                            or entry.get("id")
                            or entry.get("name")
                            or ""
                        ),
                        "name": entry.get("identifier")
                        or entry.get("name")
                        or entry.get("description")
                        or "List",
                        "description": entry.get("description") or "",
                    }
                )
            return lists

    async def add_products_to_named_list(
        self, list_id: str, product_ids: list[str]
    ) -> bool:
        """Add products to a named Collect&Go list by product id."""
        url = f"{WCS_LIST_URL}/store/{WCS_STORE_ID}/list/{list_id}/item"
        async with self._wcs_client() as client:
            resp = await client.post(url, json={"productIds": [str(p) for p in product_ids]})
            _check_response(resp)
            return resp.status_code in (200, 201, 204)

    # ------------------------------------------------------------------
    # cart (Collect&Go WCS cart service)
    # ------------------------------------------------------------------
    async def get_cart(self) -> dict[str, Any]:
        """Fetch the live Collect&Go cart (``cart/@self``).

        Needs the ``wcauthtoken`` header — without it the WCS gateway
        answers 401, which the caller maps to the 'auth' flow.
        """
        url = f"{WCS_CART_URL}/store/{WCS_STORE_ID}/cart/@self"
        params = {"langId": self._wcs_lang_id, "catalogId": WCS_CATALOG_ID}
        async with self._wcs_client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            return parse_cart_response(_json(resp))

    async def get_order_history(self) -> list[dict[str, Any]]:
        """Past Collect&Go orders of the account (``order/@history``)."""
        url = f"{WCS_ORDER_URL}/store/{WCS_STORE_ID}/order/@history"
        params = {"langId": self._wcs_lang_id, "catalogId": WCS_CATALOG_ID}
        async with self._wcs_client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            return parse_order_history(_json(resp))

    async def search_products_wcs(
        self, query: str, size: int = 24
    ) -> dict[str, Any]:
        """Search the Collect&Go shop catalog via the WCS search service.

        ``GET .../productview/bySearchTerm/{term}`` — the response carries
        products in a ``catalogEntryView`` array. Identifiers returned here
        (``partNumber``) are the ones the cart endpoints accept.
        """
        term = quote(query, safe="")
        url = (
            f"{WCS_SEARCH_URL}/store/{WCS_STORE_ID}"
            f"/productview/bySearchTerm/{term}"
        )
        params = {
            "langId": self._wcs_lang_id,
            "catalogId": WCS_CATALOG_ID,
            "pageSize": size,
        }
        async with self._wcs_client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            data = _json(resp)
            if not isinstance(data, dict):
                raise UpstreamError("unexpected WCS search response shape")
            raw = data.get("catalogEntryView") or []
            if not isinstance(raw, list):
                raw = []
            return {
                "total": data.get("recordSetTotal") or len(raw),
                "products": [
                    normalize_wcs_product(p) for p in raw if isinstance(p, dict)
                ],
            }

    async def add_to_cart(
        self, product_id: str, quantity: int = 1
    ) -> dict[str, Any]:
        """Add a product straight to the real Collect&Go cart.

        The WCS cart backend expects the session as a ``wcauthtoken``
        header (grabbed from the Collect&Go site, see
        docs/api-collect-and-go-notes.md). Whether a bare clpbff_session
        cookie is accepted can differ per account — hence best-effort:
        failures raise UpstreamError/AuthError and the UI falls back to
        adding to the shopping list instead.

        ``product_id`` is the WCS ``partNumber`` (use the ``source=wcs``
        search to resolve one).
        """
        url = f"{WCS_CART_URL}/store/{WCS_STORE_ID}/cart/@self/update_order_item"
        body = {
            "orderItem": [
                {
                    "partNumber": str(product_id),
                    "quantity": str(max(1, int(quantity))),
                }
            ],
            "catalogId": WCS_CATALOG_ID,
            "langId": self._wcs_lang_id,
        }
        params = {"langId": self._wcs_lang_id, "catalogId": WCS_CATALOG_ID}
        async with self._wcs_client() as client:
            resp = await client.put(url, json=body, params=params)
            _check_response(resp)
            return _json(resp)
