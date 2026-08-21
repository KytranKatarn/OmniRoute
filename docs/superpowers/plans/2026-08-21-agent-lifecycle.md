# Agent Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator create an agent (AI or human-like), edit its profile and skills, regenerate its portrait, and decommission it safely — from the Department HQ Roster.

**Architecture:** One new service orchestrator composes creation server-side by calling existing service functions, returning per-side-effect results. Decommission is new code (no `deactivate_agent` exists) and is gated by a precheck that refuses to silently manufacture a capability gap. Profile editing and portrait regeneration are UI wiring against endpoints that ALREADY EXIST — no parallel CRUD surface.

**Tech Stack:** Python 3 / Flask blueprints, psycopg2 (RealDictCursor), `unittest` (tests under `platform_v2/tests/`), vanilla ES5-style browser JS (globals, no build step).

**Spec:** `docs/superpowers/specs/2026-08-20-agent-lifecycle-design.md` (AMENDED 2026-08-21 — read §7.1/§7.2/§7.3, they replace the original endpoint table)

## Global Constraints

- **All agent mutations go through `services/agent_service.py`.** No direct SQL on the `agents` table. Enforced by `scripts/check_agent_single_writer.py` (pre-commit).
- **NEVER rebuild what §7.2 lists as existing.** `PATCH /api/agent/<id>` (which also writes `governance_audit_log`), `GET`/`POST /api/agent/<id>/skills`, and `POST /api/agents/<id>/generate-portrait` all exist. Call them; do not add parallel endpoints.
- **Create composes side effects SERVER-SIDE** by importing service functions — never by issuing internal HTTP calls to our own routes, and never by having the browser fire follow-up requests (§7.3).
- **Every side effect reports its own outcome.** A create where the agent row succeeded and the mailbox failed must say exactly that — never a bare "Agent created".
- **Decommission is soft only.** `shift_state='decommissioned'`. Never `DELETE` — agents are FK-referenced by `node_agents`, `email_mailboxes`, `task_execution_log`, `work_notes`, `agent_skills`, `agent_budgets`.
- **Agent names are dotted.** `ILIKE '%HAVEN%'` does not match `H.A.V.E.N.` — use `replace(name,'.','')`. Caused bug #5272.
- **`agent_skills` columns are `skill_name`, `skill_category`, `proficiency_level`** — not `category`/`level`.
- **`get_db_cursor()` returns RealDictCursor.** Use `row['col']`; never int-index; never pass `dict_cursor=True` (no such kwarg).
- **Run Python tests IN THE CONTAINER:** `docker exec archie_platform python3 -m pytest /app/tests/<file> -v`. The host cannot reach the DB. `platform_v2` is bind-mounted to `/app`, so edits are live — but **restart `archie_platform` after any .py change**, because running gunicorn workers already imported the old module.
- **Branch:** `feat/agent-lifecycle` (already created off merged main). Never commit to `main`.
- **Live browser drive is the acceptance gate**, not a green suite (KB #292215). Log in as `claude`, never `kytran`.

---

## File Structure

| file | responsibility |
|---|---|
| `platform_v2/services/agent_lifecycle.py` | CREATE — the new service: `decommission_precheck`, `decommission_agent`, `create_agent_full`. All new business logic lives here, not in routes |
| `platform_v2/tools/department_hq/agent_detail_routes.py` | MODIFY — add the two decommission endpoints beside the existing agent endpoints |
| `platform_v2/tools/department_hq/roster_routes.py` | MODIFY — add `POST /api/roster/agent` |
| `platform_v2/tools/department_hq/templates/department_hq.html` | MODIFY — `[+ New Agent]` button + the create modal markup |
| `platform_v2/tools/department_hq/static/js/agent_create.js` | CREATE — create-modal logic, its own file (the modal is self-contained and department-hq.js is already large) |
| `platform_v2/static/js/agent_profile_modal.js` | MODIFY — edit fields, skills, Regenerate portrait, Decommission |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | MODIFY — create-modal styles |
| `platform_v2/tests/test_agent_decommission.py` | CREATE — Tasks 1–2 |
| `platform_v2/tests/test_agent_create.py` | CREATE — Tasks 3–5 |

---

### Task 1: Decommission precheck — refuse to manufacture a capability gap

**Files:**
- Create: `platform_v2/services/agent_lifecycle.py`
- Test: `platform_v2/tests/test_agent_decommission.py`

**Interfaces:**
- Produces: `decommission_precheck(agent_id) -> {"agent": {...}, "warnings": [{"kind": str, "message": str, "skills": [str]}], "blocking": bool}`

**Why this exists:** decommissioning the only agent holding a skill creates a capability dead-end — dispatches for it find no candidate. That is the exact gap K.I.N. would later propose a hire to fill. Refusing to create it silently is the point of the task.

- [ ] **Step 1: Write the failing test**

```python
"""Decommission must not silently create a capability dead-end."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import agent_lifecycle  # noqa: E402


class TestDecommissionPrecheck(unittest.TestCase):
    def _agent(self, **kw):
        base = {"id": 7, "name": "T.E.S.T.", "display_name": "T.E.S.T.",
                "is_department_ai": False, "department": "Engineering & Technology",
                "shift_state": "active"}
        base.update(kw)
        return base

    def test_sole_skill_holder_is_warned_and_skills_named(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=self._agent()), \
             patch.object(agent_lifecycle, "_skills_of", return_value=["code_review", "debug"]), \
             patch.object(agent_lifecycle, "_other_active_holders",
                          side_effect=lambda s, a: 0 if s == "code_review" else 3):
            out = agent_lifecycle.decommission_precheck(7)
        sole = [w for w in out["warnings"] if w["kind"] == "sole_skill_holder"]
        self.assertEqual(len(sole), 1)
        self.assertEqual(sole[0]["skills"], ["code_review"])
        self.assertNotIn("debug", sole[0]["skills"])

    def test_department_director_is_warned(self):
        with patch.object(agent_lifecycle, "get_agent",
                          return_value=self._agent(is_department_ai=True)), \
             patch.object(agent_lifecycle, "_skills_of", return_value=[]), \
             patch.object(agent_lifecycle, "_other_active_holders", return_value=5):
            out = agent_lifecycle.decommission_precheck(7)
        self.assertTrue(any(w["kind"] == "department_director" for w in out["warnings"]))

    def test_clean_agent_has_no_warnings(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=self._agent()), \
             patch.object(agent_lifecycle, "_skills_of", return_value=["code_review"]), \
             patch.object(agent_lifecycle, "_other_active_holders", return_value=4):
            out = agent_lifecycle.decommission_precheck(7)
        self.assertEqual(out["warnings"], [])
        self.assertFalse(out["blocking"])

    def test_missing_agent_raises(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=None):
            with self.assertRaises(ValueError):
                agent_lifecycle.decommission_precheck(999)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_decommission.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.agent_lifecycle'`

- [ ] **Step 3: Write minimal implementation**

Create `platform_v2/services/agent_lifecycle.py`:

```python
"""Agent lifecycle: create with side effects, and soft decommission.

Decommission is NEW code. `agent_service.deactivate_agent()` does not exist —
CLAUDE.md listed it for a long time, but no deactivate/decommission/retire
function was ever written. Agents are retired by setting shift_state.
"""

from database import get_db_cursor
from services.agent_service import get_agent, update_agent


def _skills_of(agent_id):
    """Skill names this agent holds."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT skill_name FROM agent_skills WHERE agent_id = %s", (agent_id,))
        return [r["skill_name"] for r in cur.fetchall()]


def _other_active_holders(skill_name, agent_id):
    """How many OTHER non-decommissioned agents hold this skill."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COUNT(*) AS n
                 FROM agent_skills s
                 JOIN agents a ON a.id = s.agent_id
                WHERE s.skill_name = %s
                  AND s.agent_id <> %s
                  AND a.status = 'active'
                  AND a.shift_state <> 'decommissioned'""",
            (skill_name, agent_id),
        )
        row = cur.fetchone()
        return row["n"] if row else 0


def decommission_precheck(agent_id):
    """What would break if this agent were retired.

    Warnings are advisory, never blocking: the owner may legitimately retire a
    sole holder. What is NOT acceptable is doing it silently.
    """
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    warnings = []
    orphaned = [s for s in _skills_of(agent_id) if _other_active_holders(s, agent_id) == 0]
    if orphaned:
        warnings.append({
            "kind": "sole_skill_holder",
            "message": ("This agent is the ONLY active holder of %d skill(s). Retiring it "
                        "leaves those capabilities with no candidate: %s"
                        % (len(orphaned), ", ".join(orphaned))),
            "skills": orphaned,
        })
    if agent.get("is_department_ai"):
        warnings.append({
            "kind": "department_director",
            "message": ("This agent is the director of %s — the department loses its "
                        "default routing target." % agent.get("department")),
            "skills": [],
        })
    return {"agent": agent, "warnings": warnings, "blocking": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_decommission.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_lifecycle.py platform_v2/tests/test_agent_decommission.py
git commit -m "feat(agent-lifecycle): decommission precheck — sole-skill-holder + director warnings"
```

---

### Task 2: `decommission_agent()` + its two endpoints

**Files:**
- Modify: `platform_v2/services/agent_lifecycle.py`
- Modify: `platform_v2/tools/department_hq/agent_detail_routes.py`
- Test: `platform_v2/tests/test_agent_decommission.py` (append)

**Interfaces:**
- Consumes: `decommission_precheck` (Task 1)
- Produces: `decommission_agent(agent_id, acknowledge_warnings=False) -> {"ok": bool, "agent_id": int, "previous": str, "warnings": [...], "refused": str|None}`; endpoints `GET /api/agent/<id>/decommission-precheck`, `POST /api/agent/<id>/decommission`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_decommission.py`:

```python
class TestDecommissionAgent(unittest.TestCase):
    def test_refuses_when_warnings_not_acknowledged(self):
        pre = {"agent": {"id": 7, "shift_state": "active"},
               "warnings": [{"kind": "sole_skill_holder", "message": "x", "skills": ["code_review"]}],
               "blocking": False}
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), \
             patch.object(agent_lifecycle, "update_agent") as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=False)
        self.assertFalse(out["ok"])
        self.assertIsNotNone(out["refused"])
        upd.assert_not_called()

    def test_proceeds_when_acknowledged(self):
        pre = {"agent": {"id": 7, "shift_state": "active"},
               "warnings": [{"kind": "sole_skill_holder", "message": "x", "skills": ["code_review"]}],
               "blocking": False}
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), \
             patch.object(agent_lifecycle, "update_agent") as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["previous"], "active")
        upd.assert_called_once()
        self.assertEqual(upd.call_args.kwargs.get("shift_state"), "decommissioned")

    def test_no_warnings_needs_no_acknowledgement(self):
        pre = {"agent": {"id": 7, "shift_state": "active"}, "warnings": [], "blocking": False}
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), \
             patch.object(agent_lifecycle, "update_agent") as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=False)
        self.assertTrue(out["ok"])
        upd.assert_called_once()

    def test_never_issues_a_delete(self):
        import inspect
        src = inspect.getsource(agent_lifecycle.decommission_agent)
        self.assertNotIn("DELETE", src.upper())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_decommission.py -v -k Decommission`
Expected: FAIL — `AttributeError: module 'services.agent_lifecycle' has no attribute 'decommission_agent'`

- [ ] **Step 3: Write minimal implementation**

Append to `services/agent_lifecycle.py`:

```python
def decommission_agent(agent_id, acknowledge_warnings=False):
    """Retire an agent by SHIFT STATE. Never deletes.

    Refuses when the precheck raised warnings and the caller has not
    acknowledged them — the operator must see what breaks before it breaks.
    """
    pre = decommission_precheck(agent_id)
    warnings = pre["warnings"]
    if warnings and not acknowledge_warnings:
        return {
            "ok": False,
            "agent_id": agent_id,
            "previous": pre["agent"].get("shift_state"),
            "warnings": warnings,
            "refused": "unacknowledged_warnings",
        }
    previous = pre["agent"].get("shift_state")
    update_agent(agent_id, shift_state="decommissioned")
    return {"ok": True, "agent_id": agent_id, "previous": previous,
            "warnings": warnings, "refused": None}
