"""M.A.V.E.N. chat action parsing and execution."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import requests

from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.chat")

# Action parsing + execution
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(r"\[ACTION:(request|delete)\|([^\|\]]+)(?:\|(tv|movie))?\]", re.IGNORECASE)

# Fallback: detect obvious request/delete intent directly from user message
# so actions fire even if the LLM forgets to emit the tag.
_REQUEST_RE = re.compile(
    r"(?:please\s+)?(?:can you\s+)?(?:request|add|download|get me|fetch)\s+[\"']?(.+?)[\"']?"
    r"(?:\s+(?:season\s*\d+|s\d+|for me|please|now))*\s*$",
    re.IGNORECASE,
)
_DELETE_RE = re.compile(
    r"(?:please\s+)?(?:can you\s+)?(?:delete|remove)\s+[\"']?(.+?)[\"']?"
    r"(?:\s+(?:from (?:the )?library|please|now))*\s*$",
    re.IGNORECASE,
)


_MOVIE_HINTS = re.compile(r"\b(movie|film|cinema)\b", re.IGNORECASE)
_TV_HINTS = re.compile(r"\b(show|series|season|episode|tv)\b", re.IGNORECASE)


def _sniff_media_type(text: str) -> str:
    """Return 'movie', 'tv', or 'auto' based on keywords in the message."""
    if _MOVIE_HINTS.search(text):
        return "movie"
    if _TV_HINTS.search(text):
        return "tv"
    return "auto"  # let Overseerr pick the best match


def _detect_intent(user_msg: str) -> Optional[Dict]:
    """Detect clear request/delete intent in user message as LLM tag fallback."""
    m = _REQUEST_RE.match(user_msg.strip())
    if m:
        title = m.group(1).strip().rstrip("?!.")
        if len(title) >= 2 and title.lower() not in ("it", "that", "this", "something"):
            media_type = _sniff_media_type(user_msg)
            return {"type": "request", "title": title, "media_type": media_type}
    m = _DELETE_RE.match(user_msg.strip())
    if m:
        title = m.group(1).strip().rstrip("?!.")
        if len(title) >= 2 and title.lower() not in ("it", "that", "this"):
            media_type = _sniff_media_type(user_msg)
            return {"type": "delete", "title": title, "media_type": media_type}
    return None


def _parse_action(reply: str) -> Tuple[str, Optional[Dict]]:
    """Strip the first [ACTION:...] tag from reply text and return (clean_text, action_dict).
    Media type is optional — defaults to 'tv' for request, 'movie' not assumed."""
    m = _ACTION_RE.search(reply)
    if not m:
        return reply, None
    action = {
        "type": m.group(1).lower(),
        "title": m.group(2).strip(),
        "media_type": (m.group(3) or "tv").lower(),
    }
    clean = _ACTION_RE.sub("", reply).strip()
    return clean, action


def _svc(service_type: str) -> Optional[Dict]:
    """Return {key, host, port, ssl} for a service or None."""
    rows = _rows_for_type(service_type)
    if not rows:
        return None
    _, _, _, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    return {"key": key, "host": host, "port": port, "ssl": use_ssl}


def execute_action(action_type: str, title: str, media_type: str) -> Dict:
    """Execute a request or delete action. Returns {ok, message}."""
    import time as _time

    _t0 = _time.monotonic()
    if action_type == "request":
        res = _do_request(title, media_type)
    elif action_type == "delete":
        res = _do_delete(title, media_type)
    else:
        return {"ok": False, "message": f"Unknown action: {action_type}"}
    # A.R.M.A.D.A. visibility (#4755) — record the chat/UI action as a 0-token row.
    try:
        from archie_coordination import log_dispatch

        log_dispatch(
            f"media_{action_type}",
            capability=("media_request" if action_type == "request" else "media_delete"),
            description=f"{action_type} {media_type}: {title}"[:200],
            success=bool(res.get("ok")),
            duration_ms=int((_time.monotonic() - _t0) * 1000),
            target=title,
            error=(None if res.get("ok") else str(res.get("message"))),
            metadata={"media_type": media_type},
        )
    except Exception:  # noqa: BLE001 — visibility logging must never break the action
        pass
    return res


def _do_request(title: str, media_type: str) -> Dict:
    """Search Overseerr for title and submit a request."""
    svc = _svc("overseerr")
    if not svc:
        return {"ok": False, "message": "Overseerr not configured"}
    scheme = "https" if svc["ssl"] else "http"
    base = f"{scheme}://{svc['host']}:{svc['port']}"
    hdrs = {"X-Api-Key": svc["key"], "Content-Type": "application/json"}

    # Strip season/episode qualifiers before searching — Overseerr needs the show title only
    import re as _re
    search_query = _re.sub(r'\s+(?:season|series|episode|ep|s)\s*\d+.*$', '', title, flags=_re.IGNORECASE).strip() or title

    # Search for the title
    try:
        r = requests.get(f"{base}/api/v1/search", params={"query": search_query, "page": 1, "language": "en"},
                         headers=hdrs, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        return {"ok": False, "message": f"Overseerr search failed: {e}"}

    # Pick best match — ranked: exact title+type > exact title > correct type > first result
    norm_query = search_query.strip().lower()
    want = None if media_type == "auto" else ("tv" if media_type == "tv" else "movie")
    match = None
    # 1. Exact title match with correct type
    for r in results:
        r_title = (r.get("title") or r.get("name") or "").strip().lower()
        if r_title == norm_query and (want is None or r.get("mediaType") == want):
            match = r
            break
    # 2. Exact title match, any type
    if not match:
        for r in results:
            if (r.get("title") or r.get("name") or "").strip().lower() == norm_query:
                match = r
                break
    # 3. First result of correct type
    if not match and want:
        match = next((r for r in results if r.get("mediaType") == want), None)
    # 4. First result (last resort)
    if not match:
        match = results[0] if results else None
    if not match:
        return {"ok": False, "message": f"No results found for '{title}' on Overseerr"}

    # Resolve want from the actual match (covers auto-detection case)
    want = match.get("mediaType", "tv")  # Overseerr returns "movie" or "tv"
    tmdb_id = match.get("id")
    found_title = match.get("title") or match.get("name") or title
    media_info = match.get("mediaInfo") or {}

    # Already available?
    if media_info.get("status") == 5:
        return {"ok": True, "message": f"✅ '{found_title}' is already in the library"}
    # Already requested?
    if media_info.get("status") in (2, 3, 4):
        return {"ok": True, "message": f"⏳ '{found_title}' is already requested/downloading"}

    # For TV shows, get season numbers from the match details
    seasons_payload: list = []
    if want == "tv":
        try:
            det = requests.get(f"{base}/api/v1/tv/{tmdb_id}", headers=hdrs, timeout=10).json()
            seasons_payload = [
                s["seasonNumber"]
                for s in det.get("seasons", [])
                if s.get("seasonNumber", 0) > 0
            ]
        except Exception:
            pass  # fall back to empty list — Overseerr accepts this for some versions

    # Submit request
    body: Dict = {"mediaType": want, "mediaId": tmdb_id}
    if want == "tv" and seasons_payload:
        body["seasons"] = seasons_payload
    try:
        r2 = requests.post(f"{base}/api/v1/request", json=body, headers=hdrs, timeout=10)
        r2.raise_for_status()
        return {"ok": True, "message": f"✅ Requested '{found_title}' — Overseerr will pick it up shortly"}
    except requests.HTTPError as e:
        body = e.response.text[:200] if e.response else str(e)
        return {"ok": False, "message": f"Request failed: {body}"}
    except Exception as e:
        return {"ok": False, "message": f"Request failed: {e}"}


def _do_delete(title: str, media_type: str) -> Dict:
    """Find title in Radarr or Sonarr and delete it (files included)."""
    if media_type == "auto":
        # Try both — check Sonarr first, then Radarr
        result = _do_delete(title, "tv")
        if not result["ok"] and "not found" in result["message"]:
            result = _do_delete(title, "movie")
        return result
    if media_type == "movie":
        svc = _svc("radarr")
        if not svc:
            return {"ok": False, "message": "Radarr not configured"}
        scheme = "https" if svc["ssl"] else "http"
        base = f"{scheme}://{svc['host']}:{svc['port']}"
        hdrs = {"X-Api-Key": svc["key"]}
        try:
            movies = requests.get(f"{base}/api/v3/movie", headers=hdrs, timeout=10).json()
            title_lower = title.lower()
            match = next((m for m in movies if title_lower in m.get("title", "").lower()), None)
            if not match:
                return {"ok": False, "message": f"'{title}' not found in Radarr"}
            movie_id = match["id"]
            found_title = match["title"]
            requests.delete(f"{base}/api/v3/movie/{movie_id}",
                            params={"deleteFiles": "true", "addImportExclusion": "false"},
                            headers=hdrs, timeout=10).raise_for_status()
            return {"ok": True, "message": f"🗑️ '{found_title}' deleted from library (files removed)"}
        except Exception as e:
            return {"ok": False, "message": f"Delete failed: {e}"}
    else:
        svc = _svc("sonarr")
        if not svc:
            return {"ok": False, "message": "Sonarr not configured"}
        scheme = "https" if svc["ssl"] else "http"
        base = f"{scheme}://{svc['host']}:{svc['port']}"
        hdrs = {"X-Api-Key": svc["key"]}
        try:
            series = requests.get(f"{base}/api/v3/series", headers=hdrs, timeout=10).json()
            title_lower = title.lower()
            match = next((s for s in series if title_lower in s.get("title", "").lower()), None)
            if not match:
                return {"ok": False, "message": f"'{title}' not found in Sonarr"}
            series_id = match["id"]
            found_title = match["title"]
            requests.delete(f"{base}/api/v3/series/{series_id}",
                            params={"deleteFiles": "true"},
                            headers=hdrs, timeout=10).raise_for_status()
            return {"ok": True, "message": f"🗑️ '{found_title}' deleted from library (files removed)"}
        except Exception as e:
            return {"ok": False, "message": f"Delete failed: {e}"}
