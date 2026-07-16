"""Sovereign-local acronym name generator for net-new agent hires.

Generates a dotted-uppercase acronym name (F.O.R.G.E. convention) recommended
for a capability, deduped against every existing agent name (all shift states).
All inference is local_only via the DHQ dispatcher (ADR-013) — no direct Ollama,
no cloud.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Hard wall-clock bound on the (creative) dispatch so the interactive button can
# never hang on a cold/slow fleet — on timeout the generator falls back to a
# deterministic name. Naming is a creative task, so it routes to the creative
# agent (M.U.S.E.); a tiny model would ignore the single-word format even more.
_DISPATCH_TIMEOUT_S = 20

_SYSTEM_PROMPT = (
    "You name AI agents for the A.R.C.H.I.E. platform. A name is ONE single real or "
    "pronounceable English word of 4-7 letters, UPPERCASE with a dot after EACH "
    "LETTER — e.g. F.O.R.G.E. (5 letters), V.I.G.I.L. (5), M.A.V.E.N. (5), C.O.D.E.X. "
    "(5), V.E.R.I.F.Y. (6). It is ALWAYS a single word, NEVER two words. Each letter "
    "is the first letter of a word describing the role. Reply with STRICT JSON only."
)


def _normalize(name: str) -> str:
    """Comparison key: uppercase letters only (V.E.R.I.F.Y. == VERIFY)."""
    return re.sub(r"[^A-Z]", "", (name or "").upper())


def _dotify(letters: str) -> str:
    """'VERIFY' -> 'V.E.R.I.F.Y.'  (empty -> '')."""
    up = _normalize(letters)
    return ".".join(up) + "." if up else ""


def _valid_letters(name: str) -> bool:
    """House style is 4-7 letters (FORGE=5, VIGIL=5, MAVEN=5, CODEX=5)."""
    return 4 <= len(_normalize(name)) <= 7


def _department_for_capability(capability: str) -> str:
    """CAPABILITY_DEPARTMENT_MAP home dept; Engineering fallback. Lazy import."""
    try:
        from tools.department_hq.services.department_coordinator import (
            CAPABILITY_DEPARTMENT_MAP,
        )

        return CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")
    except Exception:
        return "Engineering & Technology"


def _existing_names() -> set[str]:
    """All agent names (every shift_state) as normalized keys. Mockable seam."""
    names: set[str] = set()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT name FROM agents WHERE name IS NOT NULL")
        for r in cur.fetchall():
            nm = r["name"] if isinstance(r, dict) else r[0]
            norm = _normalize(nm)
            if norm:
                names.add(norm)
    return names


def _parse_json(text: str) -> Optional[dict]:
    """Best-effort extract a JSON object from an LLM response (tolerates ```json
    fences and surrounding prose)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) >= 2:
            s = parts[1]
            if s.lstrip()[:4].lower() == "json":
                s = s.lstrip()[4:]
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b < a:
        return None
    try:
        obj = json.loads(s[a : b + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _dispatch_name(capability: str, prompt: str) -> Optional[dict]:
    """Sovereign-local creative dispatch, routed to a warm model and HARD-bounded
    by a wall-clock timeout so the interactive caller can never hang on a cold
    fleet. Returns the parsed JSON dict, or None on timeout/failure. Mockable seam.
    """
    import concurrent.futures

    def _call() -> Optional[dict]:
        from tools.department_hq.services.department_dispatcher import dispatch

        res = dispatch(
            capability="creative",
            prompt=prompt,
            module_id="hire_name_generator",
            system_prompt=_SYSTEM_PROMPT,
            json_mode=True,
            local_only=True,
            timeout=_DISPATCH_TIMEOUT_S,
        )
        if not res or not getattr(res, "success", False):
            return None
        return _parse_json(getattr(res, "response", "") or "")

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(_call).result(timeout=_DISPATCH_TIMEOUT_S + 3)
    except concurrent.futures.TimeoutError:
        logger.warning("name-gen dispatch exceeded %ss — using fallback", _DISPATCH_TIMEOUT_S)
        return None
    except Exception as e:
        logger.warning("name-gen dispatch failed: %s", e)
        return None
    finally:
        ex.shutdown(wait=False)  # don't block on a still-running dispatch thread


def _build_prompt(capability: str, department: str, avoid: set[str]) -> str:
    role = capability.replace("_", " ")
    # Bound the in-prompt avoid-list; server-side dedupe is authoritative.
    avoid_sample = ", ".join(sorted(avoid)[:60]) if avoid else "(none)"
    return (
        f"Invent ONE agent name for the job '{role}' ({department} department).\n"
        "Rules:\n"
        "- The name is ONE single word, 4 to 7 letters TOTAL (never two words).\n"
        "- UPPERCASE with a dot after EACH LETTER: F.O.R.G.E. has 5 letters -> 5 dots.\n"
        "- Each letter starts a word describing the role (the expansion).\n"
        '- GOOD: {"name":"V.E.R.I.F.Y.","expansion":"Validation Engine Reviewing '
        'Information For Yield","title":"Fact Checker"}\n'
        '- BAD (never do this): "TRUTH.CHECKER." or "F.A.C.T.C.H.E.C.K." — that is '
        "two words / more than 7 letters.\n"
        f"- The name MUST NOT match any of these: {avoid_sample}\n"
        'Return STRICT JSON only: {"name":"X.X.X.X.","expansion":"Word Word ...",'
        '"title":"<short human role>"}'
    )


def suggest_name(
    capability: str,
    department: Optional[str] = None,
    *,
    avoid_names: Optional[set[str]] = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Return {'name','expansion','title','source'} (source: 'llm'|'fallback').

    Sovereign-local creative dispatch, validated for format + uniqueness, with
    <=max_attempts retries (each collision fed back into the avoid-list) and a
    deterministic unique fallback so the caller never gets a malformed/dup name.
    """
    capability = (capability or "general").strip() or "general"
    department = department or _department_for_capability(capability)
    avoid = set(avoid_names or ())
    try:
        avoid |= _existing_names()
    except Exception as e:  # a DB hiccup must not break generation
        logger.warning("name-gen: existing-names lookup failed: %s", e)

    for _ in range(max(1, max_attempts)):
        prompt = _build_prompt(capability, department, avoid)
        try:
            data = _dispatch_name(capability, prompt)
        except Exception as e:
            logger.warning("name-gen dispatch failed: %s", e)
            data = None
        if not isinstance(data, dict):
            break  # timeout / failure — go straight to the deterministic fallback
        letters = _normalize(str(data.get("name") or ""))
        if _valid_letters(letters) and letters not in avoid:
            return {
                "name": _dotify(letters),
                "expansion": str(data.get("expansion") or "").strip(),
                "title": str(data.get("title") or "").strip(),
                "source": "llm",
            }
        if letters:
            avoid.add(letters)  # never re-propose a rejected/dup name
    return _fallback_name(capability, avoid)


def _fallback_name(capability: str, avoid: set[str]) -> dict[str, Any]:
    """Deterministic, guaranteed-unique acronym derived from the capability."""
    words = re.sub(r"[^a-z ]", " ", capability.lower().replace("_", " ")).split()
    letters = "".join(w[0] for w in words if w).upper()
    for ch in "AGENTCOREUNIT":  # pad short capabilities up to 4 letters
        if len(letters) >= 4:
            break
        letters += ch
    letters = _normalize(letters)[:7]

    cand = letters if (_valid_letters(letters) and letters not in avoid) else ""
    if not cand:
        base = letters[:6]  # leave room for a distinguishing final letter
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            trial = base + ch
            if _valid_letters(trial) and trial not in avoid:
                cand = trial
                break
    if not cand:  # absurd corner — accept a possibly-dup but valid name
        cand = letters[:6] + "X"
    return {
        "name": _dotify(cand),
        "expansion": " ".join(w.capitalize() for w in words) or "Agent Core Unit",
        "title": f"{capability.replace('_', ' ').title()} Specialist",
        "source": "fallback",
    }
