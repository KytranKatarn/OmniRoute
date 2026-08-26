# Self-Repair Lifecycle Completion — Design (Approach B: Git Is the Apply Mechanism)

**Date:** 2026-08-26 · **Project:** #380 · **Status:** Approved direction (owner, 2026-08-26); Phases 1–2 planned
**Evidence base:** 8-agent lifecycle-map workflow `wf_1e81cfa3-e35` (2026-08-26), KB #296234, tasks #6044–#6046

---

## 1. Problem — measured, not assumed

The Consciousness Code Health → Repair Bay self-repair loop is severed at the **deploy** step, and every
metric downstream of deploy has been faithfully reporting it:

- `proposal_service.deploy_to_production` **never writes production code**. It takes a module backup and
  flips `status='deployed'` with `metadata.code_applied:false` / `apply_mode:'manual'` (the #5808 safety
  hold, thoroughly documented in-code at `proposal_service.py:1210-1260`). 381/403 deployed rows carry
  `code_applied=false`; 35/35 deploys in the last 7 days.
- Re-verification: **366 still_open vs 14 fixed** all-time. All 14 date to 2026-05-11/12 in the classes now
  excluded from auto fix-gen — the automated loop has **never** demonstrated a confirmed repair.
- Every safety net around deploy is dead code: post-deploy P.R.O.B.E. QA never fires (`prop_meta`
  NameError, `proposal_service.py:683` — the variable is never assigned; 0 QA runs with
  `triggered_by 'repair_bay_deploy%'` ever); `verify_fix_deployment` (audit_pipeline.py:1619) and
  `creed_gate_pre_apply` (audit_pipeline.py:221) have zero callers; `deploy_via_forge`
  (forge_pipeline.py:146) is unreachable; all 370 `improvement_deployments` rows are stuck `'deploying'`.
- The human Deploy button (`proposal_routes.py:229` → `deploy_to_production`) bypasses the sandbox gate
  entirely; the tiered path runs the gate (`model_dispatch_service.py:981-993`, 399 P.R.O.B.E. suite-79
  rehearsals prove it works) — and then **also** ends at the no-op `deploy_to_production`.
- Detection genuinely works (daily scans, nightly 52-module audits, standalones covered), but its
  change-detection half is off: snapshot `commit_hash` capture has been dead in the scheduler container
  since 2026-03-23 (`_get_commit_hash` lacks the `safe.directory` handling `hub_deploy_state.py` uses),
  killing `detect_changes_since_last_snapshot`, change-triggered audits, and `mark_stale_audits`.
- Throughput: 347 `ready_for_review` proposals (oldest 133 days); 30d production (186) outpaces 30d
  deploys (119).

**The lesson encoded in KB #296234:** a lifecycle stage that flips its own status without performing its
action poisons every downstream metric. Fix quality was unmeasurable because fixes were never applied.

## 2. Decision

**Git becomes the apply mechanism.** Approving a repair produces a **branch + PR**, never a production
file write. The merge — through the existing, governance-gated `merge_pr` choke point — is the apply.
`status='deployed'` comes to mean *merged and in the tree*, which is provable. The #5808 hold is thereby
honored permanently rather than worked around: `deploy_to_production`'s direct-write path stays dead.

Rejected alternatives:
- **A — resurrect direct apply.** The hub is volume-mounted; a direct write is live before any review.
  Duplicates the PR governance already built (merge gates, F.O.R.G.E. verdicts, tier ceilings).
- **C — honesty-only.** Fix the dead code and keep manual shipping. Ships no lifecycle. (Its fixes are
  Phase 1 here regardless.)

### Principles (binding for all phases)

1. **Gate on the artifact, never the status field** (ADR-014, already in-code at deploy_to_production).
   A stage may only flip a status it has proven: `deployed` requires a merged PR; `fixed` requires the
   re-audit to no longer find the issue.
