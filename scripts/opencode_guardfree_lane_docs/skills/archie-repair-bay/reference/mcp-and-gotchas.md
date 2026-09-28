# MCP forge tools and review gotchas

**Reference for `archie-repair-bay`.** Split out so the skill file itself fits a review pass window. The SKILL.md carries the decision rules; this carries the detail.

---

## 7. The lane's MCP `forge_*` tools are NOT a source of truth

`forge_health` returns **401** and `forge_list_prs` returns **404** for this
lane's MCP identity. Treat those as *unavailable*, not as evidence that the
system is down.

**CORRECTED 2026-09-27 — the old text here was wrong in two ways. Do not repeat
its reasoning.**

1. It was **not** a "credential/scope problem." The 401 is a *wiring* bug:
   `FORGE_REVIEW_TOKEN` is valid, but the MCP forge path reads the **expired**
   `GITHUB_TOKEN` env var. Three call sites were affected (task #6974). So it
   *was* reportable as a platform fault — the old text said "do not report their
   failure to the owner as a platform fault," and following that instruction is
   what let a real bug sit unfiled. **Report it.** A tool returning 401 is a
   defect to report, not noise to swallow.
2. A 401/404 on the MCP tool does **not** mean you lack access. In-process
   access via `docker exec -i -w /app archie_platform python3 -` works fine and
   the app user can read the tables the MCP role cannot. Try that before
   concluding anything is inaccessible.

**The verdict is DB-side, not on GitHub.** F.O.R.G.E. verdicts are stored in
`pr_reviews` and parsed out of `ai_summary` by `verdict_is_approved()` — they
are *not* posted as GitHub PR reviews, so a PR routinely shows "no reviews" on
GitHub while holding a stored verdict. `review_status` only ever takes
`reviewed` / `skipped` / `REQUEST CHANGES`-style values; **never** infer
approval from a GitHub review list, and never infer it from `review_status`
either. The real gate, in order of authority:

- `verdict_is_approved(r['ai_summary'])` — the safety property, binds everyone
- `reviewed_head_sha == pr_head_sha(...)` — a verdict on stale code is not a verdict
- `machine_authored_reason(...)` — machine PRs are never auto-merged by any actor
- `classify_pr_tier(...)` + `FORGE_AUTO_MERGE_MAX_TIER` — the only per-actor limit

Correct import paths (note: `/app` *is* `platform_v2`, so there is no
`platform_v2.` prefix):

    import sys; sys.path.insert(0, "/app")
    from tools.repair_bay.services.pr_review_service import (
        get_review, verdict_is_approved, parse_verdict, pr_head_sha,
        classify_pr_tier, machine_authored_reason)

`get_db_cursor` defaults to **`RealDictCursor`** — rows are dicts. Unpacking a
row with `a, b = row` silently yields its *keys*, which looks like plausible
data rather than an error. Use `row['col']`.

For GitHub-side reads: **`gh` is unauthenticated in this image** (`gh api` returns
"please run gh auth login"), and `/opencode-home/bin/gh-read.sh` does not exist
here — both measured 2026-09-28 in the guard-free instance. Go through the platform
container, which holds a working credential that never leaves it:

```bash
docker exec -i archie_platform python3 -   # script on stdin
```

`gh pr merge` is REFUSED by the `/usr/local/bin/gh` guard whether or not `gh` is
authenticated — that refusal is real, and it is why this lane cannot merge its
own work.

## 8. Gotchas that cost real time

- **A review can be correct and still useless**: a large per-file pass on a
  slow model can blow the dispatch timeout and end `skipped`. That is a
  throughput problem, not a verdict. Check `review_status='skipped'` before
  concluding the reviewer had nothing to say.
- **A verdict is only valid for the head it reviewed.** After any re-push or
  amend, treat the previous verdict as stale.
- **`skipped` on a brand-new PR is normal** while the diff is still being sized.
- Coverage demotions and real findings look identical in the summary text. Use
  `coverage_only_demotion()` before treating it as a code problem.
