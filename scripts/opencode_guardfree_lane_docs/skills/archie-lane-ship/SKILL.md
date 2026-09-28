---
name: archie-lane-ship
description: opencode lane shipping, PR hygiene, owner-authorized merge, and Dev HQ/KB task coordination. Use when shipping changes (website or platform), creating or fixing PR titles/bodies, shipping from the lane clone, or updating tasks/knowledge "like Claude-CLI does". READ THE BANNER BEFORE THE RECIPES: the ship path differs per instance - in the guard-free instance (port 17687) it is opencode-pr from /work/archie-platform, NOT ship-branch.sh and NOT the live tree; in the guarded lane (17685) it is Path A/B as written below.
---

# archie-lane-ship — opencode ship + Repair Bay + Dev HQ coordination

Verified 2026-09-23. Where this conflicts with `AGENTS.md` on disk, THIS is current
(option-B, 2026-09-13: lanes are host-direct, `contained=False`; AGENTS.md's
"opencode does not ship" is stale).

> ⚠️ **IF YOU ARE IN THE GUARD-FREE INSTANCE** (`archie_opencode_terminal_gf`,
> port 17687) — this skill is the guarded lane's, copied wholesale, and its ship
> paths do not apply to you. Measured 2026-09-28:
> - **Ship with `opencode-pr "<title>"` from `/work/archie-platform`.** The Path A
>   `ship-branch.sh` below lives in `/opencode-home/bin/`, which does NOT exist in
>   this image. The Path B runner is the scope gate this instance was built without.
> - **Never ship from `/mnt/archie_brain`** — `opencode-pr` refuses the live tree
>   by design (it runs `git add -A`; an untracked copy of platform_v2 was once
>   swept into a lane commit that way).
> - `/opencode-home/bin/gh-read.sh` does not exist here either, and `gh` is
>   unauthenticated; read GitHub through `docker exec -i archie_platform python3 -`.
> - Read `/ship` first — it was rewritten for this instance on 2026-09-28.

> Detail moved to `reference/devhq-contract-and-traps.md` — read it when the short version is not enough.

