# OmniRoute — DS9/LCARS Branded Routing & Contractor → Engineer Rebrand

> **Status:** spec for scoping. Nothing here is implemented yet.
> **Date:** 2026-09-30
> **Dev HQ:** project *OmniRoute — DS9/LCARS Branded Routing & Contractor→Engineer Rebrand* (to be created; `create_project` is not exposed to the opencode lane)
> **Source of truth for the existing implementation:** `docs/superpowers/plans/2026-09-09-phase3-omniroute-contractor.md` (1,652 lines, marked *Executed 2026-09-09*)

## Why this document exists

The Phase 3 OmniRoute plan was executed on 2026-09-09 and the DS9 governed-routing
work shipped, but **the knowledge base held zero entries for `omniroute`, DS9, or
LCARS**. Two sessions have now reported the plan as "lost". It was never lost — it
was undiscoverable. This spec is the durable pointer, and it is paired with KB
entries so the next session finds it by search rather than by archaeology.

## What already exists (do not rebuild)

| Artifact | State |
|---|---|
| `docs/superpowers/plans/2026-09-09-phase3-omniroute-contractor.md` | Executed 2026-09-09. Source of truth. |
| 6 sibling omniroute plans/specs (09-09, 09-18, 09-19, 09-22) | Present in `docs/superpowers/` |
| `#3439` quota-aware DS9 governed routing (Phase 2+3) | **In `main`** (`dc108d4eb`) |
| `#3395` design spec, OmniRoute quota awareness (DS9 phase 2) | **In `main`** (`ae202ff1c`) |
| `fd13ebe43`, `e911e8f9d`, `10b0a6208` | Earlier DS9 drafts, **not** in `main`. Superseded — keep or delete deliberately, do not treat as pending work. |
| LCARS theme assets | `kytran-server-manager/themes/lcars.json`, `kytran-business-suite/shared/theme/lcars.css` |

## Verified state (2026-09-30, measured — not inferred)

```
container      diegosouzapw/omniroute:3.8.50   Up 11 days (healthy)
publishes      192.168.1.200:20128 -> 20128/tcp
reachable      http://192.168.1.200:20128/v1/models   -> HTTP 200, 534 models
in-network     http://omniroute:20128/v1/models       -> HTTP 401 without key, 200 with
OMNIROUTE_API_KEY  root .env == platform_v2/.env      (sha256[:12] 24945baa01b6)
```

### The live defect

```
opencode.json  omniroute baseURL = http://127.0.0.1:20128/v1  ->  HTTP 000, nothing bound
```

The container publishes to `192.168.1.200:20128`. **No process listens on
`127.0.0.1:20128`.** All six `omniroute/*` models configured in
`~/.config/opencode/opencode.json` point at a dead address and cannot serve a call.
This is the most likely single cause of OmniRoute "having issues to get working".

### Correction worth recording

An earlier check in this session reported "OmniRoute's gateway is down" from a
`curl` to `127.0.0.1:20128` returning HTTP 000. **That was wrong** — the gateway is
healthy. The probe used an address the gateway does not bind. The lesson is the
standing one: assert what you need to know, not what you expect.

## Scope

### A. Fix the routing address and prove the free tier

Seven model ids are configured in `opencode.json`. Only two are explicitly free:

| Id | Marked free |
|---|---|
| `auto/coding:free` | yes |
| `auto/best-free` | yes |
| `auto/coding` | **no** |
| `auto/coding:reliable` | **no** |
| `auto/coding:fast` | **no** |
| `auto/best-coding` | **no** |
| `auto/reasoning` | **no** |

The gateway also serves `auto/pro-*` **paid** tiers; none are configured here, which
is correct and must stay true.

An attempt to settle free-vs-paid by probing `/v1/chat/completions` returned HTTP
`000` (timeout) for four ids and `502` for one inside a 10 s budget. **That question
is unanswered.** It matters because the executed plan's constraint is free-only until
V.I.G.L. clears, and states *"every prompt sent is treated as public."*

