# Complete Agent Hire (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the net-new agent hire flow produce a *complete, directory-aligned* agent — meaningful acronym + expansion, title, bio, personality, a rich ≥400-char system prompt with the expansion woven in, and a representative sci-fi portrait.

**Architecture:** A new sovereign-local `agent_identity_builder.build_identity()` runs ONE creative dispatch (M.U.S.E., `local_only`) for the creative parts, then a deterministic template assembles the system prompt (guaranteed length/shape). The suggest-name route returns the full identity; the Generate button previews it; approval persists every field via `agent_service` (single-writer) and queues a portrait via `agent_service.add_portrait` (async, fail-open). Server-side `build_identity` fallback guarantees completeness even when a user types a name manually.

**Tech Stack:** Python 3 (Flask app in `archie_platform` container), pytest (`platform_v2/tests/`), Postgres `agents` table, DHQ dispatcher (ADR-013), Media Studio portrait pipeline.

## Global Constraints

- **Sovereign-local only.** All inference via `tools.department_hq.services.department_dispatcher.dispatch(..., local_only=True)`. NEVER direct Ollama, NEVER cloud (ADR-013).
- **Single-writer for `agents`.** All agent-row writes go through `services.agent_service` (`create_agent`, `update_agent`, `add_skill`, `init_budget`, `add_portrait`). NEVER raw SQL on `agents`.
- **Fail-open.** A name/identity/portrait failure must NEVER block a hire or hang the interactive button (existing 20s wall-clock bound on the dispatch).
- **System prompt floor:** `MIN_SYSTEM_PROMPT_CHARS = 400` — the assembled prompt must be ≥400 chars even on the fallback path.
- **Scope:** `worker_type='ai'` acronym agents only.
- **Deploy:** platform_v2 Python + template changes are volume-mounted → `docker compose restart archie_platform` to pick up. Run pytest inside the container: `docker exec archie_platform python3 -m pytest <path> -v`.
- **Tests dir:** `platform_v2/tests/` → in-container path `/app/tests/`.

---

## File Structure

- **Create:** `platform_v2/services/agent_identity_builder.py` — the identity builder (one responsibility: produce a complete identity dict).
- **Create:** `platform_v2/tests/test_agent_identity_builder.py` — builder unit tests.
- **Modify:** `platform_v2/tools/department_hq/approvals_routes.py` (`suggest_hire_name`, ~L618) — return the full identity.
- **Modify:** `platform_v2/services/hiring_service.py` (`_create_new_hire`, L188–316) — persist all identity fields + queue portrait, with server-side completeness fallback.
- **Modify:** `platform_v2/tools/department_hq/templates/department_hq.html` (Generate handler ~L1436) — stash the extra fields, show an identity preview, send them on approve.
- **Modify tests:** `platform_v2/tests/test_hiring_service.py` (or `test_hiring_acronym_persist.py`) — assert full persistence + portrait enqueue.

Reuses (import, do NOT duplicate) from `services/agent_name_generator.py`: `_normalize`, `_dotify`, `_valid_letters`, `_parse_json`, `_department_for_capability`, `_existing_names`, `_fallback_name`, `MAX_ATTEMPTS`, `_DISPATCH_TIMEOUT_S`.

---

### Task 1: Agent Identity Builder

**Files:**
- Create: `platform_v2/services/agent_identity_builder.py`
- Test: `platform_v2/tests/test_agent_identity_builder.py`

**Interfaces:**
- Consumes: `agent_name_generator` helpers (above); `agent_service.DEPARTMENT_FLOOR_MAP`; `department_dispatcher.dispatch`.
- Produces: `build_identity(capability, department=None, *, existing_name=None, avoid_names=None, max_attempts=MAX_ATTEMPTS) -> dict` with keys `name, expansion, title, bio, personality, system_prompt, portrait_prompt, source`. Also `MIN_SYSTEM_PROMPT_CHARS = 400`.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_agent_identity_builder.py
import re
from unittest.mock import patch
from services import agent_identity_builder as aib


