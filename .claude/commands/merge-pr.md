---
allowed-tools: Bash(gh pr merge:*), Bash(gh pr view:*)
description: Check F.O.R.G.E. review then merge a PR. Always run this instead of gh pr merge directly.
---

## Your task

Merge PR #$ARGUMENTS safely by checking F.O.R.G.E. review first.

**Step 1: Get the PR number**
- If $ARGUMENTS is set, use it as the PR number.
- If not set, run `gh pr view --json number,title,state` to get the current branch's PR.

**Step 2: Check F.O.R.G.E. review status**
Call `mcp__archie__forge_list_prs` to get all tracked PRs. Find the entry matching the PR number. Look at:
- `review_status`: pending / in_progress / reviewed / skipped
- `ai_summary`: F.O.R.G.E.'s review text
- `review_flags`: any blocking issues flagged

**Step 3: Evaluate and decide**

| review_status | Action |
|--------------|--------|
| `reviewed` | Show summary, proceed to merge if no critical flags |
| `pending` or `in_progress` | Report "F.O.R.G.E. review not yet complete (~60s). Trigger with Repair Bay → PR Review → Analyze." Ask user if they want to wait or merge anyway. |
| `skipped` | Note it, proceed to merge |
| Not found in list | Note "PR not yet tracked by F.O.R.G.E. poller." Proceed with merge but note it. |

**Step 4: Show the summary**
Output this block before merging:
```
## F.O.R.G.E. Review — PR #<n>
Status: <review_status>
Summary: <ai_summary or "Not reviewed yet">
Verdict: <APPROVED / FLAGGED / PENDING>
```

**Step 5: Merge (if proceeding)**
```
gh pr merge <pr_number> --squash --delete-branch
```

**Step 6: Sync local main**
```
git fetch origin && git reset --hard origin/main
```

Do NOT merge if review_status is `reviewed` AND ai_summary contains phrases like "critical issue", "security vulnerability", "data loss", "breaking change" without explicit user confirmation first.
