# KBS Phase 1 — tenant_1 MVP (Kytran Empowerment eats its own cooking)

**Date**: 2026-04-16
**Status**: Spec
**Project**: #269 KBS Overhaul — Schema Fix, UI Review, Store Integration
**Blocks**: Phase 2 (external customer resale)
**Supersedes**: Individual tasks #2015, #2017 (rolled into slice plans)

## Goal

KBS tenant_1 becomes Kytran Empowerment's primary system of record for business operations. The product proves itself — "eat your own cooking" — before external resale opens in Phase 2.

## Constraints

- **Timeline**: 1–2 months serial (5–7 weeks with modest overlap).
- **Quality bar**: full-quality (option C from brainstorming) — Plans 2–5 shipped, every plugin audited, E2E tested, real double-entry accounting.
- **Blank slate**: Day 0 = go-live. No imports. No backfill. Every customer/invoice/contract entered going forward.
- **Stripe-primary**: Stripe is the system of record for money movement. KBS is the system of record for business context (who/what/why).
- **Push freeze**: all work lands on local branches through 2026-04-30; push in dependency order May 1 (see Repair Bay Pushes tab).

## In Scope — 7 Slices (across 6 plugins)

| Slice | Plugin | Role |
|-------|--------|------|
| — | `kbs_core_objects` | Foundation (accounts/contacts/leads/opportunities). **Already shipped (Plan 1, KBS PR #4).** Not a Phase 1 slice; listed for dependency context. |
| **S0** | `kbs_accounting` (skeleton) | Chart of accounts + `post_entry()` service + minimal ledger viewer. Ships first so downstream slices hook in. |
| **S1** | `kbs_crm` | Who the customers are. Rewrite to `core.objects`. First "eat own cooking" milestone. |
| **S2** | `kbs_invoicing` | Main revenue loop. Stripe-backed. Webhooks post entries into accounting. |
| **S3** | `kbs_contracts` | Written agreements tied to accounts. Low-risk, quick. |
| **S4** | `kbs_store` | shop.kytranempowerment.com + Printful orders + COGS/revenue into accounting. |
| **S5** | `kbs_automations` | Glue layer: triggers across CRM/invoicing/contracts/store. Ships last because it wires what exists. |
| **S6** | `kbs_accounting` (full) | Finish the skeleton: P&L, A/R aging, chart-of-accounts editor, CSV export, reconciliation. |

(S0 and S6 both touch `kbs_accounting` — same plugin, two ship phases.)

## Out of Scope (Phase 2, tracked not blocking)

- The other 17 plugins: `appointments`, `content_studio`, `social_media`, `website_builder`, `marketing`, `call_center`, `help_desk`, `automations_ui`, `industry` + 7 vertical plugins, `knowledge_base`.
- External customer self-serve signup (pricing page → checkout → auto-provision tenant).
- Multi-tenant Plan 2 migration for tenants other than tenant_1 (blank slate = Plan 2 is a no-op for tenant_1).
- Marketplace / resale UX.
- New industry verticals.
- SOC 2 evidence collection (separate track).

## Definition of "Working" per slice

A slice is done when all of the following are true:

1. UI renders cleanly on LCARS (no 500s, keyboard-reachable, responsive at 480/768/1024).
2. CRUD works end-to-end (create/read/update/delete primary entities).
3. Uses `core.objects` where applicable. Direct SQL on accounts/contacts/leads/opportunities is a review-blocker (matches K.I.N. single-writer guardrail pattern).
4. Integrations wired: Stripe for `invoicing` + `store`; Printful for `store`; ARCHIE Bridge for optional AI assists (`contracts` drafts, `crm` auto-tag, `invoicing` line-item suggestions).
5. P.R.O.B.E. suite added covering main endpoints + a browser-level E2E happy-path.
6. Kytran admin can walk the slice's primary workflow without hitting a blocker (manual acceptance walkthrough attached to the PR as screen capture).

## Success Metric for Phase 1 Shipping

Kytran Empowerment operates a full business month (acquire lead → close → invoice → collect → record → expense-track → reconcile) entirely in KBS tenant_1 with no external spreadsheets.

Hard gates for Phase 1 → Phase 2 cutover (all must be true for ≥ 7 consecutive days):

1. All 7 slices' P.R.O.B.E. suites green.
2. All 7 slices' Playwright E2E green.
3. Real Kytran Empowerment business month reconciles: P&L, A/R, A/P all match bank + Stripe reality within normal rounding.
4. No TODO / FIXME / hardcoded test values in production paths (git grep check).
5. All Phase 1 ADR decisions logged in Dev HQ.
6. Push-freeze inventory fully drained on the KBS branch post-May 1.

## Per-Slice Template

Every slice follows this shape. Individual slices may skip sections that don't apply.

### 1. Data-model audit

Read the plugin's current tables + route handlers. Identify every reference to legacy tables (e.g. `crm_customers`). Map each to a `core.objects` equivalent. Decide: rewrite in place, or shim behind a view (Plan 2 pattern).

### 2. Data migration (if plugin has tables)

Write idempotent, rollback-safe migration SQL. For tenant_1, run through `provision_tenant_schema` where possible. Evidence logs in `docs/superpowers/plans/.../evidence/`.

### 3. Service-layer rewrite

Plugin's service (or equivalent) uses `core.objects` for account/contact/lead/opportunity lookups. Plugin still owns its own domain tables (invoices, contracts, store_orders, ledger_entries, etc.).

### 4. Routes

Thin HTTP handlers. All logic in service. `@login_required` + tier gate where applicable. Standard shape: `/tools/<plugin>/api/<resource>` for UI reads; `/api/<plugin>/<action>` for external webhooks.

### 5. UI

LCARS frame pattern. `bm-overlay` modals. `var(--archie-*)` tokens. No inline `onclick` (use `data-action` + dispatcher per Account Center playbook). Template-extracted CSS (`static/css/<plugin>.css`) and JS (`static/js/<plugin>.js`). No `innerHTML =` with interpolated values — use DOM construction or escapeHtml helper.

### 6. Integrations

- **Stripe**: idempotency keys on every write. Webhook router at `/api/stripe/webhook` (signature-verified, already partial). Event handling: `invoice.paid`, `invoice.payment_failed`, `charge.refunded`, `payment_intent.succeeded`, `checkout.session.completed`. Exponential-backoff retry, max 3. Final failure → admin "Stripe errors" view + Telegram alert.
- **Printful** (store only): product catalog sync job, order fulfillment webhook, shipping status sync.
- **ARCHIE Bridge**: `bridge_client.ask(capability, prompt, ...)` façade. Dispatch via `get_dispatcher()`, never direct Ollama (ADR-013).

### 7. Accounting hook

Every money-moving event emits a double-entry ledger line via `kbs_accounting.service.post_entry()`. Signature:

```python
post_entry(
    tenant_id: int,
    entry_date: date,
    description: str,
    source_plugin: str,
    source_entity_type: str,
    source_entity_id: int,
    lines: list[dict],  # [{account, dr, cr}, ...]
    metadata: dict | None = None,
) -> int  # entry_id
```

Rules:
- Double-entry invariant: `sum(dr) == sum(cr)`, enforced in service. Raises on mismatch.
- Chart of accounts preloaded at slice S0: `1xxx` assets, `2xxx` liabilities, `3xxx` equity, `4xxx` revenue, `5xxx` expenses.
- Reversals via `reverse_entry(entry_id, reason)` — creates mirror entry, both linked for audit.
- Source entity linkage: every ledger line traces back to invoice/order/contract. No orphan entries.
- All writes inside a single DB transaction with the source slice's own write (atomic).

### 8. Subscription gating

- `@tier_required('business')` decorator on gated routes. Checks `tenant.subscription_tier` against declared minimum.
- `module_registry.minimum_tier` per plugin.
- Sidebar hides plugins the current tier doesn't include.
- Tier change (upgrade/downgrade) via Stripe subscription webhook → updates `tenant.subscription_tier` → UI re-renders on next request.
- Trial grants (from Account Center) override tier for the trial window.

Phase 1 detail: tenant_1 is always Enterprise tier, so gating is a no-op for Kytran internal use. We wire it correctly now so Phase 2 tenants work without rework.

### 9. Tenant context threading

Every plugin service function accepts `tenant_id` as its first argument. Service layer receives it from `current_user.tenant_id` at the route boundary and passes down. No service code reads `current_user` directly. Keeps testing and batch/webhook contexts clean.

### 10. Secrets / config

All external API keys in `.env`, validated at app boot. Missing key → WARN log + plugin starts in "degraded" mode (endpoints return 503 with a clear message) rather than crashing the whole app. No secret committed.

### 11. Deliverables per slice

- Spec + plan committed to `docs/superpowers/` (ARCHIE repo).
- PR against the KBS repo, freeze-aware, batched per push-freeze rules.
- Dev HQ task completion with notes.
- ADR entry logged in `project_decisions` for any architectural choice made per slice.

## Slice Order + Dependency Chain

```
[kbs_core_objects] ── shipped (Plan 1)
         │
         ▼
[kbs_accounting SKELETON (S0)]
         │
         ▼
[kbs_crm (S1)]
         │
    ┌────┴────┐
    ▼         ▼
[invoicing] [contracts]
    │  (S2)   │ (S3)
    └────┬────┘
         ▼
    [store (S4)]
         │
         ▼
   [automations (S5)]
         │
         ▼
 [accounting FULL (S6)]
```

### Recommended shipping order

| # | Slice | Weeks | Depends on | Reason |
|---|-------|-------|------------|--------|
| S0 | `kbs_accounting` skeleton | 1 | core_objects | Ship chart-of-accounts + `post_entry()` + minimal ledger viewer first so downstream slices hook in as they ship. Avoids retrofits. |
| S1 | `kbs_crm` | 1–1.5 | core_objects | Rewrite to `core.objects`. Kytran enters real contacts/leads/accounts day 1. First "eat own cooking." |
| S2 | `kbs_invoicing` | 1.5–2 | crm, accounting skeleton | Main revenue loop. Stripe wiring. Webhooks → accounting entries. |
| S3 | `kbs_contracts` | 0.5–1 | crm | Written agreements tied to accounts. Low-risk, can run parallel with S2. |
| S4 | `kbs_store` | 1.5 | Printful, accounting skeleton | shop.kytranempowerment.com. Catalog sync, order fulfillment, COGS + revenue entries. |
| S5 | `kbs_automations` | 1–1.5 | all above | Glue layer. Triggers across slices. |
| S6 | `kbs_accounting` full | 1 | all above | Finish skeleton: P&L, A/R aging, chart-of-accounts editor, CSV export, reconciliation. |

**Serial total**: 8–10 weeks one-dev. With S3 parallel to S2 and cleanup overlap: 5–7 weeks wall-clock.

### Push-freeze integration

All slice work lands on local branches through **2026-04-30**. One inventory row per slice in the Repair Bay **Pushes** tab. On **2026-05-01**, push in dependency order (S0 → S1 → S2 → S3 → S4 → S5 → S6), one PR per slice, sequential CI.

### Kill-switch rules

- If any slice blows past 1.5× its estimate, STOP, reassess, re-brainstorm that slice only.
- If a slice turns out to need a Phase-2 plugin, stub the dependency.
- If Stripe webhook/idempotency turns out to be the hidden complexity in S2, split into S2a (invoice creation) + S2b (payment reconciliation).

## Cross-Cutting Concerns

### Stripe integration

Location: `integrations/stripe_client.py` (exists). Single client, all slices import.

Webhook router dispatches by `event.type`:
- `invoice.paid` → `kbs_invoicing.handle_invoice_paid(event)` → marks invoice paid + posts accounting entry (Dr cash, Cr A/R).
- `invoice.payment_failed` → alert + retry schedule.
- `charge.refunded` → reverse accounting entry + invoice status.
- `payment_intent.succeeded` (store) → mark order paid.
- `checkout.session.completed` (subscriptions, Phase 2 handler stubbed for now).

Test mode vs live mode detected via `STRIPE_SECRET_KEY` prefix (`sk_test_` vs `sk_live_`). UI banner when in test mode.

### ARCHIE Bridge integration

Location: `integrations/bridge_client.py` (to create). Uses `get_dispatcher()` + `dispatch()` / `dispatch_json()` per ADR-013.

Phase 1 capabilities:
- `kbs_contracts`: `legal_drafting` (cloud-tier OK for quality).
- `kbs_invoicing`: `text_generation` (optional line-item descriptions).
- `kbs_crm`: `text_classification` (auto-tag leads from a pasted note).

### Tenant context

Every service function: `def do_x(tenant_id, payload): ...`. Route reads `current_user.tenant_id` and passes in. Webhooks resolve `tenant_id` from the Stripe customer's metadata or from a tenant-keyed `stripe_customers` join.

### Secrets / config

`.env` validated at app boot. Missing keys → plugin degraded mode. Stripe secret + webhook secret + Printful API key + RingCentral creds + Google OAuth + Twilio + SMTP + Bridge URL. Documented in `.env.example`.

## Testing Strategy

### Layer 1 — Unit (pytest)

Pure service-layer functions. Real test schema per class (`tenant_test_N` via `provision_tenant_schema`). Coverage target: ≥ 80% on services, **100% on `kbs_accounting.service`** (money-touching code). Every `core.objects` CRUD path. Edge cases: duplicate idempotency, reversed entries, tier-gate denials. Money-math invariant: `sum(dr) == sum(cr)`.

### Layer 2 — Integration (pytest + Flask test client + stripe-mock)

Route → service → DB round-trips. `stripe-mock` container for deterministic webhook testing. Coverage: every route's JSON/HTML shape, auth enforcement, webhook router dispatch, transactional correctness (inject error mid-flight, verify rollback).

### Layer 3 — P.R.O.B.E. suites

One YAML suite per slice, registered as `internal`, runs on schedule every 4 h (matches existing KBS cadence). Covers page loads + API GET endpoints + webhook endpoint acceptance (sign locally with test secret). Telegram alert on failure. Acceptance: every slice ships with its suite 100% green.

### Layer 4 — E2E (Playwright)

One happy-path per slice, scripted via the platform's Playwright plugin. Examples:
- **crm**: log in → Create Lead → fill → save → appears in list → click → open detail → add interaction.
- **invoicing**: Create Invoice → pick customer → add line items → Send → Stripe test card → return to KBS → invoice Paid → accounting shows entries.
- **contracts**: Create → template → Bridge suggests language → edit → send → countersign mock → Active.
- **store**: shop.kytranempowerment.com → pick Printful product → checkout → order confirmed → Printful mock fulfills → accounting logs revenue + COGS.
- **automations**: trigger "invoice paid" → verify side-effects.

Runs via `scripts/e2e.sh <slice>` against dev instance. CI variant runs against spun-up `tenant_test` with stripe-mock.

### Layer 5 — Manual acceptance (Kytran admin walkthrough)

Before any slice PR merges:
- Kytran (or Claude on their behalf) walks the primary workflow live in tenant_1.
- Short screen capture (or Playwright trace) attached to the PR body.

This is the "can you actually run Kytran Empowerment's business with this" gate — the hardest gate and the most meaningful for dual-use operator software.

### Flake policy

- E2E flake → quarantine, file follow-up, don't block the slice.
- Unit/integration flakes → fix before merging (indicate real race conditions).
- P.R.O.B.E. suite flake → investigate transient vs too-strict.

### Deliberately skipped in Phase 1

- Load / performance tests (no customer load yet).
- Security pentest (separate compliance-standalone track).
- Accessibility audit beyond keyboard reachability (Phase 2 a11y pass).

## Risk Register

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Stripe test-mode → live-mode cutover surprises | medium | Dual-mode banner + idempotency keys + S2a/S2b split available |
| Kytran uses tenant_1 daily → we break it with a slice change | medium | Each slice merged behind a feature flag when non-trivial; manual acceptance walkthrough required pre-merge |
| 7 slices in 8–10 weeks is optimistic | medium-high | Kill-switch rule (1.5× estimate = reassess); Phase 2 items tracked not promised |
| Double-entry accounting wrong by 1 cent | low | Unit test invariants + decimal-typed money everywhere (no floats) + reconciliation as first-class feature |
| Cross-session collision on the KBS repo | medium | Branch-per-slice + `git branch --show-current` before every commit (existing memory rule) |
| ARCHIE Bridge latency | low | Bridge calls opt-in (contract drafts); synchronous-OK for Phase 1 scope |

## Phase 1 Deliverables

**Code**:
- 7 slices on the KBS main branch (one PR per slice, pushed post-2026-05-01).
- `kbs_accounting` with real chart-of-accounts + double-entry + P&L + A/R aging + CSV export.
- `@tier_required` decorator applied to every gateable plugin (no-op for tenant_1, ready for Phase 2).
- 8 integration hooks operational (Stripe, Printful, RingCentral stubbed, Hostinger, Google stubbed, Twilio stubbed, SMTP, Bridge).

**Docs**:
- This design: `docs/superpowers/specs/2026-04-16-kbs-phase-1-tenant1-mvp-design.md`.
- 7 slice specs + 7 slice plans.
- ADR entries in `project_decisions`.

**Testing artifacts**:
- 7 P.R.O.B.E. suites green.
- 7 Playwright E2E scripts.
- pytest unit + integration suites green.

**Business evidence**:
- A full month of Kytran Empowerment operations in tenant_1: ≥ 5 real leads, ≥ 3 real invoices paid via Stripe, ≥ 1 real contract, ≥ 1 real store order, reconciled P&L.
- Per-slice walkthrough capture attached to PR.

## Phase 2 Inherits (not built in Phase 1, unblocked by it)

| Phase 2 item | Phase 1 foundation |
|--------------|---------------------|
| External customer signup | `@tier_required` wired; `provision_tenant_schema` migrates plugin tables; Stripe subscription webhooks route to tenant provisioning — just needs the pricing → checkout UX |
| Other 17 plugins | Each follows the vertical-slice template; no new architecture |
| Industry verticals | Thin layer over `core.objects` + slice patterns |
| Resale marketplace | `module_registry.minimum_tier` already drives per-tier plugin visibility |
| Kytran expands own ops | Activate more plugins for tenant_1 via the same slice template |

## Next Step

Invoke `superpowers:writing-plans` to turn Slice **S0 (kbs_accounting skeleton)** into an executable task-by-task plan. Subsequent slices get their own plans as earlier ones complete.
