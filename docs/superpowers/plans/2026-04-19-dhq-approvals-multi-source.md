# DHQ Approvals — Multi-Source Dispatch + Escalation Display — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DHQ Approvals tab's approve/deny buttons work for all three approval sources (autonomy_approval_queue, contractor_approval_requests, bridge_jobs), render source-specific card details with an escalation-chain line, log escalation Telegrams to the COMs feed, and mirror escalations into `unified_messages` so they appear in A.R.C.H.I.E.'s unified chat view.

**Architecture:** Backend handlers split the prefixed approval ID (`autonomy:123` / `contractor:456` / `bridge:789`) and dispatch to per-source SQL helpers. The `/pending` response grows an `escalation_chain` field derived from the originating agent's department. `/history` becomes a UNION over all three tables. The frontend row renderer grows two new category branches + a source badge pill + an escalation-chain line. `send_escalation_notification` is patched to write to both `telegram_message_log` (DHQ COMs) and `unified_messages` (A.R.C.H.I.E. Chat — Project #265).

**Tech Stack:** Flask (Python 3.11), psycopg2, PostgreSQL, vanilla JS + LCARS CSS, pytest, Playwright (optional for browser verification).

**Spec:** `docs/superpowers/specs/2026-04-19-dhq-approvals-multi-source-design.md`

**Alignment:** Project #265 (A.R.C.H.I.E. Unified Communications) — unified_conversations + unified_messages are the canonical store for cross-channel user↔A.R.C.H.I.E. dialog. Escalations are part of that dialog.

**Branch:** `feat/dhq-approvals-multi-source` (already created, spec already committed)

---

## File Structure

**Create:**
- `database/migrations/approvals_multi_source_audit_columns.sql` — idempotent migration adding `denied_by` / `denied_at` to `contractor_approval_requests` and approval/cancellation audit columns to `bridge_jobs`.
- `platform_v2/tests/test_approvals_multi_source.py` — pytest unit + integration tests for the new endpoints + escalation logging.

**Modify:**
- `platform_v2/tools/department_hq/approvals_routes.py` — change route path to `<path:approval_id>`, add per-source approve/deny helpers, extend `/pending` with `escalation_chain`, rewrite `/history` as 3-way UNION.
- `platform_v2/tools/department_hq/templates/department_hq.html` — extend `_renderApprovalCard` with `contractor_dispatch` + `cloud_dispatch` branches, add source badge pill + escalation-chain line.
- `ai_bridge/telegram_gateway.py` — patch `send_escalation_notification` to insert into `telegram_message_log` AND `unified_messages` after each successful `bot.send_message`.

---

## Task 1: Schema discovery + migration

**Files:**
- Read: `platform_v2/tools/department_hq/approvals_routes.py`
- Create: `database/migrations/approvals_multi_source_audit_columns.sql`

- [ ] **Step 1: Confirm missing columns**

Run:
```bash
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='contractor_approval_requests' ORDER BY column_name;"
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='bridge_jobs' ORDER BY column_name;"
```

Expected:
- `contractor_approval_requests` should have `approved_by`, `approved_at`, `denial_reason` but NOT `denied_by` or `denied_at`.
- `bridge_jobs` should have `status`, `error_message`, `metadata`, `completed_at` but NOT `approved_by`, `approved_at`, `cancellation_reason`, `cancelled_by`, `cancelled_at`.

If actual state already has those columns, skip steps 2–3 and go to Task 2. If a column exists under a different name than assumed below, adjust the migration to match — don't rename existing columns.

- [ ] **Step 2: Write the migration**

Create `database/migrations/approvals_multi_source_audit_columns.sql`:

```sql
-- Audit columns for multi-source approvals UI (spec 2026-04-19-dhq-approvals-multi-source-design).
-- Idempotent: safe to run multiple times.

-- contractor_approval_requests: add denied_by + denied_at so web deny can mirror autonomy audit shape.
ALTER TABLE contractor_approval_requests
    ADD COLUMN IF NOT EXISTS denied_by INTEGER,
    ADD COLUMN IF NOT EXISTS denied_at TIMESTAMP WITHOUT TIME ZONE;

-- bridge_jobs: add approval + cancellation audit columns.
ALTER TABLE bridge_jobs
    ADD COLUMN IF NOT EXISTS approved_by INTEGER,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS cancelled_by INTEGER,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
```

- [ ] **Step 3: Apply the migration**

Run:
```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/approvals_multi_source_audit_columns.sql
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='contractor_approval_requests' AND column_name IN ('denied_by','denied_at');"
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='bridge_jobs' AND column_name IN ('approved_by','approved_at','cancelled_by','cancelled_at','cancellation_reason');"
```

Expected: both verification queries return the added columns.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/approvals_multi_source_audit_columns.sql
git commit -m "feat(db): add audit columns for multi-source approvals

contractor_approval_requests: denied_by, denied_at
bridge_jobs: approved_by/at, cancelled_by/at, cancellation_reason

Idempotent — safe re-run. Supports DHQ Approvals multi-source spec."
```

---

## Task 2: Approve endpoint — refactor to per-source helpers

**Files:**
- Create: `platform_v2/tests/test_approvals_multi_source.py`
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`

- [ ] **Step 1: Read the current approvals_routes.py end-to-end**

`cat /mnt/archie_brain/platform_v2/tools/department_hq/approvals_routes.py`

Note the route signatures on lines 158 (`/approve`) and 197 (`/deny`) — both use `<int:approval_id>`. Note the handler structures so you can preserve logging and response shapes.

- [ ] **Step 2: Write the failing test**

Create `platform_v2/tests/test_approvals_multi_source.py`:

