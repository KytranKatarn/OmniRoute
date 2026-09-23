# 🔭 A.R.C.H.I.E. Platform Findings Index

**Last Updated:** September 14, 2026
**Maintained by:** opencode lane (Applications & Concepts)
**Scope:** Platform modules & features the opencode lane owns, plus cross-cutting
learning that should survive session boundaries.

This index is the durable home for lane findings. It is ingested by the knowledge
base as a `github_file` entry (nightly KB job), so anything merged to `main` here
becomes searchable via the `archie_kb` MCP tools. **Keep it updated as features ship**
— one short entry per feature/module/workstream, with pointers to the code that
proves the claim.

---

## How to use this index

- **Before building anything new** → `search_knowledge("docs/FINDINGS_INDEX" or the
  module name)` to see if the finding already exists. It usually does.
- **After finishing a task** → add/refresh an entry below, then merge it so the KB
  re-indexes it.
- Entries are deliberately terse: what exists, where, how it ships, gotchas that cost
  someone time.

---

## Module & feature findings

### Repair Bay — Pushes tab "Create PR" (`platform_v2/tools/repair_bay/`)
- **Feature:** the Pushes tab lists pending branches (`GET /api/pushes/summary`,
  read-only). The "Create PR" action used to be a static GitHub compare `<a>` link
  with no backend route — the button appeared dead. Fixed by adding a real
  `POST /api/pushes/<path:branch>/create-pr` endpoint + wired button.
