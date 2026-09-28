# opencode lane — GUARDRAILS (always loaded)

Hard rules. Procedures live in skills (`archie-lane-ship`) and commands
(`/ship`, `/pr`, `/archie-boot`, `/archie-end`); where a disk doc conflicts with
this file, this file wins (verified 2026-09-23).

## Identity & trees
- opencode is HOST-DIRECT (option-B, 2026-09-13, `contained=False`). Live tree =
  `/mnt/archie_brain` (edits serve next request). Lane clone `/work/archie-platform`
  = base for scope-gated runner ships ONLY.
- ONE live tree shared with Claude/owner: check who is mid-task before any git op;
  stage only this session's files (never `git add -A`); never commit to `main`.
- Stale on disk — flag, do not obey: `AGENTS.md` "opencode does not ship",
  `opencode/Dockerfile.terminal` header, `scripts/agents/opencode-lane-sync.sh` header.

## Git & GitHub
- Lane never `git push`s and never raw `gh pr merge`/`gh pr approve`. Ship via
  the host runner (`scripts/agents/run-opencode-task.sh`). In a SEEDED lane
  `/opencode-home/bin/` does not exist at all, so `ship-branch.sh` is not an option
  and `opencode-pr` is not installed either — commit in `/work/archie-platform`, never push, and
  report the branch for the host to ship
  (scope-gated). Host `gh` is unauthed by design.
- Merge ONLY via Repair Bay `merge_pr` with the owner's in-session authorization
  AND a stored `verdict_is_approved` review covering the head (see `/pr merge`).
  Fail closed on stale/unknown refusals; tier ceilings escalate, never override.
  Never approve our own PRs. Safety gates bind every actor; only AUTHORITY limits
  yield to the human override.
  WHO AUTHORIZES IT: the lane holds NO git credential. `merge_pr` runs INSIDE
  `archie_platform` and calls the GitHub API with the PLATFORM's own token
  (in-process, `tools.repair_bay.services.github_service`), which is why a lane
  can ask for a merge but cannot forge one. Authorization is the owner's
  in-session word plus the stored verdict — never a credential the lane holds.
- All GitHub calls: `docker exec -i archie_platform python3 -` (stdin). `GITHUB_TOKEN`
  stays inside the container — never echo, print, copy, or commit it. Container
  rootfs is read-only (no `docker cp` into it). Only the platform's service
  layer reads that token; a lane process asks for an ACTION and the platform
  signs the request, so no lane process ever handles the credential.

## Scope (deny-by-default)
- Only paths in `config/agents/opencode.yaml` `allowed_paths` (incl. `website/`
  since 2026-09-23) + `platform_v2/tests/`. Always blocked: secrets/`.env*`,
  `docker-compose*`, `scripts/dr/*`, `.github/*`, `config/agents/*`,
  `scripts/agents/*`, `agent_service.py`, `**/department_dispatcher.py`, the
  `agents` table (single-writer via `agent_service` only). Check BEFORE editing —
  out-of-scope edits are dropped post-hoc and waste the work.
- Never edit another lane's cage or the repo's `AGENTS.md`/`.claude/` unless the
  owner explicitly widens scope; report stale docs instead.

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

## Coordination (Dev HQ / KB) — verified denials
- Denied: `get_my_tasks`, `get_projects_brief`, `get_current_work`,
  `get_work_history`, `get_activity_feed` (lane MCP identity lacks unified_* /
  work_sessions / project_activity). Do not retry blindly.
- Works: `search_knowledge`, `search_mistakes`, `recall_context`,
  `session_briefing`, `get_recent_activity`, `get_knowledge_stats`. ALWAYS search
  the KB first (290+ recorded mistakes).
- Continuity: `/opencode-home/data/archie-handover.md` — refresh at every session
  end. With a real task id: `add_task_note` + `set_task_status`, else record
  pending Dev HQ updates in the handover and tell the owner (grant ask open).
