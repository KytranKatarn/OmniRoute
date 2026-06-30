---
allowed-tools: Bash(docker exec:*), Bash(gh pr merge:*), Bash(gh pr view:*), Bash(git fetch:*), Bash(git reset:*)
description: Check F.O.R.G.E. review via Repair Bay then merge a PR. Always run this instead of gh pr merge directly.
---

## Your task

Merge PR #$ARGUMENTS safely through the Repair Bay pipeline.
All operations route through `docker exec archie_platform python3` — Claude's admin identity is implicit inside the container.

**BASE = docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); ...**

---

### Step 1: Resolve PR number

If $ARGUMENTS is set, use it as PR_NUMBER. Otherwise:
```bash
gh pr view --json number,title,state
```

---

### Step 2: Check Repair Bay review status

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review, poll_open_prs
r = get_review(PR_NUMBER)
if not r:
    print('NOT_TRACKED — polling now...')
    result = poll_open_prs()
    print('Poll:', result)
    r = get_review(PR_NUMBER)
if r:
    print('STATUS:', r.get('review_status'))
    print('SUMMARY:', (r.get('ai_summary') or 'none')[:400])
else:
    print('STILL_NOT_FOUND')
"
```

---

### Step 3: Trigger analysis if pending OR stuck

If status is `pending`, `not_tracked`, **or a stale `in_progress` with no summary**
(a review orphaned when a one-shot process was killed mid-dispatch — KB #270002),
trigger a **diff-grounded** F.O.R.G.E. review. `review_pr()` is idempotent — safe to
re-run on a stuck row; it re-drives the review to a terminal verdict instead of
polling a dead row for 90s.

**Always use `review_pr()`** — it fetches the REAL unified diff and puts it in the
prompt. Do NOT hand-roll a `dispatch(prompt=f'...Diff: {diff_url}...')` — the local
model can't fetch a URL, so a bare diff_url yields generic, ungrounded "reviews".

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr(PR_NUMBER)
print('OK:', r.get('ok'), '| VERDICT:', r.get('verdict'), '| ERR:', r.get('error'))
print('SUMMARY:', (r.get('summary') or 'none')[:300])
"
```
If it returns `ok=False` with `empty/queued review`, the model was cold — wait ~60s
and re-run (the diff is already cached on the row).

---

### Step 4: Poll until reviewed (max 90s)

```bash
docker exec archie_platform python3 -c "
import sys, time; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review
for i in range(18):
    r = get_review(PR_NUMBER)
    st = (r or {}).get('review_status', 'not_found')
    print(f'[{i*5}s] {st}')
    if st in ('reviewed', 'skipped'): break
    time.sleep(5)
if r:
    print('FINAL STATUS:', r.get('review_status'))
    print('SUMMARY:', (r.get('ai_summary') or 'none')[:400])
"
```

---

### Step 5: Show the review block

```
## F.O.R.G.E. Review — PR #<n>
Status: <review_status>
Summary: <ai_summary or "Not reviewed yet">
Verdict: <APPROVED / FLAGGED / PENDING>
```

**Do NOT proceed if** summary contains: "critical issue", "security vulnerability", "data loss", "breaking change" — ask user first.

---

### Step 6: Merge via Repair Bay service layer

Use `github_service.merge_pr` — do NOT put an inline `requests.put(...)` in the bash
command: the context-mode hook blocks inline HTTP literals and the call will be
cancelled. The service wraps the GitHub merge API inside the container.

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.github_service import merge_pr
res = merge_pr(PR_NUMBER, 'squash')
print('MERGE:', 'merged' if res.get('merged') else 'FAILED', '|', res.get('error',''))
"
```
If the service path is unavailable, fall back to the `gh` CLI:
`gh pr merge PR_NUMBER --squash --delete-branch`

---

### Step 7: Sync local main

```bash
git fetch origin && git reset --hard origin/main
```

---

### Step 8: Queue documentation (MANDATORY — never skip)

**Always queue documentation after every merge — even if there's no time to write it now.**
C.O.D.E.X. processes it async via the fleet. Nothing gets lost.

```python
mcp__archie__delegate_task(
    capability='documentation',
    reason=f'Document PR #{PR_NUMBER}: {title} — store user-doc + coder-doc vault_notes in Consciousness KB',
    delegation_source='claude',
    args={
        'pr_number': PR_NUMBER,
        'pr_title': title,
        'repo': repo,
        'auto_store': True,
    }
)
```

This routes through DHQ → C.O.D.E.X. (Documentation & Knowledge dept) → best available fleet node (outpost nodes handle text work). C.O.D.E.X. reads the PR description + changed files → stores TWO vault_notes (user-doc + coder-doc) → Consciousness Knowledge tab.

**Rule: NEVER skip this step. If no time to document now → queue it. The queue clears asynchronously via the fleet.**

---

### Notes

- **Claude (CLI)**: runs as implicit `claude` admin — tracked in Repair Bay by the `pr_review_service` layer
- **A.R.C.H.I.E. Chat**: when F.O.R.G.E. overlay calls analyze/merge, it authenticates as `archie` (admin) via session auth — same pipeline, different principal
- After merge, Repair Bay `sync_closed_prs()` will mark the PR closed on the next poll cycle (every 4h) or immediately via F.O.R.G.E. chat action
- **Documentation**: Step 8 queues C.O.D.E.X. to store vault_notes for the PR. Check Consciousness → Knowledge tab to verify after ~5 minutes.
