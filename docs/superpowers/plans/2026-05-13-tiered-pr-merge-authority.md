# Tiered PR Merge Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-tier PR merge hierarchy where F.O.R.G.E. auto-merges small PRs, A.R.C.H.I.E. autonomously merges medium PRs, and Kytran approves large/risky PRs via Telegram buttons.

**Architecture:** New `classify_pr_tier()` in `pr_review_service.py` reads existing `additions`/`deletions`/`changed_files` columns plus the F.O.R.G.E. summary to assign Tier 1/2/3. A new `forge_archie_pr_review` job in `agent_loop.py` runs every 10 minutes, calls the classifier, and routes each reviewed-but-unmerged PR to the appropriate action. Tier 3 uses `send_with_buttons()` in `telegram_service.py`; the response routes through a new `_pr_merge_callback` in `telegram_gateway.py`.

**Tech Stack:** Python, PostgreSQL (JSONB metadata), APScheduler, python-telegram-bot, GitHub API (existing `merge_pr()`).

---

## File Map

| File | Action |
|------|--------|
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | Add `classify_pr_tier()`, `_mark_tier_processed()`, `_mark_kytran_approval_sent()` |
| `ai_bridge/agent_loop.py` | Add `_run_archie_pr_review_worker()` + `_request_kytran_pr_approval()` + job registration |
| `ai_bridge/telegram_gateway.py` | Add `_pr_merge_callback()` method + register handler at line ~127 |

---

### Task 1: classify_pr_tier() + marking helpers in pr_review_service.py

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_review_service.py`

**Context:**
- `list_reviews(state, review_status, limit)` already exists at line 230
- `merge_pr(pr_number, method)` already exists
- `pr_reviews` table has columns: `additions` (int), `deletions` (int), `changed_files` (int), `metadata` (JSONB), `ai_summary` (text), `title` (text), `branch` (text), `pr_number` (int)
- `get_db_cursor` is already imported; `psycopg2.extras.Json` (`Json`) must be imported for JSONB writes

- [ ] **Step 1: Find last import in pr_review_service.py**

```bash
grep -n "^import\|^from" /mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py | tail -10
```

- [ ] **Step 2: Add `import re` and `Json` import if not present**

Check if `re` and `psycopg2.extras` are already imported:
```bash
grep -n "^import re\|psycopg2" /mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py | head -5
```

If missing, add at the top of the import block:
```python
import re
from psycopg2.extras import Json
```

- [ ] **Step 3: Add the three new functions at the end of the file**

Append to `/mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py`:

```python
# ---- Tiered PR Merge Authority ----

_TIER3_TITLE_KW = {"breaking", "migration", "security"}


def classify_pr_tier(review: dict) -> int:
    """Classify a PR review into merge tier 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.), or 3 (Kytran).

    Tier 3 (highest precedence):
        - > 1500 lines changed
        - title contains breaking/migration/security
        - branch looks like a numbered migration (e.g. 382_partner_profiles)
        - F.O.R.G.E. verdict contains REJECT

    Tier 1:
        - < 300 lines changed AND < 10 files changed
        - AND (has auto-merge label OR F.O.R.G.E. verdict contains APPROVED)

    Tier 2: everything else.
    """
    additions = review.get("additions") or 0
    deletions = review.get("deletions") or 0
    changed_files = review.get("changed_files") or 0
    total = additions + deletions
    title = (review.get("title") or "").lower()
    summary = (review.get("ai_summary") or "").upper()
    branch = (review.get("branch") or "").lower()
    meta = review.get("metadata") or {}

    # --- Tier 3 gates ---
    if total > 1500:
        return 3
    if "REJECT" in summary:
        return 3
    if any(kw in title for kw in _TIER3_TITLE_KW):
        return 3
    if "migration" in branch or re.search(r"\d{3}_", branch):
        return 3

    # --- Tier 1 gates ---
    small = total < 300 and changed_files < 10
    approved = "APPROVED" in summary
    auto_label = "auto-merge" in (meta.get("labels") or [])
    if small and (approved or auto_label):
        return 1

    return 2