```python
"""Tests for multi-source approval endpoints.

Covers autonomy_approval_queue, contractor_approval_requests, and bridge_jobs
via the unified /api/approvals/<prefix:id>/(approve|deny) endpoints.
"""
import pytest
from datetime import datetime, timedelta


@pytest.fixture
def admin_client(app, db_conn):
    """Flask test client logged in as an admin user. Uses the platform's
    existing conftest.py fixtures — adapt fixture names to what conftest
    provides if they differ."""
    with app.test_client() as client:
        client.post("/login", data={"username": "admin", "password": "test_admin_pw"})
        yield client


def _seed_autonomy_row(db_conn, action_type="test_action"):
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO autonomy_approval_queue
               (action_type, action_data, tier, status, priority, requested_by, reason)
               VALUES (%s, '{}'::jsonb, 2, 'pending', 5, 'test', 'test reason')
               RETURNING id""",
            (action_type,),
        )
        return cur.fetchone()[0]


def _seed_contractor_row(db_conn, agent_id=None):
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO contractor_approval_requests
               (agent_id, task_type, task_description, status, priority,
                contractor_provider, contractor_model, estimated_cost, estimated_tokens)
               VALUES (%s, 'test_task', 'test desc', 'pending', 'normal',
                       'openai', 'gpt-4o-mini', 0.02, 1000)
               RETURNING id""",
            (agent_id,),
        )
        return cur.fetchone()[0]


def _seed_bridge_row(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bridge_jobs
               (job_type, module_source, description, status, agent_name, total_steps, completed_steps)
               VALUES ('test', 'test_module', 'test desc', 'pending_approval', 'test_agent', 1, 0)
               RETURNING id""",
        )
        return cur.fetchone()[0]


class TestApprove:
    def test_approve_autonomy_ok(self, admin_client, db_conn):
        row_id = _seed_autonomy_row(db_conn)
        resp = admin_client.post(f"/tools/department-hq/api/approvals/autonomy:{row_id}/approve")
        assert resp.status_code == 200
        assert resp.json["success"] is True
        with db_conn.cursor() as cur:
            cur.execute("SELECT status, approved_by FROM autonomy_approval_queue WHERE id=%s", (row_id,))
            status, approved_by = cur.fetchone()
        assert status == "approved"
        assert approved_by is not None

    def test_approve_contractor_sets_14d_expiry(self, admin_client, db_conn):
        row_id = _seed_contractor_row(db_conn)
        resp = admin_client.post(f"/tools/department-hq/api/approvals/contractor:{row_id}/approve")
        assert resp.status_code == 200
        assert resp.json["success"] is True
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, approved_by, expires_at FROM contractor_approval_requests WHERE id=%s",
                (row_id,),
            )
            status, approved_by, expires_at = cur.fetchone()
        assert status == "approved"
        assert approved_by is not None
        expected = datetime.utcnow() + timedelta(days=14)
        assert abs((expires_at - expected).total_seconds()) < 3600

    def test_approve_bridge_flips_status(self, admin_client, db_conn):
        row_id = _seed_bridge_row(db_conn)
        resp = admin_client.post(f"/tools/department-hq/api/approvals/bridge:{row_id}/approve")
        assert resp.status_code == 200
        assert resp.json["success"] is True
        with db_conn.cursor() as cur:
            cur.execute("SELECT status, approved_by FROM bridge_jobs WHERE id=%s", (row_id,))
            status, approved_by = cur.fetchone()
        assert status == "approved"
        assert approved_by is not None

    def test_approve_invalid_prefix_400(self, admin_client):
        resp = admin_client.post("/tools/department-hq/api/approvals/junk:123/approve")
        assert resp.status_code == 400

    def test_approve_already_processed_404(self, admin_client, db_conn):
        row_id = _seed_autonomy_row(db_conn)
        admin_client.post(f"/tools/department-hq/api/approvals/autonomy:{row_id}/approve")
        resp2 = admin_client.post(f"/tools/department-hq/api/approvals/autonomy:{row_id}/approve")
        assert resp2.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestApprove -v
```

Expected: all five approve tests FAIL — route regex still requires `<int:>`; `autonomy:123` doesn't match. Already-processed test may pass (existing autonomy code already returns 404 on re-approve).

If conftest.py doesn't provide `app` and `db_conn` fixtures in the shape assumed above, look at the existing `conftest.py` (`cat /mnt/archie_brain/platform_v2/tests/conftest.py`) and adapt the fixture names — do NOT rewrite conftest. Match what's there.

- [ ] **Step 4: Refactor the approve endpoint**

Edit `platform_v2/tools/department_hq/approvals_routes.py`. Replace the existing `approvals_approve` function (lines ~158–195) with:

```python
    @bp.route("/api/approvals/<path:approval_id>/approve", methods=["POST"])
    @login_required
    @admin_required_decorator
    def approvals_approve(approval_id):
        """Approve a pending approval via web UI (mirrors Telegram approve).

        Accepts source-prefixed IDs: `autonomy:123`, `contractor:456`, `bridge:789`.
        Dispatches to the appropriate per-source helper.
        """
        try:
            prefix, _, raw_id = approval_id.partition(":")
            if not raw_id or prefix not in ("autonomy", "contractor", "bridge"):
                return jsonify({"success": False, "error": "Invalid approval ID format"}), 400
            try:
                source_id = int(raw_id)
            except ValueError:
                return jsonify({"success": False, "error": "Invalid approval ID"}), 400

            if prefix == "autonomy":
                ok, action_type = _approve_autonomy(source_id, current_user.id)
            elif prefix == "contractor":
                ok, action_type = _approve_contractor(source_id, current_user.id)
            else:  # bridge
                ok, action_type = _approve_bridge(source_id, current_user.id)

            if not ok:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            logger.info(
                "Approval %s (%s) approved via web by user %s",
                approval_id,
                action_type,
                current_user.id,
            )
            return jsonify(
                {
                    "success": True,
                    "approval_id": approval_id,
                    "action_type": action_type,
                }
            )
        except Exception as exc:
            logger.error("approvals_approve error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
```

Add these helpers at module scope (below the existing imports, above `register_approvals_routes`):

```python
def _approve_autonomy(source_id: int, user_id: int):
    """Approve an autonomy_approval_queue row. Returns (ok, action_type)."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(), updated_at = NOW()
               WHERE id = %s AND status = 'pending'
               RETURNING action_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["action_type"] if isinstance(row, dict) else row[0])


def _approve_contractor(source_id: int, user_id: int):
    """Approve a contractor_approval_requests row. Sets 14-day expiry window.

    The 14-day expires_at aligns with the re-check in
    archie_bridge.request_contractor_approval, which only honors approvals
    where expires_at IS NULL OR expires_at > NOW().
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE contractor_approval_requests
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(),
                   expires_at = NOW() + INTERVAL '14 days'
               WHERE id = %s AND status = 'pending'
               RETURNING task_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["task_type"] if isinstance(row, dict) else row[0])


def _approve_bridge(source_id: int, user_id: int):
    """Approve a bridge_jobs row (pending_approval → approved).

    NOTE: No resume consumer exists yet — this is a flag-only approval. The
    original dispatch does not auto-retry. Resume path is a follow-up task.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE bridge_jobs
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(), updated_at = NOW()
               WHERE id = %s AND status = 'pending_approval'
               RETURNING job_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["job_type"] if isinstance(row, dict) else row[0])
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestApprove -v
```

Expected: all five approve tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "feat(dhq): multi-source approve endpoint

Route now accepts <path:approval_id> with prefix (autonomy|contractor|bridge).
Per-source helpers updated their own tables. Contractor sets 14-day expiry
to match archie_bridge.request_contractor_approval lookup window.

Bridge approval flips status to 'approved' but no consumer exists yet
to resume the original dispatch — follow-up task."
```

---

## Task 3: Deny endpoint — mirror the approve refactor

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/tests/test_approvals_multi_source.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_approvals_multi_source.py`:

