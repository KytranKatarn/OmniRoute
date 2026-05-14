# Tiered PR Merge Authority

**Date:** 2026-05-13
**Task:** #2794 — PR Review Pipeline
**Scope:** 3-tier PR merge hierarchy — F.O.R.G.E. auto-merges low-risk PRs, A.R.C.H.I.E. (COO) autonomously merges medium-risk PRs, Kytran approves high-risk PRs via Telegram.

---

## Context

The existing pipeline (`pr_review_service.py`) already:
- Polls open PRs (`poll_open_prs()`)
- Triggers F.O.R.G.E. code review (`mark_review_done()`)
- Has `merge_pr(pr_number, method)` ready to call
- Has `auto_merge=True` logic that fires on `VERDICT: APPROVED` in summary

The problem: mistral:7b (F.O.R.G.E.) always returns "NEEDS REVIEW", so auto-merge never fires. No tier system exists — Claude manually runs `/merge-pr` for every PR. No A.R.C.H.I.E. involvement in PR governance.

---

## Risk Classification

New function `classify_pr_tier(review_row)` in `pr_review_service.py`:

**Tier 1 — F.O.R.G.E. auto-merge:**
All of the following must be true:
- `additions + deletions < 300`
- `changed_files < 10`
- No migration files in diff (check `diff_url` content or branch name `contains "migration"`)
- PR does not touch protected files: `app.py`, `rbac.py`, `auth_service.py`, `database.py`
- F.O.R.G.E. summary contains `VERDICT` (any verdict is fine — size alone gates this tier)
- PR has label `auto-merge` OR F.O.R.G.E. verdict is APPROVED

**Tier 3 — Kytran required (highest precedence):**
Any of the following triggers Tier 3:
- `additions + deletions > 1500`
- Diff touches: `database/migrations/`, `rbac.py`, `auth_service.py`, `app.py` core auth sections
- F.O.R.G.E. verdict contains `REJECT`
- PR title contains `breaking`, `migration`, `security`

**Tier 2 — A.R.C.H.I.E. autonomous merge:**
Everything that doesn't qualify for Tier 1 or Tier 3.

Classification priority: Tier 3 checks first, then Tier 1, else Tier 2.

---

## New Job: `forge_archie_pr_review`

**File:** `ai_bridge/agent_loop.py`

New function `_run_archie_pr_review_worker()`, scheduled every 10 minutes:

```python
def _run_archie_pr_review_worker():
    """Tiered PR merge authority — F.O.R.G.E./A.R.C.H.I.E./Kytran governance."""
    from tools.repair_bay.services.pr_review_service import (
        list_reviews, merge_pr, classify_pr_tier,
    )
    from services.telegram_service import send_alert, send_info

    reviews = list_reviews(status="reviewed", state="open")
    for review in reviews:
        if review.get("merged_at") or review.get("tier_processed"):
            continue

        tier = classify_pr_tier(review)
        pr_num = review["pr_number"]
        title = review.get("title", f"PR #{pr_num}")
        summary = (review.get("ai_summary") or "")[:300]

        if tier == 1:
            result = merge_pr(pr_num, "squash")
            if result.get("merged"):
                _mark_tier_processed(pr_num, tier=1)
                send_info(
                    f"✅ F.O.R.G.E. auto-merged PR #{pr_num}: {title}",
                    source_agent="F.O.R.G.E.",
                )

        elif tier == 2:
            # A.R.C.H.I.E. autonomous merge — COO authority
            result = merge_pr(pr_num, "squash")
            if result.get("merged"):
                _mark_tier_processed(pr_num, tier=2)
                send_info(
                    f"✅ A.R.C.H.I.E. merged PR #{pr_num}: {title}\n"
                    f"Tier 2 (COO authority). F.O.R.G.E. summary: {summary}",
                    source_agent="A.R.C.H.I.E.",
                )

        elif tier == 3:
            # Escalate to Kytran via Telegram approval
            if not review.get("kytran_approval_sent"):
                _request_kytran_pr_approval(pr_num, title, summary)
                _mark_kytran_approval_sent(pr_num)
```

---

## New Function: `classify_pr_tier(review_row)`

**File:** `platform_v2/tools/repair_bay/services/pr_review_service.py`

```python
PROTECTED_FILES = {"app.py", "rbac.py", "auth_service.py", "database.py"}
TIER3_TITLE_KEYWORDS = {"breaking", "migration", "security"}


def classify_pr_tier(review: dict) -> int:
    """Return 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.), or 3 (Kytran)."""
    additions = review.get("additions") or 0
    deletions = review.get("deletions") or 0
    changed_files = review.get("changed_files") or 0
    total_changes = additions + deletions
    title = (review.get("title") or "").lower()
    summary = (review.get("ai_summary") or "").upper()
    branch = (review.get("branch") or "").lower()

    # Tier 3 gates (highest precedence)
    if total_changes > 1500:
        return 3
    if "REJECT" in summary:
        return 3
    if any(kw in title for kw in TIER3_TITLE_KEYWORDS):
        return 3
    if "migration" in branch or re.search(r"\d{3}_", branch):
        return 3

    # Tier 1 gates
    tier1_size = total_changes < 300 and changed_files < 10
    tier1_verdict = "APPROVED" in summary
    has_auto_label = "auto-merge" in ((review.get("metadata") or {}).get("labels") or [])

    if tier1_size and (tier1_verdict or has_auto_label):
        return 1

    # Default: Tier 2
    return 2
```

