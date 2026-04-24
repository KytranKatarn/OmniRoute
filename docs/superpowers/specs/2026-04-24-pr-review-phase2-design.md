# PR Review Pipeline — Phase 2: F.O.R.G.E. AI Diff Analysis

**Date**: 2026-04-24
**Project**: #247 — PR Review Pipeline — Repair Bay Integration
**Task**: #1800 — Phase 2: AI Review via F.O.R.G.E. — Bridge dispatch for diff analysis
**Status**: Approved by user 2026-04-24

---

## Goal

Wire F.O.R.G.E. into the PR review pipeline so every pending PR gets an AI code review: a one-paragraph summary, a bulleted issues list with severity, and an APPROVE / REQUEST CHANGES / NEEDS REVIEW verdict — all stored in `pr_reviews.ai_summary`.

---

## Context: What Phase 1 Built

- **Table**: `pr_reviews` — columns include `pr_number`, `repo`, `title`, `author`, `diff_url`, `additions`, `deletions`, `changed_files`, `review_status` (pending → in_progress → reviewed), `ai_summary`, `ai_review_at`
- **Service**: `platform_v2/tools/repair_bay/services/pr_review_service.py`
  - `get_pending_reviews(limit)` — returns PRs with `review_status='pending'`
  - `mark_review_started(pr_number)` — sets status to `in_progress`
  - `mark_review_done(pr_number, summary)` — sets status to `reviewed`, stores summary
- **Scheduler**: Agent loop polls GitHub every 5 min for new PRs
- **Routes**: `platform_v2/tools/repair_bay/github_routes.py` — list, get, poll, skip endpoints

---

## Architecture

```
agent_loop (10min job) → analyze_pending_prs(max_prs=3)
    └── get_pending_reviews(limit=3)
        └── for each pending PR:
              mark_review_started(pr_number)
              _fetch_diff(diff_url)           ← GitHub API, GITHUB_TOKEN
              _build_prompt(review, diff)     ← truncate at 6000 chars
              dispatch("code_review", prompt) ← F.O.R.G.E. via Bridge
              mark_review_done(pr_number, summary)
              [on error: mark back to pending, log, continue]
```

---

## Components

### 1. `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py` (new)

**Public API:**
```python
def analyze_pending_prs(max_prs: int = 3) -> dict:
    """Process up to max_prs pending reviews. Returns {processed, failed, skipped}."""
```

**Internal functions:**
- `_fetch_diff(diff_url: str) -> str` — GET diff_url with `Authorization: token {GITHUB_TOKEN}`, `Accept: application/vnd.github.v3.diff`. Returns raw diff string. Raises on non-200.
- `_build_prompt(review: dict, diff: str) -> str` — assembles the F.O.R.G.E. prompt (see below). Truncates diff at 6000 chars with a note.
- `_run_forge_review(prompt: str) -> str` — calls `dispatch("code_review", prompt, module_id="repair_bay")`. Returns the response string.

**Error contract:**
- If `_fetch_diff` fails → mark review back to `pending` (not `in_progress`) so it retries next cycle. Log with `logger.warning`.
- If `_run_forge_review` fails → same: revert to `pending`, log.
- One PR failure does not block others — exception is caught per-PR, loop continues.

### 2. Agent loop job

In `ai_bridge/agent_loop.py`, add a new scheduled job:

```python
def _run_pr_diff_analysis():
    """Phase 2: F.O.R.G.E. AI review of pending PRs."""
    from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs
    result = analyze_pending_prs(max_prs=3)
    logger.info(f"[PR Review] processed={result['processed']} failed={result['failed']}")
```

Schedule: every 10 minutes (`minutes=10`), `max_instances=1`, `coalesce=True`.

### 3. On-demand route

In `platform_v2/tools/repair_bay/github_routes.py`, add:

```
POST /api/repair-bay/pr-reviews/<int:pr_number>/analyze
```

- Calls `analyze_pending_prs` on the specific PR (by setting its status to `pending` first if it's `reviewed`, or processing it directly if already `pending`/`in_progress`)
- Returns `{success, summary}` or `{error}`
- `@admin_required`

---

## F.O.R.G.E. Prompt

```
You are F.O.R.G.E., A.R.C.H.I.E.'s Full-cycle Optimization & Regenerative GitHub Engine.
Review this pull request diff and provide a structured code review.

PR #{pr_number} — {title}
Author: {author} | Repo: {repo}
Changes: +{additions} -{deletions} across {changed_files} files

--- DIFF ---
{diff_content}
--- END DIFF ---

[Note: diff truncated to first 6000 chars.]  ← only if truncated

Provide your review in this format:

SUMMARY
One paragraph describing what this PR does and its overall quality.

ISSUES
- [CRITICAL] <issue> — <why it matters>
- [WARNING] <issue> — <why it matters>
- [INFO] <issue> — <why it matters>
(List only real issues. If none, write "No issues found.")

VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW
```

---

## Stored Output

`ai_summary` field stores the raw F.O.R.G.E. response text (SUMMARY + ISSUES + VERDICT).
`ai_review_at` is set to `NOW()` by `mark_review_done`.

---

## Bridge Dispatch

```python
from tools.department_hq.services.department_dispatcher import dispatch

result = dispatch(
    capability="code_review",
    prompt=prompt,
    module_id="repair_bay",
    source_agent="F.O.R.G.E.",
)
summary = result.response if result.success else None
```

Capability `code_review` maps to Engineering & Technology department (F.O.R.G.E.). No model override needed — dispatcher selects the best available agent.

---

## Environment

- `GITHUB_TOKEN` — already in platform_v2 `.env` (used by Phase 1 polling)
- No new secrets needed

---

## Testing

| Scenario | Expected |
|----------|---------|
| Pending PR with small diff | Processed, `ai_summary` populated, `review_status='reviewed'` |
| Pending PR with large diff (>6000 chars) | Truncated with note, still processed |
| GitHub fetch fails (bad token, rate limit) | Status reverts to `pending`, logged, next PR continues |
| F.O.R.G.E. dispatch fails | Status reverts to `pending`, logged |
| On-demand route for a specific PR | Triggers immediate analysis, returns summary |
| No pending PRs | Returns `{processed: 0, failed: 0, skipped: 0}` |
