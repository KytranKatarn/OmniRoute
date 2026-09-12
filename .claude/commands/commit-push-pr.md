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

### Step 3.5: Declare merge order (when it matters)

If this PR must land AFTER another open PR — it calls something the other adds, or
its migration builds on the other's — write it in the PR body, on its own line:

```
Depends on #<N>
```
(`Blocked by #N`, `Merge after #N` and `Requires #N` are equivalent.) Repair Bay's
PR Review tab ranks open PRs from these markers plus shared-file overlap, and
`merge_pr` REFUSES a PR whose declared dependency is still open — for every actor,
including the human click. A bare `#N` ("fixes #N", "see #N") is deliberately NOT
a dependency, so cite freely.

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

### Step 5: Trigger F.O.R.G.E. analysis

Kick off a **diff-grounded** F.O.R.G.E. review. **Run this bash step with `run_in_background: true`** — `review_pr()` blocks until F.O.R.G.E. returns (can be minutes on a cold model load), and backgrounding lets it finish out-of-band without stalling the rest of the flow. You'll be notified when it completes; read the verdict then (or when you next `/merge-pr`).

**Use `review_pr()`** — it fetches the REAL unified diff and grounds the review (same path `/merge-pr` uses). Do NOT hand-roll a `dispatch(prompt=f'Review PR #...')` with a bare prompt — the local model can't fetch a URL, so a bare prompt/diff_url yields a generic, ungrounded "review".

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr(PR_NUMBER)
print('OK:', r.get('ok'), '| VERDICT:', r.get('verdict'), '| ERR:', r.get('error'))
print('SUMMARY:', (r.get('summary') or 'none')[:300])
"
```

> ⚠️ **Do NOT** wrap the review in a `threading.Thread(target=_bg, daemon=True)` inside `python3 -c`. The one-shot process exits the instant it returns, killing the daemon thread mid-dispatch — `mark_review_started()` runs (status → `in_progress`) but `mark_review_done()` never does, so the review is **stuck `in_progress` forever** (the "status ≠ artifact" trap, KB #270002). `review_pr()` run synchronously in a backgrounded step is the fix: the process stays alive until the review reaches a terminal verdict.

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