```

Then in `tools/department_hq/agent_detail_routes.py`, beside the existing agent endpoints:

```python
    @bp.route("/api/agent/<int:agent_id>/decommission-precheck")
    @admin_required
    def api_agent_decommission_precheck(agent_id):
        from services.agent_lifecycle import decommission_precheck
        try:
            out = decommission_precheck(agent_id)
            return jsonify({"success": True, "warnings": out["warnings"],
                            "agent": {"id": out["agent"]["id"],
                                      "name": out["agent"].get("name"),
                                      "shift_state": out["agent"].get("shift_state")}})
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/decommission", methods=["POST"])
    @admin_required
    def api_agent_decommission(agent_id):
        from services.agent_lifecycle import decommission_agent
        data = request.get_json(silent=True) or {}
        try:
            out = decommission_agent(agent_id, acknowledge_warnings=bool(data.get("acknowledge_warnings")))
            return (jsonify(out), 200) if out["ok"] else (jsonify(out), 409)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 404
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 4: Run tests + restart**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_agent_decommission.py -v
cd /mnt/archie_brain && docker compose restart archie_platform && sleep 9
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
print([str(r) for r in app.url_map.iter_rules() if 'decommission' in str(r)])"
```
Expected: 8 tests pass; both decommission routes listed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_lifecycle.py platform_v2/tools/department_hq/agent_detail_routes.py platform_v2/tests/test_agent_decommission.py
git commit -m "feat(agent-lifecycle): decommission endpoints, soft-only, warning-gated"
```

