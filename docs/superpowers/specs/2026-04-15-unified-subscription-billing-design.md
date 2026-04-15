# Unified Subscription & Billing Architecture — Design Spec

**Date:** 2026-04-15
**Status:** Approved
**Author:** Kytran + Claude Opus 4.6

---

## Goal

Make KBS (Kytran Business Suite) the centralized billing authority for all Kytran products. Users subscribe, pay, manage invoices, and track costs through KBS. All standalone products (Watch series, KSO, future products) gate features based on entitlements that flow from KBS through the platform's OAuth system.

## Context

### What Exists Today

| Component | Status | Notes |
|-----------|--------|-------|
| `billing_subscriptions` table | Exists | Links user_id to product (module) + stripe_price_id |
| `billing_customers` table | Exists | Stripe customer ID mapping |
| `billing_products` table | Exists | Product catalog |
| `billing_events` table | Exists | Stripe webhook event log |
| `oauth_userinfo.py` | Working | Returns entitlements + product_tiers from billing_subscriptions |
| `oauth_clients` table | Working | All 10 products registered with redirect URIs |
| `kytran_auth.py` SDK | Working | All products have it, checks entitlements on SSO |
| `auth.py` tier system | Working | `resolve_tier()` + `@tier_required()` in each product |
| KSO paywall UI | Working | `upgrade_required.html` with tier comparison table |
| KBS `stripe_billing.py` | Exists | Needs verification — may be scaffold only |
| KBS `stripe_checkout.py` | Exists | Needs verification — may be scaffold only |
| Account Center module | Working | User CRUD + subscription_tier field (read/write) |
| KBS container | Running | Code extracted from Docker, gitignored, SSO partially wired |

### What's Broken / Missing

1. **KBS SSO not completing** — `on_login` callback missing (no local user/tenant creation)
2. **KBS is gitignored** — source extracted to `/mnt/archie_brain/kytran-business-suite/` but not tracked
3. **No billing checkout flow** — Stripe files exist but no working checkout endpoint
4. **No upgrade redirect** — Watch products have no "Upgrade" button linking to KBS
5. **billing_subscriptions not populated** — admin access works via role bypass, but no actual subscription records exist for testing
6. **No subscription management UI** — users can't view/cancel/change their subscriptions

---

## Architecture

### Three-Layer Model

```
IDENTITY (Platform Account Center)
  ├── Users, roles, admin flag
  ├── OAuth provider (/oauth/authorize, /oauth/token, /oauth/userinfo)
  └── Reads billing_subscriptions for entitlements (read-only)

BILLING (KBS — Business Suite)
  ├── Stripe integration (checkout, webhooks, customer sync)
  ├── Subscription lifecycle (create, upgrade, downgrade, cancel)
  ├── billing_subscriptions table (write authority)
  ├── billing_products catalog
  ├── Invoice history + PDF export (future)
  ├── Tax calculation (future)
  ├── Shop storefront at shop.kytranempowerment.com (future)
  └── CRM integration (crm_billing_link table)

ACCESS (Each Standalone Product)
  ├── kytran_auth.py SDK — SSO + entitlement check
  ├── auth.py — resolve_tier() maps entitlements to free/viewer/pro
  ├── @tier_required() decorator gates routes
  └── Paywall UI for locked features (upgrade_required pattern from KSO)
```

### Data Flow — New User Subscription

```
1. User visits legal.kytranempowerment.com
2. Clicks "Connect with Kytran Empowerment"
3. Redirects to platform.kytranempowerment.com/oauth/authorize
4. User logs in (or creates account)
5. OAuth callback → Legal Watch checks entitlements
6. User has no "legal-watch" entitlement → Free tier
7. User sees dashboard with locked Viewer/Pro features (blurred + upgrade prompt)
8. Clicks "Upgrade to Viewer"
9. Redirects to business.kytranempowerment.com/billing/checkout
   ?product=legal-watch&tier=viewer&return_url=https://legal.kytranempowerment.com/dashboard
10. KBS shows plan selection (pre-selected to Viewer)
11. User completes Stripe Checkout
12. Stripe webhook → KBS writes billing_subscriptions row
    (user_id, module='legal-watch', stripe_subscription_id, stripe_price_id, status='active')
13. KBS redirects to return_url
14. Legal Watch re-authenticates → OAuth userinfo now includes 'legal-watch' in entitlements
15. User has Viewer access — locked features unlocked
```

### Admin Bypass

`resolve_tier()` in every product already returns "pro" for admin role:
```python
if user.get("role") == "admin":
    return "pro"
```
Kytran staff get full access everywhere without subscription records. No changes needed.

### Internal vs SaaS Use

The Watch products serve dual purpose:
- **Internal:** Kytran employees use them for business intelligence (admin bypass)
- **SaaS:** External customers subscribe through KBS for paid access