def _fake_parts(name="V.E.R.I.F.Y."):
    return {
        "name": name, "expansion": "Validation Engine Reviewing Information For Yield",
        "title": "Fact Checker", "bio": "Two sentence backstory. Second sentence.",
        "personality": "Skeptical, rigorous, calm.", "voice": "precise and neutral",
        "portrait_hint": "a vigilant analyst with a data visor",
    }


def test_build_identity_llm_full_package():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts()), \
         patch.object(aib, "_existing_names", return_value=set()):
        out = aib.build_identity("fact_check", department="News & Media")
    assert out["source"] == "llm"
    assert out["name"] == "V.E.R.I.F.Y."
    assert out["expansion"]
    assert out["title"]
    assert out["bio"]
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert "Validation Engine" in out["system_prompt"]  # expansion woven in
    assert out["portrait_prompt"]


def test_build_identity_fallback_is_still_complete():
    # dispatch times out -> deterministic fallback, STILL a full identity
    with patch.object(aib, "_dispatch_identity", return_value=None), \
         patch.object(aib, "_existing_names", return_value=set()):
        out = aib.build_identity("classify", department="Analytics & Intelligence")
    assert out["source"] == "fallback"
    assert re.match(r"^([A-Z]\.){4,7}$", out["name"])
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert out["portrait_prompt"]


def test_build_identity_existing_name_is_kept():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts(name="X.X.X.")), \
         patch.object(aib, "_existing_names", return_value={"FORGE"}):
        out = aib.build_identity("code", department="Engineering & Technology",
                                 existing_name="P.R.O.B.E.")
    assert out["name"] == "P.R.O.B.E."          # kept, not the LLM's name
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS


def test_build_identity_dedupes_against_existing():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts(name="F.O.R.G.E.")), \
         patch.object(aib, "_existing_names", return_value={"FORGE"}):
        out = aib.build_identity("code", department="Engineering & Technology", max_attempts=1)
    # collided name rejected -> falls back to a unique deterministic name
    assert out["name"] != "F.O.R.G.E."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_identity_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.agent_identity_builder'`

- [ ] **Step 3: Write the implementation**

```python
# platform_v2/services/agent_identity_builder.py
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


def _build_identity_prompt(capability: str, department: str, avoid: set[str],
                           existing_name: Optional[str]) -> str:
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


def _assemble_system_prompt(*, name: str, expansion: str, title: str, role: str,
                            department: str, floor: str, personality: str,
                            voice: str) -> str:
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


def _build_portrait_prompt(*, name: str, expansion: str, title: str,
                           department: str, hint: str = "") -> str:
    base = hint.strip() or f"a {title} specializing in {expansion}"
    return (
        f"Sci-fi character portrait of {name}, {base}. Futuristic A.R.C.H.I.E. platform "
        f"crew member in the {department} department. Cinematic lighting, clean sci-fi "
        f"uniform, confident expression, head-and-shoulders composition, high detail, "
        f"LCARS-inspired color palette."
    )


def _fallback_identity(capability: str, department: str, floor: str,
                       existing_name: Optional[str], avoid: set[str]) -> dict[str, Any]:
    role = capability.replace("_", " ")
    if existing_name:
        letters = _normalize(existing_name)
        name = existing_name if existing_name.endswith(".") else _dotify(letters)
        words = re.sub(r"[^a-z ]", " ", capability.lower().replace("_", " ")).split()
        expansion = " ".join(w.capitalize() for w in words) or "Agent Core Unit"
        title = f"{role.title()} Specialist"
    else:
        fb = _fallback_name(capability, avoid)
        name, expansion, title = fb["name"], fb["expansion"], fb["title"]
    sysp = _assemble_system_prompt(name=name, expansion=expansion, title=title,
                                   role=role, department=department, floor=floor,
                                   personality="", voice="")
    return {
        "name": name,
        "expansion": expansion,
        "title": title,
        "bio": f"{name} serves the {department} department, owning {role} for the "
               f"A.R.C.H.I.E. platform.",
        "personality": "",
        "system_prompt": sysp,
        "portrait_prompt": _build_portrait_prompt(name=name, expansion=expansion,
                                                  title=title, department=department),
        "source": "fallback",
    }


def build_identity(capability: str, department: Optional[str] = None, *,
                   existing_name: Optional[str] = None,
                   avoid_names: Optional[set[str]] = None,
                   max_attempts: int = MAX_ATTEMPTS) -> dict[str, Any]:
    """Return a COMPLETE identity dict (see module docstring). Sovereign-local,
    validated, with a deterministic complete fallback."""
    capability = (capability or "general").strip() or "general"
    department = department or _department_for_capability(capability)
    floor = _floor_for_department(department)
    role = capability.replace("_", " ")
    avoid = set(avoid_names or ())
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
        expansion = str(data.get("expansion") or "").strip()
        title = str(data.get("title") or "").strip() or f"{role.title()} Specialist"
        if name_ok and expansion:
            sysp = _assemble_system_prompt(name=name, expansion=expansion, title=title,
                                           role=role, department=department, floor=floor,
                                           personality=str(data.get("personality") or ""),
                                           voice=str(data.get("voice") or ""))
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
                        name=name, expansion=expansion, title=title,
                        department=department, hint=str(data.get("portrait_hint") or "")),
                    "source": "llm",
                }
        if letters and not existing_name:
            avoid.add(letters)
    return _fallback_identity(capability, department, floor, existing_name, avoid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_identity_builder.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/agent_identity_builder.py platform_v2/tests/test_agent_identity_builder.py
git commit -m "feat(agents): sovereign-local complete-identity builder (Phase 1 core)"
```

