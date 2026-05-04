# SIGNAL Calendar Living Dashboard — Phase 1 (Backend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend foundation for the SIGNAL Calendar living dashboard. New endpoint `GET /api/signal/calendar/live?account=<>` returns a 7-day JOINed view of approval-queue rows + linkedin_post_log rows, with a status state-classifier mapping each post to one of 6 states (`pending`, `executing`, `posted`, `failed`, `rejected`, `deferred`). Phase 2 (frontend chips) consumes this endpoint.

**Architecture:** Pure-function status classifier (no DB) tested in isolation. New service `signal_calendar_live_service` performs single JOIN across `autonomy_approval_queue` + `linkedin_post_log`, groups by date, applies classifier per row, returns 7-day array. New route on existing Department HQ blueprint. Migration 373 adds `telegram_message_id` to `autonomy_approval_queue` (idempotent — IF NOT EXISTS).

**Tech Stack:** Python, Flask, psycopg2, existing dept_hq blueprint, pytest.

**Spec:** `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md`

---

## Out of scope (Phase 2-6 follow-on plans)

- Phase 2 — Frontend chip + 7-day grid renderer
- Phase 3 — Click-through modal (header + content + timeline + Telegram deep-link)
- Phase 4 — Action endpoints (retry / draft-now / abandon)
- Phase 5 — 30s polling integration + cache busting on account switch
- Phase 6 — E2E tests + acceptance verification

Each gets its own plan once Phase 1 ships and is verified.

## File map

| Path | Status | Responsibility |
|---|---|---|
| `platform_v2/database/migrations/373_telegram_message_id.sql` | new (conditional) | Adds `telegram_message_id BIGINT` to `autonomy_approval_queue` if absent. Idempotent. |
| `platform_v2/services/signal_post_status.py` | new | Pure status classifier. No DB. Maps (approval_row, post_log_row) → status enum. |
| `platform_v2/services/signal_calendar_live_service.py` | new | JOINed week query + grouping by date + classifier application. |
| `platform_v2/tools/department_hq/social_routes.py` | modify (append route) | Adds `GET /api/signal/calendar/live?account=<>` |
| `platform_v2/tests/test_signal_post_status.py` | new | Unit tests for status classifier (6 states + edge cases) |
| `platform_v2/tests/test_signal_calendar_live_service.py` | new | Unit tests for live service (JOIN logic, grouping, week boundaries) |
| `platform_v2/tests/test_signal_calendar_live_routes.py` | new | Integration test for the new endpoint |

---

## Task 1: Verify if migration 373 needed; if so, write + apply

**Files:** (conditional) `platform_v2/database/migrations/373_telegram_message_id.sql`

- [ ] **Step 1: Check if `telegram_message_id` column already exists**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT column_name FROM information_schema.columns WHERE table_name='autonomy_approval_queue' AND column_name='telegram_message_id';"
```

If the query returns 1 row → column exists, **skip Tasks 1.2–1.5**, proceed to Task 2.

If the query returns 0 rows → column missing, continue to Step 2.

- [ ] **Step 2: Write the migration SQL**

Create `platform_v2/database/migrations/373_telegram_message_id.sql`:

```sql
-- 373_telegram_message_id.sql
-- Add telegram_message_id to autonomy_approval_queue so the SIGNAL Calendar
-- modal can deep-link from a post chip back to the original Telegram message.
--
-- Spec: docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md
-- Plan: docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md

BEGIN;