```python
class TestDeny:
    def test_deny_autonomy_records_reason(self, admin_client, db_conn):
        row_id = _seed_autonomy_row(db_conn)
        resp = admin_client.post(
            f"/tools/department-hq/api/approvals/autonomy:{row_id}/deny",
            json={"reason": "Not needed"},
        )
        assert resp.status_code == 200
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, rejected_reason FROM autonomy_approval_queue WHERE id=%s",
                (row_id,),
            )
            status, reason = cur.fetchone()
        assert status == "rejected"
        assert reason == "Not needed"

    def test_deny_contractor_records_reason(self, admin_client, db_conn):
        row_id = _seed_contractor_row(db_conn)
        resp = admin_client.post(
            f"/tools/department-hq/api/approvals/contractor:{row_id}/deny",
            json={"reason": "Too expensive"},
        )
        assert resp.status_code == 200
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, denial_reason, denied_by FROM contractor_approval_requests WHERE id=%s",
                (row_id,),
            )
            status, reason, denied_by = cur.fetchone()
        assert status == "denied"
        assert reason == "Too expensive"
        assert denied_by is not None

    def test_deny_bridge_cancels(self, admin_client, db_conn):
        row_id = _seed_bridge_row(db_conn)
        resp = admin_client.post(
            f"/tools/department-hq/api/approvals/bridge:{row_id}/deny",
            json={"reason": "Try local model first"},
        )
        assert resp.status_code == 200
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, cancellation_reason, cancelled_by FROM bridge_jobs WHERE id=%s",
                (row_id,),
            )
            status, reason, cancelled_by = cur.fetchone()
        assert status == "cancelled"
        assert reason == "Try local model first"
        assert cancelled_by is not None

    def test_deny_invalid_prefix_400(self, admin_client):
        resp = admin_client.post(
            "/tools/department-hq/api/approvals/junk:123/deny",
            json={"reason": "x"},
        )
        assert resp.status_code == 400
```

Run:
```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestDeny -v
```

Expected: all four deny tests FAIL.

- [ ] **Step 2: Refactor the deny endpoint**

Replace `approvals_deny` (lines ~197–225) with:

```python
    @bp.route("/api/approvals/<path:approval_id>/deny", methods=["POST"])
    @login_required
    @admin_required_decorator
    def approvals_deny(approval_id):
        """Deny a pending approval via web UI (mirrors Telegram deny).

        Accepts source-prefixed IDs: `autonomy:123`, `contractor:456`, `bridge:789`.
        Dispatches to the appropriate per-source helper.
        """
        try:
            prefix, _, raw_id = approval_id.partition(":")
            if not raw_id or prefix not in ("autonomy", "contractor", "bridge"):
                return jsonify({"success": False, "error": "Invalid approval ID format"}), 400
            try:
                source_id = int(raw_id)
            except ValueError:
                return jsonify({"success": False, "error": "Invalid approval ID"}), 400

            data = request.get_json(silent=True) or {}
            reason = (data.get("reason") or "Denied via web UI").strip()

            if prefix == "autonomy":
                ok = _deny_autonomy(source_id, current_user.id, reason)
            elif prefix == "contractor":
                ok = _deny_contractor(source_id, current_user.id, reason)
            else:
                ok = _deny_bridge(source_id, current_user.id, reason)

            if not ok:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as exc:
            logger.error("approvals_deny error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
```

Add these helpers alongside the approve helpers:

```python
def _deny_autonomy(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
               SET status = 'rejected', approved_by = %s,
                   approved_at = NOW(), rejected_reason = %s,
                   updated_at = NOW()
               WHERE id = %s AND status = 'pending'""",
            (user_id, reason, source_id),
        )
        return cur.rowcount > 0


def _deny_contractor(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE contractor_approval_requests
               SET status = 'denied', denied_by = %s,
                   denied_at = NOW(), denial_reason = %s
               WHERE id = %s AND status = 'pending'""",
            (user_id, reason, source_id),
        )
        return cur.rowcount > 0


def _deny_bridge(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE bridge_jobs
               SET status = 'cancelled', cancelled_by = %s,
                   cancelled_at = NOW(), cancellation_reason = %s,
                   updated_at = NOW()
               WHERE id = %s AND status = 'pending_approval'""",
            (user_id, reason, source_id),
        )
        return cur.rowcount > 0
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestDeny -v
```

Expected: all four deny tests PASS.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "feat(dhq): multi-source deny endpoint

Deny now dispatches by prefix. Contractor writes denial_reason + denied_by/at.
Bridge writes cancellation_reason + cancelled_by/at (status='cancelled')."
```

---

## Task 4: `/api/approvals/pending` — add `escalation_chain` field

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/tests/test_approvals_multi_source.py`

- [ ] **Step 1: Write the failing test**

Append to `platform_v2/tests/test_approvals_multi_source.py`:

```python
class TestPendingEscalationChain:
    def test_pending_includes_escalation_chain(self, admin_client, db_conn):
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name FROM agents WHERE department IS NOT NULL "
                "AND display_name IS NOT NULL LIMIT 1"
            )
            agent_row = cur.fetchone()
        if not agent_row:
            pytest.skip("No agent with department found; skip escalation test")
        agent_id, display_name = agent_row
        row_id = _seed_contractor_row(db_conn, agent_id=agent_id)

        resp = admin_client.get("/tools/department-hq/api/approvals/pending")
        assert resp.status_code == 200
        body = resp.json
        assert body["success"] is True
        target = next(a for a in body["approvals"] if a["id"] == f"contractor:{row_id}")
        chain = target.get("escalation_chain")
        assert chain is not None
        assert chain[0] == display_name
        assert chain[-1] == "A.R.C.H.I.E."
        assert len(chain) >= 2

    def test_pending_null_chain_when_agent_missing(self, admin_client, db_conn):
        row_id = _seed_contractor_row(db_conn, agent_id=None)
        resp = admin_client.get("/tools/department-hq/api/approvals/pending")
        target = next(a for a in resp.json["approvals"] if a["id"] == f"contractor:{row_id}")
        assert target.get("escalation_chain") is None
```

Run:
```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestPendingEscalationChain -v
```

Expected: both tests FAIL — `escalation_chain` key does not exist in the response.

- [ ] **Step 2: Add the escalation chain derivation helper**

At module scope in `approvals_routes.py` (above `register_approvals_routes`), add:

```python
def _build_escalation_chain(agent_display, department, agent_cache):
    """Return [agent_name, department_director_name, 'A.R.C.H.I.E.'] or None.

    Skips the director hop if the agent IS the director (is_department_ai).
    Returns None if the agent can't be resolved (no display name).
    """
    if not agent_display:
        return None
    chain = [agent_display]
    if department and department.lower() != "executive office":
        director = None
        for cached in agent_cache.values():
            if (
                cached.get("department") == department
                and cached.get("is_department_ai")
                and (cached.get("display_name") or cached.get("name")) != agent_display
            ):
                director = cached.get("display_name") or cached.get("name")
                break
        if director:
            chain.append(director)
    chain.append("A.R.C.H.I.E.")
    return chain if len(chain) >= 2 else None
```

