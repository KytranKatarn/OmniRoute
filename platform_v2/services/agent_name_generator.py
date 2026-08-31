"""Sovereign-local acronym name generator for net-new agent hires.

Generates a dotted-uppercase acronym name (F.O.R.G.E. convention) recommended
for a capability, deduped against every existing agent name (all shift states).
All inference is local_only via the DHQ dispatcher (ADR-013) — no direct Ollama,
no cloud.
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Hard wall-clock bound on the (creative) dispatch so the interactive button can
# never hang on a cold/slow fleet — on timeout the generator falls back to a
# randomized deterministic name. Naming dispatches the `creative` capability but
# pins a WARM small model (llama3.2:3b, see _dispatch_name's model_override)
# instead of the cold default 7B creative model, so the interactive button
# returns fast; strict-JSON + format/uniqueness validation + the randomized
# fallback below catch any output-format misses from the smaller model.
_DISPATCH_TIMEOUT_S = 20

_SYSTEM_PROMPT = (
    "You name AI agents for the A.R.C.H.I.E. platform. A name is ONE single real or "
    "pronounceable English word of 4-7 letters, UPPERCASE with a dot after EACH "
    "LETTER — e.g. F.O.R.G.E. (Engineering & Technology, 5 letters), D.A.R.W.I.N. "
    "(Research & Development, 6), S.P.E.C.T.R.A. (Analytics & Intelligence, 7), "
    "C.O.D.E.X. (Documentation & Knowledge, 5). It is ALWAYS a single word, NEVER "
    "two words. Each letter is the first letter of a word describing the role. Be "
    "INVENTIVE — the acronym should spell a real or pronounceable word that evokes "
    "the role; vary your word choices across requests, and do NOT lean on generic "
    "filler words like Process, Operations, Router, or Task. Reply with STRICT JSON "
    "only."
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
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

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
            # Route to a model that's kept warm on the hub GPU (ai-bridge.md)
            # instead of the cold 7B `creative` default — the cold load alone
            # exceeded the 20s bound 100% of the time, so the LLM path never
            # actually ran (task #4969).
            model_override="llama3.2:3b",
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


def capability_words(capability: str) -> list[str]:
    """Split a capability into display words, KEEPING digits.

    The old split was `[^a-z ]` -> " ", which deletes digits: "e2e_automation"
    became ["e", "e", "automation"] and rendered as "E E Automation". Digits are
    part of real capability names (e2e, s3, oauth2), and dropping them produces a
    caption that is wrong rather than merely terse.

    Digits never reach a NAME — _normalize() strips non-alpha for the acronym — so
    this only affects the human-readable expansion.
    """
    return re.sub(r"[^a-z0-9 ]", " ", (capability or "").lower().replace("_", " ")).split()


def capability_phrase(words: list[str]) -> str:
    """Title-case words for display. A word containing a digit is UPPERCASED
    ("e2e" -> "E2E"), because .capitalize() would render it "E2e"."""
    return " ".join(w.upper() if any(c.isdigit() for c in w) else w.capitalize() for w in words)


def _capability_candidates(words: list[str]) -> list[tuple[str, str]]:
    """Meaningful (letters, expansion) candidates derived from the capability's own
    words, best-first. Filtering is the caller's job — this only proposes.

    Each candidate's expansion DESCRIBES the capability rather than being a strict
    letter-by-letter backronym. That is deliberate: proper backronyms come from the
    LLM path, and this deterministic fallback's job is to be truthful and specific
    ("E.D.G.E." / "Edge Computing"), never poetic. A wrong-but-pretty expansion is
    worse than a plain accurate one — the whole defect being fixed here is names
    that read well and mean nothing.
    """
    words = [w for w in words if w]
    if not words:
        return []
    phrase = capability_phrase(words)
    out: list[tuple[str, str]] = []

    def add(raw: str, expansion: str) -> None:
        letters = _normalize(raw)
        if letters and all(letters != prev for prev, _ in out):
            out.append((letters, expansion))

    # 1. The first word itself — "edge_computing" -> EDGE, the most recognisable
    #    handle for the job. Trimmed to the 7-letter house maximum.
    add(words[0][:7], phrase)
    # 2. A later word, when the first is too short/long to be valid on its own
    #    ("api_testing" -> TESTING).
    for w in words[1:]:
        add(w[:7], phrase)
    # 3. First word + the initials of the rest — "api_testing" -> APIT. Keeps the
    #    leading concept and still distinguishes siblings sharing that concept.
    if len(words) > 1:
        add(words[0][:5] + "".join(w[0] for w in words[1:]), phrase)
    # 4. The words run together, trimmed — last meaningful shape before the
    #    generic pool ("edge_computing" -> EDGECOM).
    add("".join(words)[:7], phrase)
    return out


def _fallback_name(capability: str, avoid: set[str]) -> dict[str, Any]:
    """Guaranteed-valid, guaranteed-unique acronym for a net-new hire. Tries the
    capability's own word-initials ONLY if that already yields a pronounceable,
    unused name; otherwise picks a RANDOM entry from the valid+unused entries of
    the curated on-theme pool (_FALLBACK_POOL), so repeated clicks for the same
    capability vary instead of always returning the same name (task #4969) —
    falling back further to a deterministic collision-safe extra-letter tail as
    a last resort. Either way the UI never again shows a gibberish blob like
    "I.A.A.G." (the old AGENTCOREUNIT-padding bug fixed in task #4960)."""
    words = capability_words(capability)
    initials = _normalize("".join(w[0] for w in words if w))
    title = f"{capability.replace('_', ' ').title()} Specialist"

    if initials and _valid_letters(initials) and initials not in avoid:
        return {
            "name": _dotify(initials),
            "expansion": capability_phrase(words),
            "title": title,
            "source": "fallback",
        }

    # ── capability-derived names, BEFORE the generic pool (#6237) ────────────
    # The initials branch above only fires when the initials themselves are 4-7
    # letters, so a TWO-WORD capability can never use it: edge_computing -> "EC"
    # (2 letters) fails _valid_letters and drops straight to the generic pool.
    # That is why a 30-entry pool was exhausted by one ~40-agent batch on
    # 2026-08-04 and ten unrelated specialists ended up as P.O.R.T.A.L.,
    # P.O.R.T.A.L.A. ... P.O.R.T.A.L.Y. — names carrying NO information about the
    # job (P.O.R.T.A.L.O. is the Edge Computing Specialist) and all sharing one
    # expansion. Deriving from the capability first keeps the name meaningful AND
    # leaves the shared pool for capabilities that genuinely cannot yield one.
    for letters, expansion in _capability_candidates(words):
        if _valid_letters(letters) and letters not in avoid:
            return {
                "name": _dotify(letters),
                "expansion": expansion,
                "title": title,
                "source": "fallback",
            }

    # Randomize among ALL valid, unused pool entries (not "first unused") so
    # repeated clicks for the same capability don't always return the same
    # name (task #4969 — this was the "always PORTAL" bug). The two safety
    # nets below stay deterministic (first-match) — they're a last resort.
    candidates = [
        (letters, expansion)
        for acronym, expansion in _FALLBACK_POOL
        if (letters := _normalize(acronym)) and _valid_letters(letters) and letters not in avoid
    ]
    if candidates:
        letters, expansion = random.choice(candidates)
        return {
            "name": _dotify(letters),
            "expansion": expansion,
            "title": title,
            "source": "fallback",
        }

    # Every capability-derived candidate AND every curated pool entry collided.
    # Disambiguate with one extra pronounceable letter — NEVER reintroduce the
    # old "AGENTCOREUNIT" padding blob.
    #
    # ⚠️ CAPABILITY-DERIVED BASES GO FIRST. Suffixing a POOL entry is what produced
    # P.O.R.T.A.L.A. / .B. / .C. ... — the suffix order here is literally
    # "AEIOUYBCD...", which is the exact sequence found in the roster. Those names
    # describe nothing, and worse, they inherited the pool entry's expansion, so
    # ten different specialists advertised one identity. A suffixed EDGE is still
    # about edge computing; a suffixed PORTAL is about nothing.
    cap_candidates = _capability_candidates(words)
    # (letters, expansion, from_capability) — the flag decides whether the
    # expansion already describes THIS agent or is a borrowed pool entry.
    suffix_bases = [(letters, expansion, True) for letters, expansion in cap_candidates]
    suffix_bases += [(_normalize(a), e, False) for a, e in _FALLBACK_POOL]
    for base_letters, expansion, from_capability in suffix_bases:
        base = base_letters[:6]
        for ch in "AEIOUYBCDFGHJKLMNPQRSTVWXZ":
            trial = base + ch
            if _valid_letters(trial) and trial not in avoid:
                return {
                    "name": _dotify(trial),
                    # Keep the expansion tied to THIS agent's capability where it
                    # came from one; only a pool-derived base gets " Extended".
                    "expansion": expansion if from_capability else f"{expansion} Extended",
                    "title": title,
                    "source": "fallback",
                }

    # Truly absurd corner (every pool entry AND every extension collided):
    # accept a possibly-duplicate but still valid, pronounceable name rather
    # than ever emit gibberish.
    acronym, expansion = _FALLBACK_POOL[0]
    return {"name": _dotify(acronym), "expansion": expansion, "title": title, "source": "fallback"}
