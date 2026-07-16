# Hire-Queue Agent Name Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Generate" button to the DHQ hiring-queue net-new approval form that proposes a unique, job-fit dotted-acronym agent name (+ expansion + title) via sovereign-local inference.

**Architecture:** New `agent_name_generator` service dispatches a `local_only` `creative` call through the DHQ dispatcher, validates format + dedupes against every existing agent name, retries ≤3, falls back deterministically. A thin admin route exposes it per pending candidate. The frontend adds a Generate button; the approve path persists `acronym`/`acronym_expansion`/`title`.

**Tech Stack:** Python 3 / Flask (blueprint routes), psycopg2 (`database.get_db_cursor`, RealDictCursor), `tools.department_hq.services.department_dispatcher.dispatch_json`, pytest + `unittest.mock`, vanilla JS in a Jinja template.

## Global Constraints

- **Sovereign only:** generation dispatches `dispatch_json(capability="creative", …, local_only=True)` — NEVER direct Ollama, NEVER cloud (ADR-013).
- **Naming house style:** dotted UPPERCASE acronym, **4–7 letters** (F.O.R.G.E., V.I.G.I.L., M.A.V.E.N., C.O.D.E.X.).
- **Uniqueness:** dedupe against `SELECT name FROM agents` across **ALL** shift states (incl. `decommissioned`); comparison is normalized (letters-only, so `V.E.R.I.F.Y.` == `VERIFY`). The existing `_create_new_hire` all-states guard stays as the final authority.
- **Fail-soft:** any dispatch/DB error must NOT block manual approval — the route returns HTTP 200 `{ok:false}` and the UI falls back to typing.
- **XSS-safe:** all API-derived text set via `textContent`, never `innerHTML`.
- **Tests DB:** pytest runs inside the `archie_platform` container against `archie_test` (conftest hard-overrides `DB_NAME`); run with `docker exec archie_platform python -m pytest …`.
- **Never touch the 6 real pending candidates** — live verification uses a throwaway candidate that is fully cleaned up.

---

### Task 1: `agent_name_generator` service + unit tests

**Files:**
- Create: `platform_v2/services/agent_name_generator.py`
- Test: `platform_v2/tests/test_agent_name_generator.py`

