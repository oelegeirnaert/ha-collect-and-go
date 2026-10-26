"""Probe Collect&Go auth variants against the live cart endpoints.

Reads cookies from a local .env file (git-ignored):

    CG_COOKIES=<paste anything: cookie header, single pair, ...>

For each candidate combination of headers/cookies it calls both
``cart/@self`` endpoints (API gateway and direct WCS resource) and prints a
status table. Run from the repo root:

    .venv/bin/python tools/probe_auth.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "collect_and_go" / "app"))

import httpx  # noqa: E402

from collectandgo import (  # noqa: E402
    API_KEY,
    CART_URL,
    CATALOG_ID,
    LANG_IDS,
    STORE_ID,
    USER_AGENT,
    WCS_RESOURCES_URL,
)
from session_store import extract_session_cookies  # noqa: E402

GATEWAY_CART = f"{CART_URL}/store/{STORE_ID}/cart/@self"
DIRECT_CART = f"{WCS_RESOURCES_URL}/cart/@self"
PARAMS = {"langId": LANG_IDS["nl"], "catalogId": CATALOG_ID}


def load_cookies() -> dict[str, str]:
    env = Path(__file__).parent.parent / ".env"
    if not env.exists():
        sys.exit("No .env file found — create one with CG_COOKIES=<paste>")
    raw = ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("CG_COOKIES="):
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    cookies = extract_session_cookies(raw)
    if not cookies:
        sys.exit("CG_COOKIES did not contain a WC_AUTHENTICATION cookie")
    return cookies


def split_auth(cookies: dict[str, str]) -> tuple[str, str, str, str]:
    """Return (auth_name, auth_value, useractivity_value, user_id)."""
    auth_name = next(k for k in cookies if k.startswith("WC_AUTHENTICATION_"))
    auth_value = cookies[auth_name]
    user_id = auth_name.rsplit("_", 1)[-1]
    activity = cookies.get(f"WC_USERACTIVITY_{user_id}", "")
    return auth_name, auth_value, activity, user_id


def token_part(value: str) -> str:
    """``<userId>%2C<token>`` → ``<token>`` (also handles a raw comma)."""
    if "%2C" in value:
        return value.split("%2C", 1)[1]
    if "%2c" in value:
        return value.split("%2c", 1)[1]
    if "," in value:
        return value.split(",", 1)[1]
    return value


def main() -> None:
    cookies = load_cookies()
    auth_name, auth_value, activity_value, user_id = split_auth(cookies)
    wctoken = token_part(auth_value)
    wctrusted = token_part(activity_value) if activity_value else ""
    print(f"Session: {auth_name}=…{auth_value[-6:]}  activity={'yes' if activity_value else 'NO'}")

    base_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.collectandgo.be",
        "Referer": "https://www.collectandgo.be/",
    }
    api_headers = {**base_headers, "x-cg-apikey": API_KEY}

    context_cookies = {
        "WC_SESSION_ESTABLISHED": "true",
        "WC_ACTIVEPOINTER": f"{LANG_IDS['nl']}%2C{STORE_ID}",
    }
    auth_only = {k: v for k, v in cookies.items() if k.startswith(("WC_AUTHENTICATION_", "WC_USERACTIVITY_"))}

    candidates = [
        # (label, url, extra_headers, cookies)
        ("gateway: all extracted cookies", GATEWAY_CART, {}, cookies),
        ("gateway: WC_AUTH(+ACTIVITY) only", GATEWAY_CART, {}, auth_only),
        ("gateway: all + wcauthtoken header", GATEWAY_CART, {"wcauthtoken": wctoken}, cookies),
        ("gateway: wcauthtoken header, no cookies", GATEWAY_CART, {"wcauthtoken": wctoken}, {}),
        ("gateway: cookies + WCToken headers", GATEWAY_CART, {"WCToken": wctoken, "WCTrustedToken": wctrusted}, cookies),
        ("direct: all extracted cookies", DIRECT_CART, {}, {**context_cookies, **cookies}),
        ("direct: WC_AUTH(+ACTIVITY) + context", DIRECT_CART, {}, {**context_cookies, **auth_only}),
        ("direct: WCToken headers + context", DIRECT_CART, {"WCToken": wctoken, "WCTrustedToken": wctrusted}, context_cookies),
        ("direct: cookies + WCToken headers", DIRECT_CART, {"WCToken": wctoken, "WCTrustedToken": wctrusted}, {**context_cookies, **cookies}),
    ]

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for label, url, extra, jar in candidates:
            is_gateway = url == GATEWAY_CART
            headers = {**(api_headers if is_gateway else base_headers), **extra}
            try:
                resp = client.get(url, headers=headers, cookies=jar, params=PARAMS)
                body = resp.text.replace("\n", " ")[:110]
                print(f"{resp.status_code:>3}  {label:<42} {body}")
            except httpx.HTTPError as exc:
                print(f" ERR  {label:<42} {exc}")


if __name__ == "__main__":
    main()