---

### Task 2: suggest-name route returns the full identity

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py` (`suggest_hire_name`, ~L618–642)
- Test: `platform_v2/tests/test_approvals_hire_routes.py` (add one test)

**Interfaces:**
- Consumes: `agent_identity_builder.build_identity(capability)`.
- Produces: `POST /api/approvals/hire/<id>/suggest-name` → `{ok, name, expansion, title, bio, personality, system_prompt, portrait_prompt, source}` (superset of the old `{ok,name,expansion,title,source}` — nothing breaks).

- [ ] **Step 1: Write the failing test**

```python
# add to platform_v2/tests/test_approvals_hire_routes.py
def test_suggest_name_returns_full_identity(client, monkeypatch):
    from services import agent_identity_builder
    monkeypatch.setattr(agent_identity_builder, "build_identity", lambda cap, **k: {
        "name": "V.E.R.I.F.Y.", "expansion": "Validation Engine ...", "title": "Fact Checker",
        "bio": "b", "personality": "p", "system_prompt": "x" * 500,
        "portrait_prompt": "sci-fi ...", "source": "llm"})
    # ... existing harness inserts a pending hire with a capability; call the route ...
    resp = client.post("/api/approvals/hire/<HID>/suggest-name")
    data = resp.get_json()
    assert data["ok"] and data["bio"] and data["system_prompt"] and data["portrait_prompt"]
```

> Match the existing fixtures/harness style in `test_approvals_hire_routes.py` (client fixture, how it seeds a `hiring_candidates` row + admin session). Replace `<HID>` with the seeded id.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_approvals_hire_routes.py::test_suggest_name_returns_full_identity -v`
Expected: FAIL (route still returns only name/expansion/title from `agent_name_generator`).

- [ ] **Step 3: Modify the route**

In `approvals_routes.py`, inside `suggest_hire_name`, change the import + call:

```python
        from database import get_db_cursor
        from services import agent_identity_builder

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            result = agent_identity_builder.build_identity(capability)
            return jsonify({"ok": True, **result}), 200
        except Exception as exc:
            logger.warning("suggest_hire_name(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_approvals_hire_routes.py -v`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_hire_routes.py