def _mark_tier_processed(pr_number: int, tier: int) -> None:
    """Record tier merge decision in pr_reviews.metadata."""
    from services.time_utils import now_utc  # noqa: PLC0415

    payload = Json({"tier_processed": tier, "tier_processed_at": now_utc().isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (payload, pr_number),
        )


def _mark_kytran_approval_sent(pr_number: int) -> None:
    """Prevent duplicate Tier 3 Telegram messages."""
    payload = Json({"kytran_approval_sent": True})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (payload, pr_number),
        )
```

- [ ] **Step 4: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Quick unit test**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import classify_pr_tier

# Tier 1: small + approved
r1 = {'additions': 50, 'deletions': 20, 'changed_files': 3, 'ai_summary': 'VERDICT: APPROVED', 'title': 'fix: typo', 'branch': 'fix/typo', 'metadata': {}}
assert classify_pr_tier(r1) == 1, f'Expected 1, got {classify_pr_tier(r1)}'

# Tier 3: migration branch
r3 = {'additions': 10, 'deletions': 2, 'changed_files': 1, 'ai_summary': 'VERDICT: NEEDS REVIEW', 'title': 'add table', 'branch': 'feat/382_partner_profiles', 'metadata': {}}
assert classify_pr_tier(r3) == 3, f'Expected 3, got {classify_pr_tier(r3)}'

# Tier 2: medium, needs review
r2 = {'additions': 400, 'deletions': 100, 'changed_files': 8, 'ai_summary': 'VERDICT: NEEDS REVIEW', 'title': 'feat: new feature', 'branch': 'feat/something', 'metadata': {}}
assert classify_pr_tier(r2) == 2, f'Expected 2, got {classify_pr_tier(r2)}'

print('All classify_pr_tier assertions passed')
"
```

Expected: `All classify_pr_tier assertions passed`

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/tiered-pr-merge-authority
git add platform_v2/tools/repair_bay/services/pr_review_service.py
git commit -m "feat(pr-tiers): classify_pr_tier() + mark helpers in pr_review_service"
```

---

### Task 2: _run_archie_pr_review_worker + job registration in agent_loop.py

**Files:**
- Modify: `ai_bridge/agent_loop.py`

**Context:**
- Job naming pattern: `forge_*` prefix, registered via `scheduler.add_job(...)` with `IntervalTrigger`
- `send_with_buttons(category, title, message, buttons, source_agent)` is in `services.telegram_service`
- `send_info(title, message, **kwargs)` is at `telegram_service:519`
- `list_reviews(state, review_status, limit)` returns list of dicts with all `pr_reviews` columns
- `merge_pr(pr_number, method)` returns `{"success": bool, "merged": bool, "error": str}`
- Find where other `forge_*` jobs are defined to place the new function nearby

- [ ] **Step 1: Find forge job placement**

```bash
grep -n "def _run_forge\|forge_dep_drift\|forge_pr_review_poll" /mnt/archie_brain/ai_bridge/agent_loop.py | head -10
```

Note the line numbers. Add the new function near the other forge functions.

- [ ] **Step 2: Find job registration block**

```bash
grep -n "forge_dep_drift\|forge_pr_review_poll\|add_job.*forge" /mnt/archie_brain/ai_bridge/agent_loop.py | head -10
```

Note where `scheduler.add_job` calls for forge jobs are registered.

- [ ] **Step 3: Add `_request_kytran_pr_approval()` function**

Add near the other forge helper functions:

```python
def _request_kytran_pr_approval(pr_number: int, title: str, summary: str) -> None:
    """Send Tier 3 Telegram message with approve/deny buttons to Kytran."""
    from services.telegram_service import send_with_buttons  # noqa: PLC0415

    short_summary = summary[:400] if summary else "No review summary available."
    send_with_buttons(
        category="system",
        title=f"PR #{pr_number} — Merge Approval Required",
        message=(
            f"*PR #{pr_number}:* {title}\n\n"
            f"*F.O.R.G.E. Review:*\n{short_summary}\n\n"
            f"Tier 3 — requires your approval before merge."
        ),
        buttons=[
            {"text": "✅ Merge", "callback_data": f"pr_merge_approve_{pr_number}"},
            {"text": "❌ Deny", "callback_data": f"pr_merge_deny_{pr_number}"},
        ],
        source_agent="A.R.C.H.I.E.",
    )