- [ ] **Step 3: Wire the helper into the pending handler**

In the `approvals_pending` handler, after the 3 SELECT blocks but before the final `return jsonify(...)`, add:

```python
            # Load agent cache once and decorate each row with escalation_chain.
            try:
                from services.agent_service import get_agent_cache
                agent_cache = get_agent_cache() or {}
            except Exception:
                agent_cache = {}

            for a in approvals:
                display = a.get("agent_name")
                department = None
                if display:
                    for cached in agent_cache.values():
                        cname = cached.get("display_name") or cached.get("name")
                        if cname == display:
                            department = cached.get("department")
                            break
                a["escalation_chain"] = _build_escalation_chain(display, department, agent_cache)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestPendingEscalationChain -v
```

Expected: both tests PASS.

If `get_agent_cache` is not importable from `services.agent_service` under that exact name, search for it:
```bash
grep -rn "def get_agent_cache\|_agent_cache" /mnt/archie_brain/platform_v2/services/agent_service.py | head
```
Adapt the import to match. Do NOT introduce a new cache — use what exists.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "feat(dhq): escalation_chain field on /api/approvals/pending

Derived from agent department + agent_service cache. Chain is
[agent, department_director, A.R.C.H.I.E.] or [agent, A.R.C.H.I.E.] when
the agent IS the director. Null when agent can't be resolved."
```

---

## Task 5: `/api/approvals/history` — UNION across 3 tables

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/tests/test_approvals_multi_source.py`

- [ ] **Step 1: Write the failing test**

Append to `platform_v2/tests/test_approvals_multi_source.py`:

```python
class TestHistory:
    def test_history_unions_all_three_sources(self, admin_client, db_conn):
        aut_id = _seed_autonomy_row(db_conn)
        con_id = _seed_contractor_row(db_conn)
        brd_id = _seed_bridge_row(db_conn)
        admin_client.post(f"/tools/department-hq/api/approvals/autonomy:{aut_id}/approve")
        admin_client.post(
            f"/tools/department-hq/api/approvals/contractor:{con_id}/deny",
            json={"reason": "too expensive"},
        )
        admin_client.post(f"/tools/department-hq/api/approvals/bridge:{brd_id}/approve")

        resp = admin_client.get("/tools/department-hq/api/approvals/history?limit=20")
        assert resp.status_code == 200
        history = resp.json["history"]
        ids = {h["id"] for h in history}
        assert f"autonomy:{aut_id}" in ids
        assert f"contractor:{con_id}" in ids
        assert f"bridge:{brd_id}" in ids

        auto_row = next(h for h in history if h["id"] == f"autonomy:{aut_id}")
        con_row = next(h for h in history if h["id"] == f"contractor:{con_id}")
        brd_row = next(h for h in history if h["id"] == f"bridge:{brd_id}")
        assert auto_row["status"] == "approved"
        assert con_row["status"] == "denied"
        assert brd_row["status"] == "approved"
        for r in (auto_row, con_row, brd_row):
            assert "decided_at" in r and r["decided_at"] is not None
```

Run:
```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestHistory -v
```

Expected: FAIL — history endpoint only reads autonomy_approval_queue.

- [ ] **Step 2: Rewrite the history handler**

Replace `approvals_history` (lines ~227–254) with:

```python
    @bp.route("/api/approvals/history", methods=["GET"])
    @login_required
    @admin_required_decorator
    def approvals_history():
        """Recent approval history across all three sources."""
        try:
            from database import get_db_cursor

            limit = min(request.args.get("limit", 50, type=int), 200)
            history = []

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, action_type AS display_name, status,
                              COALESCE(approved_at, executed_at, updated_at) AS decided_at,
                              approved_by AS decided_by,
                              rejected_reason AS reason
                       FROM autonomy_approval_queue
                       WHERE status != 'pending'
                       ORDER BY updated_at DESC LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append({
                        "id": f"autonomy:{r['id']}",
                        "source": "autonomy_approval_queue",
                        "display_name": r["display_name"],
                        "status": r["status"],
                        "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                        "decided_by": r.get("decided_by"),
                        "reason": r.get("reason"),
                    })

                cur.execute(
                    """SELECT id, task_type AS display_name, status,
                              COALESCE(approved_at, denied_at, created_at) AS decided_at,
                              COALESCE(approved_by, denied_by) AS decided_by,
                              denial_reason AS reason
                       FROM contractor_approval_requests
                       WHERE status != 'pending'
                       ORDER BY COALESCE(approved_at, denied_at, created_at) DESC NULLS LAST
                       LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append({
                        "id": f"contractor:{r['id']}",
                        "source": "contractor_approval_requests",
                        "display_name": r["display_name"],
                        "status": r["status"],
                        "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                        "decided_by": r.get("decided_by"),
                        "reason": r.get("reason"),
                    })

                cur.execute(
                    """SELECT id, job_type AS display_name, status,
                              COALESCE(approved_at, cancelled_at, completed_at, updated_at) AS decided_at,
                              COALESCE(approved_by, cancelled_by) AS decided_by,
                              cancellation_reason AS reason
                       FROM bridge_jobs
                       WHERE status IN ('approved', 'cancelled', 'completed', 'failed')
                       ORDER BY COALESCE(approved_at, cancelled_at, completed_at, updated_at) DESC NULLS LAST
                       LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append({
                        "id": f"bridge:{r['id']}",
                        "source": "bridge_jobs",
                        "display_name": r["display_name"],
                        "status": r["status"],
                        "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                        "decided_by": r.get("decided_by"),
                        "reason": r.get("reason"),
                    })

            history.sort(key=lambda h: h.get("decided_at") or "", reverse=True)
            history = history[:limit]
            return jsonify({"success": True, "history": history})
        except Exception as exc:
            logger.error("approvals_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestHistory -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "feat(dhq): unified approvals history across all 3 sources

/api/approvals/history now UNIONs autonomy_approval_queue +
contractor_approval_requests + bridge_jobs. Normalised shape with
id (source-prefixed), status, decided_at, decided_by, reason."
```

---

## Task 6: Frontend — row renderer specialization + source badge + escalation line

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

No pytest — verification is browser-level (Task 9).

- [ ] **Step 1: Read the current `_renderApprovalCard`**

`sed -n '545,700p' /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html`

Confirm the function structure — the existing `compliance_fix` branch on `a.action_data` is the pattern to follow.

- [ ] **Step 2: Add source-specific specialization branches (safe DOM — no innerHTML)**

Find the block inside `_renderApprovalCard`:

```javascript
        if (a.category === 'compliance_fix') {
            var fixDef = a.action_data.fix_def || {};
            var sev = a.action_data.severity || '?';
            details.textContent = 'Rule: ' + (a.action_data.rule_id || '?') + ' | Severity: ' + sev + ' | Fix: ' + (fixDef.type || '?');
        }
        card.appendChild(details);
```

