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

### Step 3: Trigger analysis if pending

If status is `pending` or `not_tracked`, trigger F.O.R.G.E. analysis:
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review, mark_review_started, mark_review_done, mark_review_skipped
from tools.department_hq.services.department_dispatcher import dispatch
r = get_review(PR_NUMBER)
if not r:
    print('PR not found'); exit(1)
mark_review_started(PR_NUMBER)
result = dispatch(
    capability='code_review',
    prompt=f'Review PR #{r[\"pr_number\"]}: {r[\"title\"]}. Diff: {r.get(\"diff_url\",\"\")}. VERDICT (APPROVED/NEEDS REVIEW/REJECT), SUMMARY, ISSUES.',
    context={'pr_number': r['pr_number'], 'repo': r['repo'], 'title': r['title']}
)
if result.success:
    mark_review_done(PR_NUMBER, result.response)
    print('REVIEWED:', result.response[:300])
else:
    mark_review_skipped(PR_NUMBER)
    print('DISPATCH_FAILED — skipped:', result.error)
"
```

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

```bash
docker exec archie_platform python3 -c "
import sys, os, requests; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review
r = get_review(PR_NUMBER)
repo = (r or {}).get('repo', 'KytranKatarn/archie-platform')
title = (r or {}).get('title', 'PR #PR_NUMBER')
token = os.getenv('GITHUB_TOKEN', '')
resp = requests.put(
    f'https://api.github.com/repos/{repo}/pulls/PR_NUMBER/merge',
    headers={'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'},
    json={'commit_title': f'Merge PR #PR_NUMBER: {title}', 'merge_method': 'squash'},
    timeout=15
)
print('MERGE:', resp.status_code, resp.json().get('message',''))
"
```

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