- **The engine — how local-only commits reach GitHub:** the Pushes tab lists
  branches whose commits exist ONLY in the live checkout (`/mnt/archie_brain`),
  never on origin. The clone-based workers (`/tmp/repair_bay_clone`) only ever
  hold origin's state, so they cannot carry these commits. `push_pending_branch()`
  in `github_service.py` spins up a per-call scratch clone under /tmp, fetches the
  branch FROM the live checkout (local-path fetch — read-only on the host tree;
  git refuses as root, so both the command and its spawned upload-pack carry
  `safe.directory=/mnt/archie_brain/.git`, and `--no-filter` keeps the
  blob:none filter from stripping the commits' blobs), adds the origin remote,
  pushes from the scratch clone with token auth, then removes it. **All git
  writes stay under /tmp — the shared tree and the shared pipeline clone are
  never written.** E2E-verified SHA-identical against a real pending branch.
- **Key files:** `pending_push_routes.py` (new route validates via
  `scan_pending_pushes()`: 404 unknown / 400 nothing-ahead / 502 push-or-PR
  failure; title from newest pending subject, body lists the ahead commits),
  `pending_push_service.py` (scan + `pending_commit_subjects()`),
  `github_service.py` (`push_pending_branch()`, `create_pr()` :486,
  `create_branch()` :342, `_api_post` with rate-guard, clone-based writes at
  `CLONE_PATH=/tmp/repair_bay_clone`), template button → `createPrFromPush()`.
- **Tests:** `platform_v2/tests/test_repair_bay_push_create_pr.py` (7 tests:
  404/400/502×2/success/fallback-title/branch-with-slashes). Run via
  `docker exec archie_platform python3 -m pytest` (pytest 9.0.3 installed there;
  the lane container has no pytest). Note: `pending_push_routes` imports its
  services lazily inside each route, so tests monkeypatch the SOURCE modules
  (`services.pending_push_service.*`, `services.github_service.*`), not the route
  module, or the patch never binds.
- **Ship & deploy:** a merge is NOT a deploy. The hub mounts `./platform_v2:/app:rw`
  (docker inspect confirmed), so on the hub `git pull` on `main` +
  `docker compose restart archie_platform` IS the deploy for Python/templates.
  Verify through the running process, not the file. (Earlier wording here claimed
  the hub ran COPY-baked code — wrong; the bind mount is the deploy mechanism.)
- **Scope note:** `platform_v2/tools/repair_bay/`, the template, and `docs/` were
  originally NOT in the opencode lane's `allowed_paths`; the scope guard dropped
  out-of-scope edits at ship time. `config/agents/opencode.yaml` was widened
  (backups: `.bak.20260914111811`, `.bak.20260914114324`). Repair Bay is not in the
  Applications/Concepts catalogue set, so it needed an explicit grant.

### Faith module — Scriptures feature (58 collections) (`platform_v2/tools/faith/`)
- **Feature:** 58 scriptural collections, searchable, incl. a reader experience.
  Shipped via F.O.R.G.E. review → merge → deploy.
- **Deploy gotcha:** the hub mounts `./platform_v2:/app:rw`, so on the hub a
  `git pull` on `main` + container restart IS the deploy for Python/templates; the
  baked-image footnote does not apply to the live mount. Always verify against the
  RUNNING process (native JS beats "file is current, module is stale").
- **Status:** shipping via host-runner handoff files
  (`/mnt/archie_brain/opencode-scriptures-task.txt`,
  `/mnt/archie_brain/ship-scriptures.sh`).

### Faith module — online chat with memory (parallel workstream)
- **Status:** PR open — `opencode/featfaith-online-chat-with-faith--memory-1789345528`
  @ `12062e2a9`, needs F.O.R.G.E. review → merge → deploy → verify.

### OpenCode lane — scope config, ship mechanics
- The opencode lane holds **no git credentials**; `codex-pr` does not exist for it.
  `git push` will fail — that is design. Work ships when the HOST runner
  (`scripts/agents/run-opencode-task.sh`) stages the changes, scope-checks them
  against `config/agents/opencode.yaml`, runs pre-commit + tests in a throwaway
  container, and opens the PR. Lane's job ends at "edit is on disk and correct".
- **Scope guard mechanics:** `check_diff_paths` (in `services/agents/codex_scope.py`)
  is agent-agnostic; it is enforced for opencode *on the host after the fact*, so an
  out-of-scope edit is silently dropped later — check the path before editing.
- `config/agents/*` and `scripts/agents/*` are blocked to the lane itself; widening
  is done by a human via `widen-opencode-scope.sh`.

---

## Cross-cutting gotchas (recurring cost)

- **All git writes happen under /tmp, never in the host tree.** The container runs
  as root on a host-owned checkout; running git in `/mnt/archie_brain` as root
  would root-poison its `.git`. Read-only scans are fine; any write goes through a
  throwaway clone. When you must ship local-only commits (present ONLY in the live
  checkout), **fetch FROM the live tree** (read) into a scratch clone, then push
  the scratch clone. A local-path fetch refuses for root unless BOTH the command
  and its spawned `upload-pack` carry `safe.directory=/mnt/archie_brain/.git` —
  note the **`.git` suffix**: git checks ownership of the `.git` directory, and an
  env-only `safe.directory` does not propagate into the subprocess; use
  `--upload-pack="git -c safe.directory=.../.git upload-pack"`.
- **A blob:none partial clone strips blobs on fetch** — when fetching commits that
  exist nowhere else, pass `--no-filter` or the push fails on missing objects.
- **Functions that import their helpers lazily (inside the route) can't be
  monkeypatched on the route module** — patch the source module
  (`services.*`), not the importing one, or the `from X import Y` rebinds and your
  patch is dead code.
- **Verify through the RUNNING process, not the file** — a bind mount keeps the file
  current while an imported module stays stale.
- **A test passing proves nothing until you know it CAN fail** — re-introduce the bug
  in a COPY and watch it go red; never mutate the live file to check.
- **Inter-service calls use mesh IPs, never public hostnames** — public URL routes
  through a CDN capped at 60s and bypasses the queue.
- **Storage is UTC; users see EDT** via `services.time_utils` / `|localtime` /
  `ArchieTime` — never emit raw `datetime.utcnow()` or a literal "UTC" to users.
- **ALL LLM/inference goes through the Department-HQ dispatcher**, never Ollama
  directly (ADR-013). Long LLM calls should 202 + poll, not block the web thread.
- **Never write the `agents` table directly** — go through `services/agent_service.py`.

---

## Legend / status flags

| Flag | Meaning |
|---|---|
| ✅ shipped | merged + deployed + verified |
| 🚧 building | code in progress in the lane |
| 🔁 PR open | branch pushed, waiting on review |
| ⚠️ blocked | waiting on a human or other lane |

**Footer:** When you read this, you are expected to leave it more accurate than you
found it.
