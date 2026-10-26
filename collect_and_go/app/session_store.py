"""Persistence of the Xtra session cookie in the add-on data folder.

Only the ``clpbff_session`` value (an UUID) is stored — never a password.
Optionally, the Collect&Go ``wcauthtoken`` (the WCS session token used by
the cart/order gateways) is kept next to it. The file lives in ``/data`` so
it survives add-on restarts and updates.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSION_COOKIE = "clpbff_session"
WCS_TOKEN = "wcauthtoken"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def load(self) -> Optional[str]:
        """Return the stored session id, or None."""
        value = self._read().get("session")
        return str(value) if value else None

    def load_wcauthtoken(self) -> Optional[str]:
        """Return the stored Collect&Go WCS auth token, or None."""
        value = self._read().get(WCS_TOKEN)
        return str(value) if value else None

    def save(self, session: str, wcauthtoken: Optional[str] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session": session,
            WCS_TOKEN: wcauthtoken or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        # Session == credentials: keep the file private.
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def extract_session_cookie(raw: str) -> Optional[str]:
    """Accept a bare UUID, a ``clpbff_session=...`` pair, or a whole cookie
    header, and return just the session id."""
    raw = (raw or "").strip()
    if not raw:
        return None
    # Full cookie header or single pair?
    for part in raw.split(";"):
        part = part.strip()
        if part.lower().startswith(SESSION_COOKIE + "="):
            return part.split("=", 1)[1].strip() or None
    # Bare value?
    if _UUID_RE.match(raw):
        return raw
    return None


def extract_wcauthtoken(raw: str) -> Optional[str]:
    """Accept a bare token, a ``wcauthtoken=...`` pair, or a whole cookie
    header, and return just the token value."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for part in raw.split(";"):
        part = part.strip()
        if part.lower().startswith(WCS_TOKEN + "="):
            return part.split("=", 1)[1].strip() or None
    # Bare value: one header-safe blob; "=" only allowed as trailing
    # padding (tokens are often base64), not as a key=value pair.
    if not re.search(r"[\s;]", raw) and "=" not in raw.rstrip("="):
        return raw
    return None