Replace with:

```javascript
        if (a.category === 'compliance_fix') {
            var fixDef = (a.action_data && a.action_data.fix_def) || {};
            var sev = (a.action_data && a.action_data.severity) || '?';
            details.textContent = 'Rule: ' + ((a.action_data && a.action_data.rule_id) || '?') + ' | Severity: ' + sev + ' | Fix: ' + (fixDef.type || '?');
        } else if (a.category === 'contractor_dispatch') {
            // Build the line with DOM nodes so the cost node can be styled inline
            // without relying on innerHTML (safer against any future untrusted data).
            var cost = (typeof a.estimated_cost === 'number') ? a.estimated_cost : null;
            var costColor = '#94a3b8';
            if (cost !== null && cost > 0.10) costColor = '#ef4444';
            else if (cost !== null && cost > 0.01) costColor = '#fbbf24';

            details.textContent = '';  // clear any default text
            details.appendChild(document.createTextNode('Provider: '));

            var provSpan = document.createElement('span');
            provSpan.style.color = '#cbd5e1';
            provSpan.textContent = a.contractor || '?';
            details.appendChild(provSpan);

            details.appendChild(document.createTextNode(' | Cost: '));

            var costSpan = document.createElement('span');
            costSpan.style.color = costColor;
            costSpan.style.fontWeight = 'bold';
            costSpan.textContent = (cost !== null) ? ('$' + cost.toFixed(4)) : 'cost: ?';
            details.appendChild(costSpan);

            if (a.estimated_tokens) {
                details.appendChild(document.createTextNode(
                    ' | ~' + a.estimated_tokens.toLocaleString() + ' tok'
                ));
            }
        } else if (a.category === 'cloud_dispatch') {
            var mod = a.module_source || '?';
            var reason = (a.reason || '').slice(0, 200);
            details.textContent = 'Module: ' + mod + (reason ? ' — "' + reason + '"' : '');
        }
        card.appendChild(details);
```

- [ ] **Step 3: Add the source badge pill in the header**

Find the header assembly:

```javascript
    var priority = document.createElement('span');
    var prioColor = a.priority <= 3 ? '#ef4444' : (a.priority <= 5 ? '#fbbf24' : '#94a3b8');
    priority.style.cssText = 'color:' + prioColor + ';font-size:0.75rem;font-weight:bold';
    priority.textContent = 'P' + a.priority;
    header.appendChild(title);
    header.appendChild(priority);
    card.appendChild(header);
```

Replace with:

```javascript
    var rightWrap = document.createElement('div');
    rightWrap.style.cssText = 'display:flex;align-items:center;gap:8px';

    var sourcePill = document.createElement('span');
    var srcColors = {
        'autonomy_approval_queue': ['#00e5ff', '#042e38'],
        'contractor_approval_requests': ['#fbbf24', '#3a2e00'],
        'bridge_jobs': ['#a855f7', '#2d1044']
    };
    var srcLabels = {
        'autonomy_approval_queue': 'AUTONOMY',
        'contractor_approval_requests': 'CONTRACTOR',
        'bridge_jobs': 'CLOUD'
    };
    var colors = srcColors[a.source] || ['#94a3b8', '#1e293b'];
    sourcePill.style.cssText = 'color:' + colors[0] + ';background:' + colors[1] + ';font-size:0.65rem;font-weight:bold;padding:2px 8px;border-radius:10px;letter-spacing:0.06em';
    sourcePill.textContent = srcLabels[a.source] || 'OTHER';

    var priority = document.createElement('span');
    var prioColor = a.priority <= 3 ? '#ef4444' : (a.priority <= 5 ? '#fbbf24' : '#94a3b8');
    priority.style.cssText = 'color:' + prioColor + ';font-size:0.75rem;font-weight:bold';
    priority.textContent = 'P' + (a.priority || '?');

    rightWrap.appendChild(sourcePill);
    rightWrap.appendChild(priority);

    header.appendChild(title);
    header.appendChild(rightWrap);
    card.appendChild(header);
```

- [ ] **Step 4: Add the escalation chain line**

Find in `_renderApprovalCard`, just before the `btns` element creation:

```javascript
    var btns = document.createElement('div');
    btns.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
```

Insert right before it:

```javascript
    if (Array.isArray(a.escalation_chain) && a.escalation_chain.length >= 2) {
        var chainDiv = document.createElement('div');
        chainDiv.style.cssText = 'font-size:0.7rem;color:#64748b;margin-bottom:8px;font-style:italic';
        var chain = a.escalation_chain.slice();
        if (chain.length > 4) {
            chain = [chain[0], chain[1], '…', chain[chain.length - 1]];
        }
        chainDiv.textContent = 'Escalated: ' + chain.join(' → ');
        card.appendChild(chainDiv);
    }

    var btns = document.createElement('div');
    btns.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
```

- [ ] **Step 5: Restart and smoke-test in browser**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/department-hq/#approvals`. Seed rows for visual verification:

```bash
docker exec archie_database psql -U archie -d archie <<'SQL'
INSERT INTO contractor_approval_requests (agent_id, task_type, task_description, status, priority, contractor_provider, contractor_model, estimated_cost, estimated_tokens)
VALUES ((SELECT id FROM agents WHERE display_name='Pixel' LIMIT 1), 'image_generation', 'Smoke test: generate a banner', 'pending', 'normal', 'openai', 'gpt-image-1', 0.08, 2500);

INSERT INTO bridge_jobs (job_type, module_source, description, status, agent_name, total_steps)
VALUES ('dispatch', 'media_studio', 'Smoke test: cloud dispatch pending approval', 'pending_approval', 'Pixel', 1);
SQL
```

Confirm: pills render (teal AUTONOMY, amber CONTRACTOR, purple CLOUD), contractor cost shows amber $0.0800 in bold, bridge row shows module + description snippet, escalation chain line appears when resolvable.

Cleanup:
```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM contractor_approval_requests WHERE task_description LIKE 'Smoke test%';"
docker exec archie_database psql -U archie -d archie -c "DELETE FROM bridge_jobs WHERE description LIKE 'Smoke test%';"
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): approval card source pill + category specialization

_renderApprovalCard now branches for contractor_dispatch (provider + color-
coded cost + tokens) and cloud_dispatch (module + description snippet),
shows an AUTONOMY/CONTRACTOR/CLOUD source pill in the header, and renders
the escalation_chain as a muted italic line."
```

---

## Task 7: Telegram escalations → COMs feed (telegram_message_log)

**Files:**
- Modify: `ai_bridge/telegram_gateway.py`

- [ ] **Step 1: Confirm telegram_message_log schema the logger uses**

