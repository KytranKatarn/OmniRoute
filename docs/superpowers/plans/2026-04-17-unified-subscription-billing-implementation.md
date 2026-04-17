# Unified Subscription & Billing — Implementation Plan (2026-04-17)

**Consolidates**: Projects #266, #264, #268
**Spec**: `docs/superpowers/specs/2026-04-15-unified-subscription-billing-design.md`
**Decision**: #453 (6-Tier Subscription Model)
**Push-freeze**: Active through 2026-05-01 — all work local commits until then.

---

## Why this plan exists

Three projects track the same underlying work from different angles:

| Project | Angle | Status |
|---|---|---|
| **#266** Profile + AC + Subscription Integration | Platform side (Account Center) | 95% (1 task #1994 open) |
| **#264** Unified Subscription & Billing — KBS as Billing Authority | Architecture / KBS side | 38% (task #1952 falsely complete) |
| **#268** Website Transaction Buttons — Payment Integration | kytranempowerment.com side | 0% |

Session 13 audit (2026-04-17) discovered:
- **Task #1952 (Stripe checkout in KBS) is marked complete but no `kbs_billing` plugin exists.** KBS has only `kbs_invoicing` (one-off invoices) and `kbs_store` (product orders). Neither handles **subscriptions**.
- **ARCHIE `subscription_tiers` table has the OLD 1.0 tier model** (free/pro/business/enterprise at $9.99/$29.99/$99.99) — Decision #453's 6-tier model (Explorer/Starter/Pro/Enterprise/Staff/VIP at $299/$799/$1,499 CAD) is not in the DB.
- **Live Stripe products from vault-note 256750 (prod_ULar…, price_1TMt…) appear nowhere in platform code.**
- **No link between `subscription_tiers` and `billing_subscriptions`** — two disconnected tables.

---

## Architecture (from spec, reconfirmed)

**Three-layer model**:
- **Identity** (Account Center) — *who you are, read-only subscription view*
- **Billing** (KBS) — *owns Stripe, handles subscription lifecycle, emits webhooks*
- **Access** (each product) — *checks tier, renders paywall, redirects upgrade → KBS checkout*

**Single source of truth**: `billing_subscriptions` table in ARCHIE DB (already exists from Project #195).
**`subscription_tiers`**: product catalog + tier metadata + Stripe price IDs.

---

## Live Stripe state (from vault-note 256750, 2026-04-16)

```
Starter       prod_ULarbP2VrC0AqB   price_1TMtfi06cZ0yWDKJnCmKKeNu   $299/mo CAD
Professional  prod_ULarkVTZDVxtz4   price_1TMtfi06cZ0yWDKJsocTKBAn   $799/mo CAD
Enterprise    prod_ULar6OoTAIyWzh   price_1TMtfj06cZ0yWDKJFfiyL6I0   $1,499/mo CAD
```

Webhook endpoint: `https://business.kytranempowerment.com/api/webhooks/stripe`
(Currently wired for kbs_store orders — needs sibling for subscriptions.)

---

## Phases

### Phase A — Platform tier catalog alignment (THIS SESSION)
**Goal**: make ARCHIE's `subscription_tiers` table reflect Decision #453 + Stripe IDs, non-destructively.

- [x] **A1** Migration `database/migrations/subscription_tiers_stripe_alignment.sql`:
  - ADD COLUMN `stripe_product_id`, `stripe_price_id_monthly`, `stripe_price_id_yearly`, `currency` (default 'cad'), `kbs_product_slug`
  - SET existing tiers (pro, business, enterprise) to `enabled=false` (kept for FK safety on user_subscriptions; not deleted)
  - INSERT new tiers: `explorer` ($0), `starter` ($299), `professional` ($799), `enterprise_plus` ($1,499) — with live Stripe IDs
  - Keep `free`, `kytran`, `vip` untouched (free becomes alias/legacy for Explorer in future cleanup)
- [x] **A2** Idempotent — re-runnable without duplicates.
- [x] **A3** Verified: `SELECT name, price_monthly, stripe_price_id_monthly FROM subscription_tiers WHERE enabled;` returns the 4 new tiers + staff/vip.

### Phase B — Dev HQ cleanup (THIS SESSION)
- [x] Reopen #1952 with context note about false completion.
- [x] Cross-link #266 ↔ #264 ↔ #268 via work notes pointing to this plan.
- [x] Add task to Project #264: "Create kbs_billing plugin scaffold" (replaces #1952's false status).

### Phase C — KBS billing plugin scaffold (NEXT SESSION, KBS REPO)
**Goal**: spin up `kbs_billing` plugin skeleton so Phase D can build.

- Scaffold `plugins/kbs_billing/` (manifest.yaml, `__init__.py`, `routes.py`, `service.py`, `templates/`, `migrations/`)
- Tier/product catalog in plugin (mirrors ARCHIE `subscription_tiers` or reads via API)
- Placeholder `/billing/checkout` GET + `/billing/webhook` POST (501 Not Implemented)
- Tests: plugin loads, routes register under `/plugins/kbs_billing/`
- Add to `plugin_registry`

### Phase D — KBS Stripe checkout flow (NEXT SESSION+1)
- `/billing/checkout` accepts `?product=X&tier=Y&return_url=Z` → Stripe Checkout Session → redirect
- Implementation mirrors `kbs_store/public_routes.py` stripe setup
- Get/create Stripe customer for tenant user
- `/billing/success` confirms + eagerly updates `billing_subscriptions`
- E2E test with Stripe test mode

### Phase E — Stripe webhook handler (NEXT SESSION+1)
- `/billing/webhook` handles 5 event types per spec §1.3
- Signature verification
- Writes to `billing_subscriptions`
- Tests with Stripe CLI event replay

### Phase F — Account Center read-only sub view (follow-up)
- Subscription tab reads `billing_subscriptions` (already partial from #2005)
- Tier comparison table renders from DB (instead of hardcoded prices in template)
- "Manage Billing" link → redirects to KBS billing dashboard
- All write operations removed from AC (moved to KBS)

### Phase G — Watch product paywalls (follow-up)
- Per spec §3.1-§3.2 — upgrade button redirects to KBS checkout with current URL as return_url
- Per-product feature gating tables (Legal, Civic, Market, Gov Watch)

### Phase H — kytranempowerment.com CTAs (absorbs #268)
- Audit pricing page CTAs
- Wire each to `https://business.kytranempowerment.com/billing/checkout?...`
- E2E test: landing page → checkout → success → platform entitlement

---

## What this session actually ships

| Item | File | Status |
|---|---|---|
| This plan | `docs/superpowers/plans/2026-04-17-unified-subscription-billing-implementation.md` | ✅ |
| Migration A1 | `database/migrations/subscription_tiers_stripe_alignment.sql` | ✅ |
| Dev HQ #1952 reopened with note | — | ✅ |
| Project cross-links | #266/#264/#268 work notes | ✅ |

---

## Push-freeze considerations

All commits stay local on `feat/probe-suite-account-center` until 2026-05-01. Migrations are idempotent so they can be re-applied if a later session restores state.

---

## Follow-up tasks created in Dev HQ

- Project #264: "Create kbs_billing plugin scaffold (Phase C)"
- Project #264: "KBS Stripe subscription checkout flow (Phase D)"
- Project #264: "KBS Stripe webhook handler (Phase E)"

These supersede the misleading #1952 "Stripe checkout + webhook integration in KBS".
