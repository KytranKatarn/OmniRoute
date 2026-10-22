# DS9 hardening — 4 items, planned and integrated

**Date:** 2026-10-21 · **Lane:** opencode · **PR:** [#4032](https://github.com/KytranKatarn/archie-platform/pull/4032) (open)

## Outcome

| # | item | status |
|---|---|---|
| 1 | gateway liveness probe | **shipped** — a dead gateway now alarms; an idle one still does not |
| 4a | prune the token ledger | **shipped** — `task_execution_log` is in the retention service at 400d |
| 4b | move the worktree | **done** — moved out of the deployed tree, ref ambiguity gone |
| 3 | cost tracking | **shipped** — the ledger carries **$641.60** of real spend (was $0.00) |
| 2 | independent free provider | **not fixed — cannot be, by code.** The fix is an install. Task **#7424** |

The measured results, after the change:

- `task_execution_log.cost` was **0 on all 2,127,111 rows**. It now carries
  **$641.60**, and the on-the-fly 30-day figure (**$424.18**) matches the
  ledger's own 30-day sum exactly.
- Stopping `deep-space-9.service` raised **nothing**. It now writes a
  `gateway_down` fingerprint and alarms — and a live-but-idle gateway still
  does not.
- `task_execution_log` was the platform's only unbounded table of size
  (**1.25 GB**, ~7k rows/day, no pruner). It now has both a policy and a
  pruner.

**One correction to the plan below.** The plan says `governance_audit_log` and
`engineer_health` were unpruned. They were not: the audit log is pruned at
365d by the same job, and `engineer_health` at 30d by its own service. Only
the token ledger had no pruner at all. The plan below is kept as written,
because the correction is the finding.

---

Each item below is scoped, with the evidence that scoped it. Items are ordered by
value × safety, and the work is integrated so the parts reinforce each other:
the liveness probe (#1) and the prune job (#4a) are both "the platform should
know the truth about the gateway", and the cost work (#3) is what makes the
truth usable.

---

## #1 — A dead DS9 gateway is silent → add a liveness probe

**The finding (measured, not inferred).** I stopped `deep-space-9.service`,
waited 70+ seconds, and **nothing alerted**. The DS9 was unreachable and the
platform said nothing.

**Why.** `omniroute_gateway_health` reads the gateway's `call_logs` and
*deliberately* does not alarm on silence:

> *"Deliberately does NOT alarm on an idle gateway — a lane nobody called is
> not a broken lane, and paging on silence is how a channel gets muted (#6803)."*

That rule is right for an **idle** gateway. A **dead** gateway is
indistinguishable from it, because `call_logs` is the only thing the job reads.

**The fix.** Separate the two states instead of weakening the rule:

| gateway state | condition | alarm? |
|---|---|---|
| live, but nobody called it | `idle` | **no** — the #6803 rule stands |
| not answering its health endpoint | `gateway_down` | **yes** |

The liveness probe hits the DS9's own `/api/health`. `ds9_app_server_service`
already does exactly this for the app-server card (it correctly reported
`unreachable` while the gateway was down) — so the probe exists; it just isn't
wired into the *gateway* health job. This reuses that path rather than adding a
second one.

**Scope:** `platform_v2/services/omniroute_health.py` (add `check_gateway_liveness`),
`platform_v2/tools/department_hq/jobs.py` (call it, and alarm on `gateway_down`).

**Risk:** low. The probe has a short timeout, is failure-tolerant, and only
adds a *new* alarm condition — it cannot make an idle gateway noisy.

---

## #2 — The free tier has one throat → a genuinely independent path

**The finding.** The free pool is **21 candidates: 20 `cfp/*` models + 1
`uncloseai` model**. All 20 `cfp` models run through **one** headless browser
session, so a browser or Cloudflare-Playground outage takes out 95% of the free
tier at once. Spreading across models protects against a *per-model* limit; it
cannot protect against the transport.

**Why it isn't a one-line fix.** Of the 9 keyless providers in DS9's
catalogue, 4 are admitted to the auto pool, and I traced every one:

| provider | admitted | independent transport? | in the pool today |
|---|---|---|---|
| `cloudflare-playground` | yes | **no** — browser-backed | 20 models |
| `duckduckgo-web` | yes | **no** — browser-backed | 0 (models come from a sync that hasn't run for it) |
| `devin-cli-agentic` | yes | **yes** — local CLI | **0** — it is `PROBE_REQUIRED` and the devin CLI is not installed |
| `uncloseai` | yes | **yes** — no browser, no CLI | **1 model** — its upstream `/v1/models` serves exactly one at a time (the roster rotates weekly) |
| `aihorde` | **no** | yes | 0 — `toolCalling: false`, so the auto-router (which dispatches with tools) cannot use it |
| `veoaifree-web`, `auggie`, `zcode`, `codex-app-server` | no | — | 0 |

So the free tier's only independent transport serves **one model** and
rate-limits it. There is no second independent provider available in the
keyless catalogue today.

**The plan, in order of cost:**

1. **`devin-cli-agentic` is the prize** — 127 models on a path that does *not*
   use a browser, so it is independent of the cfp failure mode. It is excluded
   only because the devin CLI is not installed and the provider therefore fails
   its readiness probe. Install/provide the CLI, let the probe pass, and the
   free tier gains a second, genuinely independent path.
2. **`duckduckgo-web`** — 6 more models, but browser-backed, so it improves
   *variety*, not independence. Lower value.
3. **Document the residual** — after (1), the free tier has one browser-backed
   provider and one CLI-backed provider. A single-host failure still takes out
   both (the browser and the CLI are on the same box), so the honest residual
   is *host* independence, which is a different (bigger) piece of work.

**Scope:** #2 is a DS9-side enablement, not a platform change. It is recorded
as a task with the finding, because the enabling step is an install/decision
rather than a code edit.

---

## #3 — Cost is untracked → one pricing table, both sides read it

**The finding.** `task_execution_log.cost` is **0 on every one of its 2,126,949
rows**. The DS9 tab therefore says *"not tracked"* rather than print a `$0.00`
that reads like a real spend of nothing. The DS9's own gateway traffic now
mirrors into the platform (the mirror was dead for 10 days — fixed), so the
*rows* exist; only the price is missing.

**The plan.**

1. **One pricing source.** The platform already has per-model pricing in
   `src/shared/constants/modelSpecs.ts` (in the DS9 tree) and the platform has
   its own model metadata. Rather than two tables that drift, the platform
   resolves price by `(provider, model)` from the same spec the gateway uses.
2. **Price on write.** The token-economy write path computes `cost` from the
   resolved price instead of storing 0.
3. **Backfill.** A bounded script recomputes `cost` for existing rows, so the
   history becomes usable without waiting for the data to age in.
4. **Say "not tracked" only when it is not tracked.** `cost_tracked` becomes
   per-row truth rather than a global guess.

**Scope:** the token economy. **This is the highest-blast-radius item of the
four** — it touches the accounting the whole platform reports on. It is
sequenced last and its own PR.

---

## #4 — Two smaller things

### 4a — Nothing prunes the platform's big tables

`task_execution_log` 2,126,949 rows since 2025-12-17 · `governance_audit_log`
4,316,330 rows since 2026-02-10 · `engineer_health` 12,899 rows in 16 days.
None of them is pruned. The host was at **96%** with 18G free an hour ago.

**The fix:** extend the existing retention/prune job to cover them, with a
keep-window chosen per table (the token ledger needs longer than the health
probes do).

### 4b — The codex lane's worktree is inside the live tree

`/mnt/archie_brain/origin/main` is a registered git worktree on
`opencode/feat-ds9-image-readiness` (task #7407, **this lane's** branch). Two
problems:

- The path **shadows the `origin/main` git ref** — `git show origin/main:<file>`
  now prints an ambiguity warning. It still resolves, so it is a nuisance rather
  than a breakage, but it silently made one of my own checks return nothing.
- It leaves **165M** of untracked, unignored content in the deployed tree.

The code backup is *not* affected (it tars only `platform_v2 ai_bridge scripts
database/migrations`).

**The fix:** `git worktree move` it out to the same place the other lanes use
(`/home/kytran/.cache/opencode/tmp/...`), so the live tree has one less way to
bite.

---

## Sequencing

| # | item | surface | risk | PR |
|---|---|---|---|---|
| 1 | gateway liveness probe | platform | low | with the others |
| 4a | prune the big tables | platform | low | with the others |
| 4b | move the worktree | git | very low | n/a (no code) |
| 3 | cost tracking | platform | **highest** | own PR, last |
| 2 | independent free provider | DS9 / infra | medium | DS9 tree, after the CLI exists |

## The one thing that is urgent regardless

**#4030 and #4029 need merging.** The tokens + 500 fix is live in the running
platform but **not on `main`** (my #4027 was stacked on #4026's *branch*, so
merging it landed there). A deploy from `main` reverts it.