---

## New Helper: `_mark_tier_processed` + `_mark_kytran_approval_sent`

**File:** `platform_v2/tools/repair_bay/services/pr_review_service.py`

Two lightweight DB update functions that set flags on the `pr_reviews` row to prevent double-processing:

```python
def _mark_tier_processed(pr_number: int, tier: int) -> None:
    """Mark a PR as processed by tier merge authority."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (Json({"tier_processed": tier, "tier_processed_at": now_utc().isoformat()}), pr_number),
        )


def _mark_kytran_approval_sent(pr_number: int) -> None:
    """Mark that a Kytran Telegram approval request has been sent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (Json({"kytran_approval_sent": True}), pr_number),
        )
```

---

## Kytran Telegram Approval (Tier 3)

**File:** `ai_bridge/agent_loop.py`

New function `_request_kytran_pr_approval(pr_number, title, summary)`:

```python
def _request_kytran_pr_approval(pr_number: int, title: str, summary: str) -> None:
    """Send Telegram message to Kytran with approve/deny buttons for Tier 3 PR."""
    from services.telegram_service import send_alert

    text = (
        f"🔐 PR MERGE APPROVAL REQUIRED\n"
        f"PR #{pr_number}: {title}\n\n"
        f"F.O.R.G.E. Review:\n{summary}\n\n"
        f"Tier 3 — requires your approval to merge."
    )
    buttons = [
        [
            {"text": "✅ Merge", "callback_data": f"pr_merge_approve_{pr_number}"},
            {"text": "❌ Close", "callback_data": f"pr_merge_deny_{pr_number}"},
        ]
    ]
    send_alert(text, buttons=buttons, source_agent="A.R.C.H.I.E.")
```

**Telegram callback handler** — add to `telegram_gateway.py` in the `_escalation_callback` or equivalent:

```python
if data.startswith("pr_merge_approve_"):
    pr_num = int(data.split("_")[-1])
    from tools.repair_bay.services.pr_review_service import merge_pr, _mark_tier_processed
    result = merge_pr(pr_num, "squash")
    reply = f"✅ Merged PR #{pr_num}" if result.get("merged") else f"❌ Merge failed: {result.get('error')}"
    if result.get("merged"):
        _mark_tier_processed(pr_num, tier=3)

elif data.startswith("pr_merge_deny_"):
    pr_num = int(data.split("_")[-1])
    # Close the PR via GitHub API
    from tools.repair_bay.services.github_service import close_pr
    close_pr(pr_num)
    reply = f"❌ Closed PR #{pr_num}"
```

---

## `pr_reviews` — No Schema Change

All tier tracking uses the existing `metadata` JSONB column. No new columns needed.

Keys added to `metadata`:
- `tier_processed` (int: 1/2/3) — set after merge
- `tier_processed_at` (ISO timestamp)
- `kytran_approval_sent` (bool) — prevents repeat Telegram messages

---

## Job Registration

In `agent_loop.py` job registration block:

```python
scheduler.add_job(
    _run_archie_pr_review_worker,
    IntervalTrigger(minutes=10, timezone="America/Toronto"),
    id="forge_archie_pr_review",
    name="Tiered PR Merge Authority",
    max_instances=1,
    coalesce=True,
)
```

---

## Files Changed

| File | Action |
|------|--------|
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | Add `classify_pr_tier()`, `_mark_tier_processed()`, `_mark_kytran_approval_sent()` |
| `ai_bridge/agent_loop.py` | Add `_run_archie_pr_review_worker()` + `_request_kytran_pr_approval()` + job registration |
| `ai_bridge/telegram_gateway.py` | Add `pr_merge_approve_*` and `pr_merge_deny_*` callback handlers |

---

## Out of Scope

- GitHub PR label management (labels checked if present, not auto-applied)
- F.O.R.G.E. model upgrade (mistral:7b stays — Tier 1 uses size as primary gate)
- UI in Repair Bay for viewing tier decisions (audit trail is in metadata + logs)
- Rollback on bad auto-merge (existing auto-rollback via qa_baseline_service handles post-deploy regressions)

---

## Testing

1. Create a small test PR (<300 lines, no migrations) → verify `forge_archie_pr_review` job auto-merges it within 10 minutes
2. Create a medium PR → verify A.R.C.H.I.E. merges and Telegram notification arrives
3. Create a PR with "migration" in branch name → verify Telegram approve/deny buttons arrive
4. Tap "Merge" on Telegram → verify PR is merged
5. Tap "Close" on Telegram → verify PR is closed on GitHub
