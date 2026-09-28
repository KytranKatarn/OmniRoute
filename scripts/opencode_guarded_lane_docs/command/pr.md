---
description: PR operations through Repair Bay — list open PRs with F.O.R.G.E. verdicts, fix titles/bodies, re-trigger stuck reviews, or merge an owner-authorized approved PR. Use when the user says "pr list", "fix the PR titles", "check reviews", "merge 3450", "merge the approved PRs".
---

Route ALL GitHub operations through `docker exec -i archie_platform python3 -`
(stdin; token stays inside; rootfs is read-only — no docker cp). Repo:
`KytranKatarn/archie-platform`. Subcommand = first word of `$ARGUMENTS`.
Details and the full merge port: load skill `archie-lane-ship`.

## `/pr list`
Open PRs + stored verdicts:
```python
import os, urllib.request, sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import get_review, verdict_is_approved
req=urllib.request.Request("https://api.github.com/repos/KytranKatarn/archie-platform/pulls?state=open",
  headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"],"User-Agent":"archie-repair-bay"})
for p in json.load(urllib.request.urlopen(req)):
    r=get_review(p["number"]) or {}
    s=r.get("ai_summary") or ""
    print(p["number"], r.get("review_status","untracked"),
          "APPROVED" if s and verdict_is_approved(s) else "-", "|", p["title"][:60])
```

## `/pr fix <n>...`
Titles use `type(scope): description`; bodies use `## Summary` / `## Verification`
/ `## Merge notes` (+ honest `Depends on #N` only for hard deps). PATCH each PR
`{"title":…,"body":…}` the same way; report number/status/body_len. For bulk work
reuse `/mnt/archie_brain/platform_v2/_lane_ship/fill_pr_bodies.py` as the template.

## `/pr reviews <n>` (or all open)
`get_review(n)` → print `review_status` + `ai_summary`. If `pending`/`in_progress`
with NO summary (orphaned): `from tools.repair_bay.services.pr_diff_analyzer import
review_pr; review_pr(n)` then poll `get_review` up to 90s. Show the review block;
stop and ask if the summary contains critical/security/data-loss/breaking-change.

## `/pr merge <n>` — OWNER-AUTHORIZED ONLY
The owner typing this command IS the authorization for PR `n`. Still enforce in
code, never prose:
1. `row=get_review(n)`; refuse if no summary or `not verdict_is_approved(summary)`.
2. `res=merge_pr(n,'squash')` — if `merged`, done.
3. `governance_blocked` ⇒ inspect `error.lower()`:
   - `allowlist` / `a human must merge` ⇒ `merge_pr(n,'squash',human_override=True)` (verdict already pre-verified).
   - `stale verdict` / `head is now` ⇒ STOP: `review_pr(n)`, then re-run merge.
   - `max_tier` / `ceiling` / `next level up` ⇒ STOP: escalate (COO tier), report.
   - anything else ⇒ STOP: fail closed, print the gate text.
   Non-governance failure (conflict/CI/draft) ⇒ do NOT override; resolve cause
   (conflicts: merge main INTO branch, never force-push, then RE-REVIEW).
4. NEVER raw `gh pr merge`; NEVER merge without the stored approval; NEVER approve.
5. After success: report `MERGE: #n merged`, then `git -C /mnt/archie_brain fetch
   origin && git merge --ff-only origin/main` (refuse → stop, never `--hard`),
   queue docs: `delegate_task_to_fleet(capability='documentation', reason=...)`,
   and note the merge in the handover file.

Batch form: `/pr merge 3450 3451 3452` — run step 1-2 per PR, one at a time
(merge lock is DB-backed; a held lock means someone else is merging — wait).
