---
name: archie-lane-ship
description: opencode lane shipping, PR hygiene, owner-authorized merge, and Dev HQ/KB task coordination. Use when shipping changes (website or platform), branching/committing in the /work/archie-platform lane clone, handing work to the host runner, creating or fixing PR titles/bodies, or updating tasks/knowledge "like Claude-CLI does". For F.O.R.G.E. REVIEW STATUS, VERDICTS, stuck reviews, or the merge gate, load archie-repair-bay as well — it has the verified in-process call surface.
---

# archie-lane-ship — opencode ship + Repair Bay + Dev HQ coordination

Verified 2026-09-23. Where this conflicts with `AGENTS.md` on disk, THIS is current
(option-B, 2026-09-13: lanes are host-direct, `contained=False`; AGENTS.md's
"opencode does not ship" is stale).

> Detail moved to `reference/devhq-contract-and-traps.md` — read it when the short version is not enough.

## 1. Trees & identities
- **Live tree `/mnt/archie_brain`** — the served platform; owner/Claude also work
  here (ONE live tree: check who's mid-task before any git op; never `git add -A`;
  stage only this session's files; never commit to `main`).
- **Lane clone `/work/archie-platform`** — base for the SCOPE-GATED runner path
  (Path B). Edits here do not reach the served platform by themselves.
- **Two git identities:** lane has NO credential (never `git push`); all GitHub
  writes go through the platform container's token.

## 2. Ship paths
**Path A — lane clone (default here):**
1. `git -C /work/archie-platform switch -c <type>/<short>` (if on main), `add <explicit files>`,
   commit `--no-verify` (no pre-commit in this lane; run `git diff --cached --check`).
2. **Stop there.** No helper ships from this container: `/opencode-home/bin/` is absent,
   so neither `ship-branch.sh` nor `opencode-pr` is installed. Do not `git push` — a token
   IS mounted, so a push would succeed and skip the host's scope check. Report
   `committed on <branch>` and let the host runner ship it.

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
