---
name: archie-repair-bay
description: Operate A.R.C.H.I.E.'s Repair Bay and F.O.R.G.E. PR-review pipeline from the opencode lane — inspect review status, read verdicts, drive stuck reviews, and understand the merge gate. Use when a PR needs a F.O.R.G.E. review, a review is stuck pending/in_progress, a verdict looks wrong or stale, someone asks "what did F.O.R.G.E. say", or before any merge. Verified 2026-09-27 against archie-platform @ main.
---

# archie-repair-bay — F.O.R.G.E. review + Repair Bay, from the lane

Verified 2026-09-27 by reading the source and calling the functions. Every symbol
below was confirmed to exist; do not trust a path you have not grepped.

> Detail moved to `reference/mcp-and-gotchas.md` — read it when the short version is not enough.

## 0. READ THIS BEFORE YOU GUESS A ROUTE

On 2026-09-27 I guessed `/api/internal/forge/review`, got a 404, and reported
"the lane cannot trigger F.O.R.G.E." **Wrong on both counts** — the route is
`/api/forge/pr-reviews/<pr>/analyze`, and the review had *already* started on
its own. Everything you need is a plain function call inside the container; there
is no HTTP hop and no route to guess. Start here, not at a URL.

The `/api/forge/*` routes are `@login_required @admin_required` Flask views.
Calling them over HTTP from the lane fails on auth. **Call the service functions
in-process instead** — same database, same process, no auth layer:

```bash
docker exec -i -w /app archie_platform python3 - <<'PY'
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import get_review, verdict_is_approved
r = get_review(3503)
print(r['review_status'], '| approved:', verdict_is_approved(r.get('ai_summary')))
PY
```

`sys.path.insert(0, '/app')` is required — the package is not importable bare.

## 1. Reviews start themselves — do not "trigger" one by default

`pr_reviews` rows are created and driven by the GitHub webhook
(`/api/forge/webhook`) plus a periodic poll. **A freshly opened PR is normally
already `in_progress` within a minute.** Verified: PR #3503 was `in_progress`
with nobody having touched it.

So the first move is ALWAYS to read the status, never to assume a review is
missing:

```python
from tools.repair_bay.services.pr_review_service import get_review
r = get_review(<pr>)          # -> review_status, ai_summary, repo, title, updated_at
```

`review_status` values seen in the wild: `in_progress`, `pending`, `reviewed`,
`skipped`.

Only escalate to forcing when the status is genuinely stuck (below).

## 2. Reading a verdict — use the helper, not a substring match

```python
from tools.repair_bay.services.pr_review_service import (
    verdict_is_approved,      # strict: True ONLY on a real APPROVE
    parse_verdict,            # -> the raw verdict token
    coverage_only_demotion,   # True when the ONLY complaint is unread files
    coverage_dropped_paths,   # which files the reviewer never saw
    coverage_partial_paths,
)
```

`verdict_is_approved` is deliberately strict: `REQUEST CHANGES`, `NEEDS REVIEW`
and a coverage-only demotion all return **False**. Do not hand-roll
`"APPROVE" in summary` — a summary can *discuss* an approval it did not give.

A **coverage-only demotion** is not a code defect: the reviewer says the diff
was fine but it never read every file. It stays unmergeable until a human
acknowledges coverage in the Repair Bay UI. Do not "fix" it by re-reviewing
forever, and do not treat it as a rejection.

## 3. Driving a genuinely stuck review

| Symptom | Action |
|---|---|
| `pending` for a long time, no summary | `poll_open_prs()` — the periodic sweep, forced |
| `in_progress` >5 min, no summary | thread likely died silently; re-drive it |
| diff-grounded re-review needed | `review_pr(pr_number, repo=None)` |

```python
from tools.repair_bay.services.pr_review_service import poll_open_prs
from tools.repair_bay.services.pr_diff_analyzer import review_pr, analyze_pending_prs
```

- `review_pr(n)` is **idempotent** and diff-grounded. Use it.
- **NEVER hand-roll a dispatch with a diff URL.** The review model cannot fetch
  a URL; it must receive the diff text. A hand-built dispatch produces a
  confidently wrong review of nothing.
- `analyze_pending_prs(max_prs=3)` sweeps a batch.

Then poll `get_review` for up to ~90s.

## 4. A PR number is not an identity (#6776)

`archie-code` and `archie-platform` both have a `#71`. A bare lookup can resolve
the wrong repo and store a verdict against a PR nobody is looking at — measured
in production on 2026-07-16.

`repos_for_pr_number(pr_number)` returns the candidates:

- `None`  → the lookup itself failed. **Not** "no collision". Fail closed.
- `>1`    → ambiguous; name the repo explicitly.
- exactly 1 → safe.

Always pass `repo=` once you know it. `get_review(n)` / `review_pr(n)` /
`verdict_is_approved` all accept it.

## 5. GitHub writes go through the platform's token, never the lane's

The lane holds **no git credential**. Every GitHub read/write happens inside the
container, via the shared service:

```python
from tools.repair_bay.services.github_service import _api_get, _api_patch, _api_post
ok, pr   = _api_get('/repos/KytranKatarn/archie-platform/pulls/3503')
ok, data = _api_get('/repos/KytranKatarn/archie-platform/pulls/3503/files?per_page=100')
```

Both helpers return a **`(ok, data)` tuple** — unpacking a single value raises
`TypeError: tuple indices must be integers`. `_api_get` has a 15s default
timeout; pass `timeout=` for slow reads. Never echo, print or copy the token.

## 6. The merge gate — what I must not do

- **Never approve our own PRs.** No self-approval, ever, at any tier.
- **Never raw `gh pr merge` / `gh pr approve`.** Merge only via Repair Bay's
  `merge_pr` with the owner's in-session authorization **and** a stored
  `verdict_is_approved` review covering the current **head SHA**.
- Fail closed on a stale or unknown head. A verdict for an older commit does not
  cover a re-pushed one.
- Tier ceilings escalate to the human; they are never overridden.
- A `human_override` waives **authority** only. Safety gates and the
  stale-verdict check still bind.
- Closing a superseded **draft** PR is not a merge and is within lane rights.
  (Used legitimately on 2026-09-27 to retire a PR that wrongly carried a
  `config/agents/*` change.)

## Related

- `archie-lane-ship` — the ship path (branch, commit, ship primitive, PR
  hygiene) and the Dev HQ/KB task tools. **Load BOTH**: this skill covers
  review/verdict/merge, that one covers getting the PR there.
- Dev HQ task `#6973` — the Ollama Cloud tier that F.O.R.G.E. reviews against.