git commit -m "feat(agents): suggest-name route returns the full identity package"
```

---

### Task 3: Persist the complete identity + queue a portrait on approve

**Files:**
- Modify: `platform_v2/services/hiring_service.py` (`_create_new_hire`, L188–316)
- Test: `platform_v2/tests/test_hiring_service.py` (add tests)

**Interfaces:**
- Consumes: `new_agent` dict may now carry `system_prompt, bio, personality, portrait_prompt` (from the reviewed Generate result); `agent_identity_builder.build_identity`; `agent_service.update_agent`, `agent_service.add_portrait`.
- Produces: a fully-populated `agents` row (rich `system_prompt`, `title`, `bio`, `personality_prompt`, `acronym`, `acronym_expansion`, `portrait_prompt`) + one queued `agent_portraits` row.

- [ ] **Step 1: Write the failing tests**

```python
# add to platform_v2/tests/test_hiring_service.py
def test_create_new_hire_persists_complete_identity(monkeypatch):
    """Approving a net-new hire with no rich fields still yields a complete agent."""
    from services import hiring_service, agent_service, agent_identity_builder
    calls = {}
    monkeypatch.setattr(agent_identity_builder, "build_identity", lambda cap, **k: {
        "name": k.get("existing_name") or "N.O.V.A.", "expansion": "New Operations Virtual Agent",
        "title": "Ops Analyst", "bio": "A backstory.", "personality": "calm",
        "system_prompt": "S" * 500, "portrait_prompt": "sci-fi portrait", "source": "fallback"})
    monkeypatch.setattr(agent_service, "create_agent", lambda **kw: (calls.update(create=kw) or 9991))
    monkeypatch.setattr(agent_service, "add_skill", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "init_budget", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "log_creation_event", lambda **k: None)
    monkeypatch.setattr(agent_service, "update_agent", lambda aid, **f: calls.setdefault("update", f))
    monkeypatch.setattr(agent_service, "add_portrait", lambda aid, prompt, **k: calls.setdefault("portrait", (aid, prompt)))
    monkeypatch.setattr(hiring_service, "_verify_model_available", lambda m: (True, "ok"))
    # cur stub: name-collision SELECT returns None; the approve UPDATE returns a row
    cur = _FakeCursor(collision=None, approve_row={"id": 1})
    res = hiring_service._create_new_hire(cur, hire_id=1, capability="analyze",
        gap_reason="gap", new_agent={"name": "N.O.V.A.", "model": "qwen2.5:7b"},
        decided_by_user_id=4, notes="")
    assert res["ok"]
    assert len(calls["create"]["system_prompt"]) >= 400          # rich prompt, not the 90-char stub
    assert calls["update"]["bio"] and calls["update"]["personality_prompt"]
    assert calls["update"]["acronym_expansion"] and calls["update"]["title"]
    assert calls["update"]["portrait_prompt"]
    assert calls["portrait"][0] == 9991                          # portrait queued for the new agent
```

> Reuse/extend the existing `_FakeCursor` (or fixture) pattern already in `test_hiring_service.py`; if none exists, add a minimal cursor stub whose `execute` records SQL and whose `fetchone` returns `None` for the collision check and `{"id":1}` for the approve UPDATE.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_hiring_service.py::test_create_new_hire_persists_complete_identity -v`
Expected: FAIL (current code writes a 90-char prompt, no bio/personality/portrait).

- [ ] **Step 3: Modify `_create_new_hire`**

Replace the identity-building portion. After the name-collision guard and `from services import agent_service`, build the authoritative identity, then create + enrich + portrait:

