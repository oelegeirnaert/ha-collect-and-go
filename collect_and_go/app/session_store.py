"""Persistence of the Collect&Go session cookies in the add-on data folder.

Only cookie values are stored — never a password. The file lives in
``/data`` so it survives add-on restarts and updates.

The session consists of the WCS cookies from a logged-in collectandgo.be
browser session — most importantly ``WC_AUTHENTICATION_<userId>`` and
``WC_USERACTIVITY_<userId>`` (see docs/api-collect-and-go-notes-v2.md).
The setup panel accepts a whole pasted cookie header, a full cookie list
copied out of DevTools, or just the WC_AUTHENTICATION value, and extracts
what it needs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Cookie names that make up the session (exact names or prefixes).
AUTH_PREFIX = "WC_AUTHENTICATION_"
KEEP_EXACT = {
    "WC_ACTIVEPOINTER",
    "WC_SESSION_ESTABLISHED",
    "priceMode",
    "COL_SHOP",  # carries the store catalogId (CLPBE_10646)
}
KEEP_PREFIXES = (AUTH_PREFIX, "WC_USERACTIVITY_")


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        """Return the stored cookie mapping (empty dict when absent)."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") if isinstance(data, dict) else None
            if isinstance(cookies, dict):
                return {str(k): str(v) for k, v in cookies.items() if v}
        except (OSError, ValueError):
            pass
        return {}

    def save(self, cookies: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookies": cookies,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        # Cookies == credentials: keep the file private.
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def extract_session_cookies(raw: str) -> dict[str, str]:
    """Extract the Collect&Go session cookies from whatever the user pastes:

    * a whole ``Cookie:`` header or ``name=value; name=value`` list
      (e.g. copied from DevTools → Network);
    * a DevTools cookie-table paste (tab/comma separated, possibly quoted);
    * just the ``WC_AUTHENTICATION_…`` cookie name + value;
    * or just the bare ``WC_AUTHENTICATION`` *value* (``<userId>,<token>``).

    Returns a ``{name: value}`` mapping, empty when nothing useful is found.
    """
    raw = (raw or "").strip()
    if not raw:
        return {}

    found: dict[str, str] = {}

    # Whole header / cookie-list paste: split on ';' and newlines.
    for part in re.split(r"[;\n\r]+", raw):
        part = part.strip().strip('"').strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip().strip('"')
        value = value.strip().strip('"')
        if name in KEEP_EXACT or name.startswith(KEEP_PREFIXES):
            found[name] = value

    # Bare WC_AUTHENTICATION value: "<userId>,<token>" (often URL-encoded).
    # Check this before the table-paste branch — a comma in the raw value
    # would otherwise be mistaken for a column separator.
    if not any(k.startswith(AUTH_PREFIX) for k in found):
        match = re.fullmatch(r"(\d+)(?:%2[Cc]|,)(.+)", raw.strip().strip('"'))
        if match:
            user_id, token = match.group(1), match.group(2)
            found[f"{AUTH_PREFIX}{user_id}"] = f"{user_id}%2C{token}"

    # DevTools Application→Cookies table paste: lines like
    # "WC_AUTHENTICATION_1234567\t1234567%2Cxxx\t.collectandgo.be\t/..."
    if not any(k.startswith(AUTH_PREFIX) for k in found):
        for line in raw.splitlines():
            cols = re.split(r"[\t]", line.strip())
            if len(cols) < 2:
                cols = line.split()
            if len(cols) < 2:
                continue
            name, value = cols[0].strip().strip('"'), cols[1].strip().strip('"')
            if name in KEEP_EXACT or name.startswith(KEEP_PREFIXES):
                found[name] = value

    # Single pair like "WC_AUTHENTICATION_1234567=1234567%2Cxxx" (no ';').
    if not any(k.startswith(AUTH_PREFIX) for k in found):
        match = re.fullmatch(
            r"(%s\d+)\s*=\s*(.+)" % re.escape(AUTH_PREFIX),
            raw.strip().strip('"'),
            re.DOTALL,
        )
        if match:
            found[match.group(1)] = match.group(2).strip().strip('"')

    return found
