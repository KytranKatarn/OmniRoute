# DS9 Criterion 4 — `contractor` → `engineer` rename: scoping document

**Status:** scoping only. No rename is attempted by this document.
**Criterion 4 asks** for *"a written migration for the 809 Python occurrences, 4 tables, 2 views and 3 UI files, with an explicit exclusion list, a stated order, and a rollback. Tables and views renamed via migration, not by editing in place."*
**This document is that written migration.** Nothing here is applied.

Every count below was re-measured on 2026-10-06 against the live tree, because the spec's numbers
were taken on 2026-09-30 and the platform has moved since.

---

## 1. Measured scope (today, not the spec's)

| Surface | Spec said | Actually now |
|---|---|---|
| `contractor` occurrences in `.py` | 809 | **1134** |
| Python files containing it | 23 | **94** |
| DB tables named `contractor*` | 4 | **7** |
| DB views named `contractor*` | 2 | **2** (unchanged) |
| **DB columns containing `contractor`** | *not mentioned* | **10 across 4 objects** |
| **Public routes containing `contractor`** | *not mentioned* | **7 across 2 unrelated domains** |

By area: `platform_v2` 757, `ai_bridge` 273, `kytran-business-suite` 42, `archie_engine_staging` 37,
`what-the-fact` 13, `scripts` 6, `repos` 3, `website` 2, `archie-comms` 1.

Two facts below mean the spec's scope was materially incomplete. A rename planned from the spec's
table alone would leave columns and public URLs inconsistent, and would corrupt a second domain.

---

## 2. The word `contractor` carries two unrelated meanings here

This is the whole difficulty, and the spec names only half of it.

### Sense A — external LLM providers (DS9's usage)

The "fleet of contractors" DS9 meant. Tables, the Contractors tab, dispatch, health probing.

### Sense B — construction industry (a different product)

`kytran-business-suite/plugins/kbs_industry_construction/` — a KBS industry plugin with
`construction_projects`, `construction_rfis`, `construction_change_orders`, `/api/subcontractors`.
Real construction subcontractors. Nothing to do with DS9.

Because `subcontractor` **contains** `contractor` as a substring, a naive find-and-replace
silently rewrites Sense B into `subengineer` / `construction_subengineers`. The spec warns about
`construction_subcontractors` specifically; the same trap applies to 30 other identifiers.

### And the target word is not free

`archie_engine_staging/` is an existing subsystem, and **147 files already contain `engineer`
(657 occurrences)**. DS9 chose a word the codebase already uses for other things. No DB column
contains `engineer` today, so the *schema* is collision-free — but prose and identifiers are not.

---

## 3. Exclusion list (must be built before any rename, per the spec)

**Hard excludes — Sense B, entire plugin:**

- `kytran-business-suite/plugins/kbs_industry_construction/**`
- every `*subcontractor*` / `subcontractor*` / `Subcontractor*` identifier anywhere, including
  `subcontractors`, `subcontractor`, `construction_subcontractors`, `Subcontractors`,
  `TestSubcontractors`, `update_subcontractor`, `subcontractor_management`, and the test names
  `test_add_subcontractor`, `test_list_subcontractors`, `test_update_subcontractor`,
  `test_migration_does_not_touch_construction_subcontractors`

**That last test already exists** — a previous session started guarding this trap. Any rename must
leave it green and un-renamed.

**Also exclude:**

- `archie_engine_staging/**` — "engine" subsystem, not the rename target
- `contractor_providers_backup_pre486` — a deliberate **DB table** created by DS9 PR 1 holding the
  pre-migration snapshot of all 30 contractors. Renaming it destroys the rollback path for that
  migration, and nothing in a text search would catch it because it is a table, not a file.
- the 657 pre-existing `engineer` occurrences — they are not ours to move

---

## 4. The five surfaces, and which are safe to touch

| # | Surface | Count | Renamable? | Notes |
|---|---|---|---|---|
| 1 | **Public route URLs** | 7 | **Decision required** | AGENTS.md: *"Preserve public function names, route URLs, and helpers other code depends on."* |
| 2 | DB tables | 7 | Yes, via migration | 3 of 6 are empty (0 rows) |
| 3 | DB views | 2 | Yes, via migration | must be recreated, not renamed — bodies embed old names |
| 4 | DB columns | 10 | Yes, via migration | on tables/views *outside* the contractor set |
| 5 | Python/JS identifiers | 1134 | Yes, mechanically | after exclusions |

### 4a. Surface 1 — the routes, and why they need your decision

| Route | Sense |
|---|---|
| `/api/contractor-providers` | **A** (DS9) |
| `/api/contractors/omniroute-quota` | **A** |
| `/api/contractors/definitions` | **B** (construction) |
| `/api/contractors/providers` | **B** |
| `/api/contractors/providers/<provider>/toggle` | **B** |
| `/api/subcontractors` | **B** |
| `/api/subcontractors/<int:sub_id>` | **B** |

Sense-A routes are called from `department-hq.js`:
`/tools/department-hq/api/contractor-providers` and
`/tools/department-hq/api/contractors/omniroute-quota`.