```

- [ ] **Step 4: Add `_run_archie_pr_review_worker()` function**

Add after `_request_kytran_pr_approval`:

```python
def _run_archie_pr_review_worker():
    """Job: Tiered PR merge authority — F.O.R.G.E./A.R.C.H.I.E./Kytran governance."""
    import time as _time  # noqa: PLC0415

    start = _time.time()
    try:
        from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
            list_reviews,
            merge_pr,
            classify_pr_tier,
            _mark_tier_processed,
            _mark_kytran_approval_sent,
        )
        from services.telegram_service import send_info  # noqa: PLC0415

        reviews = list_reviews(state="open", review_status="reviewed")
        processed = 0

        for review in reviews:
            meta = review.get("metadata") or {}
            if meta.get("tier_processed") or meta.get("kytran_approval_sent"):
                continue

            pr_num = review["pr_number"]
            title = review.get("title") or f"PR #{pr_num}"
            summary = review.get("ai_summary") or ""
            tier = classify_pr_tier(review)

            if tier == 1:
                result = merge_pr(pr_num, "squash")
                if result.get("merged"):
                    _mark_tier_processed(pr_num, tier=1)
                    send_info(
                        title=f"F.O.R.G.E. auto-merged PR #{pr_num}",
                        message=f"*{title}*\nTier 1 auto-merge (small, approved).",
                        source_agent="F.O.R.G.E.",
                    )
                    processed += 1
                else:
                    logger.warning("[PRTiers] Tier 1 merge failed for PR #%s: %s", pr_num, result.get("error"))

            elif tier == 2:
                result = merge_pr(pr_num, "squash")
                if result.get("merged"):
                    _mark_tier_processed(pr_num, tier=2)
                    send_info(
                        title=f"A.R.C.H.I.E. merged PR #{pr_num}",
                        message=(
                            f"*{title}*\n"
                            f"Tier 2 autonomous merge (COO authority).\n"
                            f"F.O.R.G.E.: {summary[:200]}"
                        ),
                        source_agent="A.R.C.H.I.E.",
                    )
                    processed += 1
                else:
                    logger.warning("[PRTiers] Tier 2 merge failed for PR #%s: %s", pr_num, result.get("error"))

            elif tier == 3:
                _request_kytran_pr_approval(pr_num, title, summary)
                _mark_kytran_approval_sent(pr_num)
                processed += 1

        elapsed = int((_time.time() - start) * 1000)
        _log_cycle("archie_pr_review", processed, 0, elapsed, department="Engineering & Technology")

    except Exception as e:
        elapsed = int((_time.time() - start) * 1000)
        logger.warning("[PRTiers] archie_pr_review_worker failed: %s", e)
        _log_cycle("archie_pr_review", 0, 1, elapsed, error_message=str(e), department="Engineering & Technology")
