# Repair Bay Scope Filter — Archive Unfixable Audit Proposals — Design Spec

**Task:** #4940
**Date:** 2026-07-18 (rewritten after reading the live code — see §1)
**Area:** Self-healing repair pipeline (`services/audit_pipeline.py`)
**Governance:** C.R.E.E.D.-governed self-heal pipeline — change is scoped, reversible, adds no new auto-deploy authority.

---

## 1. Problem (corrected from first draft)

**First draft was wrong.** It assumed the dispatch path never resolves display-label file paths. Reading the code (`audit_pipeline.py:704–720, 860–880`) shows `dispatch_proposal_fix` **already** resolves them via an existing `_PLACEHOLDER_MAP` (`[APP_CORE]/`→`platform_v2/`, `[AI_BRIDGE]/`→`ai_bridge/`, every `standalone_*`/`website_*` → its real dir) and `_SKIP_PREFIXES` (`[dispatch_routing]/`).

**Accurate picture (verified against disk, proposal-level, 2026-07-18):** of the 1,224 undispatched code-health proposals, **1,188 already resolve** to a real on-disk file — they are **not blocked on resolution; they are queued behind the ~10/day drain** (`dispatch_attempted IS NULL` = never attempted, not failed). Only **36 are genuinely unfixable by the platform pipeline**:

| Prefix | Count | Why unfixable |
|---|---|---|
| `platform_v2/…` | 28 | file deleted/relocated (e.g. `tools/media_hub/*` consolidated to standalone, `tools/blueprint/*`, `tools/dev_hq/jobs.py`) |
| `standalone_what_the_fact/…` | 3 | no `_PLACEHOLDER_MAP` entry — WTF source lives on Citadel, not the hub |
| `[APP_CORE]/tools/media_hub/…` | 3 | retired media_hub under the platform tree |
| `[dispatch_routing]/…` | 2 | not files — routing labels |

When one of these 36 is eventually dispatched, it resolves → `isfile` fails → "source file not found" → the caller marks it `dispatch_attempted` → it drops out. So it self-eliminates, but only **after consuming one drain slot** (~36 slots ≈ 3–4 days of the ~10/day budget) and it sits in the queue as noise until then.

