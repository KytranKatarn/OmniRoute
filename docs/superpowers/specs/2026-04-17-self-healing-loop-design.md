# Self-Healing Loop — Design Spec

**Date:** 2026-04-17
**Status:** Draft (awaiting user review)
**Owner:** A.R.C.H.I.E. + Kytran
**Related tasks:** #2069 (adjacent build)
**Related audits:** KB 256838 (Repair Bay), 256840 (Consciousness), 256843/256844 (DHQ), 256845 (OAuth/SSO)

---

## 1. Goal

Make the end-to-end self-healing pipeline work reliably and autonomously, with A.R.C.H.I.E. as decision engine on the tech/agent side and only reaching the user for a narrow set of human/business/irreversible gates.

**Pipeline:**

```
Consciousness Code Health → Repair Bay proposal + sandbox →
  (safe-category)  → DHQ agent authors the fix → manual deploy queue
  (everything else) → A.R.C.H.I.E. Decision Service →
      approved/denied/held autonomously
      OR escalated to user via unified Telegram (ARCHIE voice)
```

Deploy stays manual. The loop runs "up to ready-to-ship" only.

---

## 2a. Known deviations from the spec's original assumptions (discovered during Phase 0 Task 2, 2026-04-17)

- The table is named **`code_audit_log`**, not `code_health_audits`. Second table `code_metrics_snapshots` holds trend data.
- **Severity is not a column.** It is reconstructed on every read by parsing `notes` (free text) against `SEVERITY_MAP` in `platform_v2/services/code_metrics_service.py`. This is a real fragility — Phase 1 must either add a severity column via migration or centralize the parser.
- **Two handlers compute severity differently** (`tools/consciousness/code_health_routes.py:254` vs `:430`). Same row yields different verdicts depending on which endpoint you hit. Phase 1 gap.
- Stale comments in `ai_bridge/agent_loop.py:915-937` reference `dev_hq/` which does not exist. Real location is `tools/department_hq/jobs.py`.
- Scan triggers: `daily_code_health_scan` at 02:00 UTC + `daily_code_health_digest` at 08:00 UTC + per-module loop (`tools/department_hq/jobs.py:103/160/238/642/651`), plus on-demand `POST /api/code-health/scan`.

These are updates to the mental model only — no change to phase ordering.

## 2b. Two Entry Points — Scan Leg + PR Leg (added 2026-04-17)

The pipeline has **two entry points that converge at the sandbox stage**:

