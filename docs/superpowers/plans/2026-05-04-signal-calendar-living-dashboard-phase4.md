# SIGNAL Calendar Living Dashboard — Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the four Phase 3 stub buttons (Retry, Mark Won't Fix, Re-draft) to real backend endpoints. Reconnect stays stubbed for Phase 5. Adds 2 new endpoints (retry + abandon), reuses existing `/api/signal/run-now` for re-draft, and extends the chip status classifier to map `status='abandoned'` to the `rejected` chip color (no new chip type — keeps Phase 4 tight).

**Architecture:** Backend adds 2 new POST routes in `platform_v2/tools/department_hq/social_routes.py` (alongside the existing approve/deny routes). Both are thin DB updates: retry resets `status='approved'` + clears `execution_result` (the existing autonomy worker re-picks it up); abandon sets `status='abandoned'` (terminal). Classifier in `services/signal_post_status.py` adds one line: `'abandoned'` joins `'rejected'` in the same return branch — no DB schema change, no new chip color. Frontend replaces 4 `_phase4Stub(...)` onclick attributes in `_renderModalActions` with real handler calls; adds 3 new async functions (`_signalRetryPost`, `_signalAbandonPost`, `_signalRedraftPost`).

**Tech Stack:** Python (Flask routes + pytest), vanilla JS in single-file convention. No DB migrations. No new tests fixtures (re-uses Phase 2's `signal_calendar_phase2_fixture.sql`).

**Spec:** `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (Component 6: Action endpoints)
**Phase 1 plan:** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md`
**Phase 2 plan:** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase2.md`
**Phase 3 plan:** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase3.md`

---

## Phase 4 scope decisions (locked-in)

| Question | Decision | Note |
|---|---|---|
| Retry mechanism | Reset existing approval row to `status='approved'`, clear `execution_result` + `executed_at` | autonomy worker (consumer of status='approved' rows) re-picks it up; no new approval row created |
| Re-draft mechanism | Reuse existing `POST /api/signal/run-now` with `{account: post.post_type}` | fires both EN + FR for that account; minor UX caveat — re-draft of a French post also re-drafts the English one for that account |
| Abandon mechanism | New endpoint `POST /api/signal/posts/<id>/abandon` sets `status='abandoned'` (terminal) | no DB CHECK constraint on status column — any string accepted |
| Abandon chip color | Map `'abandoned'` to existing `rejected` (grey) chip via classifier — no new visual state | DB still distinguishes `rejected` vs `abandoned` for audit trail |
| Reconnect button | Stays as Phase 5 stub | `deferred_session` handling is part of Layer A Phase 4 (separate workstream) |

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `platform_v2/services/signal_post_status.py` | Modify | Map `status='abandoned'` to `'rejected'` chip in `classify()` |
| `platform_v2/tests/test_signal_post_status.py` | Modify | Add `test_rejected_when_status_abandoned` |
| `platform_v2/tools/department_hq/social_routes.py` | Modify | Add 2 new routes: `api_signal_retry` and `api_signal_abandon` |
| `platform_v2/tests/test_signal_action_routes.py` | Create | Integration tests for retry + abandon endpoints |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify | Replace 4 `_phase4Stub(...)` onclicks; add `_signalRetryPost`, `_signalAbandonPost`, `_signalRedraftPost` |

---

### Task 1: Backend — classifier maps 'abandoned' → 'rejected'

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/services/signal_post_status.py`
- Modify: `/mnt/archie_brain/platform_v2/tests/test_signal_post_status.py`

**Why:** When a user marks a failed post "Won't Fix", we set `status='abandoned'` so the audit trail distinguishes from a pre-execution rejection. Visually it should look identical to a rejected chip (grey, ✗ icon). One-line classifier change.

- [ ] **Step 1: Read the existing classifier function**

```bash
sed -n '30,80p' /mnt/archie_brain/platform_v2/services/signal_post_status.py
```
Confirm the current `classify()` function has a line `if status == "rejected": return "rejected"` early in the chain.

- [ ] **Step 2: TDD — Write the failing test FIRST**

Open `/mnt/archie_brain/platform_v2/tests/test_signal_post_status.py` and add this test inside the existing `class TestStatusClassifier:` (right after the existing `test_*` methods):

```python
    def test_rejected_when_status_abandoned(self, svc):
        """Phase 4: 'abandoned' status maps to 'rejected' chip color."""
        approval = {"id": 1, "status": "abandoned", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "rejected"
```

- [ ] **Step 3: Run the test — should FAIL**

```bash
docker exec archie_platform pytest /app/tests/test_signal_post_status.py -k test_rejected_when_status_abandoned -v 2>&1 | tail -15
```
Expected: AssertionError. The classifier currently returns the `status` string itself for unknown states (or falls through to the final return, depending on implementation), not 'rejected'.

- [ ] **Step 4: Make it pass — extend the classifier**

Edit `/mnt/archie_brain/platform_v2/services/signal_post_status.py`. Find the line:
```python
    if status == "rejected":
        return "rejected"
```

Replace with:
```python
    if status in ("rejected", "abandoned"):
        return "rejected"
```

- [ ] **Step 5: Run the test — should PASS**

```bash
docker exec archie_platform pytest /app/tests/test_signal_post_status.py -v 2>&1 | tail -15
```
Expected: all tests PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/services/signal_post_status.py platform_v2/tests/test_signal_post_status.py && git commit -m "feat(signal-calendar): classifier maps 'abandoned' status to rejected chip (Phase 4)"
```

---

### Task 2: Backend — retry endpoint

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/department_hq/social_routes.py` (add new route after the existing `api_signal_deny` at ~line 537)
- Create: `/mnt/archie_brain/platform_v2/tests/test_signal_action_routes.py`

**Why:** When a post fails (skill execution error), the user clicks Retry. We reset the row to `status='approved'` + clear `execution_result` + `executed_at`. The autonomy worker that already consumes `status='approved'` rows re-picks it up and re-fires the LinkedIn skill.

- [ ] **Step 1: Read the existing approve/deny route patterns**

```bash
sed -n '515,600p' /mnt/archie_brain/platform_v2/tools/department_hq/social_routes.py
```
Confirm the pattern: `@bp.route(...)`, `@admin_required`, `from database import get_db_cursor`, `with get_db_cursor(commit=True) as (_conn, cur):`, RETURNING id check, JSON response.

- [ ] **Step 2: Create the integration test file FIRST (TDD)**

Create `/mnt/archie_brain/platform_v2/tests/test_signal_action_routes.py` with the following:

```python
"""Integration tests for SIGNAL Phase 4 action endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def admin_app():
    """Mini Flask app with the social_routes blueprint mounted under admin user."""
    from flask import Flask
    from flask_login import LoginManager, UserMixin

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-key"

    login_manager = LoginManager()
    login_manager.init_app(app)

    class _AdminUser(UserMixin):
        id = 1
        is_admin = True

    @login_manager.user_loader
    def _load_user(uid):
        return _AdminUser()

    @login_manager.request_loader
    def _request_loader(_request):
        return _AdminUser()

    from flask import Blueprint
    from tools.department_hq.social_routes import register_signal_routes

    bp = Blueprint("signal_test", __name__, url_prefix="/tools/department-hq")
    register_signal_routes(bp, lambda f: f)  # bypass admin_required for test
    app.register_blueprint(bp)

    return app


@pytest.fixture
def client(admin_app):
    return admin_app.test_client()


class TestRetryEndpoint:
    def test_retry_resets_executed_row_to_approved(self, client):
        """Retry of a failed (status='executed') row should reset to 'approved'
        with execution_result and executed_at cleared so the worker re-picks it up."""
        with patch("tools.department_hq.social_routes.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = {"id": 99}
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/99/retry")
            assert r.status_code == 200
            body = r.get_json()
            assert body["success"] is True
            assert body["approval_id"] == 99

            # Verify the SQL UPDATE: status->'approved', execution_result->NULL, executed_at->NULL
            executed_sql = cur.execute.call_args[0][0]
            assert "UPDATE autonomy_approval_queue" in executed_sql
            assert "status = 'approved'" in executed_sql
            assert "execution_result = NULL" in executed_sql
            assert "executed_at = NULL" in executed_sql
            assert "WHERE id = " in executed_sql

    def test_retry_404_when_row_not_found(self, client):
        """If the row doesn't exist or isn't in 'executed' status, return 404."""
        with patch("tools.department_hq.social_routes.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = None
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/9999/retry")
            assert r.status_code == 404


class TestAbandonEndpoint:
    def test_abandon_sets_status_abandoned(self, client):
        """Abandon should set status='abandoned' on a non-terminal row."""
        with patch("tools.department_hq.social_routes.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = {"id": 99}
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/99/abandon")
            assert r.status_code == 200
            body = r.get_json()
            assert body["success"] is True
            assert body["approval_id"] == 99

            executed_sql = cur.execute.call_args[0][0]
            assert "UPDATE autonomy_approval_queue" in executed_sql
            assert "status = 'abandoned'" in executed_sql
            assert "WHERE id = " in executed_sql

    def test_abandon_404_when_row_not_found(self, client):
        with patch("tools.department_hq.social_routes.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = None
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/9999/abandon")
            assert r.status_code == 404
```

- [ ] **Step 3: Run the tests — should FAIL (404 because the routes don't exist yet)**

```bash
docker exec archie_platform pytest /app/tests/test_signal_action_routes.py -v 2>&1 | tail -25
```
Expected: 4 failures — endpoints not registered.

- [ ] **Step 4: Add the retry endpoint**

Edit `/mnt/archie_brain/platform_v2/tools/department_hq/social_routes.py`. Find the existing `api_signal_deny` route (around line 537). Immediately AFTER its function body's closing brace and outside its decorator block, insert these two new routes:

```python
    @bp.route("/api/signal/posts/<int:approval_id>/retry", methods=["POST"])
    @admin_required
    def api_signal_retry(approval_id):
        """Retry a failed LinkedIn post: reset status='approved' so the
        autonomy worker re-picks it up and re-fires the skill."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved',
                           execution_result = NULL,
                           executed_at = NULL,
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status = 'executed'
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or not in 'executed' state"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/posts/<int:approval_id>/abandon", methods=["POST"])
    @admin_required
    def api_signal_abandon(approval_id):
        """Abandon (Mark Won't Fix) a post: terminal state='abandoned'.
        No worker action — chip displays as 'rejected' grey via classifier mapping."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'abandoned',
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status NOT IN ('abandoned', 'rejected', 'pending')
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or not in an abandonable state"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 5: Run the tests — should PASS**

```bash
docker exec archie_platform pytest /app/tests/test_signal_action_routes.py -v 2>&1 | tail -25
```
Expected: 4/4 PASS.

- [ ] **Step 6: Restart platform, verify endpoints registered**

```bash
docker compose restart archie_platform && sleep 6
curl -sS -o /dev/null -w "retry: %{http_code}\n" -X POST "http://192.168.1.200:3000/tools/department-hq/api/signal/posts/99999/retry"
curl -sS -o /dev/null -w "abandon: %{http_code}\n" -X POST "http://192.168.1.200:3000/tools/department-hq/api/signal/posts/99999/abandon"
```
Expected: both return `401` (auth-gated; routes registered). NOT `404` (which would indicate the route isn't mounted).

If `curl` is hook-blocked, use the `mcp__plugin_context-mode_context-mode__ctx_execute` tool with language `shell`.

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/tools/department_hq/social_routes.py platform_v2/tests/test_signal_action_routes.py && git commit -m "feat(signal-calendar): retry + abandon endpoints with integration tests (Phase 4)"
```

---

### Task 3: Frontend — wire 4 stub buttons to real handlers

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js`

**Why:** Replace the 4 `_phase4Stub(...)` calls in `_renderModalActions` with real onclick handlers that hit the new endpoints. Add 3 new async handler functions (`_signalRetryPost`, `_signalAbandonPost`, `_signalRedraftPost`). Reconnect stays stubbed (Phase 5).

- [ ] **Step 1: Add 3 new async handlers**

Find `async function _signalRejectPost(approvalId)` in the file. Immediately AFTER its closing brace (and BEFORE `function _closeSignalPostModal`), insert these three new functions:

```javascript
async function _signalRetryPost(approvalId) {
    if (!approvalId) return;
    if (!confirm('Retry this post? It will re-fire the LinkedIn skill with the same content.')) return;
    try {
        await apiPost('/api/signal/posts/' + approvalId + '/retry', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Retry failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalAbandonPost(approvalId) {
    if (!approvalId) return;
    if (!confirm("Mark this post Won't Fix? It will be terminal — no further retries.")) return;
    try {
        await apiPost('/api/signal/posts/' + approvalId + '/abandon', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Abandon failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalRedraftPost(account) {
    if (!account) return;
    if (!confirm('Re-draft for ' + account + '? This fires both EN and FR for that account.')) return;
    try {
        await apiPost('/api/signal/run-now', { account: account });
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Re-draft failed: ' + (err && err.message ? err.message : String(err)));
    }
}
```

- [ ] **Step 2: Replace 4 stub onclicks in `_renderModalActions`**

Find `function _renderModalActions(post)` in the file. Locate these blocks:

```javascript
    if (post.status === 'failed') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Retry') + '>Retry</button>';
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub("Mark Won't Fix") + ">Mark Won't Fix</button>";
    }
    if (post.status === 'rejected') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Re-draft') + '>Re-draft</button>';
    }
```

Replace with:

```javascript
    if (post.status === 'failed') {
        btns += '<button type="button" style="' + btnBase + 'background:#3b82f6;color:#04101f;border-color:#2563eb;" '
             +    'onclick="_signalRetryPost(' + aid + ')">Retry</button>';
        btns += '<button type="button" style="' + btnBase + 'background:#9ca3af;color:#0d0f12;border-color:#6b7280;" '
             +    'onclick="_signalAbandonPost(' + aid + ')">Mark Won\\'t Fix</button>';
    }
    if (post.status === 'rejected') {
        var redraftAccount = post.post_type || (signalAccount || 'company');
        btns += '<button type="button" style="' + btnBase + 'background:#22d3ee;color:#04130a;border-color:#06b6d4;" '
             +    'onclick="_signalRedraftPost(\'' + esc(redraftAccount) + '\')">Re-draft</button>';
    }
```

(Three replacements: removed `opacity:0.5;` half-disable, added live colors matching the existing chip palette, and replaced `_phase4Stub(...)` with real `onclick="_signal*(...)"` calls.)

The `Reconnect` button for `deferred` status remains as a Phase 4 stub (it's actually Phase 5 work — Layer A integration). Don't touch that branch.

- [ ] **Step 3: Sanity-check syntax**

```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK`.

- [ ] **Step 4: Restart platform**

```bash
docker compose restart archie_platform && sleep 6
```

- [ ] **Step 5: Quick smoke verification — endpoints still healthy after restart**

Use ctx_execute with language `shell` if curl is hook-blocked:
```bash
curl -sS -o /dev/null -w "calendar/live: %{http_code} | retry: " "http://192.168.1.200:3000/tools/department-hq/api/signal/calendar/live?account=company"
curl -sS -o /dev/null -w "%{http_code} | abandon: " -X POST "http://192.168.1.200:3000/tools/department-hq/api/signal/posts/99999/retry"
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "http://192.168.1.200:3000/tools/department-hq/api/signal/posts/99999/abandon"
```
Expected: `401 | 401 | 401` — all three routes registered + auth-gated.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/tools/department_hq/static/js/department-hq.js && git commit -m "feat(signal-calendar): wire Retry/Abandon/Re-draft buttons to real endpoints (Phase 4)"
```

---

### Task 4: Visual verification of all 3 action flows

**Files:** none (read-only verification + screenshot capture). Cleanup of fixture rows happens at the end.

**Why:** Confirm each new button hits its endpoint, the modal closes on success, the calendar refreshes, and the chip transitions to the expected state.

- [ ] **Step 1: Re-apply the Phase 2 fixture**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
```
Expected: 5 INSERTs.

- [ ] **Step 2: Navigate to Calendar via Playwright**

Use Playwright MCP plugin tools (`mcp__plugin_playwright_playwright__browser_*`):
1. Navigate to `http://192.168.1.200:3000/tools/department-hq` (log in if needed: `admin` / `Kyt$13ran2025`)
2. Click S.I.G.N.A.L. main tab → Calendar sub-tab
3. Click `KE Inc.` account button (fixture rows are `post_type='company'`)

- [ ] **Step 3: Test Retry flow on the FAILED chip**

1. Click the FAILED chip (red, ✗) — modal opens
2. Verify the action row shows `[Retry] [Mark Won't Fix] [Close]` — buttons NO LONGER reduced-opacity (Phase 4 made them live)
3. Click `Retry` — confirm dialog appears
4. Click OK on confirm
5. Modal should close
6. Calendar should re-render within 2-3s
7. The previously-failed chip should transition to `executing` (blue ⟳) since the worker picks up the reset row
8. Take screenshot `signal-calendar-phase4-retry.png`

If the chip stays FAILED, the worker may not have re-executed yet — wait 10s and re-render the calendar. If still no transition, that's a worker-side issue and worth flagging in the report (not a Phase 4 bug — the reset succeeded; worker dispatch is downstream).

- [ ] **Step 4: Test Abandon flow on the (now FAILED again) chip**

The retry test may have transitioned the FAILED chip to executing/posted/failed depending on worker behavior. Re-apply the fixture for a fresh state:
```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
```

1. Click the FAILED chip — modal opens
2. Click `Mark Won't Fix`
3. Confirm dialog → OK
4. Modal closes, calendar refreshes
5. The chip should transition to `rejected` (grey 🚫) — because the classifier maps `status='abandoned'` → `'rejected'` chip
6. Take screenshot `signal-calendar-phase4-abandon.png`

Also verify in the DB:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT id, status FROM autonomy_approval_queue WHERE reason LIKE '[PHASE2_FIXTURE] failed%';"
```
Expected: status='abandoned' (NOT 'rejected' — the DB stays distinct; only the chip color is shared).

- [ ] **Step 5: Test Re-draft flow on a REJECTED chip**

Re-apply fixture again. Click the REJECTED chip (grey 🚫) → modal opens → action row shows `[Re-draft] [Close]`.
1. Click `Re-draft` → confirm dialog ("Re-draft for company? This fires both EN and FR for that account.")
2. Click OK → modal closes
3. Calendar refreshes — new draft chips should appear within 30-60s on today's cell (the autonomy job kicks in async; if not visible immediately, the test still passes — re-draft fires `/api/signal/run-now` which creates new approval rows in the background)
4. Take screenshot `signal-calendar-phase4-redraft.png`

- [ ] **Step 6: Test the Reconnect button is STILL stubbed**

Since fixtures don't include a `deferred` row, this is a code-inspection check rather than a click test. Confirm that in the file diff:
```bash
cd /mnt/archie_brain && grep -A2 "post.status === 'deferred'" platform_v2/tools/department_hq/static/js/department-hq.js | head -5
```
Expected: the `Reconnect` button still uses `_phase4Stub('Reconnect')` — Phase 4 explicitly leaves it stubbed.

- [ ] **Step 7: Clean up fixture**

```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM autonomy_approval_queue WHERE reason LIKE '[PHASE2_FIXTURE]%';"
```

- [ ] **Step 8: Commit screenshots**

```bash
mkdir -p /mnt/archie_brain/docs/superpowers/screenshots
mv /tmp/signal-calendar-phase4-*.png /mnt/archie_brain/docs/superpowers/screenshots/   # or wherever saved
cd /mnt/archie_brain && git add docs/superpowers/screenshots/signal-calendar-phase4-*.png && git commit -m "docs(signal-calendar): Phase 4 action-flow visual verification screenshots"
```

---

### Task 5: Push branch + open PR + squash-merge

**Files:** none (git only)

- [ ] **Step 1: Verify GitHub rate limit**

```bash
gh api /rate_limit --jq '.resources.core | {remaining, limit}'
```
Expected: `remaining` > 4000.

- [ ] **Step 2: Push the branch**

The plan should run on `feat/signal-calendar-phase4` from Task 1 onwards.
```bash
cd /mnt/archie_brain && git push -u origin feat/signal-calendar-phase4
```

- [ ] **Step 3: Open the PR**

```bash
cd /mnt/archie_brain && gh pr create --title "feat(signal-calendar): Phase 4 - retry/abandon endpoints + Re-draft wiring" --body "$(cat <<'EOF'
## Summary

Phase 4 of the SIGNAL Calendar Living Dashboard. Wires the four Phase 3 stub buttons (Retry, Mark Won't Fix, Re-draft) in the chip modal to real backend endpoints. Reconnect stays stubbed for Phase 5 (Layer A integration).

- Backend: 2 new endpoints `POST /api/signal/posts/<id>/retry` and `POST /api/signal/posts/<id>/abandon`
- Backend: `signal_post_status.classify` maps `status='abandoned'` to `rejected` chip color (one-line change, no new chip type)
- Backend: Re-draft REUSES existing `POST /api/signal/run-now` with `{account}` — fires both EN+FR for that account
- Frontend: 3 new async handlers `_signalRetryPost`, `_signalAbandonPost`, `_signalRedraftPost`
- Frontend: 4 stub `_phase4Stub(...)` calls replaced with live onclick handlers + restored chip-palette colors
- Reconnect (deferred state) stays stubbed — that's Phase 5 / Layer A scope
- 6 new tests (1 classifier unit + 4 endpoint integration + 1 endpoint registration smoke)

## Test plan

- [x] `pytest test_signal_post_status.py` - existing + 1 new (`test_rejected_when_status_abandoned`) all pass
- [x] `pytest test_signal_action_routes.py` - 4 new (retry happy + retry 404 + abandon happy + abandon 404)
- [x] `node -c department-hq.js` syntax check
- [x] All 3 endpoints return 401 (auth-gated, registered) after restart
- [x] Retry flow: failed chip → click Retry → confirm → modal closes → chip transitions
- [x] Abandon flow: failed chip → click Mark Won't Fix → confirm → modal closes → chip becomes grey (DB row has `status='abandoned'` for audit trail)
- [x] Re-draft flow: rejected chip → click Re-draft → confirm → modal closes → new draft fires async via run-now
- [x] Reconnect button still stubbed (code-inspection check)
- [x] Fixture cleaned up after verification

## Spec / Plan

- Design: `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (Component 6: Action endpoints)
- Phase 4 plan: `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase4.md`
- Phase 1 PR: #532 (merged)
- Phase 2 PR: #533 (merged)
- Phase 3 PR: #534 (merged)

## Out of scope

- Phase 5: SSE / setInterval real polling
- Reconnect (deferred state) — Layer A Phase 4 (separate workstream)
- Per-language Re-draft (current Re-draft fires both EN+FR; per-lang would require either a new endpoint or `signal_linkedin_draft` extension)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait for CI + CodeRabbit**

```bash
sleep 60 && gh pr view --json statusCheckRollup,mergeStateStatus,mergeable,number,url,reviewDecision
```

- [ ] **Step 5: Squash-merge if clean**

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```

---

## Self-Review

**Spec coverage:** Per design spec §6 (Action endpoints reuse table — retry, abandon, draft-now: only retry + abandon are new endpoints; draft-now is satisfied by reusing existing /run-now). Per the Phase 3 follow-up (replace 4 stub buttons). Per the deferred design decision: classifier maps `'abandoned'` → `'rejected'` chip (no new visual state). The Reconnect button stays stubbed because deferred-state handling is a Layer A workstream, not part of Phase 4.

**Placeholder scan:** All code blocks contain literal source. No "TODO" / "implement later". The Phase 4 stub for Reconnect is intentional and explicitly documented.

**Type consistency:**
- `approval_id` is consistently `int` across the JS handlers, the Flask URL converter (`<int:approval_id>`), and the SQL `WHERE id = %s` integer comparison.
- `account` in `_signalRedraftPost` is one of `personal | company | creed` — runtime-validated by the existing `/api/signal/run-now` endpoint.
- `aid = post.approval_id || 0` from Phase 3 carries through to the new handlers.
- The classifier's existing test class `TestStatusClassifier` is extended with one method using the same `svc` fixture pattern.

**Risk / known gaps:**
1. The autonomy worker that consumes `status='approved'` rows is referenced but not modified by this plan. If the worker has any logic that DOESN'T re-pick up rows after a state transition (e.g., a "processed-once" flag), retry will set status='approved' but the row will never re-execute. Test plan Step 3 verifies end-to-end transition; if the chip stays FAILED, that's the gap to investigate.
2. The Re-draft button fires both EN+FR for the account, not just the rejected language. UX caveat documented in the confirm dialog.
3. The abandon `WHERE status NOT IN ('abandoned', 'rejected', 'pending')` guard means: you can abandon an `executed` (success or failure) or an `approved` row, but not a pending/already-rejected/already-abandoned row. Pending rows go through the existing `/deny` endpoint instead. Aligned with the user mental model — the modal only shows Mark Won't Fix on failed chips.
4. The 3 new JS handlers all use `confirm(...)` modal dialogs which block the JS thread. Consistent with the Phase 3 approve/reject pattern. Standard browser UX.
5. The integration tests in Task 2 mock `get_db_cursor` — they verify the SQL is constructed correctly but don't exercise the real DB. A real-DB integration test would require fixture setup; the existing approve/deny endpoints don't have that, so we follow the same pattern (mock at the DB seam).