## 1. Trees & identities
- **Live tree `/mnt/archie_brain`** — the served platform; owner/Claude also work
  here (ONE live tree: check who's mid-task before any git op; never `git add -A`;
  stage only this session's files; never commit to `main`).
- **Lane clone `/work/archie-platform`** — in the GUARDED lane this is the
  scope-gated runner's base (Path B) and never ships. **In the guard-free instance
  it is the opposite: a full clone with `origin` = GitHub, and the only tree you
  ship from**, via `opencode-pr` (see the banner above).
- **Credential:** the guarded lane has none and hands branches to the platform
  container's token. **The guard-free instance mounts a working fine-grained PAT**
  (`/run/secrets/opencode_github_token`) and `opencode-pr` uses it. Measured
  2026-09-28. Its presence is unconfirmed owner intent — see Dev HQ #7026.

## 2. Ship paths
**Path A — live-tree (default for direct platform edits):**
1. `git -C /mnt/archie_brain switch -c <type>/<short>` (if on main), `add <explicit files>`, commit `--no-verify` (lane lacks pre-commit; run `git diff --cached --check`).
2. `bash /opencode-home/bin/ship-branch.sh <branch> ['<TITLE>' ['<BODY>']]`
   → `push_pending_branch` + `create_pr` inside `archie_platform`; 422 ⇒ repoints
   existing PR title/body (no dup). Exit 0/1/2. Prints `SHIP: PR #N <url>`.

**Path B — scope-gated runner (batch/template/site work; prechecks + real tests):**
1. Put the patch in `platform_v2/_lane_ship/<name>.patch` (gitignored BOTH trees).
   Generate it deterministically (python edit → `git diff` → restore), then
   `docker cp` it INTO the lane — `_lane_ship` is NOT shared between trees.
2. Precheck: `docker exec -u <lane-uid> archie_opencode_terminal sh -c
   'cd /work/archie-platform && git apply --check <patch>'`.
3. Write `_lane_ship/ship-<name>.sh`: precheck → `bash
   /mnt/archie_brain/scripts/agents/run-opencode-task.sh "$TASK"` with a
   single-quote-safe TASK (first sentence = commit subject ≤64; enumerate exact
   paths + invariants + "no pytest in lane").
4. Runner pushes but its `gh pr create` NEVER fires (host gh unauthed, by design).
   Finish with **`bash platform_v2/_lane_ship/mk-pr.sh <branch> <body-file>
   ['<title>']`** — POSTs the PR via the platform token (422 ⇒ says exists).

## 3. PR hygiene (mandatory — Repair Bay reviews need context)
- Title: `type(scope): description` (repo convention), ≤70 chars, no timestamps.
- Body: `## Summary` (what+why) / `## Verification` (invariants actually run) /
  `## Merge notes` (file overlaps with other open PRs; say "disjoint hunks").
- Hard dependency only: own line `Depends on #N` (merge_pr REFUSES while #N open —
  binds every actor). Bare `#N` mentions are not dependencies; cite freely.
- Dup guard: re-running a ship script creates a 2nd branch ⇒ close the duplicate PR
  (done for #3454/#3453).
- Backfill pattern for existing thin PRs: python via
  `docker exec -i archie_platform python3 - <script.py` (stdin — the container
  rootfs is READ-ONLY, `docker cp` INTO it fails). PATCH `/pulls/<n>` with
  `Authorization: Bearer $GITHUB_TOKEN` read INSIDE the container. Never print/copy
  the token out. Template: `/mnt/archie_brain/platform_v2/_lane_ship/fill_pr_bodies.py`.

## 4. Repair Bay / F.O.R.G.E. review coordination
  **→ Load `archie-repair-bay` for this section.** It carries the verified
  in-process call surface (`get_review`, `review_pr`, `verdict_is_approved`),
  the auto-trigger behaviour, the `(ok, data)` tuple shape, and the lane's MCP
  `forge_*` 401/404 limits. Do NOT guess `/api/forge/*` routes from here — they
  are `@admin_required` and will 404/redirect from the lane.
  - Track/inspect: `from tools.repair_bay.services.pr_review_service import get_review,
    poll_open_prs` — `get_review(n)` → `review_status`, `ai_summary`, repo. New PRs are
    picked up by the webhook + periodic poll (so a fresh PR is usually ALREADY
    reviewing — read the status before assuming it needs a kick). To force: `poll_open_prs()`.
  - Stuck `pending`/`in_progress` with no summary ⇒ re-drive DIFF-GROUNDED review:
    `from tools.repair_bay.services.pr_diff_analyzer import review_pr; review_pr(n)`
    (idempotent; NEVER hand-roll a dispatch with a diff URL — the model can't fetch it).
    Then poll `get_review` up to ~90s.
  - Verdict truth: `verdict_is_approved(summary)` (strict `VERDICT: APPROVE`;
    REQUEST CHANGES / NEEDS REVIEW ⇒ False). Coverage-only demotions stay unmergeable
    until ack.
- Merge order badge on the PR Review tab mirrors `_dependency_refusal` — never a
  second gate; keep `Depends on` markers honest.

## 5. Merge — owner-authorized only (port of `.claude/commands/merge-pr.md`)
Preconditions (ALL): the owner explicitly authorized THIS PR in-session; stored
verdict exists and `verdict_is_approved`; no `Depends on #N` still open.
Two-stage, order matters (#5381/#5672/#2458):
1. `res = merge_pr(n, 'squash')` — gated path first.
2. If `governance_blocked`: override ONLY for recognised AUTHORITY refusals —
   `allowlist` / "a human must merge" ⇒ `merge_pr(n, 'squash', human_override=True)`.
   **FAIL CLOSED** on: `stale verdict`/`head is now` ⇒ re-run `review_pr(n)`, re-merge;
   `max_tier`/`ceiling`/`next level up` ⇒ ESCALATE (COO tier — not ours), stop;
   anything else ⇒ refuse, report the gate text.
3. NEVER raw `gh pr merge` (unrecorded; bypasses gates). NEVER approve our own PRs.
4. Post-merge: `git -C /mnt/archie_brain fetch origin && git merge --ff-only
   origin/main` (NEVER `reset --hard` — live tree holds owner work). Image-baked
   products need redeploy-from-main (see deploy-provenance rule) — website is
   publish-script (Phase 4, owner/Claude-Code side).