```bash
sed -n '340,385p' /mnt/archie_brain/platform_v2/services/telegram_service.py
docker exec archie_database psql -U archie -d archie -tAc "\d telegram_message_log" | head
```

Note required columns: `category`, `title`, `message`, `source_agent`, `telegram_id`, `status`.

- [ ] **Step 2: Write the failing test**

Append to `platform_v2/tests/test_approvals_multi_source.py`:

```python
class TestEscalationLogging:
    def test_escalation_logs_to_coms_feed(self, app, db_conn, monkeypatch):
        """send_escalation_notification must insert a telegram_message_log row
        (DHQ COMs feed surface)."""
        try:
            from ai_bridge.telegram_gateway import TelegramGateway
        except Exception:
            pytest.skip("telegram_gateway module not importable in test env")

        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO telegram_users (telegram_id, is_authorized) "
                "VALUES (%s, TRUE) ON CONFLICT DO NOTHING",
                (999_888,),
            )

        gw = TelegramGateway.__new__(TelegramGateway)
        monkeypatch.setattr(gw, "_running", True)

        class _FakeBot:
            @staticmethod
            async def send_message(chat_id, text, reply_markup):
                return type("M", (), {"message_id": 123})

        class _FakeApp:
            bot = _FakeBot()

        gw._application = _FakeApp()

        import asyncio
        loop = asyncio.new_event_loop()
        gw._loop = loop

        gw.send_escalation_notification(
            approval_id=12345,
            context={
                "agent_name": "TestAgent",
                "department": "ENGINEERING",
                "capability": "cap",
                "failure_count": 1,
                "original_model": "mA",
                "escalated_model": "mB",
                "est_cost": 0.02,
                "module_id": "mod",
                "recommendation": "Approve",
            },
        )
        import time; time.sleep(0.5)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM telegram_message_log "
                "WHERE category='escalation' AND source_agent='TestAgent' "
                "AND message LIKE '%12345%'"
            )
            count = cur.fetchone()[0]
        assert count >= 1
```

Run:
```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestEscalationLogging -v
```

Expected: FAIL (no log row — escalation bypasses the log).

- [ ] **Step 3: Patch `send_escalation_notification`**

Read the current function in `ai_bridge/telegram_gateway.py` around line 651. Find the `for row in rows` block:

```python
                    for row in rows:
                        try:
                            await self._application.bot.send_message(
                                chat_id=row[0], text=text, reply_markup=keyboard
                            )
                        except Exception as e:
                            logger.warning(f"Failed to notify {row[0]}: {e}")
```

Replace with:

```python
                    for row in rows:
                        chat_id = row[0]
                        send_status = "sent"
                        send_err = None
                        msg_obj = None
                        try:
                            msg_obj = await self._application.bot.send_message(
                                chat_id=chat_id, text=text, reply_markup=keyboard
                            )
                        except Exception as e:
                            send_status = "failed"
                            send_err = str(e)
                            logger.warning(f"Failed to notify {chat_id}: {e}")

                        # Mirror to telegram_message_log so DHQ COMs tab shows the escalation.
                        try:
                            from database import get_db_cursor

                            with get_db_cursor(commit=True) as (_c, log_cur):
                                log_cur.execute(
                                    """INSERT INTO telegram_message_log
                                       (category, title, message, source_agent,
                                        source_department, source_module, priority,
                                        status, error_message, chat_id, telegram_message_id)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                    (
                                        "escalation",
                                        f"Escalation #{approval_id}",
                                        text,
                                        context.get("agent_name"),
                                        context.get("department"),
                                        context.get("module_id"),
                                        "high",
                                        send_status,
                                        send_err,
                                        str(chat_id),
                                        getattr(msg_obj, "message_id", None) if msg_obj else None,
                                    ),
                                )
                        except Exception as log_err:
                            logger.debug(f"Escalation COMs log insert failed: {log_err}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestEscalationLogging -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/telegram_gateway.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "fix(telegram): log escalations to telegram_message_log

send_escalation_notification now mirrors every send (including failures)
into telegram_message_log with category='escalation', so DHQ COMs tab
surfaces escalation activity alongside other Telegram traffic."
```

---

## Task 8: Telegram escalations → A.R.C.H.I.E. Unified Chat (unified_messages)

**Files:**
- Modify: `ai_bridge/telegram_gateway.py`
- Modify: `platform_v2/tests/test_approvals_multi_source.py`

Project #265 (A.R.C.H.I.E. Unified Communications, completed 2026-04-17) introduced `unified_conversations` + `unified_messages` as the canonical cross-channel store for user↔A.R.C.H.I.E. dialog. Escalation Telegrams are A.R.C.H.I.E. talking to the user — they belong in the unified conversation too, so the user sees a coherent thread in A.R.C.H.I.E. Chat (`archie.kytranempowerment.com`) alongside Telegram and COMs.

- [ ] **Step 1: Confirm unified_messages + unified_conversations columns**

```bash
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='unified_conversations' ORDER BY ordinal_position;"
docker exec archie_database psql -U archie -d archie -tAc "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='unified_messages' ORDER BY ordinal_position;"
```

Expected: `unified_conversations` has `(id, user_id, topic, status, created_at, last_activity)`, `unified_messages` has `(id, conversation_id, channel, direction, sender, content, metadata, created_at)`. If schemas differ, adapt the SQL in Step 3.

- [ ] **Step 2: Write the failing test**

Append to `platform_v2/tests/test_approvals_multi_source.py`:

```python
class TestEscalationUnifiedChat:
    def test_escalation_logs_to_unified_messages(self, app, db_conn, monkeypatch):
        """send_escalation_notification must also insert a unified_messages row
        so A.R.C.H.I.E. Chat (Project #265) shows the escalation in the user's
        unified conversation thread."""
        try:
            from ai_bridge.telegram_gateway import TelegramGateway
        except Exception:
            pytest.skip("telegram_gateway module not importable in test env")

        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO telegram_users (telegram_id, user_id, is_authorized) "
                "VALUES (%s, %s, TRUE) ON CONFLICT (telegram_id) DO UPDATE SET user_id = EXCLUDED.user_id",
                (999_777, 1),  # user_id=1 is the admin seeded by conftest
            )

        gw = TelegramGateway.__new__(TelegramGateway)
        monkeypatch.setattr(gw, "_running", True)

        class _FakeBot:
            @staticmethod
            async def send_message(chat_id, text, reply_markup):
                return type("M", (), {"message_id": 456})

        class _FakeApp:
            bot = _FakeBot()

        gw._application = _FakeApp()

        import asyncio
        gw._loop = asyncio.new_event_loop()

        approval_id = 54321
        gw.send_escalation_notification(
            approval_id=approval_id,
            context={
                "agent_name": "Pixel",
                "department": "CREATIVE",
                "capability": "image_generation",
                "failure_count": 2,
                "original_model": "sdxl",
                "escalated_model": "gpt-image-1",
                "est_cost": 0.08,
                "module_id": "media_studio",
                "recommendation": "Approve",
            },
        )
        import time; time.sleep(0.5)

        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT um.id, um.channel, um.direction, um.sender, um.content
                   FROM unified_messages um
                   JOIN unified_conversations uc ON uc.id = um.conversation_id
                   WHERE uc.user_id = 1
                     AND um.content LIKE %s
                   ORDER BY um.created_at DESC LIMIT 1""",
                (f"%{approval_id}%",),
            )
            row = cur.fetchone()
        assert row is not None, "Expected unified_messages row linked to user's conversation"
        msg_id, channel, direction, sender, content = row
        assert channel == "telegram"
        assert direction == "outbound"
        assert sender == "A.R.C.H.I.E."
        assert str(approval_id) in content
```