---

### Task 3: `create_agent_full()` — core row + skills + budget, per-side-effect results

**Files:**
- Modify: `platform_v2/services/agent_lifecycle.py`
- Test: `platform_v2/tests/test_agent_create.py`

**Interfaces:**
- Produces: `create_agent_full(fields: dict, skills: list, side_effects: dict) -> {"ok": bool, "agent_id": int|None, "results": [{"step": str, "ok": bool, "detail": str}]}`

**Context the implementer needs:** `agent_service.create_agent(name, display_name, department, model, **kwargs)` does exactly ONE `INSERT INTO agents … RETURNING id`. It creates NO budget, NO skills, NO mailbox, NO portrait. All composition is this function's job. It already carries the #5272 duplicate-name guard (`allow_duplicate_name` defaults False).

- [ ] **Step 1: Write the failing test**

```python
"""Create composes side effects server-side and reports EACH one."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import agent_lifecycle  # noqa: E402

FIELDS = {"name": "T.E.S.T.", "display_name": "T.E.S.T.",
          "department": "Engineering & Technology", "model": "qwen2.5:7b",
          "worker_type": "ai"}


class TestCreateAgentFull(unittest.TestCase):
    def test_requires_at_least_one_skill(self):
        out = agent_lifecycle.create_agent_full(FIELDS, [], {})
        self.assertFalse(out["ok"])
        self.assertIsNone(out["agent_id"])
        self.assertTrue(any("skill" in r["detail"].lower() for r in out["results"]))

    def test_happy_path_reports_every_step(self):
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill") as sk, \
             patch.object(agent_lifecycle, "_ensure_budget") as bud:
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"budget": True})
        self.assertTrue(out["ok"])
        self.assertEqual(out["agent_id"], 42)
        steps = {r["step"] for r in out["results"]}
        self.assertIn("agent", steps)
        self.assertIn("skills", steps)
        self.assertIn("budget", steps)
        sk.assert_called_once()
        bud.assert_called_once()

    def test_side_effect_failure_does_not_roll_back_the_agent(self):
        """The agent exists. Say so, and say what else failed."""
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill"), \
             patch.object(agent_lifecycle, "_ensure_budget", side_effect=RuntimeError("db down")):
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"budget": True})
        self.assertEqual(out["agent_id"], 42)
        budget = [r for r in out["results"] if r["step"] == "budget"][0]
        self.assertFalse(budget["ok"])
        self.assertIn("db down", budget["detail"])
        agent = [r for r in out["results"] if r["step"] == "agent"][0]
        self.assertTrue(agent["ok"])

    def test_unticked_side_effect_is_not_run(self):
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill"), \
             patch.object(agent_lifecycle, "_ensure_budget") as bud:
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"budget": False})
        bud.assert_not_called()
        self.assertFalse(any(r["step"] == "budget" for r in out["results"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_create.py -v`