```python
    from services import agent_service, agent_identity_builder

    # Authoritative COMPLETE identity. Trust the reviewed Generate result when it
    # carries a rich prompt; otherwise (manual name / no Generate) build it
    # server-side so every hire is complete. existing_name keeps the reviewed name.
    ident = {
        "name": name,
        "expansion": expansion,
        "title": title,
        "bio": (new_agent.get("bio") or "").strip(),
        "personality": (new_agent.get("personality") or "").strip(),
        "system_prompt": (new_agent.get("system_prompt") or "").strip(),
        "portrait_prompt": (new_agent.get("portrait_prompt") or "").strip(),
    }
    if len(ident["system_prompt"]) < agent_identity_builder.MIN_SYSTEM_PROMPT_CHARS:
        try:
            built = agent_identity_builder.build_identity(capability, department=department,
                                                          existing_name=name)
            for k in ("expansion", "title", "bio", "personality", "system_prompt", "portrait_prompt"):
                if not ident.get(k):
                    ident[k] = built.get(k) or ""
            if len(ident["system_prompt"]) < agent_identity_builder.MIN_SYSTEM_PROMPT_CHARS:
                ident["system_prompt"] = built["system_prompt"]
        except Exception as _be:
            logger.warning("identity build fallback failed for %s: %s", name, _be)

    try:
        new_agent_id = agent_service.create_agent(
            name=name,
            display_name=(display_name or name),
            department=department,
            model=model,
            shift_state="active",
            worker_type="internal",
            tier=3,
            system_prompt=ident["system_prompt"]
            or f"You are {name}, a specialist in {capability} in the {department} department.",
        )
        agent_service.add_skill(new_agent_id, capability, level=3, category=capability)
        agent_service.init_budget(new_agent_id)
        try:
            agent_service.log_creation_event(
                child_agent_id=new_agent_id,
                reason=f"Hired via DHQ queue for '{capability}': {gap_reason}",
                source="hiring_queue",
                capabilities=[capability],
                department=department,
            )
        except Exception as _le:
            logger.warning("log_creation_event failed for #%s: %s", new_agent_id, _le)
    except ValueError as ve:
        return {"ok": False, "reason": "create_rejected", "agent_id": None, "message": str(ve)}
    except Exception as e:
        logger.exception("net-new create_agent failed (hire_id=%s)", hire_id)
        return {"ok": False, "reason": "create_failed", "agent_id": None, "message": str(e)}

    # Enrich the row with the full identity (single-writer; best-effort).
    try:
        agent_service.update_agent(
            new_agent_id,
            acronym=name,
            acronym_expansion=ident["expansion"] or None,
            title=ident["title"] or None,
            bio=ident["bio"] or None,
            personality_prompt=ident["personality"] or None,
            portrait_prompt=ident["portrait_prompt"] or None,
        )
    except Exception as _ue:
        logger.warning("identity enrich failed for #%s: %s", new_agent_id, _ue)

    # Queue a representative sci-fi portrait (async, fail-open — never blocks the hire).
    if ident["portrait_prompt"]:
        try:
            agent_service.add_portrait(new_agent_id, ident["portrait_prompt"], style="sci-fi")
        except Exception as _pe:
            logger.warning("portrait enqueue failed for #%s: %s", new_agent_id, _pe)
```

Delete the old generic-`system_prompt` `create_agent` block and the old `if expansion or title:` acronym-only `update_agent` block (replaced above).

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_hiring_service.py /app/tests/test_hiring_acronym_persist.py -v`
Expected: PASS (new test + existing acronym-persist test still green — `acronym`/`acronym_expansion`/`title` still set).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "feat(agents): net-new hire persists complete identity + queues portrait"
```

---

### Task 4: Frontend — preview the identity + send it on approve

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` (Generate handler ~L1436–1469; the approve payload builder — find where `new_agent:{name,model,...}` is assembled for the approve POST)

**Interfaces:**
- Consumes: the suggest-name response superset (`bio, personality, system_prompt, portrait_prompt`).
- Produces: `hireState.newAgent` carrying the full identity; an on-card identity preview; the approve POST body includes the identity fields.

- [ ] **Step 1: Extend the Generate success handler** — after `nameInput.value = gd.name;` stash the rich fields and render a preview:

```javascript
                        if (gd && gd.ok && gd.name) {
                            nameInput.value = gd.name;
                            hireState.newAgent.name = gd.name;
                            hireState.newAgent.display_name = gd.name;
                            hireState.newAgent.expansion = gd.expansion || '';
                            hireState.newAgent.title = gd.title || '';
                            hireState.newAgent.bio = gd.bio || '';
                            hireState.newAgent.personality = gd.personality || '';
                            hireState.newAgent.system_prompt = gd.system_prompt || '';
                            hireState.newAgent.portrait_prompt = gd.portrait_prompt || '';
                            var _meta = ((gd.expansion || '') + (gd.title ? ' · ' + gd.title : '')) || 'Generated.';
                            if (gd.bio) _meta += ' — ' + gd.bio;
                            hint.textContent = gd.source === 'fallback'
                                ? _meta + ' · ⚠ fleet warming — deterministic; click Generate again for an AI identity.'
                                : _meta;
                        }
