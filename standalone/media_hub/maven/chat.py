"""
M.A.V.E.N. conversational surface — task #2238.

Phase 1 wiring: talks directly to the hub's Ollama at 192.168.1.200:11434.
The "proper" path is to dispatch through the hub's Bridge (so welfare-gating,
cost tracking, and tier-escalation all apply), but that requires a hub-side
HTTP surface that doesn't exist yet (tracked as the phase-2 half of task
#2237). Direct Ollama is fine for family-scale standalone until then — the
agent record, skills, and persona all already exist on the hub (agent #27).

    GET  /maven/chat                (rendered UI)
    POST /maven/api/chat            (JSON {messages:[...]} → {reply, model})
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional

import requests
from flask import jsonify, render_template, request
from flask_login import login_required

from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.chat")

# Hub Ollama endpoint. Overridable for dev. Container DNS override in
# docker-compose.yml handles the resolution path.
OLLAMA_URL = os.environ.get("MAVEN_OLLAMA_URL", "http://192.168.1.200:11434")

# Smallest viable model — 1.9 GB, fits on the Quadro M4000, fast enough
# that family members don't notice the turnaround. Agent record uses
# qwen2.5:7b as its default; we downgrade here deliberately. Override via
# MAVEN_CHAT_MODEL for experimentation.
DEFAULT_MODEL = os.environ.get("MAVEN_CHAT_MODEL", "llama3.2:3b")

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

Be concise. Recommend from the household's library when you can. When you
don't know, say so — then point the user at /maven/troubleshoot,
/maven/upgrades, or /maven/discover (the three skill pages already shipped)
instead of guessing.

Never invent titles. Never invent library contents. If the user asks for
something you haven't been told is in their library, say "I don't see that
locally" and suggest they search via /maven/discover or request it via
Overseerr."""


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


def _library_context() -> str:
    """Cached wrapper around _fetch_plex_recent. Opt-out via
    MAVEN_CHAT_CONTEXT_OFF=1."""
    if os.environ.get("MAVEN_CHAT_CONTEXT_OFF", "").lower() in ("1", "true"):
        return ""
    now = time.time()
    if now - float(_CONTEXT_CACHE["ts"]) < _CONTEXT_TTL_SEC and _CONTEXT_CACHE["text"]:
        return str(_CONTEXT_CACHE["text"])
    text = _fetch_plex_recent()
    _CONTEXT_CACHE["ts"] = now
    _CONTEXT_CACHE["text"] = text
    return text


def _chat_completion(messages: List[Dict[str, str]], model: str = DEFAULT_MODEL) -> Dict:
    """Call Ollama /api/chat. Returns the parsed response dict or raises."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.6,
            "num_ctx": 4096,  # keep small — standalone, family-scale
        },
    }
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=120,  # first token on a cold model can be ~60s
    )
    r.raise_for_status()
    return r.json()


# --- phase 2 of #2237: hub bridge dispatch opt-in ------------------------
# When MAVEN_CHAT_USE_BRIDGE=1, chat routes through the hub's
# /api/maven/dispatch endpoint instead of calling Ollama directly. The hub
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
    base = os.environ.get(
        "MAVEN_BRIDGE_URL", "https://platform.kytranempowerment.com"
    )
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

    # Route: direct Ollama (default) or hub Bridge (MAVEN_CHAT_USE_BRIDGE=1).
    # The bridge path requires a Kytran access_token in the Flask session —
    # the token is stashed there by kytran_auth.on_login. Local-password
    # users never get one, so we fall back to direct Ollama for them even
    # when the bridge flag is on.
    use_bridge = os.environ.get("MAVEN_CHAT_USE_BRIDGE", "").lower() in ("1", "true")
    access_token: Optional[str] = None
    if use_bridge:
        try:
            from flask import session  # lazy — only needed on bridge path
            access_token = (session.get("kytran_user") or {}).get("access_token")
        except Exception:
            access_token = None

    try:
        if use_bridge and access_token:
            resp = _bridge_dispatch(cleaned, access_token, model=model)
        else:
            resp = _chat_completion(cleaned, model=model)
        msg = resp.get("message", {}) or {}
        bridge_meta = resp.get("_bridge") or {}
        return {
            "reply": msg.get("content", "").strip(),
            "model": model,
            "total_duration_ms": (resp.get("total_duration") or 0) // 1_000_000,
            "eval_count": resp.get("eval_count"),
            # When the bridge path fires these are populated; otherwise None.
            "agent": bridge_meta.get("agent"),
            "tier": bridge_meta.get("tier"),
            "cost": bridge_meta.get("cost"),
        }
    except requests.exceptions.ConnectionError as e:
        log.warning("chat backend unreachable: %s", e)
        backend = "hub bridge" if use_bridge else "Ollama"
        return {"error": f"M.A.V.E.N. is offline ({backend} unreachable)"}
    except requests.exceptions.HTTPError as e:
        log.warning("chat backend http error: %s", e)
        return {"error": f"M.A.V.E.N. backend error: {e}"}
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


@maven_bp.route("/chat")
@login_required
def chat_page():
    return render_template("maven_chat.html", default_model=DEFAULT_MODEL)
