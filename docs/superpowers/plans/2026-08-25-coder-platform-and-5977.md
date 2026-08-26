# Coder platform (Lane 3) + cockpit voice timeout (#5977)

**Status:** findings + plan. Nothing implemented. Written 2026-08-25.

---

## 0. SECURITY — do this first

`docker inspect archie_engine --format '{{range .Config.Env}}...'` prints **secrets in
plaintext**: `ARCHIE_GITHUB_TOKEN` (a PAT with **push + admin on archie-code**) and
`INTERNAL_API_KEY`. Both were exposed in a session transcript on 2026-08-25.

- [ ] Rotate `ARCHIE_GITHUB_TOKEN`; update the engine env and any other consumer.
- [ ] Rotate `INTERNAL_API_KEY` — ⚠️ it is SHARED (hub ↔ standalones ↔ KSO ↔ node_api).
      Rotating it is a fleet-wide change; see `billing.md` + `standalone-extraction.md`
      for every place it must land, and verify via the RUNTIME env of each container.
- [ ] Never `inspect ... Env` unfiltered again. Use
      `docker inspect X --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -vE 'KEY|TOKEN|PASSWORD|SECRET'`.

---

## 1. Lane 3 does not use the cluster (the headline finding)

**Measured 2026-08-25:**

| engine env | value | meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://100.64.0.4:11434` | **direct to hub Ollama** |
| `ARCHIE_HUB_URL` | `http://100.64.0.4:3000` | hub API (skills/KB) — fine |

The engine calls Ollama **directly**, bypassing `department_dispatcher`. Consequences:

- Violates **ADR-013** (all inference through the Bridge).
- **Pinned to the hub** — measured tonight at **45% success / 422s avg** on `code_review`,
  while USS-246 ran 73% and USS-245 **98%**. Lane 3 cannot reach either.
- No welfare gating, no cold-load queue, no capability routing.
- Its tokens never reach `task_execution_log`, so Lane 3 is invisible in Token Economy
  and A.R.M.A.D.A.

### Fix
Route Lane 3 inference through the hub dispatcher instead of raw Ollama.

- [ ] Find the engine's inference call sites: `archie_engine/{config,build_loop,session,eval_harness}.py`.
- [ ] Replace direct Ollama calls with a hub API call that lands in `dispatch()` —
      capability `code` / `code_review`, `module_id='archie_engine'`, `local_only=True`.
      The hub already exposes an internal dispatch surface (Bearer `INTERNAL_API_KEY`);
      reuse it rather than inventing a second path.
