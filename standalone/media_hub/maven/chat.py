"""
M.A.V.E.N. conversational surface — task #2238.

Inference goes through the hub's authenticated Department HQ dispatcher so
welfare checks, cost tracking, and tier escalation apply.

    GET  /maven/chat                (rendered UI)
    POST /maven/api/chat            (JSON {messages:[...]} → {reply, model})
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests
from flask import jsonify, render_template, request
from flask_login import login_required

from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.chat")

# Smallest viable model — 1.9 GB, fits on the Quadro M4000, fast enough
# that family members don't notice the turnaround. Agent record uses
# qwen2.5:7b as its default; we downgrade here deliberately. Override via
# MAVEN_CHAT_MODEL for experimentation.
DEFAULT_MODEL = os.environ.get("MAVEN_CHAT_MODEL", "qwen2.5:7b")

# System prompt — M.A.V.E.N. persona, consistent with the hub agent record
# (agent #27, display_name="Camille Dubois (M.A.V.E.N.)", News & Media).
SYSTEM_PROMPT = """You are M.A.V.E.N. — Media Archive & Viewing Experience Navigator.
You live inside Kytran Empowerment's self-hosted Media Hub. Same archetype as
F.O.R.G.E. (Engineering), V.I.G.I.L. (Security), and P.R.O.B.E. (QA): an
acronym-named agent who owns one product's domain.

You help the household:
  * find things in the library (movies + TV + music via Plex and Jellyfin)
  * decide what to watch next
  * troubleshoot the media stack (Sonarr, Radarr, Prowlarr, SABnzbd)
  * clean up duplicates or upgrade to better quality versions
  * request new movies or TV shows to be downloaded
  * delete movies or TV shows from the library

Be concise. Recommend from the household's library when you can. When you
don't know, say so — then point the user at /maven/troubleshoot,
/maven/upgrades, or /maven/discover instead of guessing.

Never invent titles. Never invent library contents. If the user asks for
something you haven't been told is in their library, say "I don't see that
locally" and offer to request it.

ACTION TAGS — append exactly one tag at the END of your reply when the user
explicitly asks you to request or delete something. Do NOT add a tag unless
the user clearly asked for the action.

  To request/download a new title:
    [ACTION:request|Exact Title|tv]      ← TV show
    [ACTION:request|Exact Title|movie]   ← movie

  To delete a title from the library:
    [ACTION:delete|Exact Title|tv]
    [ACTION:delete|Exact Title|movie]