Expected: FAIL — `AttributeError: module 'services.agent_lifecycle' has no attribute 'create_agent_full'`

- [ ] **Step 3: Write minimal implementation**

Add to the imports at the top of `services/agent_lifecycle.py`:

```python
from services.agent_service import create_agent, get_agent, update_agent
```

Then append:

```python
DEFAULT_TOKEN_LIMIT_PER_DAY = 50000


def _add_skill(agent_id, skill_name, proficiency_level=1, skill_category="general"):
    """Insert or update one skill. Columns are skill_name / skill_category /
    proficiency_level — NOT category / level."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, skill_name)
               DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level,
                             skill_category   = EXCLUDED.skill_category,
                             updated_at       = now()""",
            (agent_id, skill_name, skill_category, proficiency_level),
        )


def _ensure_budget(agent_id, token_limit_per_day=DEFAULT_TOKEN_LIMIT_PER_DAY):
    """Without a budget row, welfare gating and the K.I.N. over-budget checks
    have nothing to read for this agent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_budgets (agent_id, token_limit_per_day)
               VALUES (%s, %s) ON CONFLICT (agent_id) DO NOTHING""",
            (agent_id, token_limit_per_day),
        )


def create_agent_full(fields, skills, side_effects):
    """Create an agent and its side effects, reporting EACH outcome.

    A side-effect failure never rolls back the agent row: the agent exists and
    the failure is retryable. Reporting a bare success would hide it.
    """
    results = []
    if not skills:
        return {"ok": False, "agent_id": None, "results": [
            {"step": "validate", "ok": False,
             "detail": "At least one skill is required — an agent with no skills is "
                       "structurally undispatchable."}]}

    try:
        agent_id = create_agent(
            fields["name"], fields["display_name"], fields["department"], fields["model"],
            **{k: v for k, v in fields.items()
               if k not in ("name", "display_name", "department", "model")},
        )
        results.append({"step": "agent", "ok": True, "detail": "agent id %s" % agent_id})
    except Exception as e:
        return {"ok": False, "agent_id": None,
                "results": [{"step": "agent", "ok": False, "detail": str(e)}]}

    try:
        for s in skills:
            _add_skill(agent_id, s["skill_name"],
                       s.get("proficiency_level", 1), s.get("skill_category", "general"))
        results.append({"step": "skills", "ok": True, "detail": "%d skill(s)" % len(skills)})
    except Exception as e:
        results.append({"step": "skills", "ok": False, "detail": str(e)})

    if side_effects.get("budget"):
        try:
            _ensure_budget(agent_id)
            results.append({"step": "budget", "ok": True, "detail": "budget row created"})
        except Exception as e:
            results.append({"step": "budget", "ok": False, "detail": str(e)})

    return {"ok": True, "agent_id": agent_id, "results": results}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_create.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify the ON CONFLICT target actually exists**

```bash
docker exec -i archie_database psql -U archie -d archie 2>&1 -c "\d agent_skills" | grep -iE "unique|index"
docker exec -i archie_database psql -U archie -d archie 2>&1 -c "\d agent_budgets" | grep -iE "unique|index"
```
⚠️ `ON CONFLICT (agent_id, skill_name)` requires a unique constraint on that pair, and `ON CONFLICT (agent_id)` requires one on `agent_budgets.agent_id`. If either is missing, the INSERT raises at runtime while the unit test (which mocks these helpers) still passes. If a constraint is absent, replace that helper's `ON CONFLICT` with an explicit SELECT-then-INSERT/UPDATE and say so in your report. Do NOT add a migration in this task.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_lifecycle.py platform_v2/tests/test_agent_create.py
git commit -m "feat(agent-lifecycle): create_agent_full composes skills+budget with per-step results"
```

---

### Task 4: Mailbox side effect — VERIFY the path exists before wiring it

**Files:**
- Modify: `platform_v2/services/agent_lifecycle.py`
- Test: `platform_v2/tests/test_agent_create.py` (append)

**Interfaces:**
- Produces: `_provision_mailbox(agent_id, fields) -> str` (a detail string), consumed by `create_agent_full`'s `side_effects["mailbox"]` branch

⚠️ **THIS TASK STARTS WITH A VERIFICATION, NOT AN IMPLEMENTATION.** The only provisioning function found is `services/human_agent_provisioning.py: provision_human_agent(name, email, department) -> dict`, which is **human-agent specific**. Whether an equivalent path exists for `worker_type='ai'` is UNVERIFIED. Do not invent one.

- [ ] **Step 1: Find out what actually exists**

```bash
cd /mnt/archie_brain/platform_v2
sed -n '1,60p' services/human_agent_provisioning.py
grep -rn "def .*mailbox" services/ tools/email_manager/ | head -20
docker exec -i archie_database psql -U archie -d archie 2>&1 -c \
  "SELECT mailbox_type, count(*) FROM email_mailboxes GROUP BY 1 ORDER BY 2 DESC;"
```

Record in your report: which function provisions a mailbox for an **AI** agent, or that none exists.

- [ ] **Step 2: Implement per what you found**

**If an AI-capable path exists:** wrap it in `_provision_mailbox(agent_id, fields)` returning a detail string, and add a `side_effects.get("mailbox")` branch to `create_agent_full` in the same shape as the budget branch (try / append ok / append failure).