Same codebase, same features. The billing system is transparent to internal users.

---

## Product Catalog

| Product | OAuth Client ID | Tiers | Monthly Price | Stripe Product |
|---------|----------------|-------|---------------|----------------|
| Legal Watch | legal-watch | Free / Viewer / Pro | $0 / $29 / $79 | prod_legal_watch |
| Civic Watch | civic-watch | Free / Viewer / Pro | $0 / $19 / $49 | prod_civic_watch |
| Market Watch | market-watch-viewer | Free / Viewer / AI Trader | $0 / $29 / $99 | prod_market_watch |
| Gov Watch | gov-watch | Free / Viewer / Pro | $0 / $29 / $79 | prod_gov_watch |
| System Operations | kso | Free / Pro / Business | $0 / $19 / $49 | prod_kso |
| A.R.C.H.I.E. Platform | archie-platform | Free / Pro | $0 / TBD | prod_platform |
| Shop | shop | Per-product pricing | Varies | Multiple |

---

## KBS Prerequisites (Phase 0)

Before billing can work, KBS itself must be operational:

### 0.1 Fix KBS SSO
- Move `KytranAuth.init_app()` from `app.py` to `auth.py` inside a `register_kytran_auth(app)` function
- Add `on_login` callback that creates/updates local user in KBS PostgreSQL
- Create tenant for SSO users (or assign to default tenant)
- Call `login_user()` and set `session["tenant_id"]`
- Reference: KSO `auth.py:357-400`

### 0.2 Fix KBS Source Management
- Decide: ungitignore `kytran-business-suite/` OR create separate git repo
- Ensure source changes persist across rebuilds
- Current state: code extracted via `docker cp`, changes only in running image

### 0.3 Fix KBS Login Template
- Match KSO login design: local form + "or" divider + "Connect with Kytran Empowerment" with ram logo
- Remove broken service worker

### 0.4 Verify KBS Health
- Container starts clean (gunicorn, 4 workers)
- Health endpoint responds
- Database connectivity (shared ARCHIE PostgreSQL)
- Stripe keys configured in .env

---

## Phase 1: Billing Checkout Flow

### 1.1 Stripe Product Setup
- Create Stripe products + prices for each product/tier combination
- Store Stripe product_id and price_id in `billing_products` table
- Configure webhook endpoint in Stripe dashboard

### 1.2 KBS Checkout Endpoint
```
GET /billing/checkout?product=legal-watch&tier=viewer&return_url=https://legal...
```
- Validates product + tier exist in catalog
- Creates/retrieves Stripe customer for the user
- Creates Stripe Checkout Session with the correct price_id
- Redirects to Stripe Checkout
- On success: Stripe redirects to `/billing/success?session_id=X`
- On cancel: redirects to return_url

### 1.3 Stripe Webhook Handler
```
POST /billing/webhook
```
- Validates Stripe signature
- Handles events:
  - `checkout.session.completed` → create billing_subscriptions row
  - `customer.subscription.updated` → update tier/status
  - `customer.subscription.deleted` → deactivate subscription
  - `invoice.paid` → log to billing_events
  - `invoice.payment_failed` → notify user, grace period
- Writes to `billing_subscriptions` table (the source of truth for OAuth entitlements)

