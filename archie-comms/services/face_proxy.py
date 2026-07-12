"""Thin cockpit->platform avatar proxy (COO Cockpit Slice 4).

Fetches A.R.C.H.I.E.'s portrait from the platform @_require_internal_key endpoint
over the internal Docker network (PLATFORM_URL=http://archie_platform:3000 — never a
public hostname). Fail-SOFT: any transport/non-200/{ok:false} returns None so the
cockpit falls back to a CSS monogram — the avatar is polish, never a hard error.
"""

import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def portrait():
    """-> (raw_bytes, mime) on success, else None (fail-soft)."""
    try:
        r = requests.get(
            f"{_base()}/api/internal/archie/portrait",
            headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"},
            timeout=10,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200 and data.get("ok") and data.get("image_b64"):
            return base64.b64decode(data["image_b64"]), data.get("mime", "image/png")
    except Exception as exc:  # fail-soft -> monogram
        logger.info("avatar proxy failed: %s", exc)
    return None