### B. Key hygiene

Root `.env` is the source and `platform_v2/.env` mirrors it — that rule holds today
(verified above). But `OMNIROUTE_API_KEY` exists as a **third plaintext copy** in
`~/.config/opencode/opencode.json`. Bring it under the existing mirror rule rather
than adding a fourth convention.

The key was also printed once into a session transcript during this work. Treat it as
needing rotation.

### C. Contractor → Engineer, and other DS9/LCARS titles

The rename is **migration-scale, not cosmetic**:

| Surface | Count |
|---|---|
| `contractor` occurrences in Python | **809** |
| Files referencing `contractor_providers` | 23 |
| DB tables | `contractor_providers`, `contractor_approval_requests`, `contractor_budget_history`, `contractor_consultations` |
| DB views | `v_contractor_approval_queue`, `v_contractor_spending` |
| Templates | 2 (`platform_v2/templates/`) |
| JS | 1 (`platform_v2/static/`) |

#### Explicit exclusion — the trap

`construction_subcontractors` is a **different domain** (construction). A naive
find-and-replace across `contractor` corrupts it, along with any other
`*subcontractor*` or construction-domain identifier. Build the exclusion list before
the rename, not after.

#### Theme reuse, not invention

The DS9/LCARS layer should build on assets that already exist:
`kytran-server-manager/themes/lcars.json`, `kytran-business-suite/shared/theme/lcars.css`,
`archie-comms/static/css/lcars-header.css`. Do not start a parallel theme system.

## Acceptance criteria

1. **Routing works.** `opencode.json`'s omniroute `baseURL` resolves to a listening
   endpoint, and at least one configured model completes a real
   `/v1/chat/completions` call end to end.
2. **Free tier proven.** Each of the five unmarked ids is demonstrated **free or
   paid** by a real request, naming the upstream provider. Any id resolving to paid
   is removed or gated until V.I.G.L. clears, per the plan's free-only constraint.
   "It was probably fine" does not satisfy this.
3. **One key, one rule.** `OMNIROUTE_API_KEY` is out of plaintext in
   `opencode.json` and sourced through the root `.env` → `platform_v2/.env` mirror
   rule already in force. No third convention.
4. **Rename scoped before it is attempted.** A written migration for the 809 Python
   occurrences, 4 tables, 2 views and 3 UI files, with an explicit exclusion list
   (starting with `construction_subcontractors`), a stated order, and a rollback.
   Tables and views are renamed via migration, not by editing in place.
5. **Branding layer specified against existing assets.** The DS9/LCARS design names
   the specific `lcars.json` / `lcars.css` tokens it reuses rather than introducing
   new ones.
6. **Knowledge captured.** KB entries exist for OmniRoute and DS9 so the next session
   finds this by search. This is the criterion that has failed twice.

## Suggested sequencing

1. Criterion 1 — one line, unblocks every configured model.
2. Criterion 2 — before anything sends a real prompt.
3. Criterion 3 — independent, small.
4. Criteria 4–5 — separate PRs; the rename should not ride with a routing fix.
5. Criterion 6 — as each piece lands, not at the end.

## Related hazards on this repo

- **Env changes need `docker compose up -d --no-deps <svc>`, never `restart`.**
  `restart` does not re-read `env_file`, so a new value silently does not take and the
  caller 403s or 401s. This bit the `INTERNAL_API_KEY_CODER_LANES` rotation earlier
  the same way, and the executed Phase 3 plan records the same rule independently.
- **Keep the checkout on `main` before any `docker compose up`.** The live platform
  bind-mounts the working tree, so a container built from a feature branch serves
  that branch. Recorded in the Phase 3 plan's constraints.
- **Never pre-format with host Black.** The pre-commit hook pins Black 24.4.2; a
  newer host Black disagrees on untouched lines. Let the pinned hook decide and
  re-stage when it reformats.
