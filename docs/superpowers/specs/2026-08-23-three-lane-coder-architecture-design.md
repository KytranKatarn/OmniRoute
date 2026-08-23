# Three-Lane Coder Architecture — Design

**Date**: 2026-08-23 · **Project**: #380 (A.R.C.H.I.E. Building Machine) · **Status**: design, approved in chat, not implemented

## Problem

Three coding capabilities exist on this platform. Two of them are dormant and nobody noticed.

| Lane | Built | Last actually ran | Why it stopped |
|---|---|---|---|
| Claude CLI | yes | continuously | — |
| Codex CLI | fully — container runner, scope guard, telemetry, MCP KB access | **2026-06-28** (56 days) | nothing queues work for it |
| `archie_engine` build loop | fully — branch→plan→apply→test→push→PR | **2026-07-20** (a month) | nothing queues work for it |

Neither is broken. The delegation worker runs every minute and logs `no deferred codex tasks`. The
machinery is armed and idle.

Meanwhile Claude CLI — the *scarcest* resource, billed against weekly Max 20x buckets — does
essentially all the coding.

**The goal**: make the local cluster the default coder, Codex the middle tier, and Claude the
escalation of last resort, with `archie.kytranempowerment.com` as the surface where work is
decided, delegated and approved.

## Owner decisions (recorded)

1. **Routing basis**: sovereignty first, cost second. Local is the destination; Claude/Codex are
   escalation and transition.
2. **Routing authority**: A.R.C.H.I.E. decides, the owner approves. Not deterministic rules, not
   owner-assigns-everything (that is the current failure mode — lanes idle whenever he is not driving).
3. **Local executor**: `archie_engine.build_loop`, **not** Codex's engine. It routes all inference
   through DHQ, so it inherits welfare gating, cost tracking, attribution and ADR-013 compliance.
   **There is no archie-tui/Codex engine merge.**
4. **Work sources**: all four — `unified_tasks`, Repair Bay proposals, Code Health findings, and
   owner requests in the cockpit — every one approval-gated.
5. **Lane 3 scope**: the platform, because Lane 3 *is* A.R.C.H.I.E. and she is COO. Not standalones-only.
6. **Lane 3 constraint**: she still cannot push to main or merge without PR + approval.
7. **Merge authority**: `coo_window` — Tier ≤2, but only inside an open maintenance window whose
   manifest names the PR.
8. **Reach**: other platforms and projects too, with owner approval.

## Architecture

### The organising principle

Decision #953, already established in this codebase: **safety properties are universal, authority
limits are per-actor.** Three coders, one set of safety rules, three ceilings.

**Universal — binds every lane, no exceptions:**

- deny-by-default scope guard, fails closed
- branch + PR only; direct push to a protected branch refused by construction
- F.O.R.G.E. review at the `merge_pr` choke point
- fail closed on a missing, unparseable or non-approving verdict
- telemetry into `task_execution_log`

**Per-actor — the only things that differ:**

| | Lane 1 — Claude CLI | Lane 2 — Codex CLI | Lane 3 — A.R.C.H.I.E. |
|---|---|---|---|
| Auth | Anthropic Max 20x | ChatGPT login | none — local Ollama |
| Cost | scarce | separate free quota | free |
| Executor | interactive | `run-codex-task.sh` (container) | `build_loop` via DHQ |
| Restricted by | judgement + owner | **path** (narrow allowlist) | **process** (approval + PR + window) |
| Ceiling | Tier 3 w/ owner approval | Tier 1 | Tier 2 via `coo_window` |
| Role | architecture, hard reasoning, final merge | mechanical in-module work | the default for everything routine |

### Scope model

The distinction that makes platform-wide reach safe:

- **Codex is a third-party agent** → restricted by **scope**. It cannot reach what it is not listed for.
- **A.R.C.H.I.E. is the COO** → restricted by **process**. Platform-wide reach; every change is
  proposed → approved → branched → reviewed → merged under a ceiling.

`PLATFORM_SCOPE` therefore inverts for Lane 3: from a 19-path allowlist to *the platform minus a
never-touch kernel*. The existing `blocked_globs` become the real boundary:

```
*.env  .env*  *.key  *.pem  *.pfx  secrets/*      credentials
docker-compose*  Dockerfile*  scripts/dr/*         infra + disaster recovery
.git/*  .github/*                                  VCS + CI
*agent_service.py  *department_dispatcher.py       agent/dispatch core
```

**The kernel stays blocked for every lane, including hers.** `department_dispatcher.py` and
`agent_service.py` are the code that enforces every other rule, including which lane runs and what
gets approved. An actor that can rewrite the rules binding it is not governed. By decision #953 that
is a *safety property*, so it is universal. Changes there route to Lane 1 with the owner in the loop.

`media_studio`, `game_studio`, `media_hub` remain excluded from all autonomous lanes until they have
DB isolation — a standing data-safety decision, unchanged.

### Orchestration loop

The approval the owner wants is not per-PR nagging. It is **approving a manifest of planned work** —
which is what a maintenance window already is.