**This change is a modest cleanup, not an unlock.** It does not touch the real bottlenecks (throughput ~10/day = #4942; fix yield / `find_not_located`). It pre-archives the 36 so they never consume a drain slot, and it extracts the existing resolution into one shared helper so the sweep's notion of "fixable" is guaranteed identical to what dispatch actually does.

---

## 2. Goals / Non-goals

**Goals**
- Extract the resolution logic currently inlined in `dispatch_proposal_fix` into a single reusable helper (DRY) — one source of truth for "does this proposal's file resolve to a real on-disk file."
- One-time, idempotent sweep that archives the ~36 genuinely-unfixable undispatched proposals with a reversible reason, so the drain never spends a slot on them.

**Non-goals**
- Not raising drain throughput (#4942).
- Not touching fix-generation yield (`find_not_located`).
- Not changing `_PLACEHOLDER_MAP`/`_SKIP_PREFIXES` contents or dispatch behavior (the extract is behavior-preserving).
- Not deleting any proposal (archive only — reversible). No new auto-deploy authority.

---

## 3. Design

Two focused pieces, both in `services/audit_pipeline.py`.

### 3.1 `resolve_proposal_source(file_path) -> str | None`  (extract; behavior-preserving)
Lift the resolution currently inlined in `dispatch_proposal_fix` (lines ~860–877) into a module-level helper:

1. If `file_path` starts with any `_SKIP_PREFIXES` entry → return `None`.
2. Apply the first matching `_PLACEHOLDER_MAP` substitution.
3. `abs = /mnt/archie_brain/<file_path>`; if missing and it starts with `platform_v2/`, fall back to `/app/<stripped>` (the in-container path). *(Preserves the existing two-base lookup verbatim.)*
4. Return `abs` iff `os.path.isfile(abs)`, else `None`.

`dispatch_proposal_fix` is refactored to call it: on `None` it keeps its **current** behavior exactly (the `[dispatch_routing]` "synthetic placeholder" early return vs. the "source file not found" return are preserved by having the helper's caller branch the same way — see the plan). **No behavior change** — same inputs produce the same dispatch outcomes.

### 3.2 `archive_unfixable_audit_proposals(dry_run=False) -> dict`  (new)
Idempotent sweep over the undispatched code-health backlog:

```
SELECT id, metadata->>'file_path'
FROM improvement_proposals
WHERE metadata->>'source'='code_health_audit'
  AND status='approved'
  AND (metadata->>'dispatch_attempted') IS NULL
```

For each row, if `resolve_proposal_source(file_path) is None`:
- `UPDATE … SET status='archived', metadata = metadata || {archive_reason, archived_at, archived_by:'scope_filter_4940'}`
  - `archive_reason` ∈ `out_of_scope:standalone` (no map entry / off-platform), `source_missing:relocated` (resolved but file gone), `not_a_file:routing_label` (`_SKIP_PREFIXES`).
- `dry_run=True` counts without writing.

Returns `{scanned, archived, kept, by_reason:{…}}`. Idempotent: only touches `status='approved'`; a second run archives nothing (the 36 are now `archived`, excluded by the `WHERE`).

Run **once** this session via `docker exec archie_platform python3`.

---

## 4. Data / status semantics
- `status='archived'` already exists and is already excluded from the drain's candidate `SELECT` (`status IN ('proposed','approved')`). No migration.
- Reversible: `UPDATE improvement_proposals SET status='approved', metadata = metadata - 'archive_reason' - 'archived_at' - 'archived_by' WHERE metadata->>'archived_by'='scope_filter_4940';`

---

## 5. Testing (TDD) — `platform_v2/tests/`
1. `resolve_proposal_source`:
   - `[APP_CORE]/<real file>` → real abs path.
   - `[AI_BRIDGE]/<real file>` → real abs path.
   - `standalone_media_hub/<real file>` → real abs path (on-hub standalone resolves).
   - `standalone_what_the_fact/x` → `None` (no map entry).
   - `[dispatch_routing]/agents/…` → `None` (skip prefix).
   - `platform_v2/<deleted file>` → `None` (isfile invariant).
2. Behavior-preservation: a representative resolvable path returns the same abs path the old inline block produced (guard against a refactor regression).
3. `archive_unfixable_audit_proposals` against a synthetic proposal set (transaction-rolled-back or a temp fixture): resolvable stays `approved`; unresolvable → `archived` with the right `archive_reason`; **idempotent** second run is a no-op; `dry_run=True` writes nothing.

No test hits Ollama or the live drain. All assertions are pure path/DB-state.

---

## 6. Deploy & verification
- `services/*` volume-mounted → deploy = `docker compose restart archie_platform`.
- One-time sweep: `docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.audit_pipeline import archive_unfixable_audit_proposals as f; print(f())"` — expect ~36 archived.
- Verify: re-run the undispatched breakdown → the 36 are now `archived`; 1,188 still `approved`. Confirm `dispatch_proposal_fix` behavior unchanged on a resolvable proposal (spot check).
- Report honestly: this reclaims ~36 drain slots + de-noises the queue; it does **not** raise yield or throughput (the real levers, out of scope).

---

## 7. Rollback
- Revert the code (branch), restart the container.
- Un-archive with the single reversible `UPDATE` in §4 (the `archived_by='scope_filter_4940'` tag scopes it exactly).

---

## 8. Out of scope / follow-ups
- **#4942** drain throughput (the actual backlog-clear lever).
- `find_not_located` fix-generation yield.
- Optional: wire the sweep as a periodic guard at the tail of the repair pipeline job (file a follow-up) so a future off-platform module's findings can't re-accumulate.