2. **Guards live at choke points, never per caller** (decision #953 family). Both deploy paths terminate
   in ONE function; merge completion hooks into `sync_closed_prs`, which all three pollers share.
3. **Fail closed on ambiguity, leave rows alone on unreadable external state** (the `pr_is_open() is
   None` rule): a GitHub blip must never cancel or complete a proposal.
4. **Every new toggle/job is registered where it is surfaced** (`work_control_service` BACKLOGS) — an
   unsurfaced key is the "declared but never applied" trap, three prior incidents.
5. **No direct production writes, ever, on any repair path.** Rollback on the PR path is `git revert`;
   module backups remain for non-git surfaces.

## 3. Target architecture — the completed loop

```
Code Health scan/audit (daily, works today)
   └─> improvement_proposals (source='code_health_audit')
        └─> fix generation
             ├─ deterministic lane (mechanical F-codes; works today)
             └─ LLM lane via DHQ dispatcher (works today; Phase-3 successor: the archie-code engine)
                  └─> ready_for_review  (human approves in Repairs / Ship tab)
                       └─> ship_as_pr()                    ← NEW single terminal action, both paths
                            ├─ sandbox gate (P.R.O.B.E. on archie_staging) — now MANDATORY
                            └─ deploy_via_forge()          ← exists, currently uncalled
                                 └─> branch + PR + F.O.R.G.E. review    status='pr_open'  ← NEW status
                                      └─> human merge (existing merge_pr governance)
                                           └─> completion hook in sync_closed_prs        ← NEW
                                                ├─ status='deployed', code_applied:true
                                                ├─ improvement_deployments → completed
                                                └─ mark_stale_audits(module)
                                                     └─> hub_deploy_state_monitor        ← NEW observer
                                                          "merged fixes await checkout/restart"
                                                          → Telegram advisory + Ship-tab card
                                                               └─> human: git pull + restart
                                                                    └─> reverify (scheduled) → fixed ✓
```

Everything marked "exists" is verified working today; everything NEW is wiring, one migration, one
observer job, and UI honesty. `deploy_via_forge` (branch→apply diff→push→PR, forge_pipeline.py:146-276)
and `deploy_via_merge` (conflict check→gated merge→status completion, :313-410) already implement the
hard parts — they were written against an older column-based proposal shape and never called.

## 4. Repair Bay tab impact (Repairs · Diagnose · Test Bay · Ship)

All four tabs are in scope. Per the 2026-08-26 tab map:

| Tab | Today | After Phases 1–2 |
|---|---|---|
| **Repairs** (`#tab-proposals`) | Deploy-to-Production button → no-op deploy; no Archive UI caller; `code_applied` invisible | Deploy action becomes **Ship as PR** (sandbox-gated); proposal cards/detail show an honest apply badge (`code_applied` / PR link / merge state) and a **PR Open** filter chip; archive endpoint fixed (metadata-based) |
| **Diagnose** (`#tab-scan`) | Scans + issues render; the issues→proposals bridge (`/api/scan/issues-to-proposals`) is schema-broken AND has zero UI callers — a dead-end island | Bridge fixed (Phase 1); an **→ Proposals** button on the Issues sub-tab wires Diagnose into the loop (Phase 2). Issues remain the engine-autopull feed for Phase 3 |
| **Test Bay** (`#tab-sandbox`) | Proposal rehearsal exists server-side only (`apply_from_proposal`, per-module sandboxes — zero UI callers); tab's Run Tests buttons drive P.R.O.B.E.-on-staging and a pytest runner | The sandbox gate becomes **mandatory inside `ship_as_pr`** for every deploy path; a **Gate Runs** list on the Staging sub-tab surfaces rehearsal outcomes (`qa_test_runs` triggered_by `tiered_approval_gate_proposal_%` / `repair_bay_deploy:%`) |
| **Ship** (`#tab-deploy`) | Ready sub-tab's tiered deploy ends at the no-op; Deployment History reads `deployed` rows that mean nothing; Provenance covers image-baked products only | Ready sub-tab's approval callback terminates in `ship_as_pr`; Deployment History becomes truthful (deployed = merged); Provenance gains a **Hub Deploy State** card fed by the new observer; F.O.R.G.E. sub-tab lists the new self-heal PRs |

## 5. Phase 1 — Make the ledger honest

Scope: no behavior change to what ships; every status becomes true. Tasks #6044/#6045/#6046 plus:

1. **`prop_meta` NameError** (`run_proposal`): fetch `metadata` in the SELECT, assign `prop_meta`,
   post-deploy P.R.O.B.E. QA + perf gate can fire for the first time (#6044).
2. **Schema-mismatch trio** (#6045): `archive_proposal` → metadata-based archive (aligning with the
   8,964 rows archived by audit_pipeline's writers); `scan_routes` issues-to-proposals INSERT drops the
   nonexistent `file_path` column reference + fixes `proposed_by`; its `_has_open_proposal` dedup goes
   metadata-based (today it excepts on a missing column and **fails open**); `forge_pipeline`
   `mark_stale_audits` reads `metadata->>'file_path'`.
3. **`commit_hash` capture** (#6046): `_get_commit_hash` adopts the `git -C <root> -c
   safe.directory=<root>` invocation from `hub_deploy_state.py`; verified by the next nightly snapshot
   carrying a hash — this revives change-detection and `mark_stale_audits`.
4. **Scheduled re-verify**: a dedicated daily job (loop closure no longer rides only the audit-all tail),
   plus a dedup'd alert when the still_open count grows — `still_open` gets its first consumer.
5. **UI honesty**: `list_proposals` serialises `code_applied` + `deployed_at` (ISO, fixing the RFC-1123
   inconsistency); Repairs tab renders "backed up — NOT applied" vs "live" badges on deployed rows.

Explicitly NOT in Phase 1: touching `deploy_to_production`'s semantics (Phase 2 replaces its callers),
re-labelling historical rows (the badge makes them legible; a data migration is not worth the risk).

## 6. Phase 2 — The deploy that deploys

1. **Migration**: extend the `improvement_proposals_status_check` constraint with `'pr_open'`
   (14 statuses today; idempotent drop+add).
2. **Adapter**: `_proposal_fix_fields(proposal)` in forge_pipeline resolves `file_path` (column → then
   `metadata->>'file_path'`) and the diff (`code_diff` → `code_changes` → `suggested_fix`) so
   `deploy_via_forge` works with audit-pipeline proposals.
3. **`ship_as_pr(proposal_id, skip_gate=False)`** in proposal_service — the single terminal action:
   mandatory sandbox gate (promoted `sandbox_gate` from model_dispatch_service; late import to avoid the
   existing cycle), then `deploy_via_forge`; success → `status='pr_open'` + metadata
   `{pr_number, pr_url, branch, apply_mode:'forge_pr', code_applied:false}` + an
   `improvement_deployments` row (`deployment_type='forge_pr'`, status `'deploying'`). Both choke points
   route here: the Repairs Deploy endpoint (gate ON) and `deploy_approve_gate` (gate already ran →
   `skip_gate=True`).
4. **Merge completion**: `complete_merged_fix_proposals()` in forge_pipeline — scans `pr_open` proposals,
   asks GitHub per PR (unreadable → leave alone; merged → `deployed` + `code_applied:true` +
   `improvement_deployments` completed + `mark_stale_audits`; closed-unmerged → `fix_requested` with a
   note). Hooked into `pr_review_service.sync_closed_prs` (the three-caller choke point, beside
   `close_stale_pr_merge_approvals`). The existing `deploy_via_merge` UI path delegates to the same
   completion function.
5. **Deploy advisory** — the owner's "advise when to deploy": `hub_deploy_state_monitor` job (30-min,
   `deploy_drift_monitor` pattern, work-control-registered) reads `hub_deploy_state()`; on
   `needs_pull`/`needs_restart` with merged repair PRs pending, sends a **dedup'd** Telegram advisory
   (state-change keyed via `platform_settings deploy:advisory:last`) and feeds the Ship-tab Provenance
   card via the existing `GET /api/deploy/hub-state`. Advisory only — nothing restarts automatically.
6. **UI**: Repairs "PR Open" chip + PR link/merge state on detail; Ship Provenance hub-state card;
   Test Bay Gate Runs list; Diagnose "→ Proposals" button.
7. **Acceptance**: one real proposal driven end-to-end — scan → propose → fix → ship_as_pr → PR →
   F.O.R.G.E. review → merge → advisory fires → checkout/restart → scheduled reverify stamps `fixed`.
   **The first machine-verified `fixed` since 2026-05-12 is the definition of done.**

### Open decision folded into the plan (verified at execution)

The observer job runs in `archie_scheduler`; `hub_deploy_state()` needs git (solved — it carries
`safe.directory`) and a `docker inspect` of `archie_platform`. If the scheduler lacks the docker socket,
the job falls back to calling a new internal-key alias of `GET /api/deploy/hub-state` on the platform
(pattern: the existing `/api/internal/code-health/*` aliases at app.py:5402-5458). The plan verifies the
socket first and takes one branch.

## 7. Out of scope (follow-up specs)

- **Phase 3 — engine as the coder**: fleet placement of `qwen2.5-coder:7b` (#6041), autopull extended
  from `code_issues` to proposals (`connector.get_repair_proposals` has zero callers today),
  reviewer≠author via `prefer_agent='P.R.O.B.E.'` on engine-authored PRs (#6040), fix-quality
  measurement (#6042). Widening the drain's source filter (the ~930 invisible qa_pipeline/code_sentinel
  proposals) waits for this phase — more production before deploy works is backwards.
- **Phase 4 — per-project self-work toggle + full advisory surface**: `unified_projects.metadata.
  self_work_enabled`, enforcement in `fetch_pending_delegations` (which today does not even SELECT
  `project_id`), dynamic surfacing in `work_control_service.list_controls`, Autonomy-tab card (#6043).
- Re-labelling historical `deployed` rows; approvals-queue rows for deploy advisories (an approvals row
  implies an executable approve action — a later decision); the LLM lane's `find_not_located` problem
  (superseded by Phase 3's engine).

## 8. Testing strategy

- Every fix to a silent failure carries a test **proven to fail against the pre-fix code** via an
  `importlib` copy of the module (the `test_website_deploy_worker` pattern; never mutate the live file).
- `ship_as_pr` unit tests mock `deploy_via_forge`/gate boundaries; completion-hook tests pin the
  fail-safe (GitHub `None` → row untouched) and both terminal transitions.
- Status honesty is pinned by a test asserting `deployed ⇒ (code_applied is true ∧ pr merged)` for all
  rows created after Phase 2 ships.
- Live verification through the running process (`docker exec … python3 -c "import …"`), never grep
  (deploy-provenance rule) — and the Phase 2 acceptance drive (§6.7) is the gate for calling this done.

## 9. References

Workflow `wf_1e81cfa3-e35` journal (8 subsystem maps) · KB #296234 (deployed≠applied) · KB #282665/#282666
(fix-gen garbage classes) · tasks #6044–#6046 (Phase-1 defects), #6040–#6043 (Phase 3/4) · #5808 (the
safety hold this design makes permanent) · ADR-014 (gate on the artifact) · decision #953 (choke points)