```
  SOURCES                    A.R.C.H.I.E.              COCKPIT (owner)        LANES
  unified_tasks    ─┐
  Repair Bay        ├──►  classify + scope   ──►   proposed manifest   ──►  Lane 1 Claude
  Code Health       │     pick lane, draft         approve / trim /         Lane 2 Codex
  cockpit request  ─┘     the plan                 reject → opens WINDOW    Lane 3 engine
                                                                                 │
                                              merge ≤ Tier 2, on-manifest,  branch → PR
                                              inside the window        ◄──  F.O.R.G.E. review
```

Outside a window the system still runs: lanes keep producing PRs, they just queue for a manual
merge. **Dormancy is solved without autonomy becoming unbounded.**

### Why the window is the right approval artifact

`_pr_on_open_window()` already provides, and already fails closed on:

- no open window
- the PR not on that window's manifest
- a lookup error or the schedule service being unavailable

and `add_item()` **refuses to extend a manifest once the window is open**, so scope cannot creep
mid-window. The owner approved a specific list, in advance, and it is recorded — an audit trail by
construction.

### Multi-repo reach

The manifest entry is a **`(repo, PR)` pair**. A window opened for one repo grants nothing in
another — "safety universal, authority per-actor" extended to per-repo.

| Repo class | Scope guard | Merge authority |
|---|---|---|
| `archie-platform` | `PLATFORM_SCOPE` (platform minus kernel) | `coo_window` |
| `archie-code` | `DEFAULT_ARCHIE_CODE_SCOPE` (exists) | `coo_window` |
| Other products (KSO, creed, KBS, watch ×4, media_hub) | **per-repo scope — must be written** | `coo_window`, explicit per-repo manifest entry, never inherited |

⚠️ **This cannot rely on token scoping.** `multi-repo.md` and `repair-bay.md` both claim the write
token is archie-platform-scoped and that non-default merges are human-only. Measured 2026-08-23
against the live API: `archie-platform` push+admin, `archie-code` push+**admin**, `kytran-system-operations`
push+**admin**; only `kytran-business-suite` returns 404. Per-repo approval must be enforced by the
**governance gate**, never by assumed token absence. Tracked as task #5981.

⚠️ **A merge is not a deploy.** Every product except the platform is image-baked, so landing a PR
changes nothing until a rebuild. Deployment stays a separate, explicitly-approved step; a window
never grants it.

## Build inventory

**Exists and works**: `build_loop` · `scope_guard.py` · Codex container runner, allowlist, telemetry,
MCP KB gateway, delegation worker · F.O.R.G.E. review · `merge_pr` choke point,
`_automerge_governance_ok`, `verdict_refusal` · `_AUTHORITY_CEILING` · `_pr_on_open_window` + three
maintenance tables + two services · archie-tui (`ctrl+b`, `ctrl+k`, `ctrl+e`, `/`) · the cockpit ·
`delegate_task → unified_tasks → DHQ` · ~2,593 live Repair Bay proposals.

**Exists but has never run**: `coo_window` (0 production callers, 0 windows ever created) · Codex
lane · `archie_engine` · Fleet Backlog Runner (default OFF).

**Genuinely new — five pieces:**

1. **The proposer** — classify each source item (what it touches → lane → cost → tier) and assemble a
   proposed manifest. *The actual missing brain; everything else is plumbing that exists.*
2. **Cockpit manifest surface** — review, trim, approve; approving opens the window.
3. **Wire `authority='coo_window'`** into the engine's merge path (~one call site).
4. **Widen `PLATFORM_SCOPE`** from allowlist to platform-minus-kernel.
5. **Per-repo scopes** for the other products.

Roughly 80% of the machinery exists. The missing 20% is a proposer, an approval screen, and wiring.

## Non-negotiable: a dormancy alarm

Every dormant component above was built, tested, merged — and then quietly stopped. Codex: 56 days.
The engine: a month. `coo_window`: never once. Nobody noticed, because **nothing reports that a lane
has gone quiet.**

Therefore: **a per-lane liveness signal is part of this design, not a follow-up.** Last-dispatch age
per lane, surfaced in the cockpit, alarming on staleness — the pattern `backup_posture_monitor`
already proves in this codebase (deterministic, no LLM in the alert path, alarms on a stale
last-*success*, and reports `unknown` rather than alarming when a lane has never run).

Building autonomy without a dormancy alarm is how you end up with three coders that all look armed
and none of which are running.

## Non-goals

- **No archie-tui/Codex engine merge.** Rejected in favour of the proven `build_loop`.
- **No Codex-on-local-models.** Unproven — a test on 2026-08-23 never issued an inference call
  (Codex's bwrap sandbox cannot start bare on this host). May be revisited via a bounded spike inside
  the container harness; nothing here depends on it.
- **No change to Claude CLI's lane.** It stays as-is.
- **No autonomous deployment.** Merging and deploying stay separate.
- **No widening of the agent/dispatch kernel** to any autonomous actor.

## Open questions

1. Does the proposer run on a schedule, or only when the owner opens the cockpit?
2. What is the manifest's granularity — one window per batch, per project, or per repo?
3. Should Lane 2's ceiling stay Tier 1 once Lane 3 is live, or should Codex become owner-merge-only?
4. Do the four watch repos also carry admin on the write token? (not probed — task #5981)