**Interfaces:**
- Produces: `suggest_name(capability: str, department: str | None = None, *, avoid_names: set[str] | None = None, max_attempts: int = 3) -> dict` returning `{"name","expansion","title","source"}` (`source` ∈ `{"llm","fallback"}`). Seams for mocking: `_existing_names() -> set[str]`, `_dispatch_name(capability, prompt) -> dict | None`. Helpers: `_normalize(str)->str`, `_dotify(str)->str`, `_valid_letters(str)->bool`.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_agent_name_generator.py
"""Unit tests for agent_name_generator (sovereign acronym name generator).

All DB + dispatch access goes through two seams (_existing_names,
_dispatch_name) which we patch — no real DB or dispatcher needed.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from services import agent_name_generator as ang  # noqa: E402


def test_normalize_strips_dots_and_uppercases():
    assert ang._normalize("v.e.r.i.f.y.") == "VERIFY"
    assert ang._normalize("F.O.R.G.E.") == "FORGE"


def test_dotify_formats_letters():
    assert ang._dotify("FORGE") == "F.O.R.G.E."
    assert ang._dotify("") == ""


def test_valid_letters_bounds():
    assert ang._valid_letters("FORGE")      # 5
    assert ang._valid_letters("QUILL")      # 5
    assert not ang._valid_letters("ABC")    # 3 too short
    assert not ang._valid_letters("ABCDEFGH")  # 8 too long


def test_suggest_name_accepts_valid_unique_llm_name():
    with patch.object(ang, "_existing_names", return_value={"FORGE", "VIGIL"}), patch.object(
        ang, "_dispatch_name",
        return_value={"name": "V.E.R.I.F.Y.", "expansion": "Validation Engine …", "title": "Fact Checker"},
    ):
        out = ang.suggest_name("fact_check")
    assert out["name"] == "V.E.R.I.F.Y."
    assert out["source"] == "llm"
    assert out["expansion"] and out["title"]


def test_suggest_name_rejects_duplicate_then_retries():
    # First dispatch returns an existing name; second returns a fresh one.
    calls = [
        {"name": "FORGE", "expansion": "x", "title": "y"},        # dup -> rejected
        {"name": "S.C.R.I.B.E.", "expansion": "Scribe", "title": "Writer"},
    ]
    with patch.object(ang, "_existing_names", return_value={"FORGE"}), patch.object(
        ang, "_dispatch_name", side_effect=calls
    ):
        out = ang.suggest_name("documentation")
    assert out["name"] == "S.C.R.I.B.E."
    assert out["source"] == "llm"


def test_suggest_name_rejects_malformed_and_falls_back():
    # Every dispatch is malformed/too-short -> deterministic fallback.
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", return_value={"name": "AB", "expansion": "", "title": ""}
    ):
        out = ang.suggest_name("security_audit", max_attempts=2)
    assert out["source"] == "fallback"
    assert ang._valid_letters(out["name"])
    assert out["name"].endswith(".")


def test_fallback_is_unique_against_avoid_set():
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", return_value=None
    ):
        out = ang.suggest_name("support", avoid_names={"SUPRT", "SUPRTX"}, max_attempts=1)
    assert out["source"] == "fallback"
    assert ang._normalize(out["name"]) not in {"SUPRT", "SUPRTX"}


def test_dispatch_exception_does_not_raise():
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", side_effect=RuntimeError("cold load")
    ):
        out = ang.suggest_name("general", max_attempts=1)
    assert out["source"] == "fallback"
    assert ang._valid_letters(out["name"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker exec archie_platform python -m pytest tests/test_agent_name_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.agent_name_generator'`.

- [ ] **Step 3: Write the implementation**

```python
# platform_v2/services/agent_name_generator.py
"""Sovereign-local acronym name generator for net-new agent hires.

Generates a dotted-uppercase acronym name (F.O.R.G.E. convention) recommended
for a capability, deduped against every existing agent name (all shift states).
All inference is local_only via the DHQ dispatcher (ADR-013) — no direct Ollama,
no cloud.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

