"""Async client for the unofficial Collect&Go (Colruyt) WCS API.

Collect&Go has no public API. The endpoints below are the ones the official
collectandgo.be web app uses itself — HCL Commerce (see
docs/api-collect-and-go-notes.md and docs/api-notes.md). They can break or
get rate-limited at any time.

Authentication
--------------
Collect&Go tracks the session with plain cookies on www.collectandgo.be —
visible in DevTools → Application → Cookies:

* ``WC_AUTHENTICATION_<userId>`` — the WCS auth token
  (value ``<userId>%2C<token>`` — this exact value is *also* sent as the
  ``wcauthtoken`` request header; that is what the gateway checks);
* ``WC_USERACTIVITY_<userId>`` — the activity token (the classic
  ``WCTrustedToken``);
* ``WC_ACTIVEPOINTER`` — store context (``<langId>%2C90004``);
* ``WC_SESSION_ESTABLISHED`` — session flag.

So a working request (verified against the live site, see
docs/curl.example) is: static ``x-cg-apikey`` header +
``wcauthtoken: <WC_AUTHENTICATION value>`` header + those WC_* cookies.
The add-on's login panel accepts a whole pasted cookie header (or just the
WC_AUTHENTICATION pair/value) and extracts what it needs. The ``reese84``
bot-protection cookie is time-sensitive and cannot be reused — the add-on
caches gently instead.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote

import httpx

# Static application API key (the web app's apiGatewayKey).
API_KEY = "502b657c-624c-11eb-8024-f4d06b721e80"

BASE_URL = "https://apip.collectandgo.be/gateway"
STORE_ID = "90004"
CATALOG_ID = "10429"
SHOP_TYPE = "CLPBE"
LANG_IDS = {"nl": "-1001", "fr": "-1002"}
LIST_URL = f"{BASE_URL}/ecomfoodb2c.eshop.wcslistsvc/v1"
CART_URL = f"{BASE_URL}/ecomfoodb2c.eshop.wcscartsvcv2/v2"
SEARCH_URL = f"{BASE_URL}/ecomfoodb2c.eshop.wcsproductviewsearchsvc/v1"
ORDER_URL = f"{BASE_URL}/ecomfoodb2c.eshop.wcsordersvcv2/v2"

# Direct HCL Commerce resource endpoints on the web app itself (same cart,
# no gateway prefix). Used as fallback path; authenticated with the same
# WC_* cookies.
WCS_RESOURCES_URL = f"https://www.collectandgo.be/wcs/resources/store/{STORE_ID}"

# Cookie names the Collect&Go session is built from (see module docstring).
COOKIE_ACTIVEPOINTER = "WC_ACTIVEPOINTER"
COOKIE_SESSION_ESTABLISHED = "WC_SESSION_ESTABLISHED"
COOKIE_PREFIX_AUTH = "WC_AUTHENTICATION_"
COOKIE_PREFIX_USERACTIVITY = "WC_USERACTIVITY_"

# Product images in WCS responses are relative asset paths
# ("JPG/200x200/nl_be/…/asset-….jpg") served from this CDN.
IMAGE_BASE_URL = "https://static.colruytgroup.com/images"

# Link to the cart/checkout page in the official web app (language dependent).
CART_PAGE_URLS = {
    "nl": "https://www.collectandgo.be/nl/winkelwagen",
    "fr": "https://www.collectandgo.be/fr/chariot",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 20.0


class CollectAndGoError(Exception):
    """Base error for API failures."""


class AuthError(CollectAndGoError):
    """The wcauthtoken is missing, invalid or expired."""


class RateLimited(CollectAndGoError):
    """The API is rate-limiting / bot-challenging us (HTTP 429 or 456)."""


class UpstreamError(CollectAndGoError):
    """Unexpected response from the Collect&Go servers."""


def _check_response(resp: httpx.Response) -> None:
    """Translate HTTP status codes into meaningful exceptions."""
    if resp.status_code in (401, 403):
        raise AuthError(f"token rejected ({resp.status_code})")
    # Imperva answers bursts with its AntiBot page (405) or 429/456.
    if resp.status_code in (405, 429, 456):
        raise RateLimited(f"rate limited ({resp.status_code})")
    if resp.status_code >= 400:
        raise UpstreamError(f"unexpected status {resp.status_code}")


def _json(resp: httpx.Response) -> Any:
    """Parse a response body as JSON, tolerating empty/non-JSON bodies.

    The WAF in front of the gateway can answer with an HTML page, and some
    WCS actions answer with a plain-text body — neither parses.
    """
    try:
        return resp.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        preview = resp.text[:200] if resp.text else "(empty body)"
        raise UpstreamError(
            f"non-JSON response (HTTP {resp.status_code}): {preview}"
        ) from None


# ---------------------------------------------------------------------------
# response normalization — WCS shapes, tolerant of missing/extra fields
# ---------------------------------------------------------------------------

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


def _wcs_image(path: Any) -> str:
    """Resolve a WCS asset path to a full URL on the Colruyt Group CDN."""
    if not isinstance(path, str) or not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    # "JPG/200x200/nl_be/…/asset-….jpg" → "images/200x200/nl_be/…"
    parts = path.split("/")
    if parts and parts[0].upper() in ("JPG", "PNG", "WEBP"):
        parts = parts[1:]
    return f"{IMAGE_BASE_URL}/{'/'.join(parts)}"


def normalize_product(p: dict[str, Any]) -> dict[str, Any]:
    """Reduce a WCS ``catalogEntryView`` product to the fields the UI needs.

    The cart expects the pair ``product_id`` (``partNumber`` minus its
    ``-P``/``-K`` suffix, i.e. the technical article number) + ``entry_id``
    (the numeric ``uniqueID``, used as ``catEntryId``).
    """
    part = _first_str(p.get("partNumber"))
    if "-" in part and part.rsplit("-", 1)[-1].isalpha():
        part = part.rsplit("-", 1)[0]  # "14507-P" → "14507"
    return {
        "product_id": part,
        "entry_id": _first_str(str(p.get("uniqueID") or "")),
        "part_number": _first_str(p.get("partNumber")),
        "name": _first_str(p.get("name"), p.get("shortDescription")),
        "short_name": _first_str(p.get("shortDescription"), p.get("name")),
        "brand": _first_str(p.get("manufacturer"), p.get("brand")),
        "content": _first_str(p.get("content"), p.get("packaging")),
        "image": _wcs_image(_first_str(p.get("thumbnail"), p.get("fullImage"))),
        "price": _wcs_price(p.get("price")),
        "available": bool(p.get("buyable", p.get("available", True))),
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


class CollectAndGoClient:
    """Minimal async client for the Collect&Go backend.

    ``session`` is a mapping of cookie name → value captured from a logged-in
    collectandgo.be session. Minimum useful content:
    ``WC_AUTHENTICATION_<userId>`` and ``WC_USERACTIVITY_<userId>``;
    ``WC_ACTIVEPOINTER`` / ``WC_SESSION_ESTABLISHED`` are added automatically
    for the configured language when missing.
    """

    def __init__(
        self,
        session: Optional[dict[str, str]] = None,
        lang: str = "nl",
        api_key: str = API_KEY,
    ) -> None:
        self.lang = lang if lang in ("nl", "fr") else "nl"
        self.api_key = api_key
        cookies = {str(k): str(v) for k, v in (session or {}).items() if v}
        # Mirror the session context cookies the site sets after login.
        cookies.setdefault(COOKIE_SESSION_ESTABLISHED, "true")
        cookies.setdefault(
            COOKIE_ACTIVEPOINTER, f"{self._lang_id}%2C{STORE_ID}"
        )
        self._cookies = cookies
        # The cart lives under the *store* catalog (e.g. CLPBE_10646), not
        # the generic 10429 — read it from the COL_SHOP cookie when present
        # (verified in docs/curl/add_to_cart.example).
        self.catalog_id = CATALOG_ID
        col_shop = cookies.get("COL_SHOP", "")
        if "_" in col_shop:
            tail = col_shop.rsplit("_", 1)[-1]
            if tail.isdigit():
                self.catalog_id = tail

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    @property
    def has_session(self) -> bool:
        """Whether we hold at least the WCS authentication cookie."""
        return any(k.startswith(COOKIE_PREFIX_AUTH) for k in self._cookies)

    @property
    def _wcauthtoken(self) -> Optional[str]:
        """The ``wcauthtoken`` request header = the WC_AUTHENTICATION value
        verbatim (``<userId>%2C<token>``) — see docs/curl.example."""
        for name, value in self._cookies.items():
            if name.startswith(COOKIE_PREFIX_AUTH):
                return value
        return None

    @property
    def _lang_id(self) -> str:
        return LANG_IDS.get(self.lang, LANG_IDS["nl"])

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "x-cg-apikey": self.api_key,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": "https://www.collectandgo.be",
            "Referer": "https://www.collectandgo.be/",
        }
        wcauthtoken = self._wcauthtoken
        if wcauthtoken:
            headers["wcauthtoken"] = wcauthtoken
        return headers

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
        """Return True when the stored cookies are accepted by the backend.

        Cart read first; when Imperva is throttling that endpoint (405) we
        fall back to the order-history endpoint, which is friendlier to
        scripted reads. Any other non-2xx counts as invalid — the gateway
        answers a bare 500 (not 401) for sessions it doesn't like.
        """
        if not self.has_session:
            return False
        try:
            await self.get_cart()
            return True
        except RateLimited:
            pass
        except CollectAndGoError:
            return False
        try:
            await self.get_order_history()
            return True
        except CollectAndGoError:
            return False

    # ------------------------------------------------------------------
    # products
    # ------------------------------------------------------------------
    async def search_products(
        self, query: str, size: int = 24
    ) -> dict[str, Any]:
        """Search the Collect&Go assortment (``productview/bySearchTerm``).

        The response carries products in a ``catalogEntryView`` array; their
        ``partNumber`` is what the cart endpoints accept.
        """
        term = quote(query, safe="")
        url = f"{SEARCH_URL}/store/{STORE_ID}/productview/bySearchTerm/{term}"
        params = {
            "langId": self._lang_id,
            "catalogId": CATALOG_ID,
            "pageSize": size,
        }
        async with self._client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            data = _json(resp)
            if not isinstance(data, dict):
                raise UpstreamError("unexpected search response shape")
            raw = data.get("catalogEntryView") or []
            if not isinstance(raw, list):
                raw = []
            return {
                "total": data.get("recordSetTotal") or len(raw),
                "products": [
                    normalize_product(p) for p in raw if isinstance(p, dict)
                ],
            }

    # ------------------------------------------------------------------
    # cart ("winkelmand")
    # ------------------------------------------------------------------
    async def get_cart(self) -> dict[str, Any]:
        """Fetch the live Collect&Go cart (``cart/@self``)."""
        url = f"{CART_URL}/store/{STORE_ID}/cart/@self"
        params = {"langId": self._lang_id, "catalogId": self.catalog_id}
        async with self._client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            return parse_cart_response(_json(resp))

    async def add_to_cart(
        self, product_id: str, quantity: int = 1, entry_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Add a product to the cart.

        Verified payload (docs/curl/add_to_cart.example):
        ``POST /gateway/…/v2/store/{storeId}/cart?langId=…&catalogId=<store catalog>``
        with ``{"orderItem": [{"productId": <uniqueID>, "quantity": "1",
        "xitem_field2": "P|1|st"}]}`` — ``productId`` is the numeric
        catalog-entry id (WCS ``uniqueID`` = our ``entry_id``); the
        ``xitem_field2`` marker encodes unit type / quantity / unit.
        """
        quantity = max(1, int(quantity))
        # entry_id (numeric uniqueID) is what the cart wants as productId;
        # fall back to the plain product id when it's all we have.
        pid = str(entry_id or product_id)
        item: dict[str, Any] = {
            "productId": pid,
            "quantity": str(quantity),
            "xitem_field2": f"P|{quantity}|st",
        }
        params = {"langId": self._lang_id, "catalogId": self.catalog_id}
        async with self._client() as client:
            resp = await client.post(
                f"{CART_URL}/store/{STORE_ID}/cart",
                json={"orderItem": [item]},
                params=params,
            )
            if resp.status_code >= 500:
                # Gateway hiccup → try the direct resource endpoint.
                resp = await client.post(
                    f"{WCS_RESOURCES_URL}/cart",
                    json={"orderItem": [item]},
                    params=params,
                )
            _check_response(resp)
            return _json(resp)

    async def update_cart_item(
        self,
        order_item_id: str,
        quantity: int,
        part_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """Change the quantity of an existing cart line (by ``orderItemId``).
        Keeps the line's numeric ``partNumber`` and unit marker — WCS rejects
        updates without them."""
        quantity = max(1, int(quantity))
        item: dict[str, Any] = {
            "orderItemId": str(order_item_id),
            "quantity": str(quantity),
            "xitem_field2": f"P|{quantity}|st",
        }
        if part_number:
            item["partNumber"] = str(part_number)
        url = f"{CART_URL}/store/{STORE_ID}/cart/@self/update_order_item"
        body = {
            "orderItem": [item],
            "catalogId": self.catalog_id,
            "langId": self._lang_id,
        }
        params = {"langId": self._lang_id, "catalogId": self.catalog_id}
        async with self._client() as client:
            resp = await client.put(url, json=body, params=params)
            _check_response(resp)
            return _json(resp)

    async def remove_cart_item(self, order_item_id: str) -> bool:
        """Remove a cart line by ``orderItemId``.

        Primary: gateway ``delete_order_item``. Fallback: direct
        ``DELETE /wcs/resources/store/{id}/cart/item/{orderItemId}``.
        """
        params = {
            "orderItemId": str(order_item_id),
            "langId": self._lang_id,
            "catalogId": self.catalog_id,
        }
        async with self._client() as client:
            resp = await client.delete(
                f"{CART_URL}/store/{STORE_ID}/cart/@self/delete_order_item",
                params=params,
            )
            if resp.status_code >= 500:
                resp = await client.delete(
                    f"{WCS_RESOURCES_URL}/cart/item/{order_item_id}",
                    params={"langId": self._lang_id, "catalogId": self.catalog_id},
                )
            _check_response(resp)
            return resp.status_code in (200, 201, 204)

    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    async def get_order_history(self) -> list[dict[str, Any]]:
        """Past Collect&Go orders of the account (``order/@history``)."""
        url = f"{ORDER_URL}/store/{STORE_ID}/order/@history"
        params = {"langId": self._lang_id, "catalogId": self.catalog_id}
        async with self._client() as client:
            resp = await client.get(url, params=params)
            _check_response(resp)
            return parse_order_history(_json(resp))

    # ------------------------------------------------------------------
    # named shopping lists ("mijnlijstjes")
    # ------------------------------------------------------------------
    async def get_lists(self) -> list[dict[str, Any]]:
        """All named customer lists of the account."""
        url = f"{LIST_URL}/store/{STORE_ID}/list/@self/type/CUSTOMER"
        params = {
            "catalogId": self.catalog_id,
            "shopType": SHOP_TYPE,
            "langId": self._lang_id,
        }
        async with self._client() as client:
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
        """Add products to a named list by partNumber (best effort)."""
        url = f"{LIST_URL}/store/{STORE_ID}/list/{list_id}/item"
        async with self._client() as client:
            resp = await client.post(
                url, json={"productIds": [str(p) for p in product_ids]}
            )
            _check_response(resp)
            return resp.status_code in (200, 201, 204)