Run:
```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestEscalationUnifiedChat -v
```

Expected: FAIL — no unified_messages row is created today.

- [ ] **Step 3: Extend `send_escalation_notification` to also write to unified_messages**

In `ai_bridge/telegram_gateway.py`, immediately after the `telegram_message_log` INSERT added in Task 7, add the unified-chat write inside the same `for row in rows` loop:

```python
                        # Mirror to unified_messages (A.R.C.H.I.E. Chat, Project #265)
                        # so the user sees the escalation in their canonical conversation.
                        try:
                            from database import get_db_cursor

                            with get_db_cursor(commit=True) as (_c, uc_cur):
                                # Resolve user_id from telegram_users for this chat.
                                uc_cur.execute(
                                    "SELECT user_id FROM telegram_users WHERE telegram_id=%s",
                                    (chat_id,),
                                )
                                u = uc_cur.fetchone()
                                if not u or not u[0]:
                                    # No linked user — skip unified log (Telegram works
                                    # for authorized chat_ids without user_id linkage).
                                    raise RuntimeError("no linked user_id")
                                user_id = u[0]

                                # Find-or-create conversation topic='A.R.C.H.I.E. Escalations'.
                                uc_cur.execute(
                                    """SELECT id FROM unified_conversations
                                       WHERE user_id=%s AND topic=%s AND status='active'
                                       ORDER BY last_activity DESC LIMIT 1""",
                                    (user_id, "A.R.C.H.I.E. Escalations"),
                                )
                                conv_row = uc_cur.fetchone()
                                if conv_row:
                                    conv_id = conv_row[0]
                                    uc_cur.execute(
                                        "UPDATE unified_conversations SET last_activity=NOW() WHERE id=%s",
                                        (conv_id,),
                                    )
                                else:
                                    uc_cur.execute(
                                        """INSERT INTO unified_conversations
                                           (user_id, topic, status, created_at, last_activity)
                                           VALUES (%s, %s, 'active', NOW(), NOW())
                                           RETURNING id""",
                                        (user_id, "A.R.C.H.I.E. Escalations"),
                                    )
                                    conv_id = uc_cur.fetchone()[0]

                                # Append the escalation message.
                                import json as _json
                                uc_cur.execute(
                                    """INSERT INTO unified_messages
                                       (conversation_id, channel, direction, sender, content, metadata, created_at)
                                       VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
                                    (
                                        conv_id,
                                        "telegram",
                                        "outbound",
                                        "A.R.C.H.I.E.",
                                        text,
                                        _json.dumps({
                                            "approval_id": approval_id,
                                            "agent_name": context.get("agent_name"),
                                            "department": context.get("department"),
                                            "est_cost": context.get("est_cost"),
                                            "telegram_message_id": getattr(msg_obj, "message_id", None) if msg_obj else None,
                                            "send_status": send_status,
                                        }),
                                    ),
                                )
                        except Exception as uc_err:
                            logger.debug(f"Escalation unified_messages log failed: {uc_err}")
```

The `raise RuntimeError("no linked user_id")` intentionally falls into the outer `except` to skip silently — authorized Telegram chat_ids without a `user_id` link shouldn't break escalation sends.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose restart archie_platform
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py::TestEscalationUnifiedChat -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/telegram_gateway.py platform_v2/tests/test_approvals_multi_source.py
git commit -m "feat(telegram): mirror escalations into unified_messages (Project #265)

send_escalation_notification now appends to unified_messages under an
'A.R.C.H.I.E. Escalations' conversation for each linked user, so the
user sees a coherent escalation thread in A.R.C.H.I.E. Chat alongside
Telegram and DHQ COMs.

Aligns with Project #265 (A.R.C.H.I.E. Unified Communications) which
ships unified_conversations + unified_messages as the canonical
cross-channel dialog store."
```

---

## Task 9: Full-suite run + browser verification

- [ ] **Step 1: Run the full new test file**

```bash
docker exec archie_platform pytest /app/tests/test_approvals_multi_source.py -v
```

Expected: all tests across `TestApprove`, `TestDeny`, `TestPendingEscalationChain`, `TestHistory`, `TestEscalationLogging`, `TestEscalationUnifiedChat` PASS. Env-dependent skips on telegram_gateway are acceptable if documented.

- [ ] **Step 2: Run any existing DHQ-related tests to check for regressions**

```bash
docker exec archie_platform pytest /app/tests/ -v -k "approval or department_hq or dhq"
```

Expected: no new failures.

- [ ] **Step 3: Docker logs sanity check**

```bash
docker logs archie_platform --tail 100 | grep -iE "error|exception|traceback" | head
```

Expected: no new recurring stack traces tied to approvals/department_hq routes.

- [ ] **Step 4: Browser verification (required by platform rule #1)**

Open `http://192.168.1.200:3000/tools/department-hq/#approvals`.

Seed:
```bash
docker exec archie_database psql -U archie -d archie <<'SQL'
INSERT INTO autonomy_approval_queue (action_type, action_data, tier, status, priority, requested_by, reason)
VALUES ('smoke_test_escalation', '{}'::jsonb, 2, 'pending', 4, 'smoke', 'Browser smoke test — AUTONOMY');

INSERT INTO contractor_approval_requests
    (agent_id, task_type, task_description, status, priority,
     contractor_provider, contractor_model, estimated_cost, estimated_tokens)
VALUES ((SELECT id FROM agents WHERE display_name='Pixel' LIMIT 1),
        'image_generation', 'Smoke test: generate banner for WTF campaign',
        'pending', 'normal', 'openai', 'gpt-image-1', 0.08, 2500);

INSERT INTO bridge_jobs
    (job_type, module_source, description, status, agent_name, total_steps)
VALUES ('dispatch', 'media_studio',
        'Smoke test: cloud dispatch waiting for approval',
        'pending_approval', 'Pixel', 1);
SQL
```

