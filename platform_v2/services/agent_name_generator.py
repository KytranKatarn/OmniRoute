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


_VOWELS = "AEIOUY"
_CONSONANT_RUN_RE = re.compile(r"[^AEIOUY]{4,}")


def _valid_letters(name: str) -> bool:
    """House style is 4-7 letters (FORGE=5, VIGIL=5, MAVEN=5, CODEX=5), and must
    be pronounceable: alpha-only, at least one vowel (A E I O U Y), and no run
    of 4+ consecutive consonants. The extra checks are defense in depth against
    gibberish blobs like "BCDFG" (task #4960 — the old "AGENTCOREUNIT"-padding
    fallback only checked length and produced exactly this kind of blob)."""
    letters = _normalize(name)
    return (
        4 <= len(letters) <= 7
        and letters.isalpha()
        and any(ch in _VOWELS for ch in letters)
        and not _CONSONANT_RUN_RE.search(letters)
    )


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


# Curated, on-theme, pronounceable acronym+expansion pairs used when neither
# the LLM nor the capability's own word-initials yield a valid name (task
# #4960 — replaces the old "AGENTCOREUNIT" character padding that produced
# gibberish like "I.A.A.G."). Every expansion's word-initials spell its
# acronym exactly (verified by test_fallback_pool_expansions_spell_their_acronyms);
# every acronym passes _valid_letters and was checked against a live
# `SELECT name FROM agents` at authoring time to confirm it is NOT already in
# use (see task #4960 report for the exclusion list used).
_FALLBACK_POOL: list[tuple[str, str]] = [
    ("PORTAL", "Process Operations Router Task Automation Logic"),
    ("HELM", "Hub Engine Logistics Management"),
    ("LUMEN", "Logic Unit Monitoring Event Notification"),
    ("VECTOR", "Verified Event Coordination Task Operations Router"),
    ("FUSION", "Federated Utility Synthesis Integration Operations Network"),
    ("PILOT", "Process Intelligence Logistics Operations Terminal"),
    ("RANGER", "Resource Automation Network Guidance Engine Response"),
    ("MARSHAL", "Monitoring Analysis Router Systems Health Access Logging"),
    ("ENGINE", "Enhanced Network Guidance Intelligence Nexus Engine"),
    ("HARBOR", "Hub Access Routing Backup Operations Recovery"),
    ("SIGMA", "Systems Intelligence Guidance Monitoring Automation"),
    ("TALON", "Task Automation Logistics Operations Nexus"),
    ("GRANITE", "Guidance Resource Automation Network Intelligence Task Engine"),
    ("ORBIT", "Operations Router Backup Intelligence Tracking"),
    ("QUORUM", "Quality Unit Operations Review Utility Monitoring"),
    ("SPIRE", "Systems Process Intelligence Router Engine"),
    ("NIMBUS", "Network Intelligence Monitoring Backup Utility Systems"),
    ("VESSEL", "Verified Event Systems Synchronization Engine Ledger"),
    ("CASCADE", "Coordinated Analysis Service Continuity Automation Dispatch Engine"),
    ("TRIBUNE", "Task Review Intelligence Briefing Utility Network Engine"),
    ("PIVOT", "Process Intelligence Verification Operations Terminal"),
    ("MODULE", "Managed Operations Data Utility Logic Engine"),
    ("CIRCUIT", "Coordinated Intelligence Routing Control Utility Integration Terminal"),
    ("BRACKET", "Backup Router Automation Coordination Knowledge Engine Terminal"),
    ("FATHOM", "Field Analysis Tracking Health Operations Monitor"),
    ("TETHER", "Task Escalation Tracking Handling Engine Router"),
    ("GATEWAY", "Guided Access Task Engine Workflow Automation Yield"),
    ("GAMBIT", "Guided Analysis Mission Briefing Intelligence Terminal"),
    ("CONDUIT", "Coordinated Operations Network Data Utility Integration Terminal"),
    ("KESTREL", "Knowledge Event Scanning Tracking Router Engine Logic"),
]


def _fallback_name(capability: str, avoid: set[str]) -> dict[str, Any]:
    """Deterministic, guaranteed-valid, guaranteed-unique acronym for a net-new
    hire. Tries the capability's own word-initials ONLY if that already yields
    a pronounceable, unused name; otherwise picks the first unused entry from
    the curated on-theme pool (_FALLBACK_POOL) — so the UI never again shows a
    gibberish blob like "I.A.A.G." (the old AGENTCOREUNIT-padding bug fixed in
    task #4960)."""
    words = re.sub(r"[^a-z ]", " ", capability.lower().replace("_", " ")).split()
    initials = _normalize("".join(w[0] for w in words if w))
    title = f"{capability.replace('_', ' ').title()} Specialist"

    if initials and _valid_letters(initials) and initials not in avoid:
        return {
            "name": _dotify(initials),
            "expansion": " ".join(w.capitalize() for w in words),
            "title": title,
            "source": "fallback",
        }

    for acronym, expansion in _FALLBACK_POOL:
        letters = _normalize(acronym)
        if _valid_letters(letters) and letters not in avoid:
            return {"name": _dotify(letters), "expansion": expansion, "title": title, "source": "fallback"}

    # Implausible corner: every curated pool entry collided with `avoid`.
    # Disambiguate with one extra pronounceable letter — NEVER reintroduce the
    # old "AGENTCOREUNIT" padding blob.
    for acronym, expansion in _FALLBACK_POOL:
        base = _normalize(acronym)[:6]
        for ch in "AEIOUYBCDFGHJKLMNPQRSTVWXZ":
            trial = base + ch
            if _valid_letters(trial) and trial not in avoid:
                return {
                    "name": _dotify(trial),
                    "expansion": f"{expansion} Extended",
                    "title": title,
                    "source": "fallback",
                }

    # Truly absurd corner (every pool entry AND every extension collided):
    # accept a possibly-duplicate but still valid, pronounceable name rather
    # than ever emit gibberish.
    acronym, expansion = _FALLBACK_POOL[0]
    return {"name": _dotify(acronym), "expansion": expansion, "title": title, "source": "fallback"}
