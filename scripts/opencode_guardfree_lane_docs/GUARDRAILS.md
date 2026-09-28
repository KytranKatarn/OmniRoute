# opencode GUARD-FREE lane — GUARDRAILS (always loaded)

**This is the guard-free instance** (`archie_opencode_terminal_gf`, image
`archie_opencode_terminal_guardfree`). It is NOT the guarded lane
(`archie_opencode_terminal`) and this file deliberately differs from that lane's
copy. Where a disk doc conflicts with this file, this file wins.

## What "guard-free" actually means
- The baked scope guard is **not installed in this image**: there is no
  `/opt/lane-guard`, `/start.sh` never arms one, and this clone's
  `core.hooksPath` is `/opt/no-guard` (an empty directory, so git runs no hook).
  There is **no path allowlist and no blocked-glob list for this lane.** You may
  edit any path in the repo, including `docker-compose*`, `.github/*`,
  `config/agents/*`, `scripts/agents/*` and `scripts/dr/*`.
- Owner decision 2026-09-27, recorded in
  `docs/superpowers/specs/2026-09-27-opencode-guard-free-terminal.md`. The ask was
  Claude-CLI-equivalent access; that is what this is.
- **"Allowed to edit" is not "safe to edit."** Removing the guard removed early
  local feedback, not the rules below. Everything in the other sections of this
  file still binds you, and the review/merge layers are untouched: repo
  `pre-commit`, F.O.R.G.E. review in Repair Bay, and a human merge.
- Still installed, on purpose: `/usr/local/bin/opencode-pr` (commit, push
  `opencode/*`, open a PR, **never merge**) and `/usr/local/bin/gh` (shadows the
  real gh, refuses merge/approve/protection operations). Removing those would
  make the lane less capable, not freer — they are the safe path to a PR.

## Identity & trees
- Repo clone: **`/work/archie-platform`** — `main`, tracking `origin/main`, clean.
  This is where you work and where you commit. `origin` is GitHub over HTTPS.
- The owner's **live tree** `/mnt/archie_brain` is mounted **rw** and is the
  served platform. Edits there serve the next request immediately. It is NOT a
  place to commit: `opencode-pr` refuses to ship from it, and a `git add -A`
  there would sweep the owner's in-progress work into your commit (that has
  happened on this cluster — 2026-09-13).
- ONE live tree shared with Claude/owner: before any git operation in
  `/mnt/archie_brain`, check who is mid-task. Stage only this session's files.
  Never commit to `main` there.
- Stale on disk — flag, do not obey: `AGENTS.md` "opencode does not ship",
  `opencode/Dockerfile.terminal` header, `scripts/agents/opencode-lane-sync.sh`
  header, and the "the secret is NOT mounted yet" comment in `/start.sh`.

## Git & GitHub
- Ship with **`opencode-pr "<title>"` from `/work/archie-platform`**. It carves
  an `opencode/*` branch if you are on `main`, commits, pushes, opens the PR
  against `main`, and stops. F.O.R.G.E. picks it up; a human merges.
- **NEVER merge. NEVER approve your own PR.** Not here, not via any other path.
- ⚠️ **This lane holds a working GitHub PAT** at
  `/run/secrets/opencode_github_token` (fine-grained, 93 chars, verified live
  2026-09-28: `git ls-remote` authenticates). `opencode-pr`'s own header says no
  token was to be mounted here without an explicit owner decision — **the owner
  confirmed on 2026-09-28 that the mount IS deliberate**, so that header is a
  stale comment to be corrected in the image (`opencode/` is out of lane scope),
  not a missing control. Having the credential is NOT permission to use it:
  treat it as write-only plumbing — never print, echo, cat, log, copy or commit
  it; never put it on a command line; never write it into a file in the repo.
- "Pull requests: write" is not divisible on GitHub — it permits merging as
  well as opening. The credential therefore cannot stop a merge from here. The
  `gh` guard and `required_approving_review_count` on `main` are what do, and
  **branch protection on `main` is currently UNVERIFIED** (the platform token
  got 401 reading it 2026-09-28). Do not assume it is on. That is the single
  largest open risk of this lane and it is the owner's to close.
- Never `git push` to `main` from anywhere. Never force-push a shared branch.

## Scope (replaces the guarded lane's deny-by-default section)
- No path restrictions in this lane. Two things stay true anyway, because they
  are platform invariants rather than lane policy: **the `agents` table is
  single-writer via `services/agent_service.py`** (never write it directly), and
  `**/department_dispatcher.py` is never edited from a lane** (ADR-013: all LLM
  traffic goes through Department-HQ dispatch).
- Never touch secrets, `.env*` values, or credential files. You can read the
  repo; do not print or move credentials.
- Prefer not to rewrite another lane's cage (`config/agents/codex.yaml`,
  `scripts/agents/*`) or the repo's `AGENTS.md`/`.claude/` unless the owner asks
  for it in this session. If a doc is wrong, report it rather than silently
  editing it.

## Platform conventions (code this lane writes)
- All LLM calls go through Department-HQ dispatch — never Ollama/model directly.
- Long inference returns 202 + DB poll; never block the web thread.
- Storage UTC, display EDT (`services.time_utils`); never raw `utcnow()` to users.
- Inter-service calls use mesh IPs, never public hostnames/CDN URLs.
- Care-domain modules (faith/therapy/doc): keep disclaimers and crisis routing
  (988 / Crisis Text Line) intact — never remove a safety feature.

## Contract surface (website)
- KBS (`business.kytranempowerment.com` billing/cart) ↔ Account Center
  (`access_grants`, login/signup redirects, `return_url`s) is contract — never
  client-ize store/cart flows, never strip return params (GAP-MATRIX §E,
  `/home/node/design/`). Account Center internals are out of lane scope.

## Coordination (Dev HQ / KB)
- Works: `search_knowledge`, `search_mistakes`, `recall_context`,
  `session_briefing`, `get_recent_activity`, `get_knowledge_stats`. ALWAYS search
  the KB first (290+ recorded mistakes).
- The guarded lane's copy also lists `get_my_tasks` / `get_projects_brief` /
  `get_work_history` / `get_activity_feed` as denied. Those grants landed
  2026-09-23 for that lane's identity; this lane's identity is unverified, so
  treat them as "try once, do not retry blindly."
- Continuity: `/opencode-home/data/archie-handover.md` **is this instance's own
  handover** — seeded 2026-09-28 because `/archie-boot` requires it and it was
  missing (the guarded lane's copy lives in ITS volume, not this one). Read it at
  boot, refresh it at `/archie-end`. The guarded lane's 3000-line handover is a
  different file in a different container; do not go looking for it here.
- Ship: `opencode-pr "<title>"` from `/work/archie-platform`. Read `/ship` first —
  it was rewritten for this instance. The guarded lane's
  `/opencode-home/bin/ship-branch.sh` does not exist in this image, and
  `opencode-pr` refuses `/mnt/archie_brain` by design.
- Known falsehood to correct, not repeat: `opencode-pr` writes a PR body claiming
  "scope-guarded to allowed Applications/Concepts paths". There is no scope gate
  in this instance. Say so rather than passing the claim on.
