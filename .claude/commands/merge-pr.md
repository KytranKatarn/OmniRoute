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

**Two-stage, and the order matters (#5381).** Try the GATED merge first; only if the
governance gate refuses on an AUTHORITY ground do you re-attempt as the interactive
human. `human_override=True` is sanctioned for exactly this (decision #953: "reserved
for interactive, authenticated callers") — a sensitive-path PR *can only* be merged
that way, because the allowlist exists precisely to require a human.

⚠️ **But `human_override=True` skips the WHOLE gate, including the approved-verdict
check.** That is how PR #2458 reached main on a `needs_changes` verdict. So the script
below re-checks the verdict **in code** and refuses before it ever overrides — never
rely on Step 5's prose to catch it, because prose is advice and this is a merge.

⚠️ **`governance_blocked` does NOT mean "authority limit".** The same flag is raised for a
**STALE VERDICT** — an approval that covers an older commit than the head. The in-code
pre-check cannot catch that, because it verifies the verdict TEXT, not that the verdict
covers the head SHA. Overriding there merges code **no approval covers**.
Measured 2026-08-16 on PR #2614: a conflict resolution moved the head, the gate said
*"STALE VERDICT … re-run review_pr()"*, and a `governance_blocked`-only branch overrode it
anyway. Stage 2 below therefore **allowlists** the refusal reasons that may be overridden
and **fails closed** on everything else. If you see a stale verdict: **re-review, then merge.**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.github_service import merge_pr
from tools.repair_bay.services.pr_review_service import get_review, verdict_is_approved

PR = PR_NUMBER

# ---- HARD GATE, enforced here and not left to the operator ----
row = get_review(PR) or {}
summary = row.get('ai_summary') or ''
if not summary:
    print('REFUSED: no stored F.O.R.G.E. review — a dead review is not an approval'); sys.exit(1)
if not verdict_is_approved(summary):
    print('REFUSED: stored verdict is NOT an approval — fix and re-review, never override'); sys.exit(1)

# ---- stage 1: normal gated merge (verdict + allowlist + tier ceiling) ----
res = merge_pr(PR, 'squash')
if res.get('merged'):
    print('MERGE: merged (gated, no override needed)'); sys.exit(0)

# ---- stage 2: the gate refused. `governance_blocked` is NOT automatically an authority
#      limit. The SAME flag covers a STALE VERDICT, and human_override skips that check
#      too — so overriding it merges code that NO approval covers. The pre-check above
#      cannot catch this: it verifies the verdict TEXT, not that the verdict covers the
#      head SHA being merged.
#
#      Measured 2026-08-16 on PR #2614: resolving a merge conflict moved the head, the
#      gate correctly said "STALE VERDICT ... the review covers 1010d1be but the head is
#      now 0b5cd103 — re-run review_pr()", and a governance_blocked-ONLY branch overrode
#      it regardless. That is #2458 with extra steps.
#
#      So: override ONLY on a RECOGNISED authority refusal. Anything else fails CLOSED. ----
err = (res.get('error') or '')
low = err.lower()
stale = ('stale verdict' in low) or ('head is now' in low)
authority = ('allowlist' in low) or ('a human must merge' in low) or ('max_auto' in low) or ('ceiling' in low)

if res.get('governance_blocked') and stale:
    print('REFUSED (stale verdict): the approval covers an OLDER commit than the head.')
    print('  Re-run review_pr(PR) so the verdict covers what is actually being merged,')
    print('  then re-run this step. Never override a stale verdict.')
    print('  gate said:', err[:220]); sys.exit(1)
elif res.get('governance_blocked') and authority:
    print('gate refused (authority/allowlist):', err[:200])
    res2 = merge_pr(PR, 'squash', human_override=True)
    print('MERGE:', 'merged (human_override; verdict pre-verified AND covers head)'
          if res2.get('merged') else 'FAILED', '|', (res2.get('error') or '')[:160])
elif res.get('governance_blocked'):
    # Unrecognised governance reason -> we do not know it is safe to override. Fail closed.
    print('REFUSED: governance refusal is not a recognised AUTHORITY limit — NOT overriding.')
    print('  gate said:', err[:220]); sys.exit(1)
else:
    # NOT a governance refusal (conflict, 5xx, draft, CI) -> do NOT override; fix the cause.
    # A merge CONFLICT lands here: resolve it by merging main INTO the branch (never a
    # force-push), then RE-REVIEW, because the resolution is code nobody has reviewed.
    print('MERGE: FAILED (non-governance):', err[:200])
"
```

**Do NOT fall back to `gh pr merge`.** That bypasses the gate entirely and leaves no
record — it is how #2547/#2549/#2550 reached main with no tier state recorded. If the
service path is genuinely unavailable, say so and stop; a merge that cannot be recorded
should not happen silently.

---

### Step 7: Sync local main

```bash
git fetch origin && git merge --ff-only origin/main
```

⚠️ **NEVER `git reset --hard` here.** `/mnt/archie_brain` is Kytran's working checkout and
routinely holds uncommitted work (8 modified/untracked files on 2026-07-27 — website data,
portraits, rules). `reset --hard` **destroys all of it, unrecoverably**, to achieve something a
fast-forward already does.

`--ff-only` is also the safer failure mode: if the local branch has diverged it **refuses and
tells you**, instead of silently discarding the divergence. If it refuses, stop and look — do
NOT escalate to `--hard`.

---

### Step 7.5: Redeploy the affected product FROM main + verify integrated (anti-drift — never skip for image-baked products)

**Why:** an image-baked product (`COPY .` Dockerfile — every standalone: media_hub,
the watch products, KBS, KSO) only ever runs whatever branch it was last built from.
If you (or a parallel session) deployed feature branches during the work, the live
container reflects only the LAST branch — the others were silently reverted. "Verified
live" on a feature branch goes stale the moment another branch is built. See KB mistake
**#279350** (deploy-from-feature-branch drift) + `.claude/rules/deploy-provenance.md`.

After the merges land on main:

```bash
# Rebuild the affected product FROM the integrated main, stamping its commit:
scripts/deploy_with_sha.sh <compose-dir> <service>     # e.g. standalone/media_hub mediahub_app

# Confirm the running image now reports main's HEAD (no drift):
scripts/deploy_drift_check.py
```

Then re-verify the merged features **together** in the freshly-built container (not the
per-branch checks from earlier — those are stale). If the product is on a VPS, deploy per
`.claude/rules/outpost-vps.md` and hit its `/version` to confirm the commit.

Skip only if nothing image-baked changed (e.g. a docs-only or platform-volume-mounted change).

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