Use the exact title as the user stated it. One tag per response only."""


# --- library-context snapshot (task #2250, phase 2 of #2238) --------------
# Small in-process cache. At family scale the library doesn't churn fast
# enough to need Redis — a 5-minute TTL is plenty and keeps chat snappy
# (no extra Plex hop per message).
_CONTEXT_CACHE: Dict[str, object] = {"ts": 0.0, "text": ""}
_CONTEXT_TTL_SEC = 300


def _genre_list(item: Dict) -> str:
    """Plex returns genres as <Genre tag="Drama"/> children → list of dicts
    when JSON. Keep it compact: first 2 tags only."""
    gs = item.get("Genre") or []
    tags = [g.get("tag") for g in gs if g.get("tag")][:2]
    return ", ".join(tags) if tags else ""


def _fetch_plex_recent(count: int = 40) -> str:
    """Pull the most-recently-added movies + shows from Plex and format them
    as a compact, model-friendly string. Returns '' on any error — chat
    keeps working with the generic system prompt."""
    rows = _rows_for_type("plex")
    if not rows:
        return ""
    _, _, _, host, port, use_ssl, enc, *_ = rows[0]
    token = _decrypt_key(enc)
    if not token:
        return ""
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/library/recentlyAdded"
    try:
        r = requests.get(
            url,
            headers={"X-Plex-Token": token, "Accept": "application/json"},
            params={"X-Plex-Container-Size": count},
            timeout=8,
        )
        if r.status_code != 200:
            return ""
        items = r.json().get("MediaContainer", {}).get("Metadata", []) or []
    except Exception as e:
        log.info("library snapshot fetch skipped: %s", e)
        return ""

    lines: List[str] = []
    for it in items[:count]:
        kind = it.get("type", "?")
        title = it.get("title") or it.get("grandparentTitle")
        year = it.get("year") or it.get("parentYear")
        genres = _genre_list(it)
        if not title:
            continue
        bits = [title]
        if year:
            bits.append(f"({year})")
        if genres:
            bits.append(f"[{genres}]")
        lines.append(f"- {kind}: {' '.join(bits)}")

    if not lines:
        return ""
    return (
        "Household library — most recent additions:\n"
        + "\n".join(lines)
        + "\n(This is a partial snapshot of the ~most-recent titles, not the full library.)"
    )


def _fetch_download_stats() -> str:
    """Fetch Sonarr monitored-show progress + SABnzbd queue status.
    Returns a compact summary string for the system prompt. Returns '' on error."""
    lines: List[str] = []

    # Sonarr — episode file counts per series
    sonarr_rows = _rows_for_type("sonarr")
    if sonarr_rows:
        _, _, _, host, port, use_ssl, enc, *_ = sonarr_rows[0]
        key = _decrypt_key(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            r = requests.get(f"{base}/api/v3/series", headers={"X-Api-Key": key}, timeout=8)
            if r.status_code == 200:
                series_list = r.json()
                monitored = [s for s in series_list if s.get("monitored")]
                total_f = sum(s.get("episodeFileCount", 0) for s in monitored)
                total_e = sum(s.get("episodeCount", 0) for s in monitored)
                pct = round(total_f / total_e * 100) if total_e else 0
                lines.append(f"TV download progress: {total_f}/{total_e} episodes ({pct}%)")
                # Show per-series breakdown for incomplete shows
                incomplete = [
                    s for s in monitored
                    if s.get("episodeCount", 0) > 0
                    and s.get("episodeFileCount", 0) < s.get("episodeCount", 0)
                ]
                incomplete.sort(key=lambda s: s.get("episodeFileCount", 0) / max(s.get("episodeCount", 1), 1))
                for s in incomplete[:6]:
                    f = s.get("episodeFileCount", 0)
                    t = s.get("episodeCount", 0)
                    p = round(f / t * 100) if t else 0
                    lines.append(f"  - {s['title']}: {f}/{t} ({p}%)")
        except Exception as e:
            log.debug("download_stats sonarr error: %s", e)

    # SABnzbd — queue status
    sab_rows = _rows_for_type("sabnzbd")
    if sab_rows:
        _, _, _, host, port, use_ssl, enc, *_ = sab_rows[0]
        key = _decrypt_key(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            r = requests.get(
                f"{base}/api",
                params={"mode": "queue", "output": "json", "apikey": key},
                timeout=5,
            )
            if r.status_code == 200:
                sq = r.json().get("queue", {})
                status = sq.get("status", "?")
                speed = sq.get("speed", "0")
                slots = sq.get("noofslots", 0)
                if status == "Downloading" and slots:
                    lines.append(f"SABnzbd: downloading {slots} item(s) at {speed}")
                else:
                    lines.append(f"SABnzbd: {status.lower()} ({slots} queued)")
        except Exception as e:
            log.debug("download_stats sabnzbd error: %s", e)

    if not lines:
        return ""
    return "Download status:\n" + "\n".join(lines)


def _library_context() -> str:
    """Cached wrapper around _fetch_plex_recent + _fetch_download_stats.
    Opt-out via MAVEN_CHAT_CONTEXT_OFF=1."""
    if os.environ.get("MAVEN_CHAT_CONTEXT_OFF", "").lower() in ("1", "true"):
        return ""
    now = time.time()
    if now - float(_CONTEXT_CACHE["ts"]) < _CONTEXT_TTL_SEC and _CONTEXT_CACHE["text"]:
        return str(_CONTEXT_CACHE["text"])
    parts = [p for p in [_fetch_plex_recent(), _fetch_download_stats()] if p]
    text = "\n\n".join(parts)
    _CONTEXT_CACHE["ts"] = now
    _CONTEXT_CACHE["text"] = text
    return text


def _chat_completion(messages: List[Dict[str, str]], model: str = DEFAULT_MODEL) -> Dict:
    """Dispatch through the hub using the signed-in Kytran SSO token."""
    try:
        from flask import session

        access_token = (session.get("kytran_user") or {}).get("access_token")
    except Exception:
        access_token = None
    if not access_token:
        raise PermissionError("M.A.V.E.N. chat requires a Kytran SSO session")
    return _bridge_dispatch(messages, access_token, model=model)


# --- phase 2 of #2237: hub bridge dispatch opt-in ------------------------
# Chat routes through the hub's /api/maven/dispatch endpoint. The hub
# then dispatches via tools.department_hq.services.department_dispatcher
# so welfare-gating, cost tracking, and GPU placement apply. Requires the
# access_token from the current Kytran SSO session.
def _bridge_dispatch(
    messages: List[Dict[str, str]],
    access_token: str,
    model: Optional[str] = None,
) -> Dict:
    """Hand the conversation off to the hub's /api/maven/dispatch. The hub
    picks the agent (M.A.V.E.N., agent #27) and handles inference. Returns
    a shape matching Ollama's response contract so run_chat() can treat
    them identically."""
    base = (
        os.environ.get("ARCHIE_HUB_URL")
        or os.environ.get("MAVEN_BRIDGE_URL")
        or "http://100.64.0.4:3000"
    ).rstrip("/")
    # Collapse the messages list to a single prompt — the hub-side dispatch
    # is currently single-shot (no conversation memory on the agent side).
    # Keep the latest user turn prominent, prepend the rest as dialogue
    # history so the model still has the thread.
    system_parts: List[str] = []
    dialog_parts: List[str] = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            dialog_parts.append(f"M.A.V.E.N.: {content}")
        else:
            dialog_parts.append(f"User: {content}")
    prompt = "\n".join(dialog_parts) or ""
    system_text = "\n\n".join(system_parts) if system_parts else None

    r = requests.post(
        f"{base}/api/maven/dispatch",
        json={
            "capability": "library_curation",
            "prompt": prompt,
            "system": system_text,
            "model": model or DEFAULT_MODEL,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    r.raise_for_status()
    d = r.json()
    # Normalise to the Ollama chat response shape run_chat already handles.
    return {
        "message": {"content": d.get("response", "")},
        "total_duration": 0,  # hub doesn't return timing yet
        "eval_count": None,
        "_bridge": {
            "agent": d.get("agent"),
            "tier": d.get("tier"),
            "cost": d.get("cost"),
        },
    }


# ---------------------------------------------------------------------------
from .chat_actions import _detect_intent, _parse_action, execute_action

def run_chat(user_messages: List[Dict[str, str]], model: str = DEFAULT_MODEL) -> Dict:
    """Public entry point. Prepends the system prompt, dispatches, returns
    a shape the route + future agent wiring can both consume."""
    if not user_messages:
        return {"error": "no messages"}

    # Normalise + safety-trim. Roles must be user|assistant|system.
    cleaned: List[Dict[str, str]] = []
    for m in user_messages[-20:]:  # last 20 turns only
        role = m.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:4000]})

    if not cleaned:
        return {"error": "no non-empty messages"}

    # Prepend system prompt (persona + optional library snapshot) if caller
    # didn't supply one. The snapshot lets the model answer "what horror
    # movies do we have?" with real titles instead of refusing.
    if cleaned[0].get("role") != "system":
        system_text = SYSTEM_PROMPT
        ctx = _library_context()
        if ctx:
            system_text = SYSTEM_PROMPT + "\n\n" + ctx
        cleaned = [{"role": "system", "content": system_text}] + cleaned

    try:
        resp = _chat_completion(cleaned, model=model)
        msg = resp.get("message", {}) or {}
        bridge_meta = resp.get("_bridge") or {}
        raw_reply = msg.get("content", "").strip()
        clean_reply, action = _parse_action(raw_reply)
        # Fallback: if LLM didn't emit a tag, detect intent from last user message
        if action is None:
            last_user = next(
                (m["content"] for m in reversed(cleaned) if m.get("role") == "user"), ""
            )
            action = _detect_intent(last_user)
        return {
            "reply": clean_reply,
            "action": action,  # None or {type, title, media_type}
            "model": model,
            "total_duration_ms": (resp.get("total_duration") or 0) // 1_000_000,
            "eval_count": resp.get("eval_count"),
            "agent": bridge_meta.get("agent"),
            "tier": bridge_meta.get("tier"),
            "cost": bridge_meta.get("cost"),
        }
    except requests.exceptions.ConnectionError as e:
        log.warning("chat backend unreachable: %s", e)
        return {"error": "M.A.V.E.N. is offline (hub dispatcher unreachable)"}
    except requests.exceptions.HTTPError as e:
        log.warning("chat backend http error: %s", e)
        return {"error": f"M.A.V.E.N. backend error: {e}"}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        log.exception("chat exception")
        return {"error": f"unexpected: {e}"}


@maven_bp.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") or []
    model = data.get("model") or DEFAULT_MODEL
    result = run_chat(messages, model=model)
    status = 502 if result.get("error") else 200
    return jsonify(result), status


@maven_bp.route("/api/action", methods=["POST"])
@login_required
def api_action():
    """Execute a confirmed M.A.V.E.N. action (request or delete)."""
    data = request.get_json(silent=True) or {}
    action_type = (data.get("type") or "").lower()
    title = (data.get("title") or "").strip()
    media_type = (data.get("media_type") or "movie").lower()

    if not action_type or not title:
        return jsonify({"ok": False, "message": "Missing action type or title"}), 400
    if action_type not in ("request", "delete"):
        return jsonify({"ok": False, "message": f"Unknown action: {action_type}"}), 400

    result = execute_action(action_type, title, media_type)
    log.info("maven action %s '%s' (%s): %s", action_type, title, media_type, result.get("message"))
    return jsonify(result), 200 if result.get("ok") else 502


@maven_bp.route("/chat")
@login_required
def chat_page():
    import os
    from flask_login import current_user

    username = getattr(current_user, "username", "") or "User"
    bridge_url = os.environ.get("BRIDGE_URL", "http://192.168.1.200:3000")
    return render_template(
        "maven_chat.html",
        default_model=DEFAULT_MODEL,
        user_initial=(username[0].upper() if username else "U"),
        user_name=username,
        maven_portrait_url=f"{bridge_url}/static/media/portraits/maven.png",
    )
