# Code Health — Static-Analysis Scanner Tier (Design Spec)

**Date:** 2026-07-11
**Status:** Approved design — ready for implementation plan
**Owner:** Kytran (A.R.C.H.I.E. platform)
**Slice:** 1 of a 4-part evolution (see Roadmap). This spec covers **Slice 1** only.

---

## 1. Motivation

A full session (2026-07-11) manually ran a toolchain of static analyzers over the
scheduler files and found **35 real, latent bugs** — every one guarded by
`try/except` so it had silently degraded (never crashed, never logged loudly) and
was invisible to normal operation. Fixed across 8 PRs (#2192–#2199).

The bugs, by class:

| Class | Tool that caught it | Count |
|---|---|---|
| Wrong root/submodule/symbol/kwarg/positional-arg (imports & calls) | custom AST interface-sweeps | 28 |
| Method/alias/scoped-name type errors | mypy `--check-untyped-defs` | 6 |
| `self.<missing_method>()` (no-member) | pylint `-E` | 1 |
| undefined names | pyflakes | 0 (clean) |
| lint hygiene | ruff | 0 (cleanup) |
| security | bandit | 0 (all false positives) |

**The problem:** the Consciousness → Code Health module already exists to
"scan, audit, and keep track of code health," with audit / re-audit buttons for
modules, standalones, and websites — but its scanner is **regex pattern-matching**
(`re.search`) plus orphan-file detection plus git-churn metrics. It runs **no
`ast` / `pyflakes` / `mypy` / `ruff` / `pylint` / `bandit`**. Regex would catch
**none** of the 35 bugs (wrong-submodule imports, `self.<missing>()`, wrong-kwarg,
arity, stale APIs are all beyond regex).

So Code Health has the right *shape* (scan → audit → propose → deploy → re-verify)
but is **blind** to the highest-value class of defect. This spec gives it real eyes.

## 2. Goal & Non-Goals

**Goal (Slice 1):** add a **static-analysis scanner tier** to Code Health that runs
the proven toolchain in the **faithful runtime**, gates findings through an
**auto-verify** trust layer, and feeds *confirmed* findings into the **existing**
Repair Bay pipeline — closing the scan → fix → re-scan loop **without a single new
plumbing table**.

**Non-goals (deferred to later slices):**
- Standalone / website runtimes (Slice 1b).
- Autonomous scheduling of the whole loop nightly on the fleet (Slice 2).
- Any change to the human deploy/merge gate (kept as-is — it matches the platform's
  branch-protection rules; F.O.R.G.E. autonomy stops at `fix_generated` today and
  stays there).
- Unifying the two existing finding stores (`improvement_proposals` vs
  `code_scans`/`code_issues`) — tracked separately.

## 3. Current State (grounded 2026-07-11 by reading the code)

**Consciousness → Code Health** (`platform_v2/tools/consciousness/code_health_routes.py`,
`platform_v2/services/code_metrics_service.py`):
- `POST /scan` → async `scan_codebase()` + `save_snapshot()`.
- `POST /audit` → `run_code_health_audit(module)` → per-module `_audit_one` →
  `audit_single_module` → `log_audit(dispatched_via="local_static_analysis")` →
  **auto-submits findings to Repair Bay via `process_audit_findings`**. Audit-all
  ends with a `reverify_deployed_findings()` pass.
- `POST /reverify`, `GET /orchestration`, `/current`, `/snapshots`, `/audit-log`,
  `/module-status`, `/severity-summary`, `/standalone-status`, `/website-status`,
  `/structural-audit`, `/audit/<id>/submit-repair`, `/submit-attention`, plus
  `/api/internal/code-health/*` aliases (build-engine loop-closer #4262).
- **How it "analyzes":** `code_metrics_service.py` uses `re.search` for
  `HARDCODED_SECRET`, `DIRECT_OLLAMA`/`DIRECT_CLOUD`, `BARE_EXCEPT` (`except\s*:`),
  `SQL_INJECTION_RISK` (`.execute(f"...")`), `image:latest`, `MISSING_INIT`; plus
  `_find_orphan_files()`, `_detect_retired_modules()`, and git-churn via
  `subprocess.run(["git", "log", "--numstat", ...])`. **No linters.**
- **Data model:** findings → `improvement_proposals` (`metadata.source=
  'code_health_audit'`, `metadata.module_name`, `metadata.reverified`); audits →
  `code_audit_log`; snapshots → `code_metrics_snapshots`; jobs → `bridge_jobs`.
- **Targets:** `STANDALONE_PRODUCTS` + `WEBSITE_PRODUCTS` enumerated in
  `code_metrics_service.py`, audited by `_audit_standalone_products()`.

**Repair Bay** (`platform_v2/tools/repair_bay/`, `platform_v2/services/audit_pipeline.py`):
- `process_audit_findings()` → `_create_audit_proposal()` (skips info-tier;
  `_TIER_CONFIG` red/yellow → priority/approval_tier) → `improvement_proposals`,
  deduped by `_has_open_proposal(file_path, issue_code)`.
- Parallel path `services/scan_pipeline.py` (Code Sentinel) → `code_scans`/
  `code_issues` (not unified with the above).
- **F.O.R.G.E.** (`repair_bay/services/forge_self_heal.py` + `forge_pipeline.py` +
  `pr_diff_analyzer.py`): `run_self_heal_cycle(proposal_id)` →
  `generate_fix_from_scan()` (Bridge `dispatch_json`) → writes `code_diff`, status
  `fix_generated`. `deploy_proposal()` → sandbox test → `deploy_via_forge()`
  (branch+PR) → `deploy_via_merge()` → `deployed`. Retry loops (test 3×, review 2×,
  regression), circuit breaker (`MAX_TOTAL_ATTEMPTS=5`, `escalate_to_human`).
- `reverify_deployed_findings(module)` in `services/audit_pipeline.py` re-audits
  deployed proposals and stamps `fixed` / `still_open` (regression surfaced).

**Loop today:** audit → proposal (auto) → F.O.R.G.E. fix-generate (auto) →
**deploy/merge (human-gated)** → reverify (confirm). **Scheduled work is scan-only:**
`department_hq/jobs.py` job #55 `daily_code_health_scan` (2:00 AM ET) does
`scan_codebase` + `save_snapshot` **only**; audit → propose → heal → reverify are
**manually / MCP-triggered**. Delegation via `department_coordinator.py`
`CAPABILITY_DEPARTMENT_MAP` + `audit_pipeline._ISSUE_CAPABILITY_MAP`
(`HARDCODED_SECRET`/`SQL_INJECTION_RISK` → V.I.G.I.L.; `code`/`code_review`/`debug`
→ F.O.R.G.E.; `module_audit`/`documentation` → C.O.D.E.X.; QA/regression → P.R.O.B.E.).

## 4. Design

**Principle: reuse the existing loop, add the missing eyes + a trust gate.**
Everything downstream of a *confirmed* finding already exists. We build only the
scanner and the gate.

### 4.1 Component A — Toolchain runner (`services/code_static_analyzer.py`)

Runs the suite that found the 35 bugs and emits **normalized findings**:

- **Tools:**
  - **AST interface-sweeps** (new, in-repo): wrong-root, wrong-submodule,
    wrong-symbol, wrong-kwarg, wrong-positional-arg. These are the highest-yield
    checks (28 of 35) and are largely deterministic.
  - **pyflakes** — undefined names.
  - **ruff** — F-code lint (`--select=F`).
  - **mypy** — `--check-untyped-defs --follow-imports=silent
    --explicit-package-bases --ignore-missing-imports`.
  - **pylint** — `-E --disable=import-error` (errors-only).
  - **bandit** — security (`--severity-level medium --confidence-level medium`).
- **Faithful runtime (accuracy key):** each tool runs **inside the target's real
  container** via `docker exec` with the correct `sys.path`
  (`MYPYPATH` = `<app_root>:<extra_roots>`, `--explicit-package-bases`), matching the
  deployed import environment. This is what made the session's results accurate.
  *Alternative considered and rejected:* host-run with replicated paths — it
  reproduced false positives (module-resolution issues like bare `db` imports).
- **Per-product runtime registry** (`code_scan_targets`, small config — table or
  Python dict): `target → {container | ssh_host, app_root, extra_sys_path,
  py_version}`. Slice 1 seeds only the **platform** target
  (`archie_scheduler`, roots `/app` + `/mnt/archie_brain/ai_bridge`, py3.11).
- **Tool env:** a pinned virtualenv baked into a small scanner image (or the
  scheduler image) holding mypy/pyflakes/ruff/pylint/bandit at fixed versions.
- **Output schema (normalized finding):**
  `{target, file, line, tool, code, severity, confidence, message, module,
    capability}` — one row per finding; `module`/`capability` resolved from the
  file path via the existing ownership map.

### 4.2 Component B — Auto-verify gate (`services/finding_gate.py`)

The trust layer that decides which findings become Repair Bay proposals. This is
the session's manual triage, encoded.

- **Deterministic allowlist → auto-CONFIRMED** (no agent call): AST-sweep results,
  pyflakes `F821` (undefined-name), pylint `E1101` (no-member) *when the class was
  fully resolved*, ruff F-codes. These are near-zero false-positive.
- **Judgment set → adversarial verify:** bandit, mypy `arg-type`/`attr-defined`,
  other pylint errors. Each dispatches a **"prove it is a real runtime bug"** prompt
  to the owning agent (F.O.R.G.E. / V.I.G.I.L. via `CAPABILITY_DEPARTMENT_MAP`,
  through the DHQ dispatcher). The verifier is instructed to *default to
  FALSE-POSITIVE unless it can name the concrete failure* — the same discipline that
  turned ~180 raw flags into 35 real bugs. Result: CONFIRMED / FALSE-POSITIVE.
- **Routing:**
  - CONFIRMED → existing `process_audit_findings()` (+ `_has_open_proposal` dedup)
    → Repair Bay proposal, tagged `metadata.source='code_health_static_scan'` and
    `metadata.tool`/`metadata.verified_by`.
  - FALSE-POSITIVE / unverified → **advisory** row in Code Health (new
    `metadata.advisory=true`, surfaced in the tab; **not** sent to Repair Bay).
- **Cost control:** the judgment set is small and per-finding; verification is a
  short single-shot dispatch (welfare-gated, cost-tracked like all DHQ work). The
  deterministic allowlist carries the bulk with zero LLM cost.

### 4.3 Component C — Issue codes + Deep-Scan entry point

- **New issue codes** added to `audit_pipeline._ISSUE_CAPABILITY_MAP`
  (severity + owning capability): `WRONG_ROOT_IMPORT`, `WRONG_SUBMODULE_IMPORT`,
  `MISSING_SYMBOL`, `MISSING_METHOD`, `WRONG_KWARG`, `ARITY_MISMATCH`, `TYPE_ERROR`,
  `SECURITY_STATIC` (bandit-confirmed). Imports/symbols/arity → F.O.R.G.E. (code);
  security → V.I.G.I.L.; type errors → F.O.R.G.E.
- **Deep-Scan action** on the Code Health tab + `POST /api/code-health/deep-scan`
  (`@login_required @admin_required`) → async `bridge_jobs` job (same pattern as
  `/scan`) → runner → gate → pipeline. Findings visible via the existing
  `/audit-log`, `/severity-summary`, `/module-status` surfaces (new codes flow
  through the existing rendering).

### 4.4 Data flow

```
Deep Scan (button / job)
  → code_static_analyzer (faithful runtime, per-product) → normalized findings
    → finding_gate
        ├─ deterministic allowlist → CONFIRMED
        └─ judgment set → adversarial-verify (owning agent) → CONFIRMED | FALSE-POS
    → CONFIRMED → process_audit_findings → improvement_proposals (Repair Bay)
        → forge_self_heal.run_self_heal_cycle → code_diff (fix_generated)
        → deploy_proposal (HUMAN-GATED, unchanged) → deployed
        → reverify_deployed_findings → fixed | still_open
    → FALSE-POS/unverified → Code Health advisory (not sent to Repair Bay)
```

The loop closes through existing components; the two new services are the only
additions.

## 5. Reuse vs Build

**Reuse (unchanged):** `process_audit_findings`, `_create_audit_proposal`,
`_has_open_proposal`, `reverify_deployed_findings`, `forge_self_heal`,
`forge_pipeline`, `pr_diff_analyzer`, `CAPABILITY_DEPARTMENT_MAP`, `bridge_jobs`
async pattern, the Code Health tab rendering.

**Build:** `services/code_static_analyzer.py` (runner + per-product runtime
registry), `services/finding_gate.py` (auto-verify gate), the AST interface-sweep
checks as a reusable in-repo module, new issue codes in `_ISSUE_CAPABILITY_MAP`,
`POST /api/code-health/deep-scan` endpoint + Deep-Scan button, a pinned scanner
virtualenv/image.

## 6. Interfaces

- **`code_static_analyzer.run(target) -> list[Finding]`** — Finding is the
  normalized dict in §4.1.
- **`finding_gate.gate(findings) -> {confirmed: [...], advisory: [...]}`** — pure
  routing + verification; `confirmed` are handed to `process_audit_findings`.
- **`POST /api/code-health/deep-scan {target?}`** → `{job_id}`; poll existing
  `/job-status/<id>`.
- **Runtime registry** row: `{target, container|ssh_host, app_root,
  extra_sys_path[], py_version, enabled}`.

## 7. Error Handling

- A tool crash or timeout on one target → that tool's findings are skipped and
  logged (never fails the whole scan); the scan reports partial coverage
  explicitly (no silent truncation).
- A verify dispatch that errors/times out → the finding stays **advisory**
  (fail-closed toward *not* creating a proposal), never auto-CONFIRMED.
- Faithful-runtime unavailable (container down / SSH fail) → target skipped +
  surfaced as a scan warning; never fall back to a wrong-path host run (that
  produces the false positives this design exists to avoid).
- All existing dedup (`_has_open_proposal`) prevents re-proposing an already-open
  finding on re-scan.

## 8. Testing

- **AST-sweep unit tests:** fixtures for each class (wrong-root/submodule/symbol/
  kwarg/positional) with known-good and known-bad cases + sensitivity checks
  (a real symbol resolves, a fake one flags) — the exact checks used this session.
- **Gate tests:** deterministic finding → auto-CONFIRMED without a dispatch; a
  judgment finding with a stubbed verifier returning FALSE-POSITIVE → advisory,
  not a proposal.
- **Integration:** a seeded known bug on the platform target → deep-scan →
  CONFIRMED → `improvement_proposals` row created with the right capability/
  severity; re-scan after fix → dedup + `reverify` marks fixed.
- **Regression guard:** P.R.O.B.E. suite asserting a curated set of the 35
  session bugs would be caught by the runner (reintroduce-in-fixture).

## 9. Roadmap (this spec = Slice 1 only)

1. **Slice 1 (this spec):** scanner tier + auto-verify gate + **platform runtime**,
   feeding the existing pipeline. Deep-Scan is button/MCP-triggered.
2. **Slice 1b:** standalone + website runtimes — extend the per-product registry
   (each standalone's container; boston-2 via SSH), reusing the runner/gate.
3. **Slice 2:** autonomy — schedule the whole loop on the fleet (a nightly
   `code_health_deep_scan` fleet job that runs scan → gate → propose → F.O.R.G.E.
   heal → reverify), replacing the manual trigger. Deploy stays human-gated.
4. **Slice 3 (optional):** unify the two finding stores; consider a
   low-risk-auto-deploy lane for deterministic lint/auto-fixes (ruff `--fix`)
   behind an explicit policy toggle.

## 10. Decisions Made (during brainstorming)

- **First slice = static-analysis scanner tier** (highest ROI, self-contained,
  reuses existing plumbing). ✔
- **Scope = full-coverage goal, phased** (platform first; standalones/websites in
  1b) — derived from the owner's "modules and standalones as well as websites." ✔
- **Gating = auto-verify gate** (deterministic auto-pass; judgment set
  adversarial-verified; unverified stays advisory). ✔
- **Faithful runtime = in-container `docker exec` with correct sys.path**;
  host-run rejected. ✔
- **Human deploy gate unchanged** — matches branch-protection rules. ✔

## 11a. Expanded scope confirmed 2026-07-11 (owner)

After the spec review, the owner set two hard requirements that promote deferred
slices into first-class deliverables and add a companion track. The implementation
plans live in `docs/superpowers/plans/`:

1. **Track A — autonomy is now in scope (was Slice 2).** The scan→fix→re-scan loop
   must run **autonomously and route every fix through Department HQ** — the DHQ
   dispatcher, orchestration engine, welfare gating, and agent selection — not a
   bypass path. Grounding confirms this already exists at the seams
   (`audit_pipeline.dispatch_proposal_fix` → `get_dispatcher().request_work`,
   `forge_self_heal.generate_fix_from_scan` → `dispatch_json(capability="code_analysis")`).
   Plan: `2026-07-11-code-health-autonomous-healing.md`.

2. **Track B — A.R.C.H.I.E. as a full CLI (companion project).** Complete
   `archie.kytranempowerment.com` (the `archie_comms` service) + `archie-tui` +
   the Claude-collaboration hooks so A.R.C.H.I.E. is operable as a complete command
   line — like a Claude Code session but driven by the real agent fleet + node/mesh
   system. Plan: `2026-07-11-archie-cli-collaboration.md`.

**Stale-memory correction:** the `archie_engine` (project #380 Building Machine) is
**already rebuilt and running healthy** (verified 2026-07-11 against the live
container; the "NOT live until rebuild + ARCHIE_GITHUB_TOKEN" note was resolved
2026-06-20). Live source: `/mnt/standalone/archie-code/` (`archie_engine/` Python
ws:9090 + `archie-tui/` Go/Bubble Tea). Its `build_loop.py` already does
coordinate→build→test→PR via `dhq_complete(capability="code", prefer_agent="F.O.R.G.E.")`
and **never merges** — which is the bridge that lets Track A's confirmed findings
flow into Track B's builder while preserving the human merge gate.

**Track convergence:** Code Health confirmed findings → `improvement_proposals`
→ the engine's `pull_repair_work` → `build_loop` (DHQ F.O.R.G.E. fix + P.R.O.B.E.
test) → PR → **human merge** → `reverify_deployed_findings`. One loop, two tracks.

## 11. Open Questions (for the implementation plan)

- Scanner tool env: bake linters into the `archie_scheduler` image vs a dedicated
  `archie_scanner` sidecar image? (Leaning sidecar to keep the scheduler lean; to
  be decided in the plan.)
- Runtime registry as a DB table (`code_scan_targets`) vs a Python config dict for
  Slice 1 (only one target) — likely dict for Slice 1, table when 1b adds many.
- Exact severity mapping of each new issue code to the existing `_TIER_CONFIG`
  red/yellow tiers.
