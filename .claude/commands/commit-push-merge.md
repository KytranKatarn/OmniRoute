## Your task

Commit staged changes, push, create a PR, register in Repair Bay, and **auto-merge** — all in one flow.

This combines `/commit-push-pr` + `/merge-pr` into a single command for routine changes that don't need manual review gate.

**Use for**: bug fixes, UI tweaks, config changes, minor features.
**Don't use for**: schema migrations, security changes, breaking changes — use `/commit-push-pr` then review before `/merge-pr`.

---

### Step 1: Commit

If there are staged changes:
```bash
git commit -m "<message>"
```
Follow project convention (`feat/fix/chore(scope): description`).

If nothing staged → check unstaged, ask what to include.

---

### Step 2: Push

```bash
git push -u origin <current-branch>
```

---

### Step 3: Create PR

```bash
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-3 bullets>

## Test Plan
- [ ] <steps>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Extract PR number from output URL.

---

### Step 4: Register in Repair Bay

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs, get_review
result = poll_open_prs()
print('Repair Bay poll:', result)
r = get_review(PR_NUMBER)
if r:
    print('Tracked — review_status:', r.get('review_status'))
else:
    print('WARNING: not tracked')
"
```

---

### Step 5: Auto-merge via Repair Bay

```bash
docker exec archie_platform python3 -c "
import sys, os; sys.path.insert(0, '/app')
import requests
from tools.repair_bay.services.pr_review_service import get_review, mark_review_skipped
mark_review_skipped(PR_NUMBER)
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

### Step 6: Sync local main

```bash
git fetch origin && git checkout main && git merge --ff-only origin/main
```

⚠️ **NEVER `git reset --hard` here.** `/mnt/archie_brain` is Kytran's working checkout and
routinely holds uncommitted work. `reset --hard` **destroys it unrecoverably** to achieve what a
fast-forward already does. `--ff-only` refuses loudly on divergence instead of discarding it —
if it refuses, stop and look rather than escalating to `--hard`.

---

### Step 7: Report

```
PR #<n> created and merged: <url>
Repair Bay: tracked ✓
Merged: squash commit to main ✓
```

---

### Notes

- Skips F.O.R.G.E. review (use `/commit-push-pr` + `/merge-pr` if you want AI review first)
- Always squash-merges to keep main history clean
- For risky changes (schema, security): use `/commit-push-pr` instead and review the F.O.R.G.E. summary before merging