- [ ] ⚠️ **Use a queue-aware call.** A cold model returns `queued=True`, and a bare
      `dispatch_json` MASKS that as "dispatch failed" and DROPS the work (KB #276153).
      The correct entry point since PR #2831 is `dispatch_awaiting_queue()`.
- [ ] Keep `OLLAMA_HOST` as an explicit **fallback** for when the hub is unreachable —
      Lane 3 must still function if the platform is down, since it is what repairs it.
- [ ] VERIFY BY MEASURING, not by reading: after the change, Lane 3 work must appear in
      `task_execution_log` with a non-hub `node_used_id` at least sometimes.

---

## 2. The build loop is not running

**Measured:** `build_loop|pull_work|opened PR` → **0 log lines in 7 days**. The container is
`Up 2 days (healthy)` and serving the TUI websocket only. 9 commits in 30 days, all
git-authored `Kytran`; PRs #40–48 clustered 18–23 Aug then stopped.

⚠️ **This corrects MEMORY.md**, which claims "engine-authored PRs merge ~daily". They do not.
⚠️ All 46 merged PRs show author `KytranKatarn` because the engine uses that token —
**PR authorship cannot distinguish engine work from human work.** The loop logs are the
only evidence. Do not use PR author as a liveness signal.

- [ ] Establish whether the loop is stopped **deliberately** or regressed. Same failure
      shape as the documented boot race (project_archie-building-machine): the engine
      answers :9090 while doing none of its job, so every health check reads green.
- [ ] If it should be running: find the entry point and why it exits. Add a heartbeat so
      "loop alive" is measurable, not inferred from PR activity.
- [ ] ⚠️ Do NOT restart the loop until §1 lands, or it will hammer the 45% hub path.

---

## 3. The three-lane split: safety half exists, work half does not

**Built and tested** (`archie_engine/scope_guard.py`, 141 tests green):
- `PLATFORM_SCOPE` = platform-minus-kernel for Lane 3
- The **governance kernel is blocked for every lane, including A.R.C.H.I.E.'s own** —
  the code that enforces which lane runs cannot be edited by any lane
- Lane 2's harness/sandbox wrapper flagged as cross-lane authority
- Lane 2 (Codex) categories in `config/agents/codex.yaml`: fitness, family_tree, therapy,
  faith, brainstorm, doc, tests. ⚠️ `media_studio`/`game_studio`/`media_hub` are
  DELIBERATELY excluded (real production data) — a standing decision, not an oversight.

**Missing: nothing routes work to a lane by category.** Scope says what a lane *may write*;
nothing says what it *should pick up*.

- [ ] Define categories and their owning lane. Straw man, to be argued not assumed:
      Lane 1 (Claude) — architecture, cross-cutting refactor, anything touching governance
      Lane 2 (Codex)  — the codex.yaml app modules, mechanical edits, test authoring
      Lane 3 (engine) — platform-minus-kernel: single-module fixes, audit-proposal drains
- [ ] Router reads `unified_tasks` + Repair Bay proposals, stamps a lane, and each lane
      pulls its own queue. `pull_work` already exists engine-side — extend, don't replace.
- [ ] ⚠️ A lane must never pick work its scope guard would then refuse. Route-time and
      write-time rules must agree, or work is claimed and dropped.
- [ ] Capacity-aware: with #6024 open, a lane pinned to a saturated node should shed to
      another lane rather than queue forever.

---

## 4. Engine container ships no tests

`/app` holds `archie_engine`, `build`, `pyproject.toml` — **no `tests/`**. The 141 tests run
only from a repo checkout, so the engine's own container cannot verify the engine.

- [ ] Ship `tests/` into the image, or add a CI job that runs them against the built image.
- [ ] Note the Go tests need `GOTMPDIR` set — `/tmp` is **noexec** on this host, and the
      failure reads `permission denied`, which looks like a code failure and is not.

---

## 5. #5977 — cockpit drops a director report when the voice LLM blocks

**Measured 2026-08-25 (24h):** 466 director reports, **37** `archie_voice: LLM call failed
(timed out), using fallback` (~8%, down from ~16% on 08-23), **0** `submit_via_inbox failed`.

The dropped submission that motivated the task was the F.O.R.G.E. review report for
**archie-code PR #45** — a real review whose result never reached the cockpit.

⚠️ **This got more load-bearing tonight**: `archie-code` was added to `GITHUB_REPOS`, so more
of its PRs will now be reviewed, and their reports travel this path.

### Root cause
A **synchronous LLM call in the cockpit's request path**, with a 5s read timeout on the
`archie_platform → archie_comms:3002` hop. Same architectural shape as PR #2831: inference
on a request path that cannot absorb it.

### Fix — take the LLM off the request path
- [ ] `submit_via_inbox` should persist the report FIRST, then format the voice line
      asynchronously. A report must never be lost because prose generation was slow.
- [ ] Voice formatting becomes a queue-aware dispatch (`dispatch_awaiting_queue`), not an
      inline call with a 5s budget.
- [ ] The existing fallback stays as the display value until the formatted line arrives.
- [ ] ⚠️ **Do not "fix" this by raising the 5s timeout.** That trades a dropped report for a
      blocked worker, and 466 reports/day through a slower path is worse.
- [ ] Test: assert the report row exists even when the voice dispatch raises/times out.
      A negative control — force the LLM path to fail and prove nothing is lost.

### Related
`media_hub_action` approvals hit this exact trap and fixed it with **`voice=False`**
(KB mistake #279364) — the LLM formatter's ~8s blew an 8s caller timeout and dropped
bookkeeping. Read that before designing this.