1. **Scan Leg** (covered by Section 3 diagram below): Code Health scans → findings → `improvement_proposals` → sandbox → decision service → deploy.
2. **PR Leg** (Project #268, tasks #1799–#1803): GitHub PR lands → F.O.R.G.E. reviews diff → same sandbox → same decision service → auto-merge or escalate.

Both legs share every downstream stage: sandbox mechanics, pre-deploy gate, A+D+B authority model, ARCHIE Decision Service, Telegram escalation, and manual deploy. Only the **entry mechanism** differs.

This unification matters because:
- Repair Bay becomes the single admin surface for *every* code-change-review flow, whether it originated from a scan or from someone opening a pull request.
- F.O.R.G.E. agent (Full-cycle Optimization & Regenerative GitHub Engine) is the counterpart to the internal agents that author scan-leg fixes — same Bridge dispatch, same decision authority.
- The loop truly closes: agent-authored fixes (scan leg) create PRs (PR leg) that F.O.R.G.E. reviews, and safe-category reviews auto-merge without user touch.

See Section 6a for PR Leg phases and Section 8a for the unified data model.

## 2c. Code Health Reports → Repair Bay (added 2026-04-17)

Consciousness Code Health currently owns report generation:
- `daily_code_health_scan` at 02:00 UTC (full codebase scan)
- `daily_code_health_digest` at 08:00 UTC (rollup + summary)
- Per-module audit loop (`tools/department_hq/jobs.py:103/160/238/642/651`)
- On-demand `POST /api/code-health/scan`
- Consciousness module UI has a "report option" surface that today renders reports inside Consciousness.

**These reports should feed into Repair Bay** as the centralized admin mission-control:

1. **Actionable items in a report** → auto-become (or get linked to) `improvement_proposals` visible in Repair Bay's Repairs tab.
2. **The report document itself** → becomes a first-class artifact in a new Repair Bay "Reports" tab — so you never wonder "did the 08:00 digest run? Is anything actionable?" You see both in one place.
3. **Report status** (scanned/acknowledged/acted-on) flows through the same state machine as proposals.
4. **No duplicate display** — the Consciousness Code Health surface becomes the *producer* (scans + generates reports), and Repair Bay becomes the *consumer/review surface* (Diagnose + Reports + Repairs + PRs + Test Bay + Ship + Pushes).

This closes a seam where reports today stop at Consciousness's UI. Once integrated, Repair Bay is the single place an admin looks for all code-change-review work:

| Tab | Source | Status |
|-----|--------|--------|
| Diagnose | Scan runs + findings | exists |
| **Reports** | Code Health digests + scheduled reports | **NEW (#1985 adjacent — API/docs consolidation rhymes)** |
| Repairs | `improvement_proposals` | exists |
| **PRs** | `pr_reviews` (Project #268 Phase 3) | **NEW (#1801)** |
| Test Bay | Sandbox runs | exists |
| Ship | Manual deploy queue | exists |
| Pushes | Held branch inventory | exists |

## 2. Guiding Principles

1. **Evaluate before building.** Much of this is already wired. Phase 0 traces a real finding through the real code to identify genuine gaps vs audit uncertainty.
2. **A.R.C.H.I.E. is COO with decision authority**, not a router. She approves/denies/holds on her own authority for most tech/agent decisions.
3. **Only ARCHIE reaches the user.** Telegram sends as "A.R.C.H.I.E.", `source_agent` is logged but invisible to user. User-gated categories only.
4. **Manual deploy always.** No part of this makes irreversible production changes.
5. **Fail closed.** Sandbox failure, pre-deploy gate failure, or ARCHIE-unreachable timeout → deny/hold, never auto-apply.
6. **Traceable.** Every action gets a `pipeline_run_id` threaded through all tables + logs for end-to-end inspection.

---

## 3. Architecture (End State)

```
  ═══════════════════════════ SCAN LEG ═══════════════════════════
  ┌─────────────────────────────────┐
  │ ① Consciousness · Code Health   │   scans → code_audit_log
  │     + reports (02:00, 08:00)    │   + code_metrics_snapshots
  └───────────────┬─────────────────┘   + digests
                  │ poller + report bridge
                  ▼
  ┌─────────────────────────────────┐
  │ ② CH→RB bridge (Phase 1)        │   findings ≥ medium → proposals
  │     + reports ingestion         │   digests → Reports tab
  └───────────────┬─────────────────┘

  ═══════════════════════════ PR LEG (Project #268) ═══════════════════════════
  ┌─────────────────────────────────┐
  │ ①' GitHub PR landed / updated   │   external OR agent-authored
  └───────────────┬─────────────────┘
                  │ polling + webhooks (#1799)
                  ▼
  ┌─────────────────────────────────┐
  │ ②' PR Review Service            │   writes pr_reviews
  │     + F.O.R.G.E. diff analysis  │   Bridge dispatch → F.O.R.G.E.
  │     via rate-guard (#2070)      │   posts comment (#1800)
  └───────────────┬─────────────────┘

  ═══════════════════════════ CONVERGENCE ═══════════════════════════
                  └───────────┬───────────┘
                              ▼
  ┌─────────────────────────────────┐
  │ ③ Repair Bay · sandbox + gate   │   shared: Docker / schema-iso,
  │     (Repairs OR PRs tab)        │   tests, ADR-013 pre-deploy gate
  └───────────────┬─────────────────┘
                  │
        ┌─────────┴────────┐
        ▼                  ▼
  ┌───────────┐   ┌───────────────────────────────┐
  │ ④ DHQ     │   │ ⑤ A.R.C.H.I.E. Decision      │
  │ safe-cat  │   │    Service                    │
  │ auto-     │   │    A+D+B policy               │
  │ dispatch  │   │    approve|deny|hold|escalate │
  └─────┬─────┘   └──────────────┬────────────────┘
        │                        │ (only user-gated)
        │                        ▼
        │              ┌──────────────────────┐
        │              │ ⑥ Telegram           │   unified telegram_service,
        │              │   ARCHIE voice only  │   source_agent logged,
        │              │   + PR approval btns │   PR approve/deny inline (#1802)
        │              └──────────┬───────────┘
        │                         │
        └────────────┬────────────┘
                     ▼
             ┌──────────────────────┐
             │ ⑦ Deploy             │   scan leg: manual (unchanged)
             │   scan=manual        │   PR leg: auto-merge for
             │   PR=auto for safe   │   whitelist + clean F.O.R.G.E.
             └──────────────────────┘   review
```

---

## 4. Phase 0 — Evaluate

**Goal:** Ground the rest of the work in real code, not audit inference.

**Method:** Plant a known Code Health finding (a lint violation or missing docstring seed). Follow it through every stage. Document:

- Which tables it lands in (Code Health side)
- Whether a Repair Bay scanner/poller actually picks it up, and where that code lives
- Whether `_has_open_proposal()` or its equivalent exists (grep-missed ≠ absent)
- What status the proposal enters and what transitions it
- Whether any agent dispatch happens automatically
- What happens on sandbox pass/fail
- Whether any Telegram message fires and who sends it

**Output:** `docs/superpowers/reviews/<date>-self-healing-pipeline-trace.md` (date set at write time) — concrete `file:line` citations for every stage, gap list for phases 1-4 to target.

**Starting points** (from this session's audits):
- Code Health scanner: `platform_v2/tools/consciousness/code_health_routes.py` (952 LOC) + code-health-related services in Consciousness (KB 256840).
- Repair Bay pipeline: `platform_v2/tools/repair_bay/` — `scan_service.py`, `proposal_service.py`, `sandbox_manager.py`, `agent_loop_bridge.py` (KB 256838).
- DHQ dispatch: `platform_v2/tools/department_hq/services/department_dispatcher.py` + `orchestration_engine.py` + `smart_router.py` (KB 256844).
- Telegram service: `platform_v2/services/telegram_service.py` (Decision #441, KB 256843 part 1).
- Autonomy loop / approvals: `ai_bridge/agent_loop.py` (rules in `.claude/rules/autonomy.md`).

**Success criteria:** every stage has a cited location in code or a "confirmed missing" verdict backed by search.

---

## 5. Phase 1 — Code Health → Repair Bay

**Goal:** Findings auto-become proposals.

**Scope:**
- Ensure a scanner / poller runs on a schedule. Expected: 6h proactive scan per `.claude/rules/repair-bay.md`. Phase 0 will confirm whether this is wired; if not, add an agent-loop job.
- Complete `_has_open_proposal(file_path, issue_type)` if stubbed. Dedup prevents Sunday-batch duplication noise.
- Tag every proposal with `pipeline_run_id` (new column on `improvement_proposals`) for tracing.
- Severity mapping: critical/high → immediate individual proposal; medium → Sunday 02:00 batch; low → log only.

**Interfaces:**
- New (or completed) function: `proposal_service.create_from_code_health_finding(finding_id)` — idempotent via dedup.
- Migration: add `pipeline_run_id VARCHAR(64)` to `improvement_proposals`, `code_issues`, `sandbox_runs`, `sandbox_test_results`.

**Out of scope:** changing scan content or severity rubric; only the delivery channel.

---

## 6. Phase 2 — Repair Bay → DHQ Dispatch

**Goal:** "Safe" proposals auto-dispatch to an engineering agent instead of waiting for approval.

**Whitelist (initial):**
- `lint` — F821, E722, E501, etc.
- `docstring` — auto-complete missing module/class/function docs
- `import-sort` — isort pass
- `type-hint-trivial` — obvious `Any` or `Optional[X]` fills

**Explicitly NOT safe (always stage ⑤):**
- Schema changes, DB migrations
- Auth/security code
- Customer-facing templates or JS
- Anything flagged high risk score or high blast-radius (see Phase 4)

**Flow:**
1. Proposal enters Repair Bay with `category` field set.
2. Category + severity + agent-proficiency gate checked (see Phase 4).
3. If gate passes: `dispatcher.dispatch(capability="code-fix", agent_filter=engineering_dept, prompt=proposal_context, sandbox_id=...)`.
4. Agent authors patch in sandbox; sandbox runs tests.
5. Pass → status=`ready_to_deploy`, proposal queued for manual deploy review.
6. Fail → status=`fix_requested`, proposal routes to stage ⑤ (A.R.C.H.I.E. reviews) with failure context.

**Agents involved:** F.O.R.G.E. (general code), P.R.O.B.E. (test fixes), with training Lv3+ required.

**Interfaces:**
- New: `repair_bay.dispatch_safe_proposal(proposal_id)` — fires dispatcher, updates status, logs to `autonomy_loop_log`.
- Dispatcher input gets `sandbox_id` so the agent knows where to work.

---

## 7. Phase 3 — Telegram Unification + A.R.C.H.I.E. Decision Service

**Goal:** All non-auto-handled proposals flow to an ARCHIE decision queue. User only sees messages ARCHIE decides to send.

### 7.1 Telegram unification (Decision #441 completion)

**Migrate remaining 8 raw-SDK Telegram callers** (exact list from earlier audit — enumerate in Phase 0) to `platform_v2/services/telegram_service.py`. Every outbound message must:
- Use `send(to=user_id, body=..., source_agent=..., as_archie=True)`.
- Be stamped as ARCHIE at the user-facing layer.
- Log `source_agent` for audit (who really asked).

### 7.2 A.R.C.H.I.E. Decision Service (new)

Central queue of decisions awaiting ARCHIE review.

**Tables:**
- `archie_decisions` — id, pipeline_run_id, requesting_agent_id, category, risk_score, proposed_action (jsonb), context (jsonb), status (pending/approved/denied/held/escalated/expired), archie_rationale, resolved_at, escalated_to_user_at.

**Logic:**
1. Agent or Repair Bay submits a decision request.
2. Queue row written with `status=pending`.
3. ARCHIE polls (or is woken via pub-sub) and reviews:
   - Uses authority model (Phase 4) — category × proficiency × risk.
   - If she can decide autonomously → `approved` or `denied` with rationale; action fires.
   - If she wants to wait → `held` with reason.
   - If user-gate triggered → `escalated`, Telegram fires via unified service.
4. Timeout: decision pending for > X min → fallback. Tier-2 (user-affecting) → escalate; Tier-1 → deny (fail-closed).

**Interfaces:**
- `archie_service.submit_decision(...)` — any agent can call this.
- `archie_service.resolve_decision(id, outcome, rationale)` — ARCHIE's resolver.
- `archie_service.escalate_to_user(id)` — wraps telegram_service.send with the accumulated context.

---

## 8. Phase 4 — Authority Model (A + D + B)

### 8.1 Policy layer A: baseline category map

Table: `escalation_policy` — seeded with:

| Category | Default gate | Notes |
|----------|--------------|-------|
| code-fix, lint, docstring, tests, sandbox | `auto` | ARCHIE territory, agent-driven |
| module-toggle, dispatch-routing, agent-training | `archie` | ARCHIE reviews, can approve |
| cloud-spend >$X | `user` | financial gate |
| contractor-hire | `user` | humans gate |
| force-push-main, drop-table, db-migration | `user` | irreversibles |
| customer-facing-downtime | `user` | scheduled via user |

Gates override whitelist. ARCHIE can propose-to-user that a policy row moves from `user` to `archie` (self-expanding trust, audit-logged).

### 8.2 Proficiency overlay D

Agent must meet a proficiency floor for its category. Defaults:

| Category | Floor |
|----------|-------|
| lint | Lv1 |
| docstring | Lv2 |
| code-fix | Lv3 |
| refactor | Lv4 |
| schema | Lv4 + ARCHIE mandatory review |

Pulled from `agent_competency_scores`. Agent below floor → decision routes to ARCHIE.

### 8.3 Risk score tuning B

Every proposed action gets `risk_score` 0-100:
- Base score from category
- +N for change size (lines touched)
- +N for blast radius (files, modules, services affected)
- +N for touching protected paths (auth, billing, customer data)

Thresholds:
- `risk_score ≤ 30` → follow category policy as-is
- `31-70` → route to ARCHIE even if category says `auto`
- `≥ 71` → route to user even if category says `archie`

Tunable per category. ARCHIE can override with rationale (audit-logged).

---

## 9. Cross-Cutting

### 9.1 Observability

- `autonomy_loop_log` gets `pipeline_run_id` column — one row per stage transition.
- New view `v_pipeline_runs` joins findings → proposals → sandbox → decisions → deploys for end-to-end inspection.
- Nagios monitors: scanner heartbeat (per module), decision-queue depth + oldest-pending age, Telegram service uptime, sandbox-runs-per-hour.

### 9.2 Error Handling

- **Dedup failure** → log, skip proposal creation, no user-facing noise.
- **Sandbox failure** → proposal status=`fix_requested`, route to stage ⑤.
- **Dispatcher failure** → proposal status=`dispatch_failed`, route to stage ⑤ with dispatch error as context.
- **ARCHIE unreachable** → timeout after X min; tier-2 escalates to user, tier-1 denies (fail closed).
- **Telegram failure** → retry with exponential backoff (1s, 5s, 30s, 2m, 10m — 5 attempts max); after final failure, log to `auth_events` + Nagios alert; do NOT auto-approve in absence of user response.

### 9.3 Testing

**Integration:**
- Plant a known lint violation in a safe file → verify full pipeline → finding reaches `ready_to_deploy` queue without human touch.
- Plant a schema-touch finding → verify it routes to ARCHIE decision, never auto-dispatched.
- Simulate ARCHIE service down → verify tier-2 escalates to user, tier-1 denied.

**Unit:** per service (`proposal_service.create_from_code_health_finding`, `repair_bay.dispatch_safe_proposal`, `archie_service.*`, `escalation_policy` gate checks).

**Chaos:** randomly kill `archie_decision_service` mid-resolution, verify timeouts work.

---

## 10. Deploy Safety (unchanged)

The whole pipeline runs up to `status=ready_to_deploy`. Deploy step is manual, requires admin action, runs through existing pre-deploy health gate (ADR-013 + hardcoded-secrets scan). Nothing in this design changes that.

---

## 11. Adjacent Work (tracked separately)

**Task #2069 — Brainstorm as a platform module.**

The current brainstorm companion (superpowers plugin Python server) has persistent reliability issues rooted in its owner-process tracking. Task #2069 replaces it with a Flask blueprint at `platform_v2/tools/brainstorm/`:

- Always on (platform is always on).
- LCARS-themed, same auth as the rest of the platform.
- State in Postgres (`brainstorm_threads`, `brainstorm_screens`, `brainstorm_events`).
- Embeddable inside Repair Bay as the canonical "ARCHIE ↔ user non-urgent deliberation" surface. Pairs with Telegram (urgent).
- Links to projects, tasks, decisions — brainstorm threads become first-class artifacts.

This is **not blocking** the self-healing loop work, but is the natural UI for surfacing ARCHIE's decisions, queue depth, pending user-gates, and audit trails once Phase 3 ships.

---

## 12. Success Criteria

The loop is working when:

1. A planted Code Health finding traverses the full pipeline (scan → proposal → sandbox → ready-to-deploy) with zero user touch, for any whitelist category.
2. A planted non-whitelist finding reaches ARCHIE's decision queue and is resolved by her (approved/denied/held) without user touch for > 90% of cases in a 1-week observation.
3. User-facing Telegram message volume drops by ≥ 70% vs pre-change baseline.
4. Every outbound user-facing Telegram message comes through `telegram_service` with ARCHIE as sender.
5. End-to-end trace (`pipeline_run_id`) shows every stage for any finding.
6. Nagios: ≥ 99% uptime on scanner, decision-service, telegram-service over 30 days.
7. No auto-deploy to production. Ever.

---

## 13. Open Questions (for implementation time, not blocking spec approval)

- Exact $ threshold for `cloud-spend` gate — placeholder, user decides.
- Polling frequency for Code Health bridge — default 15 min, tune after observing volume.
- Whether `archie_decision_service` is its own process or a function of `archie_chat` module. Phase 0 audit will reveal which makes more sense given existing code.
- Whether the "hold" state has a max duration.

---

## 14. Implementation Planning Guidance

This spec covers roughly 10 sessions of work. It should **not** be reduced to a single implementation plan. When handed to `writing-plans`:

- Phase 0 → its own small plan (1 session, produces an audit doc).
- Phase 1 → its own plan, unblocked only after Phase 0's gap list is known.
- Phase 2 → its own plan.
- Phase 3.1 (Telegram unification) → its own plan. Can run in parallel with Phase 2 since they touch different code.
- Phase 3.2 (ARCHIE Decision Service) → its own plan, after Phase 3.1.
- Phase 4 (Authority model) → its own plan, after Phase 3.2 since it reuses the decision-service scaffolding.

Each plan references back to this spec for the "why" and success criteria.

---

## 15. Non-Goals

- Rewriting any of: Code Health scanner logic, Repair Bay sandbox mechanics, dispatcher routing algorithms, Telegram bot infrastructure. We wire what's there.
- Self-deploying. Deploy stays manual.
- Replacing ARCHIE's judgment with a rules engine. A+D+B is a policy floor; ARCHIE can always override with rationale.

---

## Appendix A — PR Leg Integration (Added 2026-04-17)

Adds the "PR Leg" entry point + Code Health Reports centralization announced in Sections 2b/2c. The content below extends Phases 1–4 and cross-cutting sections without renumbering them.

### A.1 PR Leg Phases (Project #268, tasks #1799–#1803)

**PR Leg Phase 1 — Task #1799: PR Review Service + data model**
- New service polls `gh api /repos/<org>/<repo>/pulls` for every repo in scope (archie-platform, kytran-business-suite, kytran-system-operations, kytran-creed, watch products)
- New table `pr_reviews` — id, pipeline_run_id, repo, pr_number, state (open/closed/merged), head_sha, first_seen_at, last_polled_at, forge_review_status, archie_decision_id (nullable)
- Rate-safe: uses shared guard from task #2070 for all API calls (read-only, low transaction cost)
- **Dependencies:** task #2070 shared rate guard (prerequisite before write-side phases; for Phase 1 nice-to-have but not blocking since only reads)

**PR Leg Phase 2 — Task #1800: F.O.R.G.E. AI review via Bridge dispatch**
- When a new PR or a new head_sha is seen, F.O.R.G.E. is dispatched via `tools.department_hq.services.department_dispatcher.dispatch(capability="pr_review", ...)` with the diff as context
- F.O.R.G.E. posts a review comment on the PR — this is a **content-creation operation**, must go through the rate-guard
- Review output written to `pr_reviews.forge_review_status` + a new `forge_review_comments` table (one row per finding in the review)
- **Dependencies:** task #2070 shared rate guard is a HARD blocker here. Do not ship Phase 2 without it.

**PR Leg Phase 3 — Task #1801: Repair Bay UI "PRs" tab**
- New tab in Repair Bay alongside Repairs, Test Bay, Ship, Pushes (see Section 2c table)
- Shows: list of open PRs, F.O.R.G.E.'s review per PR, diff viewer, approve/reject buttons
- Links each PR to its `archie_decision_id` when one exists (Phase 4 convergence)
- **Dependencies:** Phase 1 + Phase 2 (needs data + reviews to display)

**PR Leg Phase 4 — Task #1802: Telegram approval buttons for PRs**
- Integrates with ARCHIE Decision Service from Section 7.2 — PR-leg decisions use the same `archie_decisions` queue
- Telegram notification sends when ARCHIE escalates a PR decision to user (same pattern as contractor dispatch)
- Approve/deny/defer buttons inline
- **Dependencies:** Section 7.2 ARCHIE Decision Service must exist; Phase 3.1 Telegram unification complete

**PR Leg Phase 5 — Task #1803: Multi-repo + public presence audit**
- Extends polling to all standalone product repos
- Audits public-facing GitHub surfaces: README hygiene, security tab status, topic tags, license files
- Findings flow back into the Code Health report mechanism from Section 2c

### A.2 Unified Data Model (Scan Leg + PR Leg)

Both legs converge at the sandbox stage. Shared surface:

| Concept | Scan Leg artifact | PR Leg artifact | Shared |
|---------|-------------------|-----------------|--------|
| Origin | `code_audit_log` / `code_metrics_snapshots` | `pr_reviews` | — |
| Fix candidate | `improvement_proposals` | the PR's head_sha + diff | — |
| Review record | Proposal's `risk_score` + F.O.R.G.E. analysis (if dispatched) | `forge_review_comments` | — |
| Sandbox | `sandbox_runs` | `sandbox_runs` | ✓ |
| Pre-deploy gate | `sandbox_test_results` | `sandbox_test_results` | ✓ |
| Decision | `archie_decisions` | `archie_decisions` | ✓ |
| Trace | `pipeline_run_id` | `pipeline_run_id` | ✓ |
| Telegram escalation | unified `telegram_service` | unified `telegram_service` | ✓ |
| Deploy | manual | auto-merge (safe) or manual | scan = manual, PR = conditional |

**Important convergence rule:** when a scan-leg proposal results in an agent-authored PR (self-healing Phase 2 auto-dispatch), the `improvement_proposals.id` is stored on the matching `pr_reviews` row. This prevents F.O.R.G.E. from re-reviewing work its sibling agent just authored — the scan-leg proposal's risk score + review already established safety, and Phase 2's job is only to verify the PR cleanly implements the proposal.

### A.3 Success Criteria (additions to Section 12)

8. A planted scan-leg finding that produces an auto-dispatched PR is F.O.R.G.E.-reviewed, passes sandbox, and auto-merges without user touch — full end-to-end autonomy for whitelist categories.
9. An externally opened PR (from collaborator or manual branch) is indexed within 5 min of opening, has a F.O.R.G.E. review posted within 15 min, and surfaces in Repair Bay's PRs tab.
10. F.O.R.G.E.'s PR comments are attributed to the agent with `source_agent` logging (same pattern as Telegram).
11. No F.O.R.G.E. review triggers a GitHub secondary-rate-limit 403 response in a 30-day window (observable via Nagios on the rate guard).

### A.4 Open Questions (additions to Section 13)

- Do scan-leg and PR-leg share a single `improvement_proposals` row (with PR attached as the fix), or stay separate with a foreign key? Recommendation: separate tables linked by `archie_decision_id` + optional `improvement_proposal_id` on `pr_reviews` when scan-originated.
- Does F.O.R.G.E. review every PR or only ones above a file-count threshold (e.g., ≤ 50 files, ≤ 500 LOC)? Larger PRs cost more tokens + risk rate-guard pressure.
- When a PR's head_sha changes (force-push), does F.O.R.G.E. re-review from scratch or incremental?
- Auto-merge safety net: require 0 F.O.R.G.E. critical findings + passing CI + passing sandbox + whitelist category — all four must agree. Is there a fifth gate worth adding (e.g., "no files in auth/billing paths")?

### A.5 Implementation Planning Guidance (additions to Section 14)

- **PR Leg Phase 1 (task #1799)** → own plan. Read-only, unblocked by task #2070 but should use the rate guard from day one.
- **PR Leg Phase 2 (task #1800)** → own plan. **HARD blocker:** task #2070 shared rate guard must exist first. Otherwise F.O.R.G.E. will flood content-creation transactions on first multi-repo scan.
- **PR Leg Phase 3 (task #1801)** → own plan. UI only, can run in parallel with Phase 2 of the scan leg.
- **PR Leg Phase 4 (task #1802)** → own plan. Depends on Section 7.2 ARCHIE Decision Service existing.
- **PR Leg Phase 5 (task #1803)** → own plan, last. Low urgency.
- **Code Health Reports integration (Section 2c)** → add to Phase 1 of the scan leg's plan. The poller doing findings → proposals should also handle digests → Reports tab; same job, different surface.

### A.6 Repair Bay as Mission Control (consolidation call-out)

Repair Bay becomes the single admin surface for all code-change-review work once Appendix A phases ship:

- Reports tab absorbs Code Health digests (was Consciousness-only before).
- PRs tab absorbs GitHub PR review (was external CodeRabbit or browser-based before).
- Repairs tab (existing) continues to show internal proposals.
- All three feed the same sandbox + decision + deploy pipeline.

This closes the "pushes centralized" gap the user called out: a single admin dashboard where every pending code change — whether scan-originated, PR-originated, or report-flagged — converges for review, with F.O.R.G.E.'s AI analysis attached and ARCHIE's decision layer gating everything.
