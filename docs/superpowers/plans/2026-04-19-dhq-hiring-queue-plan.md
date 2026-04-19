# DHQ Hiring Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the DHQ Hiring Queue — a `hiring_candidates` table + UNION into the unified approvals endpoint + Approve/Reject endpoints + K.I.N. daily proposal-generation job, followed by a DHQ Approvals tab source pill for the `hire:` source.

**Architecture:** New `platform_v2/services/hiring_service.py` owns all business logic (shortlist SQL, propose, approve, reject, expire). `platform_v2/tools/department_hq/approvals_routes.py` is extended with the `hire:` UNION branch and two new POST handlers. `platform_v2/services/agent_jobs.py` registers `kin_generate_hire_proposals` (09:05 UTC) and `expire_stale_hire_proposals` (04:30 UTC).

**Tech Stack:** Python 3, Flask, psycopg2, APScheduler, pytest, `requests` (for `/api/tags` pre-check + bridge dispatch via `build_options`).

**Spec:** `docs/superpowers/specs/2026-04-19-dhq-hiring-queue-design.md`

**Branch:** `feat/dhq-hiring-queue-spec` (spec already committed at `2d714e78`)

**Context from prior session exploration (use these, don't re-grep):**
- K.I.N. agent row: `id = 145`, `name = 'K.I.N.'`, `display_name = 'K.I.N.'`
- `agents` table has NO `decommissioned_at` column. Use `updated_at` as the tiebreak (shift_state transitions update the row).
- `admin_required` decorator: `from .routes import admin_required` (inside `tools/department_hq/`); upstream source at `platform_v2/tools/department_hq/routes.py:24`.
- `approvals_routes.py` is 485 lines. Existing helpers: `_approve_autonomy`, `_approve_contractor`, `_approve_bridge`. Add `_approve_hire` + `_reject_hire` in the same style.
- Existing endpoint: `@bp.route("/api/approvals/pending", methods=["GET"])` at line 155 of `approvals_routes.py`.
- `check_understaffed_capabilities` lives at `platform_v2/services/agent_jobs.py:1558`. Its `_log_cycle` details dict stores only the **count** (`understaffed_capabilities`) — the actual gap list goes into `system_notifications` via `_create_hr_alert`. Rather than read back from `system_notifications`, `kin_generate_hire_proposals` re-runs the same WITH clause (single source of truth, no cross-table coupling).
- Current gap volume: 214 capabilities are understaffed. The job must cap proposals per run (MAX_PROPOSALS_PER_RUN = 10) so the first runs don't flood the queue.

---

## File Structure

**New files:**
- `database/migrations/NNN_hiring_candidates.sql` — table + indexes (NNN = next sequential at implementation time)
- `platform_v2/services/hiring_service.py` — business logic (shortlist, propose, approve, reject, expire)
- `platform_v2/tests/test_hiring_service.py` — unit tests
- `platform_v2/tests/test_approvals_hire_routes.py` — route tests
- `platform_v2/tests/test_hiring_candidates_migration.py` — migration smoke

**Modified files:**
- `platform_v2/tools/department_hq/approvals_routes.py` — extend unified endpoint + add two POST handlers
- `platform_v2/services/agent_jobs.py` — register two new scheduled jobs
- `platform_v2/tools/department_hq/static/js/department_hq_approvals.js` (PR 2) — source-pill rendering + shortlist card (create if doesn't exist; locate via grep at PR 2 start)

---

## PR 1 — Backend: schema + service + jobs + endpoints

### Task 1: Migration for `hiring_candidates` table

**Files:**
- Create: `database/migrations/NNN_hiring_candidates.sql`
- Create: `platform_v2/tests/test_hiring_candidates_migration.py`

- [ ] **Step 1: Determine next migration number**

Run: `ls database/migrations/ | sort | tail -20`
Pick the next unused number (spec says `NNN`; use e.g. `450_hiring_candidates.sql` or the next available). Substitute that number in every `NNN` reference below.

- [ ] **Step 2: Write the failing migration test**

```python
# platform_v2/tests/test_hiring_candidates_migration.py
"""Schema smoke for hiring_candidates migration."""
from __future__ import annotations

import os
import psycopg2
import pytest


def _conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def test_hiring_candidates_table_exists():
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='hiring_candidates'
            ORDER BY ordinal_position
        """)
        cols = {r[0]: r[1] for r in cur.fetchall()}
    assert cols, "hiring_candidates table missing"
    for name in [
        "id", "capability", "gap_reason", "gap_alert_id", "narrative",
        "shortlist", "proposed_at", "proposed_by_agent_id",
        "status", "chosen_agent_id", "decided_by_user_id", "decided_at",
        "decision_notes", "precheck_status", "precheck_message",
    ]:
        assert name in cols, f"hiring_candidates.{name} column missing"


def test_hiring_candidates_status_check_constraint():
    with _conn() as c, c.cursor() as cur:
        cur.execute("BEGIN;")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO hiring_candidates (capability, gap_reason, status) "
                "VALUES ('x', 'x', 'bogus')"
            )
        cur.execute("ROLLBACK;")


def test_hiring_candidates_partial_index_exists():
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT indexdef
            FROM pg_indexes
            WHERE tablename='hiring_candidates' AND indexname='idx_hiring_candidates_cap_pending'
        """)
        row = cur.fetchone()
    assert row and "WHERE (status = 'pending'" in row[0].lower() or (row and "WHERE" in row[0])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec archie_platform pytest tests/test_hiring_candidates_migration.py -v`
Expected: all 3 tests FAIL with `table hiring_candidates missing` or similar.

- [ ] **Step 4: Write the migration**

```sql
-- database/migrations/NNN_hiring_candidates.sql
-- Task #2102 — DHQ Hiring Queue backing store.

BEGIN;

CREATE TABLE IF NOT EXISTS hiring_candidates (
    id                   SERIAL PRIMARY KEY,

    capability           VARCHAR(100) NOT NULL,
    gap_reason           TEXT NOT NULL,
    gap_alert_id         INTEGER,
    narrative            TEXT,

    shortlist            JSONB NOT NULL DEFAULT '[]'::jsonb,

    proposed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposed_by_agent_id INTEGER,

    status               VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','approved','rejected','expired')),
    chosen_agent_id      INTEGER,
    decided_by_user_id   INTEGER,
    decided_at           TIMESTAMPTZ,
    decision_notes       TEXT,

    precheck_status      VARCHAR(20),
    precheck_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_status
    ON hiring_candidates(status);

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_cap_pending
    ON hiring_candidates(capability) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_proposed_at
    ON hiring_candidates(proposed_at DESC);

COMMIT;
```

- [ ] **Step 5: Apply migration and verify**

```
docker exec archie_database psql -U archie -d archie -f /var/lib/postgresql/migrations/NNN_hiring_candidates.sql
```

(If migrations are mounted at a different path, locate via `docker inspect archie_database`. Failing that, `docker cp` the file in and `psql -f /tmp/<file>.sql`.)

Run tests: `docker exec archie_platform pytest tests/test_hiring_candidates_migration.py -v`
Expected: all 3 pass.

- [ ] **Step 6: Commit**

```bash
git add database/migrations/NNN_hiring_candidates.sql \
        platform_v2/tests/test_hiring_candidates_migration.py
git commit -m "$(cat <<'EOF'
feat(db): hiring_candidates table (#2102)

Backing store for DHQ Hiring Queue. Columns track gap context,
shortlist JSONB, decision state, and the approve-time pre-check
outcome. Partial index on (capability) WHERE status='pending'
supports dedup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `hiring_service.get_shortlist`

**Files:**
- Create: `platform_v2/services/hiring_service.py`
- Create: `platform_v2/tests/test_hiring_service.py`

- [ ] **Step 1: Write failing tests**

```python
# platform_v2/tests/test_hiring_service.py
"""Unit tests for hiring_service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_db_cursor_with_rows(rows):
    """Returns (conn, cur) doubles where cur.fetchall() -> rows."""
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def test_shortlist_returns_top_3_decommissioned_by_proficiency():
    from services import hiring_service

    fake_rows = [
        {"agent_id": 1, "display_name": "A", "proficiency_level": 5,
         "department": "X", "decommissioned_at": None, "primary_model": "m"},
        {"agent_id": 2, "display_name": "B", "proficiency_level": 4,
         "department": "Y", "decommissioned_at": None, "primary_model": "m"},
        {"agent_id": 3, "display_name": "C", "proficiency_level": 3,
         "department": "Z", "decommissioned_at": None, "primary_model": "m"},
    ]
    with patch("services.hiring_service._fetch_shortlist_rows", return_value=fake_rows):
        out = hiring_service.get_shortlist("translate", limit=3)
    assert len(out) == 3
    assert [e["proficiency_level"] for e in out] == [5, 4, 3]


def test_shortlist_limits_result_size():
    from services import hiring_service

    fake_rows = [{"agent_id": i, "display_name": f"A{i}",
                  "proficiency_level": 5, "department": "X",
                  "decommissioned_at": None, "primary_model": "m"}
                 for i in range(10)]
    with patch("services.hiring_service._fetch_shortlist_rows", return_value=fake_rows):
        out = hiring_service.get_shortlist("translate", limit=3)
    assert len(out) == 3


def test_shortlist_empty_when_no_decommissioned_matches():
    from services import hiring_service

    with patch("services.hiring_service._fetch_shortlist_rows", return_value=[]):
        out = hiring_service.get_shortlist("nonexistent_skill", limit=3)
    assert out == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.hiring_service'`.

- [ ] **Step 3: Write the service module + shortlist**

```python
# platform_v2/services/hiring_service.py
"""Business logic for the DHQ Hiring Queue.

Spec: docs/superpowers/specs/2026-04-19-dhq-hiring-queue-design.md
Task: #2102 on Project #261.

Public functions:
- get_shortlist(capability, limit=3) -> list[dict]
- propose_for_gap(capability, gap_reason, ...) -> int | None
- approve_candidate(hire_id, chosen_agent_id, decided_by_user_id, notes) -> dict
- reject_candidate(hire_id, decided_by_user_id, notes) -> dict
- expire_stale_proposals(max_age_days=14) -> int
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module constants
MIN_PROFICIENCY = 3
DEFAULT_SHORTLIST_LIMIT = 3
DEFAULT_EXPIRY_DAYS = 14


def _fetch_shortlist_rows(capability: str, limit: int) -> list[dict[str, Any]]:
    """Query the DB for decommissioned candidates. Separated for ease of mocking."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                a.id                   AS agent_id,
                a.display_name         AS display_name,
                s.proficiency_level    AS proficiency_level,
                a.department           AS department,
                a.updated_at           AS decommissioned_at,
                COALESCE(
                    (SELECT model FROM agent_models
                      WHERE agent_id = a.id
                      ORDER BY is_primary DESC NULLS LAST, id ASC
                      LIMIT 1),
                    ''
                )                      AS primary_model
            FROM agents a
            JOIN agent_skills s ON s.agent_id = a.id AND s.skill_name = %s
            WHERE a.shift_state = 'decommissioned'
              AND s.proficiency_level >= %s
            ORDER BY s.proficiency_level DESC, a.updated_at DESC NULLS LAST
            LIMIT %s
            """,
            (capability, MIN_PROFICIENCY, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_shortlist(capability: str, limit: int = DEFAULT_SHORTLIST_LIMIT) -> list[dict[str, Any]]:
    """Return up to `limit` decommissioned agents with `capability` proficiency >= 3.

    Ranked by proficiency DESC then most-recently-decommissioned DESC
    (updated_at is used as a stand-in for decommissioned_at, since the
    agents table has no dedicated column).
    """
    return _fetch_shortlist_rows(capability, limit)


def propose_for_gap(*args, **kwargs) -> Optional[int]:
    raise NotImplementedError("implemented in Task 3")


def approve_candidate(*args, **kwargs) -> dict[str, Any]:
    raise NotImplementedError("implemented in Task 4")


def reject_candidate(*args, **kwargs) -> dict[str, Any]:
    raise NotImplementedError("implemented in Task 5")


def expire_stale_proposals(*args, **kwargs) -> int:
    raise NotImplementedError("implemented in Task 6")
```

Note on the `agent_models` join: the spec flagged that the agents table has no `primary_model` column; verify at implementation time that `agent_models(agent_id, model, is_primary)` is the correct structure. If not, grep `platform_v2/services/agent_models.py` for the real schema and adjust the subquery. Fall back to empty string if the lookup pattern doesn't fit — narrative & display still work.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "$(cat <<'EOF'
feat(hiring): get_shortlist — SQL-deterministic decommissioned candidates (#2102)

Implements the shortlist layer per spec §'K.I.N. proposal generation'.
Returns up to N decommissioned agents with the capability's skill at
proficiency >= 3, ranked by proficiency DESC then updated_at DESC
(agents table has no decommissioned_at column).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `hiring_service.propose_for_gap`

**Files:**
- Modify: `platform_v2/services/hiring_service.py`
- Modify: `platform_v2/tests/test_hiring_service.py`

- [ ] **Step 1: Append failing tests**

```python
def test_propose_for_gap_inserts_pending_row():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.side_effect = [None, {"id": 17}]  # no dedup hit, then INSERT returning id
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    shortlist = [{"agent_id": 1, "display_name": "A",
                  "proficiency_level": 5, "department": "X",
                  "decommissioned_at": None, "primary_model": "m"}]
    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ):
        out = hiring_service.propose_for_gap(
            capability="translate",
            gap_reason="only 2 active",
            gap_alert_id=None,
            shortlist=shortlist,
            narrative="why these 3",
            proposed_by_agent_id=145,
        )
    assert out == 17


def test_propose_for_gap_dedups_on_pending_capability():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.return_value = {"id": 99}  # existing pending row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ):
        out = hiring_service.propose_for_gap(
            capability="translate",
            gap_reason="only 2 active",
            gap_alert_id=None,
            shortlist=[{"agent_id": 1}],
            narrative=None,
            proposed_by_agent_id=145,
        )
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v -k propose`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace the `propose_for_gap` stub in `platform_v2/services/hiring_service.py`:

```python
import json
from database import get_db_cursor  # add at top of file


def propose_for_gap(
    *,
    capability: str,
    gap_reason: str,
    shortlist: list[dict[str, Any]],
    narrative: Optional[str] = None,
    gap_alert_id: Optional[int] = None,
    proposed_by_agent_id: Optional[int] = None,
) -> Optional[int]:
    """Insert a pending hiring_candidates row. Returns new id, or None on dedup."""
    if not shortlist:
        logger.info("propose_for_gap skipping empty shortlist for %s", capability)
        return None

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id FROM hiring_candidates "
            "WHERE capability = %s AND status = 'pending' LIMIT 1",
            (capability,),
        )
        if cur.fetchone():
            logger.info("propose_for_gap dedup hit for %s", capability)
            return None

        cur.execute(
            """
            INSERT INTO hiring_candidates (
                capability, gap_reason, gap_alert_id, narrative,
                shortlist, proposed_by_agent_id
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                capability,
                gap_reason,
                gap_alert_id,
                narrative,
                json.dumps(shortlist),
                proposed_by_agent_id,
            ),
        )
        row = cur.fetchone()
        return row["id"] if isinstance(row, dict) else row[0]
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: 5 pass (3 from Task 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "$(cat <<'EOF'
feat(hiring): propose_for_gap with dedup (#2102)

Inserts a pending hiring_candidates row. Skips if a pending row
already exists for the same capability (dedup). Empty shortlist
is silently skipped (caller's responsibility to avoid).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `hiring_service.approve_candidate`

**Files:**
- Modify: `platform_v2/services/hiring_service.py`
- Modify: `platform_v2/tests/test_hiring_service.py`

- [ ] **Step 1: Append failing tests**

```python
def test_approve_candidate_precheck_model_missing_blocks_transition():
    """Pre-check fails → row stays pending, 'model_missing' persisted."""
    from services import hiring_service

    row = {
        "id": 17, "status": "pending",
        "shortlist": [{"agent_id": 7, "display_name": "Oracle",
                       "primary_model": "mistral:7b"}],
    }
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ), patch(
        "services.hiring_service._verify_model_available",
        return_value=(False, "Model 'mistral:7b' not present"),
    ), patch(
        "services.hiring_service._transition_agent",
    ) as mock_transition:
        result = hiring_service.approve_candidate(
            hire_id=17, chosen_agent_id=7, decided_by_user_id=1, notes=""
        )
    assert result["ok"] is False
    assert result["reason"] == "model_missing"
    mock_transition.assert_not_called()


def test_approve_candidate_invalid_chosen_agent_rejected():
    from services import hiring_service

    row = {
        "id": 17, "status": "pending",
        "shortlist": [{"agent_id": 7, "display_name": "Oracle"}],
    }
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ):
        result = hiring_service.approve_candidate(
            hire_id=17, chosen_agent_id=999, decided_by_user_id=1, notes=""
        )
    assert result["ok"] is False
    assert result["reason"] == "candidate_not_in_shortlist"


def test_approve_candidate_already_decided_rejected():
    from services import hiring_service

    row = {"id": 17, "status": "approved", "shortlist": []}
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ):
        result = hiring_service.approve_candidate(
            hire_id=17, chosen_agent_id=7, decided_by_user_id=1, notes=""
        )
    assert result["ok"] is False
    assert result["reason"] == "already_decided"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v -k approve`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace `approve_candidate` stub:

```python
import os
import requests


def _verify_model_available(model: str, hub_host: Optional[str] = None) -> tuple[bool, str]:
    """GET /api/tags on hub; return (ok, message). 5s timeout, silent failure = not ok."""
    if not model:
        return True, "no_model_configured_skip"
    host = hub_host or os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        names = {m.get("name", "").split(":")[0] for m in r.json().get("models", [])}
        stem = model.split(":")[0]
        if stem not in names:
            return False, f"Model {model!r} not present on {host}"
        return True, "ok"
    except Exception as e:
        return False, f"Ollama unreachable: {e}"


def _transition_agent(agent_id: int, new_state: str, reason: str) -> None:
    """Wrapper around agent_service for ease of mocking."""
    from services.agent_service import transition_shift_state

    transition_shift_state(agent_id, new_state, reason=reason)


def _audit(action: str, user_id: int, subject_agent_id: Optional[int], details: dict[str, Any]) -> None:
    """Write one governance_audit_log row."""
    from database import get_db_cursor
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (event_category, action, actor_user_id, subject_agent_id, details, timestamp)
                VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
                """,
                ("agent_lifecycle", action, user_id, subject_agent_id, json.dumps(details)),
            )
    except Exception as e:
        logger.warning("governance_audit_log write failed: %s", e)


def approve_candidate(
    *,
    hire_id: int,
    chosen_agent_id: int,
    decided_by_user_id: int,
    notes: str = "",
) -> dict[str, Any]:
    """Approve a hiring candidate row. See spec §'Approve flow'.

    Returns: {"ok": bool, "reason": str, "agent_id": int | None}.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, status, shortlist FROM hiring_candidates WHERE id = %s",
            (hire_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found", "agent_id": None}
        status = row["status"] if isinstance(row, dict) else row[1]
        shortlist = row["shortlist"] if isinstance(row, dict) else row[2]
        if status != "pending":
            return {"ok": False, "reason": "already_decided", "agent_id": None}

        entries = shortlist if isinstance(shortlist, list) else json.loads(shortlist)
        match = next((e for e in entries if e.get("agent_id") == chosen_agent_id), None)
        if match is None:
            return {"ok": False, "reason": "candidate_not_in_shortlist", "agent_id": None}

        # Pre-check (Q4 model-availability)
        model = match.get("primary_model", "")
        ok, msg = _verify_model_available(model)
        if not ok:
            cur.execute(
                "UPDATE hiring_candidates "
                "SET precheck_status = %s, precheck_message = %s "
                "WHERE id = %s AND status = 'pending'",
                (
                    "model_missing" if "not present" in msg.lower() else "ollama_unreachable",
                    msg,
                    hire_id,
                ),
            )
            return {
                "ok": False,
                "reason": "model_missing",
                "agent_id": None,
                "message": msg,
            }

        # Transition
        try:
            _transition_agent(chosen_agent_id, "active", "hired_via_queue")
        except Exception as e:
            logger.exception("transition_shift_state failed for agent %s", chosen_agent_id)
            return {"ok": False, "reason": "transition_failed", "agent_id": None,
                    "message": str(e)}

        # Finalize row (last-writer-wins guard via WHERE status='pending')
        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'approved',
                   chosen_agent_id = %s,
                   decided_by_user_id = %s,
                   decided_at = NOW(),
                   decision_notes = %s,
                   precheck_status = 'ok',
                   precheck_message = NULL
             WHERE id = %s AND status = 'pending'
             RETURNING id
            """,
            (chosen_agent_id, decided_by_user_id, notes, hire_id),
        )
        if cur.fetchone() is None:
            # Someone else finalised first. Nothing to do.
            return {"ok": False, "reason": "race_lost", "agent_id": chosen_agent_id}

    _audit(
        "hire_reactivation_approved",
        decided_by_user_id,
        chosen_agent_id,
        {"hire_id": hire_id, "notes": notes},
    )
    return {"ok": True, "reason": "approved", "agent_id": chosen_agent_id}
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: 8 pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "$(cat <<'EOF'
feat(hiring): approve_candidate with model-availability pre-check (#2102)

Spec §'Approve flow'. Loads the candidate row, validates the chosen
agent is in the shortlist, runs /api/tags pre-check against the
agent's primary_model, transitions shift_state via agent_service,
then finalises the row with last-writer-wins semantics. Writes one
governance_audit_log row on success.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `hiring_service.reject_candidate`

**Files:**
- Modify: `platform_v2/services/hiring_service.py`
- Modify: `platform_v2/tests/test_hiring_service.py`

- [ ] **Step 1: Append failing test**

```python
def test_reject_candidate_flips_status_and_writes_notes():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 17, "status": "pending"},   # initial SELECT
        {"id": 17},                         # UPDATE ... RETURNING
    ]
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ), patch("services.hiring_service._audit") as mock_audit:
        result = hiring_service.reject_candidate(
            hire_id=17, decided_by_user_id=1, notes="not a fit right now"
        )
    assert result["ok"] is True
    mock_audit.assert_called_once()
```

- [ ] **Step 2: Run test, verify fail**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v -k reject`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace `reject_candidate` stub:

```python
def reject_candidate(
    *,
    hire_id: int,
    decided_by_user_id: int,
    notes: str = "",
) -> dict[str, Any]:
    """Reject a hiring candidate. See spec §'Reject flow'."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, status FROM hiring_candidates WHERE id = %s",
            (hire_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        status = row["status"] if isinstance(row, dict) else row[1]
        if status != "pending":
            return {"ok": False, "reason": "already_decided"}

        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'rejected',
                   decided_by_user_id = %s,
                   decided_at = NOW(),
                   decision_notes = %s
             WHERE id = %s AND status = 'pending'
             RETURNING id
            """,
            (decided_by_user_id, notes, hire_id),
        )
        if cur.fetchone() is None:
            return {"ok": False, "reason": "race_lost"}

    _audit(
        "hire_reactivation_rejected",
        decided_by_user_id,
        None,
        {"hire_id": hire_id, "notes": notes},
    )
    return {"ok": True, "reason": "rejected"}
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: 9 pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "$(cat <<'EOF'
feat(hiring): reject_candidate with audit (#2102)

Simple UPDATE to status='rejected'. Writes one governance_audit_log
row with action='hire_reactivation_rejected'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `hiring_service.expire_stale_proposals`

**Files:**
- Modify: `platform_v2/services/hiring_service.py`
- Modify: `platform_v2/tests/test_hiring_service.py`

- [ ] **Step 1: Append failing test**

```python
def test_expire_stale_updates_old_pending_rows():
    from services import hiring_service

    cur = MagicMock()
    cur.rowcount = 4
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur),
                               __exit__=lambda self, *a: False),
    ):
        out = hiring_service.expire_stale_proposals(max_age_days=14)
    assert out == 4
```

- [ ] **Step 2: Verify fail**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v -k expire`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace `expire_stale_proposals` stub:

```python
def expire_stale_proposals(max_age_days: int = DEFAULT_EXPIRY_DAYS) -> int:
    """Flip pending rows older than max_age_days to 'expired'. Returns affected count."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'expired'
             WHERE status = 'pending'
               AND proposed_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (max_age_days,),
        )
        return cur.rowcount
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform pytest tests/test_hiring_service.py -v`
Expected: 10 pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/hiring_service.py platform_v2/tests/test_hiring_service.py
git commit -m "$(cat <<'EOF'
feat(hiring): expire_stale_proposals (#2102)

Daily sweep that flips any pending hiring_candidates row older than
14 days to 'expired'. Keeps the queue clean when Kytran ignores a
proposal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Extend unified approvals endpoint with `hire:` UNION branch

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Create: `platform_v2/tests/test_approvals_hire_routes.py`

- [ ] **Step 1: Write failing route test**

```python
# platform_v2/tests/test_approvals_hire_routes.py
"""Route tests for the hire: source in the unified approvals endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def authed_client(client, admin_user):
    """Fixture provided by conftest: Flask test client logged in as admin."""
    return client


def test_pending_endpoint_unions_hire_rows(authed_client):
    from database import get_db_cursor

    # seed a pending hire_candidates row
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """INSERT INTO hiring_candidates
                 (capability, gap_reason, shortlist, narrative)
               VALUES ('translate', 'only 2 active', '[]'::jsonb, 'why these 3')
               RETURNING id""",
        )
        hire_id = cur.fetchone()["id"]

    resp = authed_client.get("/api/approvals/pending")
    assert resp.status_code == 200
    data = resp.get_json()
    ids = [r.get("id") for r in data.get("rows", data if isinstance(data, list) else [])]
    assert f"hire:{hire_id}" in ids

    # cleanup
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("DELETE FROM hiring_candidates WHERE id = %s", (hire_id,))
```

Note on fixtures: the exact fixture names (`client`, `admin_user`, `authed_client`) depend on what `conftest.py` already exposes. Inspect the existing `test_approvals_routes.py` (if present) or other DHQ route tests for patterns; match them. If no auth fixture exists, use `pytest.mark.skip` with a reason and mark it for a follow-up.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py -v`
Expected: FAIL (the `hire:N` id isn't produced by the current endpoint).

- [ ] **Step 3: Extend the endpoint**

Read the existing `approvals_pending` function in `approvals_routes.py` starting at line 155. Locate where the three existing sources are UNION'd or concatenated (autonomy / contractor / bridge). Add a fourth source-gathering block following the same idiom:

```python
    # ---- Hire candidate proposals (Phase A of task #2102) ----
    hire_rows = []
    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT
                    hc.id,
                    hc.capability,
                    hc.gap_reason,
                    hc.narrative,
                    hc.shortlist,
                    hc.proposed_at,
                    hc.proposed_by_agent_id,
                    a.display_name AS proposer_name
                FROM hiring_candidates hc
                LEFT JOIN agents a ON a.id = hc.proposed_by_agent_id
                WHERE hc.status = 'pending'
                ORDER BY hc.proposed_at DESC
                """
            )
            for r in cur.fetchall():
                rd = dict(r)
                hire_rows.append({
                    "id": f"hire:{rd['id']}",
                    "source": "hire",
                    "category": "hiring",
                    "display_name": rd["capability"],
                    "reason": rd.get("narrative") or rd.get("gap_reason"),
                    "agent_name": rd.get("proposer_name") or "K.I.N.",
                    "created_at": rd["proposed_at"].isoformat() if rd.get("proposed_at") else None,
                    "payload": {
                        "shortlist": rd.get("shortlist") or [],
                        "gap_reason": rd.get("gap_reason"),
                        "narrative": rd.get("narrative"),
                    },
                })
    except Exception:
        logger.exception("Failed to fetch hiring_candidates for approvals endpoint")

    # Append to whatever collection holds the existing sources. If existing
    # code returns `{"rows": [...]}`, extend that list. Match the existing
    # idiom — do not restructure the response shape.
```

Patch this block into the existing function so `hire_rows` merges into whatever response list autonomy/contractor/bridge already contribute to. The exact merge site depends on the existing code shape — locate via `grep -n 'autonomy:' approvals_routes.py` to find where the `f"autonomy:{id}"` format appears, and insert immediately after that block.

- [ ] **Step 4: Run test to verify pass**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py::test_pending_endpoint_unions_hire_rows -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py \
        platform_v2/tests/test_approvals_hire_routes.py
git commit -m "$(cat <<'EOF'
feat(approvals): union hire: source into unified pending endpoint (#2102)

Adds a fourth source to GET /api/approvals/pending alongside the
existing autonomy/contractor/bridge rows. Source-prefixed IDs follow
the established pattern: hire:<id>. Payload carries the shortlist
JSONB so the frontend can render the radio picker in one round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `POST /api/approvals/hire/<id>/approve` handler

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/tests/test_approvals_hire_routes.py`

- [ ] **Step 1: Append failing test**

```python
def test_post_approve_hire_calls_service_and_returns_200(authed_client):
    from services import hiring_service as _svc

    with patch.object(
        _svc,
        "approve_candidate",
        return_value={"ok": True, "reason": "approved", "agent_id": 42},
    ) as mock_approve:
        resp = authed_client.post(
            "/api/approvals/hire/17/approve",
            json={"chosen_agent_id": 42, "notes": "go for it"},
        )
    assert resp.status_code == 200
    mock_approve.assert_called_once()
    call_kwargs = mock_approve.call_args.kwargs
    assert call_kwargs.get("hire_id") == 17
    assert call_kwargs.get("chosen_agent_id") == 42


def test_post_approve_hire_returns_409_on_precheck_failure(authed_client):
    from services import hiring_service as _svc

    with patch.object(
        _svc,
        "approve_candidate",
        return_value={"ok": False, "reason": "model_missing",
                      "agent_id": None, "message": "Model X missing"},
    ):
        resp = authed_client.post(
            "/api/approvals/hire/17/approve",
            json={"chosen_agent_id": 42},
        )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body.get("reason") == "model_missing"
```

- [ ] **Step 2: Verify fail**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py -v -k approve`
Expected: FAIL (404 — route doesn't exist).

- [ ] **Step 3: Add the route handler**

Append to `platform_v2/tools/department_hq/approvals_routes.py` inside the `register_approval_routes(bp, admin_required)` function body (or wherever existing `_approve_*` handlers are registered):

```python
    @bp.route("/api/approvals/hire/<int:hire_id>/approve", methods=["POST"])
    @login_required
    @admin_required
    def approve_hire(hire_id: int):
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        chosen_agent_id = body.get("chosen_agent_id")
        notes = body.get("notes", "") or ""
        if not isinstance(chosen_agent_id, int):
            return jsonify({"ok": False, "reason": "chosen_agent_id required"}), 400

        result = hiring_service.approve_candidate(
            hire_id=hire_id,
            chosen_agent_id=chosen_agent_id,
            decided_by_user_id=current_user.id,
            notes=notes,
        )

        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "candidate_not_in_shortlist": 400,
            "model_missing": 409,
            "ollama_unreachable": 409,
            "transition_failed": 500,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status
```

- [ ] **Step 4: Verify pass**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py -v -k approve`
Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py \
        platform_v2/tests/test_approvals_hire_routes.py
git commit -m "$(cat <<'EOF'
feat(approvals): POST /api/approvals/hire/<id>/approve (#2102)

Admin-only endpoint that delegates to hiring_service.approve_candidate
and maps result.reason to HTTP status codes (404 not_found,
409 already_decided/race_lost/model_missing, 400 invalid_candidate,
500 transition_failed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `POST /api/approvals/hire/<id>/reject` handler

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/tests/test_approvals_hire_routes.py`

- [ ] **Step 1: Append failing test**

```python
def test_post_reject_hire_calls_service_and_returns_200(authed_client):
    from services import hiring_service as _svc

    with patch.object(
        _svc,
        "reject_candidate",
        return_value={"ok": True, "reason": "rejected"},
    ) as mock_reject:
        resp = authed_client.post(
            "/api/approvals/hire/17/reject",
            json={"notes": "not a fit"},
        )
    assert resp.status_code == 200
    mock_reject.assert_called_once()
    assert mock_reject.call_args.kwargs.get("hire_id") == 17
```

- [ ] **Step 2: Verify fail**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py -v -k reject`
Expected: FAIL (404).

- [ ] **Step 3: Add handler**

Append (adjacent to `approve_hire`):

```python
    @bp.route("/api/approvals/hire/<int:hire_id>/reject", methods=["POST"])
    @login_required
    @admin_required
    def reject_hire(hire_id: int):
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        notes = body.get("notes", "") or ""

        result = hiring_service.reject_candidate(
            hire_id=hire_id,
            decided_by_user_id=current_user.id,
            notes=notes,
        )
        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status
```

- [ ] **Step 4: Verify pass + full route-test suite**

Run: `docker exec archie_platform pytest tests/test_approvals_hire_routes.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py \
        platform_v2/tests/test_approvals_hire_routes.py
git commit -m "$(cat <<'EOF'
feat(approvals): POST /api/approvals/hire/<id>/reject (#2102)

Admin-only reject endpoint. Mirrors approve_hire's shape with a
smaller status_map (no precheck, no transition).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `kin_generate_hire_proposals` job + registration

**Files:**
- Modify: `platform_v2/services/agent_jobs.py`
- Create: `platform_v2/tests/test_kin_generate_hire_proposals.py`

- [ ] **Step 1: Write failing test**

```python
# platform_v2/tests/test_kin_generate_hire_proposals.py
"""Job-level test for kin_generate_hire_proposals."""
from __future__ import annotations

from unittest.mock import patch


def test_job_inserts_up_to_max_proposals_per_run():
    from services import agent_jobs

    fake_gaps = [{"capability": f"skill_{i}", "gap_reason": "gap"} for i in range(25)]
    with patch(
        "services.agent_jobs._list_current_capability_gaps",
        return_value=fake_gaps,
    ), patch(
        "services.hiring_service.get_shortlist",
        return_value=[{"agent_id": 1, "display_name": "A",
                        "proficiency_level": 5, "department": "X",
                        "decommissioned_at": None, "primary_model": "m"}],
    ), patch(
        "services.hiring_service.propose_for_gap",
        return_value=42,  # pretend every proposal inserts
    ) as mock_propose, patch(
        "services.agent_jobs._generate_hire_narrative",
        return_value=None,
    ), patch("services.agent_jobs._log_cycle"):
        agent_jobs.kin_generate_hire_proposals(max_proposals_per_run=10)
    assert mock_propose.call_count == 10


def test_job_skips_empty_shortlists():
    from services import agent_jobs

    fake_gaps = [{"capability": "rare", "gap_reason": "gap"}]
    with patch(
        "services.agent_jobs._list_current_capability_gaps",
        return_value=fake_gaps,
    ), patch(
        "services.hiring_service.get_shortlist",
        return_value=[],
    ), patch("services.hiring_service.propose_for_gap") as mock_propose, \
       patch("services.agent_jobs._generate_hire_narrative", return_value=None), \
       patch("services.agent_jobs._log_cycle"):
        agent_jobs.kin_generate_hire_proposals()
    mock_propose.assert_not_called()
```

- [ ] **Step 2: Verify fail**

Run: `docker exec archie_platform pytest tests/test_kin_generate_hire_proposals.py -v`
Expected: FAIL (`kin_generate_hire_proposals` not defined).

- [ ] **Step 3: Implement**

Append to `platform_v2/services/agent_jobs.py`:

```python
# K.I.N. agent id — looked up in prior session (agents.id=145).
# Falls back to NULL if the row is missing — narrative attribution is best-effort.
KIN_AGENT_ID = 145
MAX_PROPOSALS_PER_RUN = 10


def _list_current_capability_gaps() -> list[dict[str, Any]]:
    """Re-run the same WITH clause check_understaffed_capabilities uses.

    Single source of truth — avoids cross-table dependency on
    system_notifications / autonomy_loop_log for the gap list.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            WITH all_capabilities AS (
                SELECT DISTINCT skill_name
                FROM agent_skills
                WHERE proficiency_level >= 4
            ),
            staffed AS (
                SELECT DISTINCT s.skill_name
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                LEFT JOIN agent_budgets b ON b.agent_id = a.id
                WHERE s.proficiency_level >= 4
                  AND a.shift_state = 'active'
                  AND (b.agent_id IS NULL
                       OR b.current_task_count < COALESCE(b.task_queue_limit, 100))
            )
            SELECT skill_name AS capability
            FROM all_capabilities
            WHERE skill_name NOT IN (SELECT skill_name FROM staffed)
            ORDER BY skill_name
            """
        )
        return [
            {"capability": r["capability"],
             "gap_reason": f"No active Lv4+ dispatchable agent for '{r['capability']}'"}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def _generate_hire_narrative(
    gap: dict[str, Any], shortlist: list[dict[str, Any]]
) -> Optional[str]:
    """Best-effort K.I.N. narrative via bridge dispatch. Returns None on failure."""
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        candidate_lines = "\n".join(
            f"- {e.get('display_name','?')} (dept={e.get('department','?')}, "
            f"skill level={e.get('proficiency_level','?')}, "
            f"model={e.get('primary_model','?')})"
            for e in shortlist
        )
        prompt = (
            f"The capability '{gap['capability']}' is understaffed. "
            f"Reason: {gap['gap_reason']}.\n\n"
            f"Three decommissioned specialists are shortlisted:\n{candidate_lines}\n\n"
            "Write a concise 2-3 sentence rationale explaining why this gap matters "
            "and why these specific candidates are sensible picks. No preamble."
        )
        result = dispatch(
            capability="workforce_planning",
            prompt=prompt,
            agent="K.I.N.",
        )
        if result and getattr(result, "success", False):
            return (result.response or "").strip() or None
    except Exception as e:
        logger.info("K.I.N. narrative dispatch failed (non-fatal): %s", e)
    return None


def kin_generate_hire_proposals(max_proposals_per_run: int = MAX_PROPOSALS_PER_RUN):
    """Daily ~09:05 UTC. Generate hiring_candidates rows for understaffed capabilities.

    Flow per gap:
      1. SQL shortlist (top 3 decommissioned agents at Lv3+).
      2. Best-effort K.I.N. narrative via bridge dispatch.
      3. Insert via hiring_service.propose_for_gap (dedup handled there).
    """
    from services import hiring_service

    start = time.time()
    inserted = 0
    skipped_empty = 0
    skipped_dedup = 0

    try:
        gaps = _list_current_capability_gaps()
        for gap in gaps:
            if inserted >= max_proposals_per_run:
                break
            shortlist = hiring_service.get_shortlist(gap["capability"], limit=3)
            if not shortlist:
                skipped_empty += 1
                continue
            narrative = _generate_hire_narrative(gap, shortlist)
            row_id = hiring_service.propose_for_gap(
                capability=gap["capability"],
                gap_reason=gap["gap_reason"],
                shortlist=shortlist,
                narrative=narrative,
                proposed_by_agent_id=KIN_AGENT_ID,
            )
            if row_id is None:
                skipped_dedup += 1
            else:
                inserted += 1

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "kin_generate_hire_proposals",
            inserted,
            0,
            duration_ms,
            details={
                "gaps_seen": len(gaps),
                "inserted": inserted,
                "skipped_empty_shortlist": skipped_empty,
                "skipped_dedup": skipped_dedup,
            },
        )
    except Exception as e:
        logger.exception("kin_generate_hire_proposals failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "kin_generate_hire_proposals", 0, 1, duration_ms, error_message=str(e)
        )
```

- [ ] **Step 4: Register in the scheduler**

Find the scheduler setup block at the bottom of `agent_jobs.py` (search for `with_ctx(check_understaffed_capabilities)` from prior exploration). Add immediately after its `add_job` call:

```python
    scheduler.add_job(
        with_ctx(kin_generate_hire_proposals),
        trigger=CronTrigger(hour=9, minute=5, timezone="UTC"),
        id="kin_generate_hire_proposals",
        name="Agent Loop: Hire Proposals",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] **Step 5: Verify pass**

Run: `docker exec archie_platform pytest tests/test_kin_generate_hire_proposals.py -v`
Expected: 2 pass.

Also smoke: `docker exec archie_platform python -c "from services import agent_jobs; print(agent_jobs.kin_generate_hire_proposals)"`
Expected: function object printed.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/agent_jobs.py \
        platform_v2/tests/test_kin_generate_hire_proposals.py
git commit -m "$(cat <<'EOF'
feat(hiring): kin_generate_hire_proposals daily job (#2102)

Runs 09:05 UTC after agent_understaffed_digest. Re-runs the same
WITH clause as check_understaffed_capabilities (single source of
truth) and for each gap: SQL shortlist → best-effort K.I.N.
narrative via bridge dispatch → propose_for_gap (which dedups).
Caps at MAX_PROPOSALS_PER_RUN=10 per run to avoid flooding the
queue on initial adoption (current gap volume is ~214).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Register `expire_stale_hire_proposals` scheduled job

**Files:**
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 1: Add thin wrapper + schedule**

Append to `agent_jobs.py` near the other wrappers:

```python
def expire_stale_hire_proposals():
    """Daily 04:30 UTC. Flip pending hiring_candidates > 14d old to 'expired'."""
    from services import hiring_service

    start = time.time()
    try:
        n = hiring_service.expire_stale_proposals(max_age_days=14)
        _log_cycle(
            "expire_stale_hire_proposals", n, 0,
            int((time.time() - start) * 1000),
            details={"expired": n},
        )
    except Exception as e:
        logger.exception("expire_stale_hire_proposals failed")
        _log_cycle(
            "expire_stale_hire_proposals", 0, 1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )
```

Register adjacent to `kin_generate_hire_proposals`:

```python
    scheduler.add_job(
        with_ctx(expire_stale_hire_proposals),
        trigger=CronTrigger(hour=4, minute=30, timezone="UTC"),
        id="expire_stale_hire_proposals",
        name="Agent Loop: Expire Stale Hire Proposals",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] **Step 2: Smoke**

Run: `docker exec archie_platform python -c "from services import agent_jobs; agent_jobs.expire_stale_hire_proposals()"`
Expected: no exception (no-op on a fresh DB — 0 rows affected).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/agent_jobs.py
git commit -m "$(cat <<'EOF'
feat(hiring): expire_stale_hire_proposals daily job (#2102)

04:30 UTC sweep that flips pending rows older than 14 days to
'expired'. Keeps the approvals queue clean when proposals go
unreviewed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: PR 1 post-implementation manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Apply the migration in the live DB** (already done in Task 1 Step 5).

- [ ] **Step 2: Run the job once manually**

```
docker exec archie_platform python -c "from services import agent_jobs; agent_jobs.kin_generate_hire_proposals(max_proposals_per_run=3)"
```

Expect: no exception; some rows appear in `hiring_candidates`:
```
docker exec archie_database psql -U archie -d archie -c "SELECT id, capability, status, jsonb_array_length(shortlist) FROM hiring_candidates ORDER BY id DESC LIMIT 5"
```

- [ ] **Step 3: Hit the unified endpoint**

```
curl -s http://192.168.1.200:3000/api/approvals/pending -H "Cookie: <admin session>"  | jq '.[] | select(.source=="hire")' | head
```

Expect: JSON rows with `id=hire:N`, category=hiring, payload.shortlist non-empty.

- [ ] **Step 4: Open PR**

```bash
git push -u origin feat/dhq-hiring-queue-spec
gh pr create --title "feat(hiring): DHQ Hiring Queue — backend (#2102 PR 1)" \
  --body "PR 1 of 2 for task #2102. Schema + service + jobs + unified-endpoint extension + approve/reject handlers. PR 2 adds the DHQ tab UI."
```

Do NOT merge yet. PR 2 (UI) lands on the same branch; final merge happens after UI smoke.

---

## PR 2 — Frontend: DHQ Approvals tab UI for the `hire:` source

### Task 13: Locate existing DHQ Approvals UI + read current rendering

**Files:** read-only

- [ ] **Step 1: Find the JS file that renders the Approvals tab**

Run:
```
grep -rn "autonomy:\|contractor:\|bridge:" platform_v2/tools/department_hq/ \
    platform_v2/static/ 2>/dev/null | grep -v test | head
```

Likely candidates: `platform_v2/tools/department_hq/static/js/department_hq_approvals.js`, or an inline script in the DHQ template. Confirm the file path before editing.

- [ ] **Step 2: Read the render function**

Read the file. Identify:
- How source-pill colors/labels are assigned per source
- How the "Approve" / "Deny" buttons are wired
- Which API paths they POST to

Take notes in `docs/superpowers/plans/2026-04-19-dhq-hiring-queue-plan-notes.md` (if needed for your own use — don't commit unless the plan explicitly says so).

No code changes in this task. This is a reconnaissance step so Task 14's edit is surgical.

---

### Task 14: Render `hire:` source pill + shortlist card

**Files:**
- Modify: the JS file located in Task 13 (e.g., `platform_v2/tools/department_hq/static/js/department_hq_approvals.js`)

- [ ] **Step 1: Extend the source-pill dispatcher**

Near the existing pill-label map (something like `const PILLS = {autonomy: 'AUTONOMY', ...}`), add:

```javascript
  hire: { label: 'HIRE', color: '#7b5ea7' },  // LCARS purple
```

- [ ] **Step 2: Extend the card renderer for `source === 'hire'`**

Find the function that builds each approval card (likely named `renderApprovalCard` or similar). Add a branch:

```javascript
  if (row.source === 'hire') {
    const shortlist = (row.payload && row.payload.shortlist) || [];
    const picker = shortlist.map((c, i) => `
      <label class="hire-candidate">
        <input type="radio" name="hire-${row.id}" value="${c.agent_id}" ${i === 0 ? 'checked' : ''}>
        <strong>${escapeHtml(c.display_name || '?')}</strong>
        <span class="muted">${escapeHtml(c.department || '')} · Lv${c.proficiency_level || '?'} · ${escapeHtml(c.primary_model || 'no model')}</span>
      </label>
    `).join('');

    return `
      <article class="approval-card approval-card--hire" data-id="${row.id}">
        <header>
          <span class="pill hire">HIRE</span>
          <h3>${escapeHtml(row.display_name)}</h3>
        </header>
        <p class="reason">${escapeHtml(row.reason || '')}</p>
        <div class="shortlist">${picker}</div>
        <footer>
          <button class="btn btn-approve" data-action="approve-hire">Approve selected</button>
          <button class="btn btn-reject"  data-action="reject-hire">Reject</button>
        </footer>
      </article>
    `;
  }
```

(Adjust class names / DOM idioms to match existing card templates — match neighbouring cards exactly.)

- [ ] **Step 3: Wire the click handlers**

In the delegated click handler (likely `document.querySelector('.approvals').addEventListener('click', ...)`), add:

```javascript
  if (target.dataset.action === 'approve-hire') {
    const card = target.closest('.approval-card');
    const id = card.dataset.id;                    // 'hire:17'
    const hireId = id.split(':')[1];
    const picked = card.querySelector(`input[name="hire-${id}"]:checked`);
    if (!picked) { alert('Pick a candidate first.'); return; }
    const resp = await fetch(`/api/approvals/hire/${hireId}/approve`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ chosen_agent_id: Number(picked.value), notes: '' }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      alert(`Approval failed: ${body.reason || resp.status} ${body.message || ''}`);
      return;
    }
    card.remove();
    return;
  }
  if (target.dataset.action === 'reject-hire') {
    const card = target.closest('.approval-card');
    const id = card.dataset.id;
    const hireId = id.split(':')[1];
    const resp = await fetch(`/api/approvals/hire/${hireId}/reject`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ notes: '' }),
    });
    if (!resp.ok) { alert('Reject failed.'); return; }
    card.remove();
    return;
  }
```

- [ ] **Step 4: Manual browser smoke**

1. Restart platform: `docker compose restart archie_platform`
2. Browse to `http://192.168.1.200:3000/tools/department-hq/#approvals`
3. Confirm the HIRE pill renders for any pending hire: row.
4. Pick a candidate, click "Approve selected" — confirm:
   - Card disappears on 200
   - `agents.shift_state` for chosen candidate is now `'active'` (check via psql)
   - `hiring_candidates.status` is now `'approved'`
5. Pick a different row, click "Reject" — card disappears, `hiring_candidates.status='rejected'`.
6. Approve a proposal where the chosen candidate's model is NOT on the hub — confirm UI shows the precheck error alert, card stays in queue, `hiring_candidates.precheck_status='model_missing'`.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department_hq_approvals.js
git commit -m "$(cat <<'EOF'
feat(dhq-ui): render hire: source pill + shortlist picker (#2102 PR 2)

Adds the HIRE source pill, shortlist radio picker, and
Approve/Reject click handlers that POST to the new endpoints.
Manual browser smoke: approval transitions a decommissioned agent
to active; pre-check failure keeps the row in the queue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Close out PR + Dev HQ updates

**Files:** none (workflow only)

- [ ] **Step 1: Push final commit + update the PR body**

```
git push
```

Update the open PR's body (via `gh pr edit`) to reflect that PR 2 has landed on the same branch.

- [ ] **Step 2: Merge** (user approval)

```
gh pr merge <N> --squash --delete-branch
git checkout main && git pull --ff-only
```

- [ ] **Step 3: Dev HQ workflow**

Per CLAUDE.md post-commit protocol:
```
mcp complete_task task_id=2102 notes="..."
mcp log_decision title="DHQ Hiring Queue — phase A+B shipped" ...
mcp update_project_understanding project_id=261 understanding_level=100
mcp store_memory knowledge_type=vault_note title="hiring_service public API" ...
```

Project #261 moves to 51/51 (complete).

---

## Self-Review (completed)

**1. Spec coverage:** Every spec section maps to a task —
- §'New table hiring_candidates' → Task 1
- §'get_shortlist' / shortlist SQL → Task 2
- §'propose_for_gap' + dedup → Task 3
- §'Approve flow' + pre-check → Task 4
- §'Reject flow' → Task 5
- §'Expiry' / 14-day rule → Task 6 + Task 11
- §'Unified endpoint extension' → Task 7
- §'Approve / reject endpoints' → Tasks 8–9
- §'K.I.N. proposal generation' → Task 10
- §'Observability' → Task 10 (_log_cycle), Task 4 (audit log)
- §'Testing' → interleaved per-task + final manual smoke (Task 12, Task 14 Step 4)
- §'Delivery plan PR 1 / PR 2' → Task 12 / Task 15

**2. Placeholder scan:** Intentional placeholders flagged inline —
- `NNN` migration number (Task 1 Step 1 resolves)
- Exact JS filename (Task 13 resolves via grep)
- Exact `agent_models` schema (Task 2 flags fallback path)
None are load-bearing at plan time.

**3. Type consistency:** All service functions use the kwargs signatures defined in Task 2's stubs. `hire_id`, `chosen_agent_id`, `decided_by_user_id`, `notes` appear identically in service + routes + tests.
