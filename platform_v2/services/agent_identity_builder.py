"""Sovereign-local COMPLETE agent identity builder (extends agent_name_generator).

From a capability/role (+ department) produce a full, directory-aligned identity:
name, expansion, title, bio, personality, a rich (>=400 char) system prompt with
the expansion woven in, and a sci-fi portrait prompt. ONE local_only creative
dispatch supplies the creative parts; a deterministic template assembles the
system prompt so length/shape are guaranteed regardless of the local model.
Fallback yields a complete (plainer) identity. All inference via DHQ (ADR-013).
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from typing import Any, Optional

from services.agent_name_generator import (
    MAX_ATTEMPTS,
    _DISPATCH_TIMEOUT_S,
    _department_for_capability,
    _dotify,
    _existing_names,
    _fallback_name,
    _normalize,
    _parse_json,
    _valid_letters,
    capability_phrase,
    capability_words,
)

logger = logging.getLogger(__name__)

MIN_SYSTEM_PROMPT_CHARS = 400

_IDENTITY_SYSTEM_PROMPT = (
    "You design AI agent identities for the A.R.C.H.I.E. platform. A name is ONE "
    "single pronounceable English word of 4-7 letters, UPPERCASE with a dot after "
    "EACH letter (F.O.R.G.E., V.I.G.I.L., M.A.V.E.N.). Each letter starts a word of "
    "the expansion. Reply with STRICT JSON only."
)


def _floor_for_department(department: str) -> str:
    try:
        from services.agent_service import DEPARTMENT_FLOOR_MAP

        return DEPARTMENT_FLOOR_MAP.get(department, "SERVICES")
    except Exception:
        return "SERVICES"


def _build_identity_prompt(capability: str, department: str, avoid: set[str], existing_name: Optional[str]) -> str:
    role = capability.replace("_", " ")
    avoid_sample = ", ".join(sorted(avoid)[:60]) if avoid else "(none)"
    if existing_name:
        name_rule = (
            f'Use EXACTLY this name: "{existing_name}" (do not change it); craft an '
            "expansion whose words start with its letters.\n"
        )
    else:
        name_rule = (
            "- name: ONE single word, 4 to 7 letters, dotted UPPERCASE.\n"
            f"- name MUST NOT match any of: {avoid_sample}\n"
        )
    return (
        f"Design an agent for the job '{role}' ({department} department).\n"
        + name_rule
        + "- expansion: words that start with the name's letters, describing the role.\n"
        "- title: a short human job title.\n"
        "- bio: 2-3 sentence backstory.\n"
        "- personality: 1-2 sentences of traits.\n"
        "- voice: a few words on tone.\n"
        "- portrait_hint: a vivid visual description of this character.\n"
        'Return STRICT JSON only: {"name":"X.X.X.X.","expansion":"...","title":"...",'
        '"bio":"...","personality":"...","voice":"...","portrait_hint":"..."}'
    )


def _dispatch_identity(prompt: str) -> Optional[dict]:
    """Timeout-bounded sovereign creative dispatch. Returns parsed JSON or None.
    Mockable seam."""

    def _call() -> Optional[dict]:
        from tools.department_hq.services.department_dispatcher import dispatch

        res = dispatch(
            capability="creative",
            prompt=prompt,
            module_id="agent_identity_builder",
            system_prompt=_IDENTITY_SYSTEM_PROMPT,
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
    except Exception as e:  # timeout or dispatch error -> fallback
        logger.warning("identity dispatch failed/timeout: %s", e)
        return None
    finally:
        ex.shutdown(wait=False)


def _assemble_system_prompt(
    *, name: str, expansion: str, title: str, role: str, department: str, floor: str, personality: str, voice: str
) -> str:
    personality = (personality or "diligent, precise, and collaborative").strip().rstrip(".")
    voice = (voice or "clear and professional").strip().rstrip(".")
    return (
        f"You are {name} ({expansion}), the {title} in the {department} department "
        f"on Floor {floor} of the A.R.C.H.I.E. platform. Your specialty is {role}. "
        f"You own {role} tasks end to end: you plan, execute, verify your own work, "
        f"and report results honestly with evidence. Personality: {personality}. "
        f"Voice: {voice}. You operate sovereign-local under the Department HQ "
        f"dispatcher and are governed by C.R.E.E.D. ethics and welfare limits. You "
        f"never fabricate results, you escalate when blocked, and you uphold the "
        f"platform's standards: verify before claiming done, follow existing patterns, "
        f"and coordinate through the proper channels."
    )


def _build_portrait_prompt(*, name: str, expansion: str, title: str, department: str, hint: str = "") -> str:
    base = hint.strip() or f"a {title} specializing in {expansion}"
    return (
        f"Sci-fi character portrait of {name}, {base}. Futuristic A.R.C.H.I.E. platform "
        f"crew member in the {department} department. Cinematic lighting, clean sci-fi "
        f"uniform, confident expression, head-and-shoulders composition, high detail, "
        f"LCARS-inspired color palette."
    )


def _fallback_identity(
    capability: str, department: str, floor: str, existing_name: Optional[str], avoid: set[str]
) -> dict[str, Any]:
    role = capability.replace("_", " ")
    if existing_name:
        letters = _normalize(existing_name)
        name = existing_name if existing_name.endswith(".") else _dotify(letters)
        words = capability_words(capability)
        expansion = capability_phrase(words) or "Agent Core Unit"
        title = f"{role.title()} Specialist"
    else:
        fb = _fallback_name(capability, avoid)
        name, expansion, title = fb["name"], fb["expansion"], fb["title"]
    sysp = _assemble_system_prompt(
        name=name,
        expansion=expansion,
        title=title,
        role=role,
        department=department,
        floor=floor,
        personality="",
        voice="",
    )
    return {
        "name": name,
        "expansion": expansion,
        "title": title,
        "bio": f"{name} serves the {department} department, owning {role} for the " f"A.R.C.H.I.E. platform.",
        "personality": "",
        "system_prompt": sysp,
        "portrait_prompt": _build_portrait_prompt(name=name, expansion=expansion, title=title, department=department),
        "source": "fallback",
    }


def _coerce_expansion(value: Any) -> str:
    """Expansion as a STRING, whatever shape the model returned (#6237).

    The prompt asks for `"expansion":"..."` but a local model regularly answers
    with a JSON ARRAY of the per-letter words. `str()` on that yields the Python
    repr — and 17 live agents carry exactly that, verbatim:

        A.R.C.H.E.L. -> "['Architect', 'Engine', 'Lead']"
        I.N.T.E.G.R. -> "['Integrator', 'Agent', ' Bridge']"

    department-hq.js renders acronym_expansion straight onto the roster card, so
    the repr was displayed to the user as-is. Note the leading space in ' Bridge':
    a split(',') with no strip upstream, which is why each part is stripped here.

    A dict is accepted too (letter -> word) since that is the other shape a model
    reaches for; anything else falls back to str() as before, so this can only
    widen what is handled, never narrow it.
    """
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return " · ".join(parts)
    if isinstance(value, dict):
        parts = [str(v).strip() for v in value.values() if str(v).strip()]
        return " · ".join(parts)
    return str(value or "").strip()


def build_identity(
    capability: str,
    department: Optional[str] = None,
    *,
    existing_name: Optional[str] = None,
    avoid_names: Optional[set[str]] = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Return a COMPLETE identity dict (see module docstring). Sovereign-local,
    validated, with a deterministic complete fallback."""
    capability = (capability or "general").strip() or "general"
    department = department or _department_for_capability(capability)
    floor = _floor_for_department(department)
    role = capability.replace("_", " ")
    avoid = {_normalize(n) for n in (avoid_names or ()) if _normalize(n)}
    if not existing_name:
        try:
            avoid |= _existing_names()
        except Exception as e:
            logger.warning("identity: existing-names lookup failed: %s", e)

    for _ in range(max(1, max_attempts)):
        data = _dispatch_identity(_build_identity_prompt(capability, department, avoid, existing_name))
        if not isinstance(data, dict):
            break
        if existing_name:
            letters = _normalize(existing_name)
            name = existing_name if existing_name.endswith(".") else _dotify(letters)
            name_ok = bool(letters)
        else:
            letters = _normalize(str(data.get("name") or ""))
            name = _dotify(letters)
            name_ok = _valid_letters(letters) and letters not in avoid
        expansion = _coerce_expansion(data.get("expansion"))
        title = str(data.get("title") or "").strip() or f"{role.title()} Specialist"
        if name_ok and expansion:
            sysp = _assemble_system_prompt(
                name=name,
                expansion=expansion,
                title=title,
                role=role,
                department=department,
                floor=floor,
                personality=str(data.get("personality") or ""),
                voice=str(data.get("voice") or ""),
            )
            if len(sysp) >= MIN_SYSTEM_PROMPT_CHARS:
                return {
                    "name": name,
                    "expansion": expansion,
                    "title": title,
                    "bio": str(data.get("bio") or "").strip()
                    or f"{name} joined the {department} department to own {role}.",
                    "personality": str(data.get("personality") or "").strip(),
                    "system_prompt": sysp,
                    "portrait_prompt": _build_portrait_prompt(
                        name=name,
                        expansion=expansion,
                        title=title,
                        department=department,
                        hint=str(data.get("portrait_hint") or ""),
                    ),
                    "source": "llm",
                }
        if letters and not existing_name:
            avoid.add(letters)
    return _fallback_identity(capability, department, floor, existing_name, avoid)


def enrich_identity(current: dict[str, Any], capability: str, department: str) -> dict[str, Any]:
    """Complete an EXISTING agent's identity WITHOUT changing what's already good
    (Phase 2 backfill). Keep every non-empty field in `current`, fill only the
    gaps from a freshly built candidate, and ALWAYS rebuild the system prompt
    from the merged fields (>=400 chars, preserving the established
    expansion/title/personality — this "deepens" a thin/empty prompt without
    altering a live agent's meaning or voice).

    `current` keys: name, expansion, title, bio, personality, portrait_prompt,
    has_portrait (bool). Pure except for the single `build_identity` dispatch.
    Returns {name, after{...}, changed[list], portrait_needed bool}.
    """
    name = current["name"]
    role = (capability or "general").replace("_", " ")
    floor = _floor_for_department(department)
    cand = build_identity(capability, department=department, existing_name=name)

    def keep(field: str) -> str:
        cur = str(current.get(field) or "").strip()
        return cur if cur else str(cand.get(field) or "").strip()

    expansion = keep("expansion")
    title = keep("title") or f"{role.title()} Specialist"
    bio = keep("bio")
    personality = keep("personality")
    portrait_prompt = keep("portrait_prompt")
    system_prompt = _assemble_system_prompt(
        name=name,
        expansion=expansion,
        title=title,
        role=role,
        department=department,
        floor=floor,
        personality=personality,
        voice="",
    )

    after = {
        "expansion": expansion,
        "title": title,
        "bio": bio,
        "personality": personality,
        "system_prompt": system_prompt,
        "portrait_prompt": portrait_prompt,
        "source": cand.get("source", "llm"),
    }
    changed = [
        f
        for f in ("expansion", "title", "bio", "personality", "system_prompt", "portrait_prompt")
        if str(current.get(f) or "").strip() != str(after.get(f) or "").strip()
    ]
    portrait_needed = bool(portrait_prompt) and not current.get("has_portrait")
    return {"name": name, "after": after, "changed": changed, "portrait_needed": portrait_needed}