```

- [ ] **Step 2: Ensure the approve payload includes the identity.** Find the net-new approve call (searches: `new_agent` in the approve POST body / `approveHire` / `/approve`). Make the `new_agent` object spread `hireState.newAgent` so `bio/personality/system_prompt/portrait_prompt/expansion/title` are sent, e.g.:

```javascript
        body: JSON.stringify({ new_agent: hireState.newAgent })
```

(If it currently sends `{name, model}` explicitly, replace with the full `hireState.newAgent`.)

- [ ] **Step 3: Syntax check the changed script block**

Run:
```bash
cd /mnt/archie_brain/platform_v2/tools/department_hq && f=templates/department_hq.html
line=$(grep -n "_dhqApprovalsBusyNow" "$f" | head -1 | cut -d: -f1)
start=$(awk 'NR<='"$line"' && /<script/{n=NR} END{print n}' "$f"); end=$(awk 'NR>='"$line"' && /<\/script>/{print NR; exit}' "$f")
sed -n "$((start+1)),$((end-1))p" "$f" > /tmp/dhq.js && node --check /tmp/dhq.js && echo OK
```
Expected: `OK`

- [ ] **Step 4: Deploy + browser-verify** (see Task 5).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(agents): hire card previews the generated identity and sends it on approve"
```

---

### Task 5: Deploy + live end-to-end verification

- [ ] **Step 1: Deploy** — `docker compose restart archie_platform`, wait `healthy`.
- [ ] **Step 2: Browser (claude@)** — DHQ → Approvals. Click **Generate** on a net-new card; confirm the preview shows expansion · title · bio and no console errors.
- [ ] **Step 3: Approve a THROWAWAY hire** (pick one net-new candidate you will immediately clean up, or seed a disposable `hiring_candidates` row). After approve, query the new agent:

```bash
docker exec archie_database psql -U archie -d archie -x -c \
 "SELECT id,name,title,LENGTH(system_prompt) sp, acronym_expansion IS NOT NULL exp, bio IS NOT NULL bio, personality_prompt IS NOT NULL pers, portrait_prompt IS NOT NULL pp FROM agents ORDER BY id DESC LIMIT 1;"
docker exec archie_database psql -U archie -d archie -c \
 "SELECT agent_id, generation_status, style FROM agent_portraits ORDER BY id DESC LIMIT 1;"
```
Expected: `sp >= 400`, `exp/bio/pers/pp = t`, one `agent_portraits` row (`queued`/`generating`).

- [ ] **Step 4: Clean up the throwaway** if it isn't a real hire (decommission the agent + delete the test portrait row) so the 6 real pending candidates stay for Kytran.
- [ ] **Step 5:** `/commit-push-pr` → F.O.R.G.E. review → `/merge-pr`.

---

## Self-Review

- **Spec coverage:** builder (Task 1) ✓; suggest-identity route (Task 2) ✓; frontend preview (Task 4) ✓; complete creation + portrait on approve (Task 3) ✓; ≥400 floor incl. fallback (Task 1 tests) ✓; sovereign-local (Global Constraints + `local_only=True`) ✓; single-writer (`update_agent`/`add_portrait`) ✓. Backfill (Phase 2) + lifecycle (Phase 3) intentionally out of scope.
- **Placeholders:** none — every code step is complete except the two test-harness `<HID>`/`_FakeCursor` seams, which explicitly say "match the existing fixture style" (the harness already exists in those test files).
- **Type consistency:** `build_identity(...) -> dict` keys (`name, expansion, title, bio, personality, system_prompt, portrait_prompt, source`) are used identically in Tasks 2–4; `MIN_SYSTEM_PROMPT_CHARS` referenced consistently; `agent_service.update_agent(**fields)` + `add_portrait(agent_id, prompt, style=)` match the real signatures verified in the codebase.