Note the near-collision: `/api/contractor-providers` (A) and `/api/contractors/providers` (B)
differ by one character and are easy to confuse during a bulk edit.

**Recommendation: leave all 7 route URLs unchanged.** They are public, they are consumed by JS,
and renaming them buys no user-visible benefit — the tab is reached by navigation, not by typing
a URL. The DS9 rebrand is a *label* change; the URLs are plumbing. This also keeps the rename out
of the "preserve public route URLs" rule entirely.

### 4b. Surface 2 — tables

| Table | Rows | Renaming notes |
|---|---|---|
| `contractor_providers` | 23 | referenced by views, by all dispatch code |
| `contractor_health` | 597 | no FK to it; written by the health service |
| `contractor_switch_audit` | 2 | written by the toggle route |
| `contractor_approval_requests` | **0** | has an inbound FK: `task_execution_log.approval_id` |
| `contractor_budget_history` | **0** | — |
| `contractor_consultations` | **0** | — |
| `contractor_providers_backup_pre486` | 30 | **exclude** — it is the pre-#3640 snapshot, i.e. the rollback for DS9 PR 1 |

`ALTER TABLE ... RENAME TO` carries FK constraints over by OID, so `task_execution_log` needs no
re-pointing — but the rename must be verified, not assumed.

### 4c. Surface 4 — the columns nobody scoped

These are on objects that are *not* named `contractor*`, so table-only planning misses them and
leaves the schema internally inconsistent:

- `improvement_proposals.contractor_agent_id`, `.contractor_proposal`, `.escalated_to_contractor`
- `v_escalation_analysis.contractor_success_rate`
- `v_module_usage_stats.contractor_tasks`
- `v_contractor_approval_queue.contractor_model`, `.contractor_provider`
- `v_internal_agents.contractor_budget_monthly`, `.contractor_usage_this_month`

---

## 5. Proposed order

Reversible-first, and each step independently verifiable.

1. **Guard first.** `platform_v2/tests/test_contractor_dispatchability_migration.py` already carries
   `test_migration_does_not_touch_construction_subcontractors` (line ~320, and its 15-test suite
   passes today). Extend it to assert the full §3 exclusion list survives, not just the one
   identifier it names. Ship this alone — it is the tripwire for every later step, and it is the
   one piece of this criterion that is unambiguously useful regardless of the decisions in §7.
2. **Empty tables** (`contractor_budget_history`, `contractor_consultations`,
   `contractor_approval_requests`). Zero rows, zero dependents except one FK. Cheapest proof the
   mechanism works.
3. **`contractor_switch_audit`** (2 rows).
4. **`contractor_health`** (597 rows) — high row count, no FKs, verify the probe still writes.
5. **`contractor_providers`** last — everything depends on it. Verify the Contractors tab renders,
   the probe runs, and dispatch still resolves a provider.
6. **Views** — drop and recreate `v_contractor_approval_queue` and `v_contractor_spending`, since a
   view body embeds the old names and `RENAME` would leave it referencing a name that no longer exists.
7. **Columns** — the 10 above.
8. **Code identifiers**, mechanical, exclusions applied. Routes stay (§4a).
9. **Templates / UI strings** last, so they describe a schema that is already correct.

Steps 2–7 belong in **one** migration file each, numbered, `IF EXISTS`-guarded and idempotent.
Step 8 is a separate PR — per the spec's own sequencing, *"the rename should not ride with a
routing fix"*, and by the same reasoning it should not ride with a schema migration either.

---

## 6. Rollback

- **Schema (steps 2–7):** each migration is `ALTER ... RENAME` only, so rollback is the inverse
  `RENAME` with no data movement. No table is dropped and no row is rewritten at any step.
  Views are the exception: keep each pre-recreate definition in a `docs/` snapshot so they can be
  restored verbatim.
- **Code (step 8):** a single revert commit. This is the only irreversible-by-migration part, which
  is why it is its own PR with nothing else in it.
- **Pre-flight:** `pg_dump -t <each table> -t <each view>` before step 2, stored outside the repo.
- **Verification after every step:** `SELECT count(*)` on each renamed object must equal its
  pre-rename count, and `/health` must return 200.

---

## 7. Decisions required before any of this is attempted

1. **Route URLs — change or keep?** (§4a recommends **keep all 7**.)
2. **Is `engineer` still the right word?** 147 files already use it and `archie_engine_staging/`
   exists. Confirming this is cheap now and expensive after 1134 edits.
3. **Sense-A DB objects: rename or not?** The user-visible rebrand is the tab and the labels. If the
   schema is internal plumbing, renaming it is cost with no user benefit — the same argument as the
   routes, applied to tables.
4. **Does `contractor_providers_backup_pre486` stay?** It is the rollback for DS9 PR 1.

---

## Provenance

All counts, FKs, view definitions, row counts and column lists in this document were queried from
the live hub on 2026-10-06. Nothing was modified; this was read-only. The layout bug found alongside
it (clipped action buttons at ≤800px) shipped separately as PR #3679.
