"""Persistence of the Xtra session cookie in the add-on data folder.

Only the ``clpbff_session`` value (an UUID) is stored — never a password.
The file lives in ``/data`` so it survives add-on restarts and updates.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSION_COOKIE = "clpbff_session"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Optional[str]:
        """Return the stored session id, or None."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            value = data.get("session")
            return str(value) if value else None
        except (OSError, ValueError):
            return None

    def save(self, session: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session": session,
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
