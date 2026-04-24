# PR Review Pipeline — Phase 5: Multi-repo + GitHub Presence Audit

**Date**: 2026-04-24
**Project**: #247 | **Task**: #1803
**Status**: Approved by user 2026-04-24

## Goal

Three deliverables:
- **B**: Multi-repo polling — `GITHUB_REPOS` env var, poll all repos
- **A**: Per-repo health check — README/description/topics/license audit daily
- **C**: F.O.R.G.E. public profile report — weekly GitHub presence analysis

---

## B — Multi-repo polling

### Change
- `GITHUB_REPOS` env var: comma-separated list, e.g. `KytranKatarn/archie-platform,KytranKatarn/kytran-business-suite`
- Falls back to `GITHUB_REPO` if `GITHUB_REPOS` unset
- `_run_pr_review_poll` loops over all repos

### Files
- `platform_v2/tools/repair_bay/services/pr_review_service.py` — add `get_tracked_repos() -> list[str]` helper
- `ai_bridge/agent_loop.py` — update `_run_pr_review_poll` to call `get_tracked_repos()`

### Implementation

```python
# In pr_review_service.py
def get_tracked_repos() -> list:
    """Return list of repos to poll, from GITHUB_REPOS env var (comma-separated).
    Falls back to GITHUB_REPO for backward compatibility.
    """
    import os
    repos_env = os.getenv("GITHUB_REPOS", "").strip()
    if repos_env:
        return [r.strip() for r in repos_env.split(",") if r.strip()]
    fallback = os.getenv("GITHUB_REPO", "KytranKatarn/archie-platform").strip()
    return [fallback]
```

```python
# In agent_loop.py — _run_pr_review_poll update
def _run_pr_review_poll(self):
    try:
        from tools.repair_bay.services.pr_review_service import (
            poll_open_prs, sync_closed_prs, get_tracked_repos,
        )
        for repo in get_tracked_repos():
            result = poll_open_prs(repo=repo)
            closed = sync_closed_prs(repo=repo)
            logger.info(
                "pr_review_poll [%s]: polled=%d inserted=%d updated=%d closed_synced=%d",
                repo, result.get("polled"), result.get("inserted"),
                result.get("updated"), closed,
            )
    except Exception as e:
        logger.error("pr_review_poll failed: %s", e)
```

---

## A — Per-repo health check

### New job: `forge_repo_health_check` (daily 06:00 UTC)

For each repo in `get_tracked_repos()`:
1. Call GitHub API: `GET /repos/{owner}/{repo}` (description, topics, license, open_issues)
2. Call GitHub API: `GET /repos/{owner}/{repo}/readme` (check README exists)
3. Build issue list: missing description, missing topics, missing license, missing README
4. If any issues found: `submit_via_inbox(category="repo_health", severity="warning", ...)`
5. If all clear: log info, no inbox entry

### Files
- `platform_v2/tools/repair_bay/services/repo_health_service.py` (new)
- `ai_bridge/agent_loop.py` — add `_run_repo_health_check` job

### API calls
```python
# GET https://api.github.com/repos/{owner}/{repo}
# Response fields used: description, topics, license (obj), open_issues_count

# GET https://api.github.com/repos/{owner}/{repo}/readme
# 200 = README exists, 404 = missing
```

### Report format
```
Repo: KytranKatarn/archie-platform

Issues found:
- ❌ No description set
- ❌ No topics tagged
- ✅ README present
- ✅ License: MIT

View: https://github.com/KytranKatarn/archie-platform
```

### Triage policy
Add triage policy: `category_prefix="repo_health"`, `action="escalate"`, `priority=5`.
(Separate migration file.)

---

## C — F.O.R.G.E. GitHub presence audit

### New job: `forge_github_presence_audit` (weekly, Sunday 03:00 UTC)

1. Call GitHub API: `GET /users/KytranKatarn/repos?type=public&per_page=100`
2. Build repo summary (name, description, stars, updated_at, has_issues, topics)
3. Dispatch to F.O.R.G.E. via Bridge:

```python
prompt = f"""You are F.O.R.G.E., reviewing the public GitHub profile of KytranKatarn.

Public repos ({len(repos)} total):
{repo_summary}

Provide:
SUMMARY
Brief assessment of overall GitHub public presence quality.

ISSUES
- [HIGH/MEDIUM/LOW] <issue> — <recommendation>

VERDICT: PROFESSIONAL | NEEDS IMPROVEMENT | URGENT ACTION NEEDED"""
```

4. Store result in knowledge base: `store_memory(memory_type='vault_note', category='github_presence', title='GitHub Presence Audit YYYY-MM-DD', ...)`
5. Send via `submit_via_inbox(category="github_audit", severity="info", ...)`

### Files
- `platform_v2/tools/repair_bay/services/github_presence_service.py` (new)
- `ai_bridge/agent_loop.py` — add `_run_github_presence_audit` job

---

## Environment

- `GITHUB_REPOS` — new env var (comma-separated repos to poll and audit)
- `GITHUB_TOKEN` — already configured

---

## DB migrations needed

- `346_triage_policy_repo_health.sql` — `category_prefix="repo_health"` → escalate
- `347_triage_policy_github_audit.sql` — `category_prefix="github_audit"` → escalate (or suppress if weekly is too noisy)

---

## Testing

| Scenario | Expected |
|----------|---------|
| `GITHUB_REPOS` set to 2 repos | Poll job runs for both, separate pr_reviews rows |
| `GITHUB_REPOS` not set | Falls back to `GITHUB_REPO`, single repo (backward compat) |
| Repo missing description | `repo_health` director_report created with severity=warning |
| Repo fully configured | No inbox entry, info log only |
| Weekly audit runs | vault_note created in KB, github_audit director_report sent |