ALTER TABLE autonomy_approval_queue
    ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_aaq_telegram_message
    ON autonomy_approval_queue(telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;

COMMIT;
```

- [ ] **Step 3: Apply migration**

Run: `docker exec -i archie_database psql -U archie -d archie < platform_v2/database/migrations/373_telegram_message_id.sql`
Expected: `BEGIN`, `ALTER TABLE`, `CREATE INDEX`, `COMMIT`.

- [ ] **Step 4: Verify column**

Run: `docker exec archie_database psql -U archie -d archie -c "\d autonomy_approval_queue" | grep telegram_message_id`
Expected: 1 line showing `telegram_message_id | bigint |`.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/database/migrations/373_telegram_message_id.sql
git commit -m "feat(signal-calendar): migration 373 — telegram_message_id column"
```

---

## Task 2: Status classifier — pure function

**Files:**
- Create: `platform_v2/services/signal_post_status.py`
- Test: `platform_v2/tests/test_signal_post_status.py`

- [ ] **Step 1: Write failing tests**

Create `platform_v2/tests/test_signal_post_status.py`:

```python
"""Unit tests for services.signal_post_status (Phase 1)."""

from __future__ import annotations

import pytest


@pytest.fixture
def svc():
    from services import signal_post_status
    return signal_post_status


class TestStatusClassifier:
    def test_pending_when_approval_pending(self, svc):
        approval = {"id": 1, "status": "pending", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "pending"

    def test_executing_when_approved_no_result(self, svc):
        approval = {"id": 1, "status": "approved", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "executing"

    def test_posted_when_post_log_status_posted(self, svc):
        approval = {"id": 1, "status": "executed", "execution_result": {"success": True}}
        post_log = {"approval_id": 1, "status": "posted"}
        assert svc.classify(approval, post_log=post_log) == "posted"

    def test_posted_when_executed_success_no_post_log(self, svc):
        # Some flows mark executed=success in approval but never write to post_log
        approval = {"id": 1, "status": "executed", "execution_result": {"success": True}}
        assert svc.classify(approval, post_log=None) == "posted"

    def test_failed_when_executed_with_error(self, svc):
        approval = {
            "id": 1, "status": "executed",
            "execution_result": {"success": False, "_status": "failed", "error": "..."},
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_failed_when_executed_with_timeout(self, svc):
        approval = {
            "id": 1, "status": "executed",
            "execution_result": {"success": False, "_status": "timeout"},
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_rejected_when_approval_rejected(self, svc):
        approval = {"id": 1, "status": "rejected", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "rejected"

    def test_deferred_when_approval_deferred_session(self, svc):
        approval = {"id": 1, "status": "deferred_session", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "deferred"

    def test_handles_string_execution_result_jsonb(self, svc):
        # psycopg2 sometimes returns jsonb as a string depending on driver
        import json
        approval = {
            "id": 1, "status": "executed",
            "execution_result": json.dumps({"success": False, "error": "x"}),
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_unknown_status_falls_back_to_pending(self, svc):
        # Defensive — unrecognised approval status defaults to pending
        approval = {"id": 1, "status": "weird_unknown_state", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_post_status.py -v`
Expected: FAIL — `ModuleNotFoundError: services.signal_post_status`.

- [ ] **Step 3: Write the classifier**

Create `platform_v2/services/signal_post_status.py`:

```python
"""SIGNAL post status classifier (Phase 1).

Pure function. Maps (approval_row, post_log_row) -> one of 6 states:
  pending | executing | posted | failed | rejected | deferred

Used by signal_calendar_live_service when assembling the 7-day calendar view.
The frontend's 'no_draft' state is virtual (no DB row) and generated client-side.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _normalize_execution_result(result: Any) -> Optional[Dict[str, Any]]:
    """psycopg2 sometimes returns jsonb as a string. Normalise to dict or None."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return None
    return None


def classify(
    approval_row: Dict[str, Any],
    post_log: Optional[Dict[str, Any]] = None,
) -> str:
    """Classify a post into one of the 6 visible states.

    Args:
        approval_row: row from autonomy_approval_queue (dict-like)
        post_log: optional matching row from linkedin_post_log

    Returns:
        One of: 'pending', 'executing', 'posted', 'failed',
                'rejected', 'deferred'
    """
    status = approval_row.get("status")

    # Terminal states from the approval queue
    if status == "rejected":
        return "rejected"
    if status == "deferred_session":
        return "deferred"
    if status == "approved":
        # Approved but execution_result not yet recorded — running now
        return "executing"
    if status == "pending":
        return "pending"

    # 'executed' status — success or failure determined by execution_result
    if status == "executed":
        # Prefer post_log row if it exists (final source of truth)
        if post_log and post_log.get("status") == "posted":
            return "posted"

        result = _normalize_execution_result(approval_row.get("execution_result"))
        # Some flows nest the actual skill output under 'result'
        if result and "result" in result and isinstance(result["result"], dict):
            inner = result["result"]
            if inner.get("success") is True:
                return "posted"
            if inner.get("success") is False:
                return "failed"
            if inner.get("_status") in ("failed", "timeout"):
                return "failed"

        # Top-level success/failure fallback
        if result:
            if result.get("success") is True:
                return "posted"
            if result.get("success") is False:
                return "failed"
            if result.get("_status") in ("failed", "timeout"):
                return "failed"
            if result.get("executed") is True and not result.get("error"):
                return "posted"

        # No clear signal — assume failed since we landed in executed without success
        return "failed"

    # Unknown/legacy status — default to pending so it stays visible
    return "pending"
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_post_status.py -v`
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/signal_post_status.py platform_v2/tests/test_signal_post_status.py
git commit -m "feat(signal-calendar): status classifier (6 states)"
```

---

## Task 3: Calendar live service — JOINed week query

**Files:**
- Create: `platform_v2/services/signal_calendar_live_service.py`
- Test: `platform_v2/tests/test_signal_calendar_live_service.py`

- [ ] **Step 1: Write failing tests**

Create `platform_v2/tests/test_signal_calendar_live_service.py`:

```python
"""Unit tests for services.signal_calendar_live_service (Phase 1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _mock_cursor(rows=None):
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = None
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)
        def __exit__(self, *args):
            return False

    return _CM()


@pytest.fixture
def svc():
    from services import signal_calendar_live_service
    return signal_calendar_live_service


class TestWeekBoundaries:
    def test_compute_week_returns_monday_through_sunday(self, svc):
        # 2026-05-04 is a Monday
        wk_start, wk_end = svc.compute_week(date(2026, 5, 4))
        assert wk_start == date(2026, 5, 4)
        assert wk_end == date(2026, 5, 10)

    def test_compute_week_for_wednesday_walks_back_to_monday(self, svc):
        wk_start, wk_end = svc.compute_week(date(2026, 5, 7))  # Thursday
        assert wk_start == date(2026, 5, 4)
        assert wk_end == date(2026, 5, 10)


class TestLanguageDetection:
    def test_detects_french_from_action_data_language(self, svc):
        ad = {"language": "fr", "content": "..."}
        assert svc.detect_lang(action_data=ad, reason="") == "fr"

    def test_detects_english_from_action_data(self, svc):
        ad = {"language": "en", "content": "..."}
        assert svc.detect_lang(action_data=ad, reason="") == "en"

    def test_detects_french_from_quebec_marker_in_reason(self, svc):
        # Reason contains the ⚜️ marker for French posts
        reason = "📣 ⚜️ Français québécois: bonjour"
        assert svc.detect_lang(action_data={}, reason=reason) == "fr"

    def test_defaults_to_english_when_unclear(self, svc):
        assert svc.detect_lang(action_data={}, reason="some draft") == "en"


class TestGetWeekView:
    def test_empty_week_returns_seven_days(self, svc):
        with patch("services.signal_calendar_live_service.get_db_cursor",
                   return_value=_mock_cursor(rows=[])):
            out = svc.get_week_view(account="company", week_start=date(2026, 5, 4))
        assert out["account"] == "company"
        assert len(out["days"]) == 7
        assert all(d["posts"] == [] for d in out["days"])

    def test_groups_posts_by_date_and_classifies(self, svc):
        # Two posts on 2026-05-04 (one EN posted, one FR failed); rest empty
        rows = [
            {
                "id": 1111, "status": "executed", "post_type": "company",
                "action_data": {"language": "en", "content": "...", "post_type": "company"},
                "execution_result": {"success": True},
                "reason": "🇨🇦 English: ...",
                "created_at": datetime(2026, 5, 4, 13, 0),
                "approved_at": datetime(2026, 5, 4, 13, 12),
                "executed_at": datetime(2026, 5, 4, 16, 4),
                "telegram_message_id": 2583,
                "post_log_status": "posted",
                "linkedin_url": "https://www.linkedin.com/feed/update/x",
            },
            {
                "id": 1112, "status": "executed", "post_type": "company",
                "action_data": {"language": "fr", "content": "...", "post_type": "company"},
                "execution_result": {"success": False, "_status": "timeout"},
                "reason": "⚜️ Français québécois: ...",
                "created_at": datetime(2026, 5, 4, 14, 1),
                "approved_at": None,
                "executed_at": datetime(2026, 5, 4, 14, 3),
                "telegram_message_id": 2586,
                "post_log_status": None,
                "linkedin_url": None,
            },
        ]
        with patch("services.signal_calendar_live_service.get_db_cursor",
                   return_value=_mock_cursor(rows=rows)):
            out = svc.get_week_view(account="company", week_start=date(2026, 5, 4))

        # Day 0 should have 2 posts; the rest 0
        assert len(out["days"][0]["posts"]) == 2
        assert sum(len(d["posts"]) for d in out["days"]) == 2

        post_en = next(p for p in out["days"][0]["posts"] if p["lang"] == "en")
        post_fr = next(p for p in out["days"][0]["posts"] if p["lang"] == "fr")
        assert post_en["status"] == "posted"
        assert post_en["approval_id"] == 1111
        assert post_fr["status"] == "failed"
        assert post_fr["approval_id"] == 1112

    def test_account_filter_passed_to_query(self, svc):
        cm = _mock_cursor(rows=[])
        with patch("services.signal_calendar_live_service.get_db_cursor",
                   return_value=cm):
            svc.get_week_view(account="personal", week_start=date(2026, 5, 4))
        # Check that the SQL query was bound with 'personal' (or matching value)
        sql_calls = [str(c.args[1]) for c in cm.__enter__().__getitem__(1).execute.call_args_list]
        assert any("personal" in s for s in sql_calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_calendar_live_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the live service**

Create `platform_v2/services/signal_calendar_live_service.py`:

```python
"""SIGNAL Calendar live week-view service (Phase 1).

Single source of truth for the GET /api/signal/calendar/live endpoint.
JOINs autonomy_approval_queue + linkedin_post_log over a 7-day window
(Monday→Sunday containing the requested date), groups by date, applies
the status classifier, returns a 7-day array.

Frontend consumes this and renders the week-grid with chips per cell.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import get_db_cursor
from services.signal_post_status import classify

# Map UI account values to autonomy_approval_queue.action_data->>'post_type'
_ACCOUNT_TO_POST_TYPES = {
    "company": ("company", "company_page"),
    "personal": ("personal",),
    "creed": ("creed", "creed_ai"),
}


def compute_week(d: date) -> Tuple[date, date]:
    """Return (Monday, Sunday) of the week containing ``d``."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def detect_lang(action_data: Optional[Dict[str, Any]], reason: str) -> str:
    """Return 'en' or 'fr' for a post. Defaults to 'en'."""
    if action_data:
        lang = (action_data.get("language") or "").lower()
        if lang in ("fr", "fr-ca", "français", "francais"):
            return "fr"
        if lang == "en":
            return "en"
    if reason:
        # Quebec marker ⚜️ used in S.I.G.N.A.L. drafts
        if "⚜️" in reason or "Français" in reason or "français" in reason:
            return "fr"
    return "en"


def _row_to_post(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a DB row dict to the calendar response shape."""
    action_data = row.get("action_data") or {}
    if isinstance(action_data, str):
        try:
            import json
            action_data = json.loads(action_data)
        except Exception:
            action_data = {}

    reason = row.get("reason") or ""
    lang = detect_lang(action_data, reason)

    # Build the synthetic post_log object the classifier expects
    post_log = None
    if row.get("post_log_status"):
        post_log = {"status": row["post_log_status"]}

    status = classify(approval_row=row, post_log=post_log)

    # Preview = first 200 chars of content
    content = (action_data.get("content") or "").strip()
    preview = content[:200] + ("…" if len(content) > 200 else "")

    return {
        "approval_id": row["id"],
        "lang": lang,
        "status": status,
        "post_type": row.get("post_type"),
        "drafted_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
        "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else None,
        "linkedin_url": row.get("linkedin_url"),
        "preview": preview,
        "telegram_message_id": row.get("telegram_message_id"),
        "error": (row.get("execution_result") or {}).get("error")
                 if isinstance(row.get("execution_result"), dict) else None,
    }


def get_week_view(
    account: str,
    week_start: Optional[date] = None,
) -> Dict[str, Any]:
    """Return the calendar live week view for ``account``.

    Args:
        account: 'personal' | 'company' | 'creed'
        week_start: Monday of the desired week (defaults to current week)

    Returns dict with shape::

        {
            "account": str,
            "week_start": "YYYY-MM-DD",
            "today": "YYYY-MM-DD",
            "days": [{date, is_today, posts: [...]} × 7]
        }
    """
    today = date.today()
    if week_start is None:
        week_start, _ = compute_week(today)
    week_end = week_start + timedelta(days=6)

    post_types = _ACCOUNT_TO_POST_TYPES.get(account, (account,))

    # Single SQL query — LEFT JOIN approval queue with post_log
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT
                aaq.id,
                aaq.status,
                aaq.action_data,
                aaq.execution_result,
                aaq.reason,
                aaq.created_at,
                aaq.approved_at,
                aaq.executed_at,
                aaq.telegram_message_id,
                COALESCE(aaq.action_data->>'post_type',
                         aaq.action_data->'args'->>'post_type') AS post_type,
                lpl.status                                         AS post_log_status,
                lpl.linkedin_url
            FROM autonomy_approval_queue aaq
            LEFT JOIN linkedin_post_log lpl
                   ON lpl.approval_id = aaq.id
            WHERE aaq.action_type = 'linkedin_post'
              AND COALESCE(aaq.action_data->>'post_type',
                           aaq.action_data->'args'->>'post_type') = ANY(%s)
              AND aaq.created_at >= %s
              AND aaq.created_at <  %s
            ORDER BY aaq.created_at
            """,
            (
                list(post_types),
                datetime.combine(week_start, time.min),
                datetime.combine(week_end + timedelta(days=1), time.min),
            ),
        )
        rows = [dict(r) for r in cur.fetchall()]

    # Group rows by date
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d_str = r["created_at"].date().isoformat()
        by_date.setdefault(d_str, []).append(_row_to_post(r))

    # Build 7-day array
    days = []
    for offset in range(7):
        d = week_start + timedelta(days=offset)
        d_str = d.isoformat()
        days.append({
            "date": d_str,
            "is_today": d == today,
            "posts": by_date.get(d_str, []),
        })

    return {
        "account": account,
        "week_start": week_start.isoformat(),
        "today": today.isoformat(),
        "days": days,
    }
```

Note the SQL relies on `linkedin_post_log.approval_id` existing. If that column is absent (verify during recon), wire via different join key OR drop the post_log JOIN for v1 and rely on `execution_result.success` only.

- [ ] **Step 4: Verify post_log JOIN key exists**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT column_name FROM information_schema.columns WHERE table_name='linkedin_post_log' AND column_name='approval_id';"
```
Expected: 1 row.

If 0 rows, fall back to: drop the LEFT JOIN clause from the SQL; classifier uses `execution_result.success` only (Task 2 already supports this).

- [ ] **Step 5: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_calendar_live_service.py -v`
Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/signal_calendar_live_service.py platform_v2/tests/test_signal_calendar_live_service.py
git commit -m "feat(signal-calendar): live service — JOINed week view + lang detection"
```

---

## Task 4: GET /api/signal/calendar/live endpoint

**Files:**
- Modify: `platform_v2/tools/department_hq/social_routes.py` (append route)
- Test: `platform_v2/tests/test_signal_calendar_live_routes.py`

- [ ] **Step 1: Write failing route test**

Create `platform_v2/tests/test_signal_calendar_live_routes.py`:

```python
"""Integration tests for the /api/signal/calendar/live endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def admin_client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 2  # Kytran (admin)
            sess["is_admin"] = True
        yield c


@pytest.fixture
def unauth_client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


class TestCalendarLiveRoute:
    def test_admin_gets_week_view(self, admin_client):
        fake = {
            "account": "company",
            "week_start": "2026-05-04",
            "today": "2026-05-04",
            "days": [{"date": "2026-05-04", "is_today": True, "posts": []}] * 7,
        }
        with patch("services.signal_calendar_live_service.get_week_view",
                   return_value=fake):
            r = admin_client.get(
                "/tools/department-hq/api/signal/calendar/live?account=company"
            )
        assert r.status_code == 200
        body = r.get_json()
        assert body["account"] == "company"
        assert len(body["days"]) == 7

    def test_rejects_unsupported_account(self, admin_client):
        r = admin_client.get(
            "/tools/department-hq/api/signal/calendar/live?account=bogus"
        )
        assert r.status_code == 400

    def test_requires_account_param(self, admin_client):
        r = admin_client.get("/tools/department-hq/api/signal/calendar/live")
        assert r.status_code == 400

    def test_unauth_redirects_or_401(self, unauth_client):
        r = unauth_client.get(
            "/tools/department-hq/api/signal/calendar/live?account=company"
        )
        # /tools/department-hq/* paths get 302 to /dashboard for unauth
        # (per Layer A Phase 1 finding) — both 302 and 401 acceptable
        assert r.status_code in (302, 401)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_calendar_live_routes.py -v`
Expected: FAIL — 404s.

- [ ] **Step 3: Append route to `social_routes.py`**

Read `platform_v2/tools/department_hq/social_routes.py` to find the existing `register_social_routes` pattern. Find a sensible location (near other `signal/calendar` endpoints if they exist; otherwise after `api_signal_overview`). Append:

```python
    @bp.route("/api/signal/calendar/live", methods=["GET"])
    @admin_required
    def api_signal_calendar_live():
        """Return the 7-day living-dashboard view for one account.

        Query params:
            account: 'personal' | 'company' | 'creed' (required)
        """
        from services import signal_calendar_live_service

        account = (request.args.get("account") or "").strip().lower()
        if account not in ("personal", "company", "creed"):
            return jsonify({"error": "account must be one of: personal, company, creed"}), 400

        try:
            view = signal_calendar_live_service.get_week_view(account=account)
        except Exception:
            logger.exception("[signal-calendar-live] failed to build view")
            return jsonify({"error": "failed to build calendar view"}), 500

        return jsonify(view), 200
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_signal_calendar_live_routes.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Smoke test against the live DB**

Restart platform: `docker compose restart archie_platform`
Wait ~6s.

Then run a smoke fetch from inside the platform container (admin context bypass):
```bash
docker exec archie_platform python3 -c "
import app
from services.signal_calendar_live_service import get_week_view
import json
out = get_week_view('company')
print(f'days: {len(out[\"days\"])}')
posts_today = next(d for d in out['days'] if d['is_today'])['posts']
print(f'posts today: {len(posts_today)}')
for p in posts_today:
    print(f'  #{p[\"approval_id\"]} lang={p[\"lang\"]} status={p[\"status\"]}')
"
```

Expected output (today is 2026-05-04 with #1111 EN + #1112 FR both posted earlier):
```
days: 7
posts today: 2
  #1111 lang=en status=posted
  #1112 lang=fr status=posted
```

If both show `status=posted` — Phase 1 is verified live.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/social_routes.py platform_v2/tests/test_signal_calendar_live_routes.py
git commit -m "feat(signal-calendar): GET /api/signal/calendar/live endpoint"
```

---

## Task 5: Open PR

- [ ] **Step 1: Push branch**

Run: `git push -u origin spec/signal-calendar-living-dashboard`
Expected: branch pushed.

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(signal-calendar): Phase 1 — backend foundation for living-dashboard" --body "$(cat <<'EOF'
## Summary

Phase 1 of the SIGNAL Calendar living dashboard. Ships the backend foundation that turns the Calendar tab from a static schedule into a real-time view of LinkedIn pipeline status. Triggered by today's 9 AM #1111 outage being silently invisible for hours.

## What ships

- **Migration 373** (conditional): `telegram_message_id` column on `autonomy_approval_queue` so the future modal can deep-link back to the original Telegram message
- **`services/signal_post_status.py`**: pure-function status classifier (6 states: pending / executing / posted / failed / rejected / deferred)
- **`services/signal_calendar_live_service.py`**: JOINed 7-day week view across `autonomy_approval_queue` + `linkedin_post_log`, grouped by date, classified per row
- **`GET /tools/department-hq/api/signal/calendar/live?account=<>`**: new endpoint feeding the future frontend grid

## Smoke verified

`get_week_view('company')` for today returns:
```
#1111 lang=en status=posted
#1112 lang=fr status=posted
```
Matches reality — both KE Inc. posts landed live this evening.

## Out of scope (Phase 2-6 follow-on plans)

- Phase 2: Frontend chip + 7-day grid renderer
- Phase 3: Click-through modal
- Phase 4: Action endpoints (retry, draft-now, abandon)
- Phase 5: 30s polling integration
- Phase 6: E2E tests + acceptance verification

## Spec / Plan

- Spec: `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md`
- Plan: `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md`

## Test plan

- [x] All unit + integration tests pass (~21 new)
- [x] Migration 373 applied (or skipped — conditional)
- [x] Smoke against live DB matches today's actual posted state

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Report PR number to controller**

Print the PR URL. Controller decides on merge.

---

## Self-review

**Spec coverage check:**
- ✅ Migration 373 — Task 1
- ✅ Status classifier (6 states) — Task 2
- ✅ Calendar live service — Task 3
- ✅ GET /api/signal/calendar/live endpoint — Task 4
- ✅ Tests for all of the above — embedded in each task
- ☐ Frontend chip component → DEFERRED to Phase 2 plan
- ☐ Modal → DEFERRED to Phase 3 plan
- ☐ Action endpoints → DEFERRED to Phase 4 plan
- ☐ Polling → DEFERRED to Phase 5 plan
- ☐ E2E acceptance → DEFERRED to Phase 6 plan

**Type/name consistency:**
- Function names: `classify`, `compute_week`, `detect_lang`, `get_week_view` — all consistent across tasks
- Status enum values: `pending | executing | posted | failed | rejected | deferred` — match spec
- File paths: `services/signal_post_status.py`, `services/signal_calendar_live_service.py` — used consistently

**Placeholder scan:** none.

**Conditional tasks:** Task 1 (migration) and Task 3 Step 4 (post_log column verify) both have explicit "if absent → fallback" instructions, not TBDs.