**If ONLY the human path exists:** implement `_provision_mailbox` to call `provision_human_agent` for `worker_type == 'internal'`, and for `worker_type == 'ai'` raise `NotImplementedError` with a message naming what is missing. Then the create form disables the mailbox checkbox for AI agents with that reason shown.
⚠️ **Do NOT silently no-op.** A checkbox that appears to work and does nothing is worse than a disabled one that explains itself — that is the "status misreports a healthy system" failure this codebase keeps hitting.

- [ ] **Step 3: Write the test matching what you implemented**

```python
class TestMailboxSideEffect(unittest.TestCase):
    def test_mailbox_failure_is_reported_not_swallowed(self):
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill"), \
             patch.object(agent_lifecycle, "_provision_mailbox",
                          side_effect=RuntimeError("stalwart unreachable")):
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"mailbox": True})
        mb = [r for r in out["results"] if r["step"] == "mailbox"][0]
        self.assertFalse(mb["ok"])
        self.assertIn("stalwart", mb["detail"].lower())
        self.assertEqual(out["agent_id"], 42)
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_create.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_lifecycle.py platform_v2/tests/test_agent_create.py
git commit -m "feat(agent-lifecycle): mailbox side effect, honest about what it cannot do"
```

---

### Task 5: Portrait side effect — reuse the existing queued generator

**Files:**
- Modify: `platform_v2/services/agent_lifecycle.py`
- Test: `platform_v2/tests/test_agent_create.py` (append)

**Interfaces:**
- Consumes: `tools.media_studio.services.portrait_service.generate_canonical(agent_id, prompt_override=None) -> Dict` (EXISTS — returns a dict containing `queue_id`)
- Produces: the `side_effects["portrait"]` branch of `create_agent_full`

- [ ] **Step 1: Write the failing test**

```python
class TestPortraitSideEffect(unittest.TestCase):
    def test_portrait_is_queued_not_awaited(self):
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill"), \
             patch.object(agent_lifecycle, "_queue_portrait", return_value="queued (id 9)") as q:
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"portrait": True})
        q.assert_called_once()
        p = [r for r in out["results"] if r["step"] == "portrait"][0]
        self.assertTrue(p["ok"])
        self.assertIn("queued", p["detail"].lower())

    def test_portrait_failure_never_fails_the_agent(self):
        with patch.object(agent_lifecycle, "create_agent", return_value=42), \
             patch.object(agent_lifecycle, "_add_skill"), \
             patch.object(agent_lifecycle, "_queue_portrait",
                          side_effect=RuntimeError("comfyui cold")):
            out = agent_lifecycle.create_agent_full(
                FIELDS, [{"skill_name": "code_review", "proficiency_level": 3}],
                {"portrait": True})
        self.assertTrue(out["ok"])
        self.assertEqual(out["agent_id"], 42)
        p = [r for r in out["results"] if r["step"] == "portrait"][0]
        self.assertFalse(p["ok"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_create.py -v -k Portrait`
Expected: FAIL — no attribute `_queue_portrait`

- [ ] **Step 3: Write minimal implementation**

```python
def _queue_portrait(agent_id):
    """QUEUE a portrait. Never wait for it.

    generate_canonical already goes through media_generation_queue (ADR-005) and
    returns a queue_id. ComfyUI parks itself (state=exited) to free VRAM for
    Ollama — that is its correct resting state, so a cold start is normal and a
    portrait failure must never fail the agent creation.
    """
    from tools.media_studio.services.portrait_service import generate_canonical
    res = generate_canonical(agent_id) or {}
    return "queued (queue_id %s)" % res.get("queue_id", "unknown")
```

And add the branch to `create_agent_full`, after the budget branch:

```python
    if side_effects.get("portrait"):
        try:
            results.append({"step": "portrait", "ok": True, "detail": _queue_portrait(agent_id)})
        except Exception as e:
            results.append({"step": "portrait", "ok": False, "detail": str(e)})
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_agent_create.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_lifecycle.py platform_v2/tests/test_agent_create.py
git commit -m "feat(agent-lifecycle): portrait side effect reuses the queued generator"
```

---

