"""A.R.C.H.I.E.'s face — serve agent-2's portrait for the cockpit avatar. Fail-soft.

Reads agent 2's canonical portrait file (agent_portraits.canonical_image_path,
app-relative under /app) and returns it base64. Any failure -> {ok: False} so the
cockpit falls back to a CSS monogram — the avatar is polish, never a hard error.
"""

import base64
import logging
import os

logger = logging.getLogger(__name__)

ARCHIE_AGENT_ID = 2
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /app


def _portrait_path():
    """Absolute path to agent 2's canonical portrait, or '' if none."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT canonical_image_path FROM agent_portraits WHERE agent_id=%s", (ARCHIE_AGENT_ID,))
            row = cur.fetchone()
        rel = (row["canonical_image_path"] if row else "") or ""
        if not rel:
            return ""
        return os.path.join(_APP_DIR, rel.lstrip("/"))  # /static/... -> /app/static/...
    except Exception as exc:
        logger.warning("portrait path lookup failed: %s", exc)
        return ""


def get_portrait():
    """-> {ok, image_b64?, mime?, error?}. Reads the portrait file, base64. Fail-soft."""
    path = _portrait_path()
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "no portrait"}
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
            ext, "image/png"
        )
        return {"ok": True, "image_b64": base64.b64encode(raw).decode(), "mime": mime}
    except Exception as exc:
        logger.warning("portrait read failed: %s", exc)
        return {"ok": False, "error": str(exc)}