Verify:
- [ ] All three rows appear with correct source pills (teal / amber / purple).
- [ ] Contractor row shows amber-colored $0.0800 + provider + tokens.
- [ ] Bridge row shows `Module: media_studio — "Smoke test..."`.
- [ ] Escalation chain line appears on contractor/bridge rows when Pixel's director resolves.
- [ ] Approve on autonomy row → confirm modal → row disappears on next poll.
- [ ] Deny on contractor row → reason modal → row disappears.
- [ ] Approve on bridge row → row disappears.
- [ ] Recent History panel shows all three resolved rows with correct statuses.

Cleanup:
```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM autonomy_approval_queue WHERE action_type='smoke_test_escalation';"
docker exec archie_database psql -U archie -d archie -c "DELETE FROM contractor_approval_requests WHERE task_description LIKE 'Smoke test%';"
docker exec archie_database psql -U archie -d archie -c "DELETE FROM bridge_jobs WHERE description LIKE 'Smoke test%';"
```

- [ ] **Step 5: COMs tab verification**

Open `http://192.168.1.200:3000/tools/department-hq/#coms`. Note the current message count.

Trigger a synthetic escalation:

```bash
docker exec -it archie_platform python -c "
from ai_bridge.telegram_gateway import TelegramGateway
from database import get_db_cursor
import time

with get_db_cursor(commit=True) as (_, cur):
    cur.execute(
        \"\"\"INSERT INTO autonomy_approval_queue
           (action_type, action_data, tier, status, priority, requested_by, reason)
           VALUES ('cloud_throughput_escalation', '{}'::jsonb, 2, 'pending', 4, 'smoke', 'COMs log smoke')
           RETURNING id\"\"\"
    )
    approval_id = cur.fetchone()[0]

gw = TelegramGateway()
gw.send_escalation_notification(
    approval_id=approval_id,
    context={
        'agent_name': 'Pixel',
        'department': 'CREATIVE',
        'capability': 'image_generation',
        'failure_count': 3,
        'original_model': 'sdxl-local',
        'escalated_model': 'gpt-image-1',
        'est_cost': 0.08,
        'module_id': 'media_studio',
        'recommendation': 'Approve'
    }
)
time.sleep(1)
print(f'Triggered escalation #{approval_id}')
"
```

Reload COMs tab — `Escalation #<id>` message should appear with `source_agent=Pixel`.

- [ ] **Step 6: A.R.C.H.I.E. Chat verification (new surface, Task 8)**

Open `https://archie.kytranempowerment.com` (or `http://192.168.1.200:3002` internally) and log in. Look for an "A.R.C.H.I.E. Escalations" conversation containing the test message. If the standalone UI shows conversations by `topic`, it should list this thread.

Alternative DB verification:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT um.created_at, um.channel, um.sender, LEFT(um.content, 80) FROM unified_messages um JOIN unified_conversations uc ON uc.id = um.conversation_id WHERE uc.topic = 'A.R.C.H.I.E. Escalations' ORDER BY um.id DESC LIMIT 5;"
```

Expected: the synthetic escalation appears as an outbound telegram message from A.R.C.H.I.E.

Clean up smoke autonomy row:
```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM autonomy_approval_queue WHERE requested_by='smoke' AND reason='COMs log smoke';"
```

---

## Task 10: Push + PR + follow-ups

- [ ] **Step 1: Push feature branch**

```bash
git push -u origin feat/dhq-approvals-multi-source
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(dhq): multi-source approvals UI + endpoints (#2162 + #2163)" --body "$(cat <<'EOF'
## Summary
- `/api/approvals/<path:approval_id>/(approve|deny)` dispatches by prefix to per-source SQL (autonomy/contractor/bridge)
- `/api/approvals/pending` includes `escalation_chain` derived from agent department + director cache
- `/api/approvals/history` UNIONs all three tables with a normalised shape
- Approval cards render source pill (AUTONOMY/CONTRACTOR/CLOUD) + category-specific details + escalation chain line
- `send_escalation_notification` writes to `telegram_message_log` (DHQ COMs feed) AND `unified_messages` (A.R.C.H.I.E. Chat — Project #265)
- Migration adds missing audit columns (`denied_by`/`denied_at` on contractor, `approved_*`/`cancelled_*` on bridge_jobs)

Closes #2162 #2163. Aligns with Project #265 (A.R.C.H.I.E. Unified Communications). Follow-up filed for the bridge_jobs resume path.

## Test plan
- [x] `pytest platform_v2/tests/test_approvals_multi_source.py` — approve + deny + pending chain + history + COMs log + unified chat log
- [x] Browser: seeded rows in all 3 tables, verified pills + specialization + approve/deny flows + history
- [x] COMs tab shows escalation messages after synthetic `send_escalation_notification` trigger
- [x] A.R.C.H.I.E. Chat shows escalation in "A.R.C.H.I.E. Escalations" conversation (or DB verification)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Record follow-up tasks in Dev HQ**

Via MCP `create_task`:
1. Project #261, title: "Bridge_jobs resume path — consume `status='approved'` to re-dispatch original request", effort: medium, priority: 8.
2. Project #261, title: "COMs ↔ Approvals cross-link — click escalation message to scroll to its approval row", effort: small, priority: 6.
3. Project #265 (or its successor project if one was opened for post-launch polish), title: "Surface A.R.C.H.I.E. Escalations conversation in the archie_comms sidebar with a distinct badge", effort: small, priority: 6.

- [ ] **Step 4: Self-merge after verification**

Once CI is green and verified clean:

```bash
gh pr merge --squash --delete-branch
```

Then update Dev HQ:

```bash
# MCP calls:
# - complete_task id=2162 with verification notes
# - complete_task id=2163 with verification notes
# - log_decision: "Escalation Telegrams write to both telegram_message_log (COMs) and unified_messages (A.R.C.H.I.E. Chat) — aligned with Project #265 canonical cross-channel store"
# - update_project_understanding project_id=261
# - update_project_understanding project_id=265  (re-touch to note post-launch integration)
```

---

## Self-review notes

- **Spec coverage:** ✅ All 4 spec goals + 3 design sections covered. Non-goals honored (bridge_jobs resume, Telegram-side multi-source parity, COMs ↔ Approvals cross-link) — filed as follow-ups.
- **Alignment coverage:** ✅ Task 8 explicitly covers Project #265 (unified_messages write). Follow-up #3 covers UI surfacing in archie_comms.
- **Placeholder scan:** No TBDs/TODOs. Every step has real code.
- **Type consistency:** `escalation_chain` is list-or-null throughout; `source` strings match between endpoint and frontend pill mapping; `status` transitions (approved/rejected/denied/cancelled) align with history handler WHERE clauses.
- **Migration safety:** All `ADD COLUMN IF NOT EXISTS` — idempotent.
- **Security:** Frontend uses safe DOM construction (no innerHTML). Backend uses parameterized SQL everywhere. Route prefix validation rejects unknown prefixes with 400.
- **Test env drift:** Skip guards on telegram_gateway import + missing agent data so a bare test env can run without false failures.
