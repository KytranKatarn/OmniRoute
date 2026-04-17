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
  ┌─────────────────────────────────┐
  │ ① Consciousness · Code Health   │   scans → code_audit_log (+ code_metrics_snapshots)
  └───────────────┬─────────────────┘
                  │ poller (every N min)
                  ▼
  ┌─────────────────────────────────┐
  │ ② CH→RB bridge (Phase 1)        │   reads new findings ≥ medium,
  │                                 │   creates improvement_proposals,
  │                                 │   dedup via _has_open_proposal()
  └───────────────┬─────────────────┘
                  ▼
  ┌─────────────────────────────────┐
  │ ③ Repair Bay · proposal+sandbox │   Docker or schema-isolation,
  │                                 │   tests, pre-deploy health gate
  └───────────────┬─────────────────┘
                  │
        ┌─────────┴────────┐
        ▼                  ▼
  ┌───────────┐   ┌───────────────────────────────┐
  │ ④ DHQ     │   │ ⑤ A.R.C.H.I.E. Decision      │
  │ safe-cat  │   │    Service (Phase 3)          │
  │ auto-     │   │    reviews via A+D+B policy   │
  │ dispatch  │   │    approve | deny | hold |    │
  │ (Phase 2) │   │    escalate-to-user           │
  └─────┬─────┘   └──────────────┬────────────────┘
        │                        │ (only user-gated)
        │                        ▼
        │              ┌──────────────────────┐
        │              │ ⑥ Telegram (Phase 3) │   unified telegram_service,
        │              │    ARCHIE voice only │   source_agent logged
        │              └──────────┬───────────┘
        │                         │
        └────────────┬────────────┘
                     ▼
             ┌──────────────────┐
             │ ⑦ Manual deploy  │   human-gated, unchanged
             └──────────────────┘
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