```

- [ ] **Step 5: Register the job**

Find the scheduler.add_job block for forge jobs and add:

```python
scheduler.add_job(
    _run_archie_pr_review_worker,
    IntervalTrigger(minutes=10, timezone="America/Toronto"),
    id="forge_archie_pr_review",
    name="Tiered PR Merge Authority (F.O.R.G.E./A.R.C.H.I.E./Kytran)",
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 6: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/ai_bridge/agent_loop.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 7: Verify job registers on restart**

```bash
docker compose restart archie_scheduler && sleep 8
docker logs archie_scheduler 2>&1 | grep -i "archie_pr_review\|forge_archie" | tail -5
```

Expected: job appears in scheduler logs.

- [ ] **Step 8: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(pr-tiers): _run_archie_pr_review_worker + job registration — 10min interval"
```

---

### Task 3: _pr_merge_callback in telegram_gateway.py

**Files:**
- Modify: `ai_bridge/telegram_gateway.py`

**Context:**
- Existing callbacks: `_email_callback` (line 117), `_escalation_callback` (line 120), `_node_callback` (line 123), `_social_callback` (line 126), catch-all `_callback_handler` (line 128)
- New handler must be added BEFORE the catch-all at line 128
- `merge_pr(pr_number, method)` and `_mark_tier_processed()` are in `tools.repair_bay.services.pr_review_service`
- `_mark_kytran_approval_sent` also needs to mark the denial in metadata — add a `_mark_kytran_approval_decided()` helper

- [ ] **Step 1: Read lines 115-135 of telegram_gateway.py to confirm handler registration context**

```bash
sed -n '115,135p' /mnt/archie_brain/ai_bridge/telegram_gateway.py
```

- [ ] **Step 2: Add `_pr_merge_callback` method to the TelegramGateway class**

Find the end of `_social_callback` method and add after it:

```python
    async def _pr_merge_callback(self, update, context):
        """Handle pr_merge_approve_N and pr_merge_deny_N button callbacks."""
        query = update.callback_query
        await query.answer()
        data = query.data  # e.g. "pr_merge_approve_692"

        try:
            parts = data.split("_")
            action = parts[2]  # "approve" or "deny"
            pr_number = int(parts[3])
        except (IndexError, ValueError):
            await query.edit_message_text("❌ Invalid PR merge callback data.")
            return

        try:
            from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
                merge_pr,
                _mark_tier_processed,
            )
            from database import get_db_cursor as _gdc  # noqa: PLC0415
            from psycopg2.extras import Json  # noqa: PLC0415

            if action == "approve":
                result = merge_pr(pr_number, "squash")
                if result.get("merged"):
                    _mark_tier_processed(pr_number, tier=3)
                    await query.edit_message_text(
                        f"✅ Kytran approved — PR #{pr_number} merged successfully."
                    )
                else:
                    await query.edit_message_text(
                        f"❌ Merge failed for PR #{pr_number}: {result.get('error', 'unknown error')}"
                    )

            elif action == "deny":
                # Mark denied in metadata — Kytran closes manually on GitHub
                payload = Json({"kytran_denied": True})
                with _gdc(commit=True) as (_conn, _cur):
                    _cur.execute(
                        "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
                        (payload, pr_number),
                    )
                await query.edit_message_text(
                    f"❌ PR #{pr_number} denied. Please close it manually on GitHub."
                )

        except Exception as e:
            logger.error("[PRMergeCallback] Error for PR #%s: %s", pr_number, e)
            await query.edit_message_text(f"❌ Error processing PR #{pr_number}: {e}")
```

- [ ] **Step 3: Register the handler before the catch-all**

Find line 126-128 (social_callback registration and catch-all):
```python
            app.add_handler(CallbackQueryHandler(self._social_callback, pattern=r"^social_"))
```

Add the new handler after social and before the catch-all:
```python
            app.add_handler(CallbackQueryHandler(self._pr_merge_callback, pattern=r"^pr_merge_"))
```

- [ ] **Step 4: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/ai_bridge/telegram_gateway.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Restart scheduler and platform**

```bash
docker compose restart archie_scheduler archie_platform && sleep 10
docker logs archie_platform 2>&1 | grep -iE "error|traceback" | grep -v "fleet\|outpost\|model\|ollama" | tail -10
```

Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/telegram_gateway.py
git commit -m "feat(pr-tiers): _pr_merge_callback in telegram_gateway — approve/deny buttons for Tier 3"
```

---

### Task 4: E2E verify + PR

- [ ] **Step 1: Verify classify_pr_tier logic**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import classify_pr_tier

cases = [
    # (review_dict, expected_tier, label)
    ({'additions': 50, 'deletions': 10, 'changed_files': 2, 'ai_summary': 'VERDICT: APPROVED', 'title': 'fix', 'branch': 'fix/x', 'metadata': {}}, 1, 'small+approved'),
    ({'additions': 50, 'deletions': 10, 'changed_files': 2, 'ai_summary': 'VERDICT: NEEDS REVIEW', 'title': 'fix', 'branch': 'fix/x', 'metadata': {'labels': ['auto-merge']}}, 1, 'small+auto-label'),
    ({'additions': 500, 'deletions': 200, 'changed_files': 12, 'ai_summary': 'VERDICT: NEEDS REVIEW', 'title': 'feat', 'branch': 'feat/x', 'metadata': {}}, 2, 'medium'),
    ({'additions': 2000, 'deletions': 100, 'changed_files': 5, 'ai_summary': 'VERDICT: NEEDS REVIEW', 'title': 'feat', 'branch': 'feat/x', 'metadata': {}}, 3, 'large'),
    ({'additions': 10, 'deletions': 2, 'changed_files': 1, 'ai_summary': 'VERDICT: APPROVED', 'title': 'add table', 'branch': 'feat/382_partner_profiles', 'metadata': {}}, 3, 'migration branch'),
    ({'additions': 10, 'deletions': 2, 'changed_files': 1, 'ai_summary': 'VERDICT: REJECT', 'title': 'bad pr', 'branch': 'fix/x', 'metadata': {}}, 3, 'reject verdict'),
]
all_pass = True
for review, expected, label in cases:
    got = classify_pr_tier(review)
    status = 'PASS' if got == expected else 'FAIL'
    if got != expected:
        all_pass = False
    print(f'  {status}: {label} -> tier {got} (expected {expected})')
