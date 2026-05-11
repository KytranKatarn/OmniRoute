---
allowed-tools: Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh pr create:*), Bash(gh pr view:*), Bash(docker exec:*)
description: Commit, push, and open a PR — then register with Repair Bay for F.O.R.G.E. tracking. Use instead of gh pr create directly.
---

## Your task

Commit staged changes, push, create a PR, and register it in Repair Bay under Claude's identity.

$ARGUMENTS may contain a commit message, PR title hint, or be empty.

---

### Step 1: Commit

If there are staged changes:
```bash
git commit -m "<message>"
```
Follow the project's commit message convention (`feat/fix/chore(scope): description`).

If nothing is staged, check for unstaged changes and ask user what to stage.

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
<2-3 bullets of what changed>

## Test Plan
- [ ] <verification steps>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Extract the PR number from the output (e.g. `https://github.com/.../pull/613` → 613).

---

### Step 4: Register in Repair Bay (Claude tracking)

After PR creation, immediately register it in the pipeline:

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
    print('WARNING: PR not yet in pr_reviews table')
"
```

---

### Step 5: Trigger F.O.R.G.E. analysis (background)

Queue the PR for F.O.R.G.E. review without blocking:

```bash
docker exec archie_platform python3 -c "
import sys, threading; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review, mark_review_started, mark_review_done, mark_review_skipped
from tools.department_hq.services.department_dispatcher import dispatch

r = get_review(PR_NUMBER)
if not r:
    print('PR not tracked — skipping analysis'); exit()

def _bg():
    mark_review_started(PR_NUMBER)
    res = dispatch(
        capability='code_review',
        prompt=f'Review PR #{r[\"pr_number\"]}: {r[\"title\"]}. VERDICT, SUMMARY, ISSUES.',
        context={'pr_number': r['pr_number'], 'repo': r['repo'], 'title': r['title']}
    )
    if res.success:
        mark_review_done(PR_NUMBER, res.response)
    else:
        mark_review_skipped(PR_NUMBER)

t = threading.Thread(target=_bg, daemon=True)
t.start()
print('F.O.R.G.E. analysis queued in background (PR #PR_NUMBER)')
"
```

---

### Step 6: Report

Output:
```
PR #<n> created: <url>
Repair Bay: tracked ✓
F.O.R.G.E.: analysis queued (check Repair Bay → PR Review)
```

---

### Notes

- **Claude (CLI)**: this command runs as `claude` admin — PRs are tracked in `pr_reviews` table as Claude-created
- **A.R.C.H.I.E. Chat**: when Archie creates PRs via her skills, she authenticates as `archie` admin — same table, different `author` context
- Use `/merge-pr <n>` to merge — never `gh pr merge` directly