### Task 6: `POST /api/roster/agent`

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py`

**Interfaces:**
- Consumes: `create_agent_full` (Tasks 3–5); `VALID_DEPARTMENTS` (already defined at `roster_routes.py:26` as `set(DEPARTMENT_FLOOR_MAP.keys())`)
- Produces: `POST /tools/department-hq/api/roster/agent` → `{ok, agent_id, results:[{step,ok,detail}]}`

- [ ] **Step 1: Implement the route**

Inside `register_roster_routes`, beside the existing handlers:

```python
    @bp.route("/api/roster/agent", methods=["POST"])
    @admin_required
    def api_roster_create_agent():
        from services.agent_lifecycle import create_agent_full

        data = request.get_json(silent=True) or {}
        fields = data.get("fields") or {}
        skills = data.get("skills") or []
        side_effects = data.get("side_effects") or {}

        for required in ("name", "display_name", "department", "model"):
            if not fields.get(required):
                return jsonify({"ok": False, "error": "%s is required" % required}), 400
        if fields["department"] not in VALID_DEPARTMENTS:
            return jsonify({"ok": False, "error": "Invalid department: %s" % fields["department"]}), 400
        if fields.get("worker_type") not in ("ai", "internal", "contractor"):
            return jsonify({"ok": False, "error": "worker_type must be ai, internal or contractor"}), 400
        if not skills:
            return jsonify({"ok": False, "error": "At least one skill is required"}), 400

        try:
            out = create_agent_full(fields, skills, side_effects)
            return (jsonify(out), 201) if out["ok"] else (jsonify(out), 400)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Restart and confirm the route is live**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform && sleep 9
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
print([str(r) for r in app.url_map.iter_rules() if 'roster/agent' in str(r)])"
```
Expected: the route listed.

- [ ] **Step 3: Confirm validation refuses a skill-less create**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.agent_lifecycle import create_agent_full
print(create_agent_full({'name':'X','display_name':'X','department':'Engineering & Technology','model':'qwen2.5:7b','worker_type':'ai'}, [], {}))"
```
Expected: `ok: False`, no agent created. ⚠️ Do NOT run a successful create here — that would add a real agent to the live roster. Creating a real test agent happens once, deliberately, in Task 12.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/roster_routes.py
git commit -m "feat(agent-lifecycle): POST /api/roster/agent"
```

---

### Task 7: Create modal — markup + the presents-as branch

> **PLAN RULING (2026-08-21) — name assist is available ONLY when creating from a candidate.**
> Spec §4.1 says to reuse the async `generate-name` job. That endpoint is
> `POST /api/approvals/hire/<hire_id>/generate-name` — keyed by a **hire_id**, so it exists
> only for an agent created from a pending `hiring_candidates` row. A DIRECT create has no
> hire row and therefore no name-assist endpoint. Decision: Task 9's create-from-candidate
> path MAY offer name assist (it has the hire_id); a direct create requires the operator to
> type the name. Building a generalised name-assist endpoint is scope creep and is NOT in
> this plan. Cost if wrong: the operator types a name by hand on direct creates.

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`
- Create: `platform_v2/tools/department_hq/static/js/agent_create.js`
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css`

**Interfaces:**
- Produces: `openAgentCreate(prefill)`, DOM ids `agCreateOverlay`, `agKind`, `agName`, `agAcronym`, `agAcronymExp`, `agFirstName`, `agLastName`, `agGender`, `agEthnicity`, `agAgeRange`, `agDisplayName`, `agDepartment`, `agTitle`, `agModel`, `agSystemPrompt`, `agBio`, `agIsDirector`, `agSkillList`, `agSkillName`, `agSkillLevel`, `agSideBudget`, `agSideMailbox`, `agSidePortrait`, `agSubmit`, `agResults`

- [ ] **Step 1: Add the modal markup**

Use the platform's LCARS modal structure (`bm-overlay > bm-shell > bm-frame + bm-content > bm-header + bm-body + bm-footer`) — copy the class structure from an existing modal in this template rather than inventing one. Add a `[+ New Agent]` button to the roster control bar, beside the existing Export CSV / portrait buttons and NOT inside `#rosterBulkBar` (which is hidden until rows are selected).

The identity fieldsets: `#agAiFields` (name, acronym, acronym_expansion) and `#agHumanFields` (first_name, last_name, gender, ethnicity, age_range), with only one visible at a time.

- [ ] **Step 2: Implement the branch**

```javascript
/* Agent create modal. Own file — the modal is self-contained and
   department-hq.js is already large. */

function agApplyKind() {
    var kind = document.getElementById('agKind').value;   // 'ai' | 'internal'
    document.getElementById('agAiFields').style.display    = (kind === 'ai') ? '' : 'none';
    document.getElementById('agHumanFields').style.display = (kind === 'ai') ? 'none' : '';
    // Mailbox provisioning may not support AI agents — Task 4 decides this.
    var mb = document.getElementById('agSideMailbox');
    if (mb && mb.dataset.aiUnsupported === '1') {
        mb.disabled = (kind === 'ai');
        mb.title = (kind === 'ai') ? 'Mailbox provisioning is not available for AI agents' : '';
        if (kind === 'ai') mb.checked = false;
    }
}

function openAgentCreate(prefill) {
    document.getElementById('agCreateOverlay').style.display = 'flex';
    document.getElementById('agResults').innerHTML = '';
    agApplyKind();
    if (prefill && prefill.capability) {
        // From approving a pending hiring candidate
        agAddSkillRow(prefill.capability, 3);
        if (prefill.narrative) document.getElementById('agBio').value = prefill.narrative;
    }
}

function closeAgentCreate() {
    document.getElementById('agCreateOverlay').style.display = 'none';
}
```

- [ ] **Step 3: Verify structurally**

```bash
cd /mnt/archie_brain/platform_v2
node --check tools/department_hq/static/js/agent_create.js
grep -c "agCreateOverlay\|agKind\|agSkillList" tools/department_hq/templates/department_hq.html
```
Expected: syntax OK; non-zero id count. No browser claims — the drive is Task 12.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/static/js/agent_create.js platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "feat(agent-lifecycle): create modal markup + AI/human-like branch"
```

---

### Task 8: Create modal — skills, side effects, submit, per-step results

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/agent_create.js`

**Interfaces:**
- Consumes: `POST /api/roster/agent` (Task 6); `apiPost(path, body)` (exists in department-hq.js)
- Produces: `agAddSkillRow(name, level)`, `agCollectSkills()`, `agSubmit()`

- [ ] **Step 1: Implement**