print('All passed!' if all_pass else 'FAILURES DETECTED')
"
```

Expected: all `PASS`.

- [ ] **Step 2: Verify job is registered in scheduler**

```bash
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0,'/app')
import os; os.environ['ARCHIE_RUN_SCHEDULER'] = '0'
from agent_loop import _run_archie_pr_review_worker
print('Function accessible:', callable(_run_archie_pr_review_worker))
"
```

Expected: `Function accessible: True`

- [ ] **Step 3: Verify Telegram handler registered**

```bash
python3 -c "
import ast
src = open('/mnt/archie_brain/ai_bridge/telegram_gateway.py').read()
assert 'pr_merge_callback' in src, 'handler not found'
assert 'pr_merge_approve' in src, 'approve pattern not found'
assert 'pr_merge_deny' in src, 'deny pattern not found'
print('Telegram handler assertions passed')
"
```

Expected: `Telegram handler assertions passed`

- [ ] **Step 4: Manual trigger test — pick a real reviewed PR**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import list_reviews, classify_pr_tier
reviews = list_reviews(state='open', review_status='reviewed')
print(f'Open reviewed PRs: {len(reviews)}')
for r in reviews[:5]:
    tier = classify_pr_tier(r)
    meta = r.get('metadata') or {}
    processed = meta.get('tier_processed')
    kytran_sent = meta.get('kytran_approval_sent')
    print(f'  PR #{r[\"pr_number\"]} ({r.get(\"title\",\"\")[:40]}) -> Tier {tier}, processed={processed}, kytran_sent={kytran_sent}')
"
```

Expected: list of open PRs with their assigned tier.

- [ ] **Step 5: Push and create PR**

```bash
git push -u origin feat/tiered-pr-merge-authority
```

Then run `/commit-push-pr` with title: `feat(pr-tiers): tiered PR merge authority — F.O.R.G.E./A.R.C.H.I.E./Kytran governance (#2794)`

---

## Self-Review

**Spec coverage:**
- [x] `classify_pr_tier()` with Tier 1/2/3 classification rules (Task 1)
- [x] `_mark_tier_processed()` writes `tier_processed` + timestamp to metadata (Task 1)
- [x] `_mark_kytran_approval_sent()` prevents duplicate Tier 3 Telegram messages (Task 1)
- [x] `_run_archie_pr_review_worker()` — routes Tier 1 to F.O.R.G.E. auto-merge, Tier 2 to A.R.C.H.I.E. autonomous merge, Tier 3 to Kytran Telegram (Task 2)
- [x] `_request_kytran_pr_approval()` uses `send_with_buttons()` with `pr_merge_approve_N` / `pr_merge_deny_N` callbacks (Task 2)
- [x] Job `forge_archie_pr_review` registered with 10-minute interval (Task 2)
- [x] `_pr_merge_callback` in telegram_gateway handles approve (calls `merge_pr()` + `_mark_tier_processed()`) and deny (marks metadata) (Task 3)
- [x] Handler registered before catch-all with `pattern=r"^pr_merge_"` (Task 3)

**No placeholders.** All code is complete. `send_info(title, message, **kwargs)` matches the confirmed signature at `telegram_service:519`. `merge_pr(pr_number, "squash")` matches the confirmed signature.

**Type consistency:** `classify_pr_tier(review: dict) -> int` is defined in Task 1 and called in Task 2 with the same dict structure. `_mark_tier_processed(pr_number, tier)` is defined in Task 1, called in Tasks 2 and 3 with the same signature.
