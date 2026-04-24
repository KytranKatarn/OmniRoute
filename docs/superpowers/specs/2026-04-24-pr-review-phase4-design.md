# PR Review Pipeline — Phase 4: Telegram Alerts

**Date**: 2026-04-24
**Project**: #247 | **Task**: #1802
**Status**: Approved by user 2026-04-24

## Goal

Send a Telegram notification when F.O.R.G.E. completes a PR review — verdict badge, summary snippet, and two URL buttons (Repair Bay + GitHub).

## Flow

```
pr_diff_analyzer.analyze_pending_prs()
    → mark_review_done(pr_number, summary, repo)
    → _notify_pr_reviewed(pr_number, repo, title, summary)   ← NEW
        → submit_via_inbox(category="pr_reviewed", ...)
            → director_reports (pending)
                → triage policy: category_prefix="pr_reviewed" → escalate
                    → archie_comms escalation handler
                        → detects category="pr_reviewed"
                        → adds URL keyboard buttons
                        → Telegram API
```

## Changes

### 1. `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`

Add `_notify_pr_reviewed(pr_number, repo, title, ai_summary)` called after `mark_review_done()` inside `analyze_pending_prs()`:

```python
def _notify_pr_reviewed(pr_number: int, repo: str, title: str, ai_summary: str) -> None:
    """Submit a PR review completion notification to the director_reports inbox."""
    from services.director_report_service import submit_via_inbox

    # Extract verdict line
    verdict = "REVIEWED"
    if ai_summary:
        u = ai_summary.upper()
        if "VERDICT: APPROVE" in u:
            verdict = "APPROVE"
        elif "VERDICT: REQUEST CHANGES" in u:
            verdict = "REQUEST CHANGES"
        elif "VERDICT: NEEDS REVIEW" in u:
            verdict = "NEEDS REVIEW"

    # Extract summary snippet (first 200 chars after SUMMARY marker)
    snippet = ""
    if ai_summary:
        m = re.search(r"SUMMARY\s*([\s\S]{1,200})", ai_summary, re.IGNORECASE)
        if m:
            snippet = m.group(1).strip()

    _repo = repo or _DEFAULT_REPO
    github_url = f"https://github.com/{_repo}/pull/{pr_number}/files"
    platform_url = "http://192.168.1.200:3000/tools/repair-bay#pr-review"

    message = (
        f"VERDICT: {verdict}\n\n"
        f"{snippet}\n\n"
        f"View in Repair Bay: {platform_url}\n"
        f"GitHub PR: {github_url}"
    )

    try:
        submit_via_inbox(
            category="pr_reviewed",
            title=f"F.O.R.G.E. Review: {verdict} — {_repo}#{pr_number}: {title[:60]}",
            message=message,
            source_agent="F.O.R.G.E.",
            severity="info",
            department="Engineering & Technology",
        )
    except Exception as exc:
        logger.warning("[PR Review] Failed to submit Telegram notification for PR #%s: %s", pr_number, exc)
```

`import re` must be at the top of the file (add if not present).

### 2. `archie-comms/services/telegram_service.py`

In the escalation handler (the block that detects `category` and adds `reply_markup`), add a new branch for `pr_reviewed`:

```python
elif report.get("category") == "pr_reviewed":
    # Extract GitHub PR URL from message body
    _gh_m = _re.search(r"GitHub PR: (https://github\.com/\S+)", report.get("summary", ""))
    if _gh_m:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "🔧 View in Repair Bay", "url": "http://192.168.1.200:3000/tools/repair-bay#pr-review"},
                {"text": "View on GitHub ↗", "url": _gh_m.group(1)},
            ]]
        }
```

### 3. DB migration — triage policy for pr_reviewed

Insert a triage policy so `pr_reviewed` reports are escalated automatically:

```sql
INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
VALUES ('info', 'pr_reviewed', 'escalate', 'F.O.R.G.E. PR review completed — notify Kytran', 10, TRUE)
ON CONFLICT DO NOTHING;
```

Run on archie_comms Postgres DB.

## Testing

| Scenario | Expected |
|----------|---------|
| PR review completes | `director_reports` row with `category='pr_reviewed'` inserted |
| Triage consumer runs | Row escalated, Telegram message sent |
| Telegram message | Shows verdict + snippet + two URL buttons |
| `_notify_pr_reviewed` fails | Warning logged, PR marked reviewed normally (no crash) |