```javascript
function agAddSkillRow(name, level) {
    var wrap = document.getElementById('agSkillList');
    var row = document.createElement('div');
    row.className = 'ag-skill-row';
    var n = document.createElement('input'); n.type = 'text'; n.className = 'ag-skill-name';
    n.value = name || ''; n.placeholder = 'capability, e.g. code_review';
    var l = document.createElement('select'); l.className = 'ag-skill-level';
    [1,2,3,4,5].forEach(function(v){ var o=document.createElement('option'); o.value=v;
        o.textContent='Lv'+v; if(v===(level||1)) o.selected=true; l.appendChild(o); });
    var x = document.createElement('button'); x.type='button'; x.textContent='×';
    x.onclick = function(){ wrap.removeChild(row); };
    row.appendChild(n); row.appendChild(l); row.appendChild(x);
    wrap.appendChild(row);
}

function agCollectSkills() {
    return [].slice.call(document.querySelectorAll('#agSkillList .ag-skill-row'))
        .map(function(r){
            return { skill_name: r.querySelector('.ag-skill-name').value.trim(),
                     proficiency_level: parseInt(r.querySelector('.ag-skill-level').value, 10) };
        })
        .filter(function(s){ return s.skill_name; });
}

async function agSubmit() {
    var kind = document.getElementById('agKind').value;
    var val = function(id){ var e=document.getElementById(id); return e ? e.value.trim() : ''; };
    var fields = {
        department: val('agDepartment'), title: val('agTitle'), model: val('agModel'),
        system_prompt: val('agSystemPrompt'), bio: val('agBio'),
        worker_type: kind, display_name: val('agDisplayName'),
        is_department_ai: document.getElementById('agIsDirector').checked
    };
    if (kind === 'ai') {
        fields.name = val('agName');
        fields.acronym = val('agAcronym');
        fields.acronym_expansion = val('agAcronymExp');
    } else {
        fields.first_name = val('agFirstName');
        fields.last_name = val('agLastName');
        fields.gender = val('agGender');
        fields.ethnicity = val('agEthnicity');
        fields.age_range = val('agAgeRange');
        fields.name = (fields.first_name + ' ' + fields.last_name).trim();
    }
    if (!fields.display_name) fields.display_name = fields.name;

    var skills = agCollectSkills();
    if (!skills.length) {
        setHtml(document.getElementById('agResults'),
                '<div class="ag-err">At least one skill is required — an agent with no '
              + 'skills is structurally undispatchable.</div>');
        return;
    }
    var side = {
        budget:   document.getElementById('agSideBudget').checked,
        mailbox:  document.getElementById('agSideMailbox').checked,
        portrait: document.getElementById('agSidePortrait').checked
    };

    var btn = document.getElementById('agSubmit');
    btn.disabled = true;
    try {
        var res = await apiPost('/api/roster/agent', {fields: fields, skills: skills, side_effects: side});
        // EVERY step is shown, pass or fail. A bare "created" would hide a failed mailbox.
        var rows = (res.results || []).map(function(r){
            return '<li class="' + (r.ok ? 'ag-ok' : 'ag-fail') + '">'
                 + esc(r.step) + ': ' + (r.ok ? 'ok' : 'FAILED') + ' — ' + esc(r.detail) + '</li>';
        }).join('');
        setHtml(document.getElementById('agResults'),
                (res.ok ? '<div class="ag-ok">Agent #' + esc(String(res.agent_id)) + ' created</div>'
                        : '<div class="ag-err">Not created</div>') + '<ul>' + rows + '</ul>');
        if (res.ok && typeof loadRoster === 'function') loadRoster();
    } catch (err) {
        setHtml(document.getElementById('agResults'), '<div class="ag-err">' + esc(err.message) + '</div>');
    } finally {
        btn.disabled = false;
    }
}
```

- [ ] **Step 2: Verify structurally**

