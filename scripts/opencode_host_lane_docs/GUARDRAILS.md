# opencode — HOST instance — GUARDRAILS (always loaded)

**This is the HOST instance of opencode**, not a container lane. It runs the
native `opencode` binary as user `kytran` (installed by
`scripts/install_opencode_on_host.sh`), with the host's real Docker socket, real
`ssh`, and the whole filesystem. It is **not** any of the container lanes —
`archie_opencode_terminal` (17685, guarded), `archie_opencode_terminal_host`
(17686) or `archie_opencode_terminal_gf` (17687, guard-free). Where a disk doc
conflicts with this file, this file wins **for the host instance**.

## What "guard-free" means here
- The native binary has **no scope guard**: no path allowlist, no blocked-glob
  list, no `core.hooksPath` shim. You may edit any path in the repo.
- **"Allowed to edit" is not "safe to edit."** The review/merge layers still
  bind: repo `pre-commit`, F.O.R.G.E. review in Repair Bay, and a **human merge**.
- `opencode-pr` and `ship-branch.sh` do **not** exist on the host. `gh` here is
  the **real** CLI, authenticated — not the container's refusing shim. Ship with
  `git` + `gh` (below).

## Identity & trees
- You work in the **live tree `/mnt/archie_brain`** — the served platform,
  mounted rw. An edit there serves the next request. `CLAUDE.md`, `.claude/rules`,
  `AGENTS.md` and `scripts/` resolve exactly as Claude sees them.
- `/work/archie-platform` on the host is **not** a git checkout (an empty,
  root-owned `platform_v2/` only). Do not work or ship from there — that clone
  belongs to the container lanes.
- `/opencode-home` does **not** exist on the host. This instance's home is
  `~/.config/opencode/`.
- ONE live tree is shared with Claude, the owner, and every container lane:
  before any git operation in `/mnt/archie_brain`, check who is mid-task.
  **Stage only this session's files. Never `git add -A` there** — it sweeps the
  owner's in-progress work into your commit (that happened 2026-09-13).
  **Never commit to `main` there.**

## Git & GitHub
- `gh` is the real CLI, authenticated as `KytranKatarn` with `repo` and
  `workflow` scopes; `git push` over HTTPS works.
- **NEVER merge or approve your own PR** — not with `gh pr merge`, not by any
  path. F.O.R.G.E. reviews; a human merges.
- **Never ship from `/mnt/archie_brain` directly.** Build the change on a branch
  in a **separate worktree or clone** off `origin/main`, commit there, push an
  `opencode/*` branch, and open the PR:
  ```
  git -C /mnt/archie_brain worktree add -b opencode/<short> <scratch> origin/main
  # edit, then:  git -C <scratch> add <explicit files> && git -C <scratch> commit -m "..."
  git -C <scratch> push -u origin opencode/<short>
  gh pr create --base main --head opencode/<short> --title "..."
  ```
- Never `git push` to `main` from anywhere. Never force-push a shared branch.
- The credential permits merging as well as opening (`PR: write` is not
  divisible on GitHub). Branch protection on `main` is
  `required_approving_review_count: 1` (measured 2026-09-30) but will not stop
  **this** instance from merging its own PR from the host. Restraint is the only
  control.

## Scope
- No path restrictions on the host. Two platform invariants still bind: the
  `agents` table is **single-writer via `services/agent_service.py`** (never
  write it directly), and `**/department_dispatcher.py` is **never edited from a
  lane** (ADR-013 — all LLM traffic goes through Department-HQ dispatch).
- Never touch secrets, `.env*` values, or credential files. You can read the
  repo; do not print, echo, copy or move credentials.
- Prefer not to rewrite another lane's cage (`config/agents/codex.yaml`,
  `config/agents/opencode.yaml`, `scripts/agents/*`) or the repo's
  `AGENTS.md` / `.claude/` unless the owner asks for it in this session. If a doc
  is wrong, report it rather than silently editing it.

## Platform conventions (code this instance writes)
- All LLM calls go through Department-HQ dispatch — never Ollama/model directly.
- Long inference returns 202 + a DB poll row; never block the web thread.
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
- The `archie-kb` MCP tools reach the gateway at `127.0.0.1:17800/mcp` (published
  on the host). ALWAYS search the KB first — `search_knowledge`,
  `search_mistakes`, `recall_context`, `session_briefing`, `get_recent_activity`.
- **Continuity**: `~/.config/opencode/data/archie-handover.md` is **this host
  instance's own handover**. Read it at boot; refresh it at session end. The
  container lanes keep theirs inside their volumes (`/opencode-home/...`) — do
  not go looking for `/opencode-home` here.
- The platform-wide "active fire" lives in the Claude handoff at
  `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`, which
  is readable from the host. The canonical owner-identity file is
  `~/.claude/projects/-mnt-archie-brain/memory/feedback_owner-context.md`.