### 1.4 Success/Return Flow
- `/billing/success` — shows confirmation, links back to product
- Updates `billing_subscriptions` immediately (don't wait for webhook for better UX)
- Webhook serves as the authoritative backup

---

## Phase 2: Subscription Management UI

### 2.1 KBS Billing Dashboard
```
GET /billing (requires auth)
```
- List all active subscriptions with product name, tier, price, renewal date
- "Manage" button per subscription (upgrade, downgrade, cancel)
- Payment method management (Stripe Customer Portal or custom)
- Invoice history with download links

### 2.2 Upgrade/Downgrade
- Uses Stripe's subscription update API
- Prorated billing for mid-cycle changes
- Updates `billing_subscriptions` tier immediately

### 2.3 Cancellation
- Stripe cancellation at period end (not immediate)
- User retains access until current period expires
- `billing_subscriptions.status` → 'canceling', then 'canceled' at expiry

---

## Phase 3: Watch Product Paywall Integration

### 3.1 Paywall UI Component
Each Watch product adds a paywall overlay for tier-gated features:
- Blurred/glossy content with upgrade prompt (KSO pattern)
- "Upgrade to Viewer" / "Upgrade to Pro" button
- Button links to: `https://business.kytranempowerment.com/billing/checkout?product={client_id}&tier={required_tier}&return_url={current_url}`
- Tier comparison table showing what each level unlocks

### 3.2 Feature Gating per Product

**Legal Watch:**
| Feature | Free | Viewer ($29) | Pro ($79) |
|---------|------|-------------|-----------|
| Daily news digest | Yes | Yes | Yes |
| Federal legislation | Yes | Yes | Yes |
| Basic search | Yes | Yes | Yes |
| All jurisdictions | No | Yes | Yes |
| Custom alerts | No | Yes | Yes |
| AI case summaries | No | Yes | Yes |
| Compliance tracking | No | Yes | Yes |
| API access | No | No | Yes |
| Team workspaces | No | No | Yes |
| Bulk export | No | No | Yes |

**Civic Watch:**
| Feature | Free | Viewer ($19) | Pro ($49) |
|---------|------|-------------|-----------|
| Daily digest | Yes | Yes | Yes |
| Federal spending | Yes | Yes | Yes |
| MP voting records | Yes | Yes | Yes |
| All jurisdictions | No | Yes | Yes |
| Custom watchlists | No | Yes | Yes |
| AI spending analysis | No | Yes | Yes |
| Contract tracking | No | Yes | Yes |
| API access | No | No | Yes |
| Bulk data export | No | No | Yes |
| FOI tracking | No | No | Yes |

**Market Watch:**
| Feature | Free | Viewer ($29) | AI Trader ($99) |
|---------|------|-------------|-----------------|
| Daily summary | Yes | Yes | Yes |
| Major indices | Yes | Yes | Yes |
| Basic screener | Yes | Yes | Yes |
| Unlimited watchlists | No | Yes | Yes |
| AI pattern detection | No | Yes | Yes |
| Real-time alerts | No | Yes | Yes |
| Earnings analysis | No | Yes | Yes |
| Paper trading | No | No | Yes |
| API access | No | No | Yes |
| Backtesting | No | No | Yes |

**Gov Watch:**
| Feature | Free | Viewer ($29) | Pro ($79) |
|---------|------|-------------|-----------|
| Daily digest | Yes | Yes | Yes |
| Federal bills | Yes | Yes | Yes |
| Basic profiles | Yes | Yes | Yes |
| All jurisdictions | No | Yes | Yes |
| Custom alerts | No | Yes | Yes |
| AI impact scores | No | Yes | Yes |
| Budget analysis | No | Yes | Yes |
| API access | No | No | Yes |
| Team workspaces | No | No | Yes |
| Stakeholder mapping | No | No | Yes |

---

## Phase 4: Account Center Updates (Read-Only View)

Account Center module on the platform shows:
- User's active subscriptions (read from `billing_subscriptions`)
- "Manage Billing" link → redirects to KBS billing dashboard
- Subscription status badges on user profiles
- Admin can view any user's subscriptions

No write operations — all billing writes go through KBS.

---

## Future Phases (Not In Scope)

- **Shop storefront** at shop.kytranempowerment.com (physical/digital products)
- **Tax calculation agents** — automated tax computation per jurisdiction
- **Invoice generation** — branded PDF invoices with line items
- **Cost tracking dashboard** — internal cost analysis for Kytran operations
- **Agent-assisted billing support** — AI agents handling billing inquiries
- **Embedded checkout** — Stripe.js modals inside Watch products (upgrade from redirect)
- **Annual pricing** — discounted yearly plans
- **Team/enterprise billing** — multi-seat subscriptions with org management

---

## Database Tables (Existing — No Schema Changes Needed)

| Table | Owner | Purpose |
|-------|-------|---------|
| `users` | Account Center | Identity, role, admin flag |
| `billing_subscriptions` | KBS (write) / OAuth (read) | Active subscriptions per user per product |
| `billing_customers` | KBS | Stripe customer ID ↔ user_id mapping |
| `billing_products` | KBS | Product catalog with Stripe price IDs |
| `billing_events` | KBS | Webhook event log for auditing |
| `crm_billing_link` | KBS | Links CRM contacts to billing records |
| `oauth_clients` | Platform | Registered OAuth client IDs per product |

---

## Environment Variables Required

### KBS (.env additions)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
KBS_BILLING_RETURN_URL=https://business.kytranempowerment.com/billing/success
```

### Each Watch Product (already set)
```
KYTRAN_AUTH_URL=https://platform.kytranempowerment.com
KYTRAN_CLIENT_ID=<product-client-id>
KYTRAN_CLIENT_SECRET=<secret>
KYTRAN_REDIRECT_URI=https://<product>.kytranempowerment.com/auth/kytran/callback
```

---

## Implementation Order

1. **Phase 0** — Get KBS operational (SSO, source management, login template)
2. **Phase 1** — Stripe checkout + webhook (the billing pipe)
3. **Phase 2** — Subscription management UI in KBS
4. **Phase 3** — Paywall integration in Watch products
5. **Phase 4** — Account Center read-only view

Each phase is independently shippable and testable.