```bash
cd /mnt/archie_brain/platform_v2 && node --check tools/department_hq/static/js/agent_create.js
```
Expected: syntax OK.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/agent_create.js
git commit -m "feat(agent-lifecycle): create modal submit with per-step results"
```

---

### Task 9: Wire both entry points

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

**Interfaces:**
- Consumes: `openAgentCreate(prefill)` (Task 7); `GET /api/hiring/pending` (already exists, returns `capability`, `gap_reason`, `narrative` is NOT in that payload — only `capability`, `gap_reason`, `precheck_status`, `precheck_message`, `proposed_at`, `age_hours`)

⚠️ The hiring endpoint does NOT return `narrative` or `shortlist`. If the pre-fill needs them, add them to `hiring_routes.PENDING_SQL` in this task (they exist as columns on `hiring_candidates`) rather than reading fields that are not sent.

- [ ] **Step 1: Roster button**

In `department_hq.html`, on the `[+ New Agent]` button added in Task 7:

```html
<button class="dhq-btn" id="rosterNewAgentBtn" onclick="openAgentCreate(null)">+ New Agent</button>
```

- [ ] **Step 2: Candidate pre-fill**

Add `narrative` to `hiring_routes.PENDING_SQL`'s SELECT list (the column exists on
`hiring_candidates`), then in `renderHiringStrip` give each row a create affordance built with
`JSON.stringify` + quote-escaping — the values are database text going into an inline handler:

```javascript
var payload = JSON.stringify({capability: c.capability, narrative: c.narrative || '',
                              hire_id: c.id}).replace(/'/g, '&apos;');
// ... + " <button class='dhq-btn-sm' onclick='openAgentCreate(" + payload + ")'>Create from this</button>"
```

- [ ] **Step 3: Verify structurally**

```bash
cd /mnt/archie_brain/platform_v2
node --check tools/department_hq/static/js/department-hq.js
grep -c "openAgentCreate" tools/department_hq/static/js/department-hq.js tools/department_hq/templates/department_hq.html
```
Expected: syntax OK; both entry points reference it.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/department-hq.js platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/hiring_routes.py
git commit -m "feat(agent-lifecycle): wire New Agent button + create-from-candidate"
```

---

### Task 10: Profile modal — edit, skills, regenerate portrait, decommission

**Files:**
- Modify: `platform_v2/static/js/agent_profile_modal.js`

**Interfaces:**
- Consumes: `PATCH /api/agent/<id>` · `POST /api/agent/<id>/skills` · `POST /api/agents/<id>/generate-portrait` · `GET /api/agent/<id>/decommission-precheck` · `POST /api/agent/<id>/decommission` (Task 2)

⚠️ **Edit `static/js/agent_profile_modal.js` — the SHARED modal.** Do NOT add UI to `department-hq.js`'s `openAgentDetail`: that function is dead code, shadowed at load by `agent_profile_modal.js`'s `window.openAgentDetail =`. UI added there renders nowhere, and this exact trap cost a live-drive bug in #4959.

⚠️ **Do not add new endpoints.** All five above already exist (Task 2 added the last two). This task is wiring only.

- [ ] **Step 1: Editable fields**

Add an edit affordance for `title`, `bio`, `system_prompt`, `model` that PATCHes `/api/agent/<id>` with only the changed keys. That endpoint already validates unknown fields and writes `governance_audit_log` — which is a reason to use it rather than anything else.

- [ ] **Step 2: Skills**

Add/update a skill via `POST /api/agent/<id>/skills` with `{skill_name, level, category}` — note this existing endpoint takes **`level`** and **`category`**, not `proficiency_level`/`skill_category`. Match its contract, do not change it.

- [ ] **Step 3: Regenerate portrait (formerly sub-project D)**

A button calling `POST /api/agents/<id>/generate-portrait`, showing the returned `queue_id` and the word **queued** — never "done". A portrait can sit behind a ComfyUI cold start.

- [ ] **Step 4: Decommission**

A button that first GETs `/api/agent/<id>/decommission-precheck` and renders every warning verbatim. Only if the operator confirms does it POST `/decommission` with `{"acknowledge_warnings": true}`. A 409 means warnings were not acknowledged — show them, do not retry automatically.

- [ ] **Step 5: Verify structurally**

```bash
cd /mnt/archie_brain/platform_v2
node --check static/js/agent_profile_modal.js
grep -c "decommission-precheck\|generate-portrait" static/js/agent_profile_modal.js
```
Expected: syntax OK; both referenced.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/static/js/agent_profile_modal.js
git commit -m "feat(agent-lifecycle): profile modal — edit, skills, portrait, decommission"
```

---

### Task 11: Full suite, deploy, live drive, PR

**Files:** none modified

- [ ] **Step 1: Run every new test**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_agent_decommission.py /app/tests/test_agent_create.py -v
```
Expected: all pass.

- [ ] **Step 2: No regression in the wider suite**

```bash
docker exec archie_platform python3 -m pytest /app/tests/ -q 2>&1 | tail -20
```
Record any pre-existing failures rather than "fixing" them here.

- [ ] **Step 3: Deploy**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform && sleep 9
docker logs --tail 30 archie_platform 2>&1 | grep -iE "error|traceback" || echo clean
```

- [ ] **Step 4: Live browser drive — THE acceptance gate**

Log in as `claude` (password from `/mnt/archie_brain/credentials/agent_passwords.env`, key `ARCHIE_CLAUDE_PASSWORD`) — never `kytran`.

1. Roster → `[+ New Agent]` opens the modal.
2. Switch kind AI ↔ Human-like: the identity fieldsets swap; mailbox checkbox disables for AI if Task 4 found no AI path.
3. Submit with **zero skills** → refused, with the undispatchable explanation. **No agent created** (re-check the roster count).
4. Create ONE real AI agent with one skill. Confirm the per-step result list shows every side effect, pass or fail.
5. Confirm it appears in the roster, in the right department group.
6. Open its profile → edit `title` → confirm it persists after reload.
7. Regenerate portrait → shows **queued** with a queue id.
8. Decommission it → precheck warnings shown → acknowledge → it leaves the roster listing.
9. Confirm the roster count returns to its starting value.

⚠️ Step 4 creates a REAL agent. Step 8 retires it. Do both, in the same drive, so the roster is left as you found it.

- [ ] **Step 5: Confirm the DB is where it started**

```bash
docker exec -i archie_database psql -U archie -d archie 2>&1 -c \
  "SELECT count(*) FROM agents WHERE status='active' AND shift_state<>'decommissioned';"
```
Expected: 140 (the pre-drive count), the test agent having been decommissioned.

- [ ] **Step 6: Open the PR**

```bash
cd /mnt/archie_brain && git push -u origin feat/agent-lifecycle
```
Then `/commit-push-pr` to register with Repair Bay. Do **not** self-merge — a REQUEST CHANGES is not a clear, and a missing verdict is never an approval.

---

## Notes for the executor

- **Do not rebuild §7.2's existing endpoints.** If a task seems to need `PATCH /api/roster/agent/<id>` or a new skills endpoint, re-read the amended spec — that surface already exists and writes an audit trail.
- `create_agent` does ONE INSERT and no side effects. Everything else is `create_agent_full`'s job.
- The fleet cannot implement this (`CAP_MAP` excludes `bugfix`/`implementation`; 7B agents produce analysis, KB #290290), and Codex CLI is scoped out of `department_hq` by `config/agents/codex.yaml`.
- Sub-project E (agent platform identity/access) remains out of scope.