_SYSTEM_PROMPT = (
    "You name AI agents for the A.R.C.H.I.E. platform. Every name is a short real "
    "or pronounceable English word, 4-7 letters, UPPERCASE and dot-separated "
    "(F.O.R.G.E., V.I.G.I.L., M.A.V.E.N.). Each letter begins a word describing the "
    "agent's role. Reply with STRICT JSON only, no prose."
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


def _dispatch_name(capability: str, prompt: str) -> Optional[dict]:
    """Sovereign-local creative dispatch. Mockable seam."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    return dispatch_json(
        capability="creative",
        prompt=prompt,
        module_id="hire_name_generator",
        system_prompt=_SYSTEM_PROMPT,
        local_only=True,
    )


def _build_prompt(capability: str, department: str, avoid: set[str]) -> str:
    role = capability.replace("_", " ")
    # Bound the in-prompt avoid-list; server-side dedupe is authoritative.
    avoid_sample = ", ".join(sorted(avoid)[:60]) if avoid else "(none)"
    return (
        f"Invent ONE name for an A.R.C.H.I.E. agent whose job is '{role}' in the "
        f"{department} department.\n"
        "Requirements:\n"
        "- A short real or pronounceable English word, 4 to 7 letters.\n"
        "- UPPERCASE, a dot after every letter: e.g. F.O.R.G.E., V.I.G.I.L., M.A.V.E.N.\n"
        "- Each letter begins a word describing the role (the acronym expansion).\n"
        f"- MUST NOT match any of these existing names: {avoid_sample}\n"
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
    ≤max_attempts retries (each collision fed back into the avoid-list) and a
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
        if isinstance(data, dict):
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
        cand = (letters[:6] + "X")
    return {
        "name": _dotify(cand),
        "expansion": " ".join(w.capitalize() for w in words) or "Agent Core Unit",
        "title": f"{capability.replace('_', ' ').title()} Specialist",
        "source": "fallback",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker exec archie_platform python -m pytest tests/test_agent_name_generator.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/agent_name_generator.py platform_v2/tests/test_agent_name_generator.py
git commit -m "feat(hiring): sovereign acronym name generator service"
```

---

### Task 2: `suggest-name` admin route + route test

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py` (add a route inside `register_approvals_routes`, after `approve_hire` ends at ~L616)
- Test: `platform_v2/tests/test_approvals_hire_routes.py` (add one test using the existing `approvals_client` + `_login_as_admin` fixtures)

**Interfaces:**
- Consumes: `agent_name_generator.suggest_name(capability)` (Task 1); `database.get_db_cursor`.
- Produces: `POST /tools/department-hq/api/approvals/hire/<int:hire_id>/suggest-name` → `{ok, name, expansion, title, source}` or fail-soft `{ok:false, error}` (HTTP 200).

- [ ] **Step 1: Write the failing test** (append to `test_approvals_hire_routes.py`)

```python
def test_suggest_name_returns_generated_name(approvals_client, monkeypatch):
    """POST suggest-name reads the candidate capability and returns a name."""
    import approvals_routes  # noqa: F401  (ensure module import path)
    from services import agent_name_generator

    # Stub the DB read (capability lookup) and the generator.
    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return {"capability": "fact_check"}

    class _CM:
        def __enter__(self): return (None, _Cur())
        def __exit__(self, *a): return False

    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _CM())
    monkeypatch.setattr(
        agent_name_generator, "suggest_name",
        lambda cap: {"name": "V.E.R.I.F.Y.", "expansion": "…", "title": "Fact Checker", "source": "llm"},
    )
    _login_as_admin(approvals_client)
    resp = approvals_client.post("/tools/department-hq/api/approvals/hire/123/suggest-name", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True and data["name"] == "V.E.R.I.F.Y."


def test_suggest_name_failsoft_on_generator_error(approvals_client, monkeypatch):
    from services import agent_name_generator

    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return {"capability": "fact_check"}

    class _CM:
        def __enter__(self): return (None, _Cur())
        def __exit__(self, *a): return False

    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _CM())
    monkeypatch.setattr(agent_name_generator, "suggest_name",
                        lambda cap: (_ for _ in ()).throw(RuntimeError("boom")))
    _login_as_admin(approvals_client)
    resp = approvals_client.post("/tools/department-hq/api/approvals/hire/123/suggest-name", json={})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False
```

Note: confirm the helper name `_login_as_admin` in this file; if it differs, use the file's actual admin-login helper. If `monkeypatch.setattr("database.get_db_cursor", …)` does not intercept the route's local `from database import get_db_cursor`, patch `approvals_routes.get_db_cursor` after the route imports it, or seed a real `hiring_candidates` row via the `db` fixture instead.

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec archie_platform python -m pytest tests/test_approvals_hire_routes.py -k suggest_name -v`
Expected: FAIL — route 404 (not registered yet).

- [ ] **Step 3: Add the route** (inside `register_approvals_routes`, immediately after the `approve_hire` function block, before `@bp.route(".../reject")`)

```python
    @bp.route("/api/approvals/hire/<int:hire_id>/suggest-name", methods=["POST"])
    @admin_required_decorator
    def suggest_hire_name(hire_id: int):
        """Generate a unique, job-fit acronym name for a net-new hire.

        Server reads the candidate's capability itself (nothing client-supplied
        to trust). Fail-soft: any error returns 200 {ok:false} so the UI can fall
        back to manual typing — never blocks approval.
        """
        from database import get_db_cursor
        from services import agent_name_generator

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            result = agent_name_generator.suggest_name(capability)
            return jsonify({"ok": True, **result}), 200
        except Exception as exc:
            logger.warning("suggest_hire_name(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec archie_platform python -m pytest tests/test_approvals_hire_routes.py -k suggest_name -v`
Expected: PASS (2 tests). If the DB-read patch doesn't intercept, apply the note from Step 1.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_hire_routes.py
git commit -m "feat(hiring): suggest-name route (sovereign, fail-soft)"
```

---

### Task 3: Persist acronym/expansion/title in `_create_new_hire`

**Files:**
- Modify: `platform_v2/services/hiring_service.py` (`_create_new_hire`, ~L203-272)
- Test: `platform_v2/tests/test_hiring_service.py` (add one test)

**Interfaces:**
- Consumes: `new_agent` dict now may carry `expansion`, `title` (from Task 4 payload). `display_name` already supported.
- Produces: agent row has `acronym`, `acronym_expansion`, `title` set when the generated fields are present. No behavior change on the manual path (fields absent).

- [ ] **Step 1: Verify the target columns exist** (one-time check, not a code change)

Run: `docker exec archie_database psql -U archie -d archie -c "\d agents" | grep -E 'acronym|title'`
Expected: rows `acronym`, `acronym_expansion`, `title`. If any is missing, STOP and reconcile with migration 158 before continuing (the UPDATE is try/except-guarded, but silent no-persist is not acceptable).

- [ ] **Step 2: Write the failing test** (append to `test_hiring_service.py`)

```python
def test_create_new_hire_persists_acronym_metadata():
    """When new_agent carries expansion/title, _create_new_hire UPDATEs the row."""
    import sys
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from unittest.mock import MagicMock, patch
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.return_value = None  # no name collision, then approve RETURNING

    # fetchone is called twice: name-collision (None) then approve RETURNING (a row).
    cur.fetchone.side_effect = [None, {"id": 1}]

    with patch.object(hiring_service, "_verify_model_available", return_value=(True, "ok")), patch(
        "services.agent_service.create_agent", return_value=4242
    ), patch("services.agent_service.add_skill"), patch(
        "services.agent_service.init_budget"
    ), patch("services.agent_service.log_creation_event"):
        out = hiring_service._create_new_hire(
            cur,
            hire_id=7,
            capability="fact_check",
            gap_reason="pool maxed",
            new_agent={
                "name": "V.E.R.I.F.Y.",
                "model": "qwen2.5:7b",
                "display_name": "V.E.R.I.F.Y.",
                "expansion": "Validation Engine …",
                "title": "Fact Checker",
            },
            decided_by_user_id=4,
            notes="",
        )
    assert out["ok"] is True and out["agent_id"] == 4242
    # Assert an UPDATE agents … acronym … was executed with our values.
    update_calls = [c for c in cur.execute.call_args_list if "UPDATE agents" in c.args[0]]
    assert update_calls, "expected an UPDATE agents … acronym set"
    sql, params = update_calls[0].args[0], update_calls[0].args[1]
    assert "acronym" in sql and "acronym_expansion" in sql and "title" in sql
    assert params[0] == "V.E.R.I.F.Y." and params[1] == "Validation Engine …"
    assert params[3] == 4242
```

- [ ] **Step 3: Run to verify it fails**

Run: `docker exec archie_platform python -m pytest tests/test_hiring_service.py -k acronym_metadata -v`
Expected: FAIL — no `UPDATE agents … acronym` call yet.

- [ ] **Step 4: Implement** — two edits in `_create_new_hire`.

Edit A — read the new fields (after the `display_name = …` block, ~L211):

```python
    display_name = (new_agent.get("display_name") or "").strip() or (
        f"{capability.replace('_', ' ').title()} Specialist"
    )
    expansion = (new_agent.get("expansion") or "").strip()
    title = (new_agent.get("title") or "").strip()
    department = _department_for_capability(capability)
```

Edit B — persist them right after the `log_creation_event` try/except block (after ~L266, before the `UPDATE hiring_candidates` at ~L273):

```python
        # Persist acronym metadata so the roster shows what the letters stand
        # for + a human role (F.O.R.G.E./M.A.V.E.N. convention). Best-effort:
        # a column/DB hiccup must not fail an otherwise-successful hire.
        if expansion or title:
            try:
                cur.execute(
                    "UPDATE agents SET acronym = %s, acronym_expansion = %s, "
                    "title = %s WHERE id = %s",
                    (name, expansion or None, title or None, new_agent_id),
                )
            except Exception as _ue:
                logger.warning("acronym-metadata update failed for #%s: %s", new_agent_id, _ue)
```

- [ ] **Step 5: Run to verify it passes**

Run: `docker exec archie_platform python -m pytest tests/test_hiring_service.py -k acronym_metadata -v`
Expected: PASS. Then run the whole hiring file to confirm no regression: `docker exec archie_platform python -m pytest tests/test_hiring_service.py -v`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "feat(hiring): persist acronym/expansion/title for net-new hires"
```

---

### Task 4: Frontend — Generate button + hint + payload

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` (net-new form ~L1421-1429; `_dhqApproveHire` body ~L1721)

**Interfaces:**
- Consumes: `POST .../hire/<id>/suggest-name` (Task 2); `a.id` (source-prefixed, e.g. `hiring:<id>`); closure vars `nameInput`, `hireState`, `hint`.
- Produces: approve payload `{new_agent:{name,model,display_name,expansion,title}}`.

- [ ] **Step 1: Add the Generate button + wire it** — replace the block that starts `var hint = document.createElement('div');` and ends `return;` (net-new branch, ~L1421-1429) with:

```javascript
                var genBtn = document.createElement('button');
                genBtn.type = 'button';
                genBtn.textContent = '✨ Generate';
                genBtn.style.cssText = 'background:rgba(192,132,252,0.15);border:1px solid rgba(192,132,252,0.5);color:#e9d5ff;font-size:0.75rem;padding:6px 10px;border-radius:3px;cursor:pointer;white-space:nowrap';

                var nameRow = document.createElement('div');
                nameRow.style.cssText = 'display:flex;gap:6px;align-items:stretch';
                nameInput.style.flex = '1';
                nameRow.appendChild(nameInput);
                nameRow.appendChild(genBtn);

                var hint = document.createElement('div');
                hint.style.cssText = 'color:#94a3b8;font-size:0.72rem';
                hint.textContent = (cand.note || 'Net-new agent') + (cap ? ' · skill: ' + cap : '');

                genBtn.onclick = async function() {
                    var hid = String(a.id).split(':')[1] || '';
                    if (!hid) { hint.textContent = 'Cannot generate (missing id).'; return; }
                    genBtn.disabled = true;
                    var _prev = genBtn.textContent;
                    genBtn.textContent = 'Generating…';
                    hint.textContent = 'Asking the fleet for a name…';
                    try {
                        var gr = await fetch('/tools/department-hq/api/approvals/hire/' + hid + '/suggest-name', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: '{}'
                        });
                        var gd = await gr.json();
                        if (gd && gd.ok && gd.name) {
                            nameInput.value = gd.name;
                            hireState.newAgent.name = gd.name;
                            hireState.newAgent.display_name = gd.name;
                            hireState.newAgent.expansion = gd.expansion || '';
                            hireState.newAgent.title = gd.title || '';
                            hint.textContent = ((gd.expansion || '') + (gd.title ? ' · ' + gd.title : '')) || 'Generated.';
                        } else {
                            hint.textContent = 'Could not generate — type a name or try again.';
                        }
                    } catch (e) {
                        hint.textContent = 'Could not generate — type a name or try again.';
                    } finally {
                        genBtn.disabled = false;
                        genBtn.textContent = _prev;
                    }
                };

                form.appendChild(nameRow);
                form.appendChild(modelSel);
                form.appendChild(hint);
                shortlistBox.appendChild(form);
                return;
```

- [ ] **Step 2: Extend the approve payload** — in `_dhqApproveHire` (~L1721) replace:

```javascript
        body = { new_agent: { name: na.name, model: na.model }, notes: '' };
```

with:

```javascript
        body = { new_agent: { name: na.name, model: na.model, display_name: na.display_name || na.name, expansion: na.expansion || '', title: na.title || '' }, notes: '' };
```

- [ ] **Step 3: Deploy the template + smoke-import**

Run: `docker restart archie_platform` then wait for healthy:
`docker exec archie_platform python -c "import approvals_routes; import services.agent_name_generator; print('import ok')"`
Expected: `import ok` (the template is volume-mounted; the Python restart picks up Tasks 1-3).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(hiring): Generate button on net-new hire form + rich payload"
```

---

### Task 5: Live verification tick (status ≠ artifact) + throwaway end-to-end

**Files:** none (verification only). This is the mandatory live proof — a passing unit suite is not a shipped feature (KB #270002 / #250232).

- [ ] **Step 1: Full suite green**

Run: `docker exec archie_platform python -m pytest tests/test_agent_name_generator.py tests/test_approvals_hire_routes.py tests/test_hiring_service.py -v`
Expected: all PASS.

- [ ] **Step 2: Live generation tick against the running platform** — create a THROWAWAY pending candidate, POST suggest-name, assert unique + well-formed. Use the platform's own DB + an in-container script (NOT curl — inline HTTP is blocked; call the service directly):

```bash
docker exec archie_platform python -c "
import sys; sys.path.insert(0,'/app')
from services import agent_name_generator as ang
out = ang.suggest_name('fact_check')
print('RESULT', out)
assert out['name'].endswith('.') and 4 <= len(ang._normalize(out['name'])) <= 7, out
assert ang._normalize(out['name']) not in ang._existing_names(), 'collision!'
print('OK unique + well-formed; source=', out['source'])
"
```
Expected: `OK unique + well-formed`. Record whether `source` is `llm` (fleet warm) or `fallback` (cold/queued — still valid).

- [ ] **Step 3: Throwaway end-to-end approve** (proves the persist path; mirrors PR #2289's discipline). Seed a throwaway `hiring_candidates` row (net_new shortlist), call `hiring_service.approve_candidate(..., new_agent={name,model,expansion,title})`, assert the agent is created + skill dispatchable + budget seeded + acronym columns persisted, then **delete the throwaway agent + candidate**. Write the script to `$CLAUDE_JOB_DIR/tmp/verify_hire_namegen.py` and run it in-container. Confirm at the end: `SELECT count(*) FROM hiring_candidates WHERE status='pending'` is unchanged (the 6 real pending untouched).

- [ ] **Step 4: Browser check** (P.R.O.B.E./Playwright or manual): open `/tools/department-hq` → Approvals → a net-new candidate card shows the **Generate** button; click → name field fills + hint shows expansion·title; regenerate gives a different name; 0 console errors. Screenshot before/after.

- [ ] **Step 5: Commit any doc/notes; do NOT commit throwaway artifacts.**

---

## Self-Review

**Spec coverage:** §4.1 generator → Task 1. §4.2 route → Task 2. §4.4 persist acronym/expansion/title → Task 3. §4.3 frontend Generate + payload → Task 4. §5 prompt → Task 1 `_build_prompt`/`_SYSTEM_PROMPT`. §6 validation/dedupe/fallback → Task 1. §8 error handling → Tasks 1 (fallback) + 2 (fail-soft). §9 testing → Tasks 1-3 unit + Task 5 live tick + browser. §10 sovereign compliance → Global Constraints + Task 1 `_dispatch_name(local_only=True)`. All spec sections have a task. ✅

**Placeholder scan:** No TBD/TODO; every code step has complete code. The two soft spots are explicitly bounded: Task 2 Step 1/4 gives a concrete fallback if `monkeypatch` doesn't intercept the local import; Task 3 Step 1 hard-gates on column existence. ✅

**Type consistency:** `suggest_name(capability, department=None, *, avoid_names, max_attempts)` and `{name,expansion,title,source}` are identical across Tasks 1→2→5. `_normalize`/`_dotify`/`_valid_letters`/`_existing_names`/`_dispatch_name` names match between impl and tests. Route path `/api/approvals/hire/<id>/suggest-name` identical in Tasks 2 and 4. Payload keys `name/model/display_name/expansion/title` identical in Tasks 3 and 4. ✅

## Execution Handoff

Terminal state per writing-plans. Two execution options — see the message after this file is saved.
