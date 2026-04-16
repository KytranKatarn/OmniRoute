# Profile + Account Center + Subscription Integration — Design Spec

**Date:** 2026-04-16
**Status:** Draft — Pending Approval
**Author:** Kytran + Claude Opus 4.6
**Projects:** #264 (Billing), #266 (Profile + Account Center), #268 (Website Buttons)
**Related Spec:** `2026-04-15-unified-subscription-billing-design.md` (approved — this spec extends it)

---

## Goal

Create a unified user experience where:
1. New users sign up as **Explorer** (free), see gated modules on the platform dashboard, and can upgrade through an in-platform funnel → KBS Stripe checkout
2. **Account Center** becomes the admin hub for user management, trial grants, tier overrides, and subscription visibility
3. **Profile page** shows users their own subscription status, connected services, and account details
4. **Website** (kytranempowerment.com) aligns pricing, services, and product pages with the platform — pulling live stats from a public API
5. All standalone products (Watch series, KSO, KBS) gate features based on entitlements flowing from KBS through the platform's OAuth system

---

## Tier Structure (6 Tiers)

### Finalized Pricing

| Tier | Price | Target Audience | AI Agents | Watch Products |
|------|-------|-----------------|-----------|----------------|
| **Kytran Staff** | Internal | Kytran employees & admins | All | All |
| **Explorer** | $0 | Anyone curious | 0 | 0 |
| **Starter** | $299/mo | Solo entrepreneurs & small teams | 5 | 1 (pick) |
| **Professional** | $799/mo | Growing businesses | 20 | 2 (pick) |
| **Enterprise** | $1,499/mo | Organizations needing everything | Unlimited | All |
| **VIP** | Invite only | Strategic partners | Unlimited | All |

- **Kytran Staff** = `role == 'admin'` in the DB. Not shown on public pricing pages. Full access to all modules including Admin Ops and AI Command.
- **Explorer** is permanent free tier (not a trial). Trials are a separate mechanism granted by admins.
- Pricing matches `membership.html` on the public website. The `services.html` pricing table ($499/$1,499/$3,999) is OUT OF DATE and will be updated to match.

### Cancellation Policy

| Plan Type | Policy |
|-----------|--------|
| **Monthly** | Cancel anytime. Access continues through end of current billing period. No early termination fee. |
| **Annual** (future) | 2 months free (10 months price for 12 months access). Early cancellation = remaining months non-refundable. |
| **Enterprise** | 6-month minimum commitment. Early termination = 50% of remaining months. |
| **VIP** | Custom terms negotiated per client. |
| **Data export** | 30-day window after cancellation to export data. After 30 days, user data is purged. |

No setup fees — lower barrier to entry matters more than recouping onboarding cost. Real lock-in comes from the value of data inside the platform (CRM contacts, watchlists, AI agent configurations).

### Trial System

Admins can grant time-limited tier access from Account Center:
- Select user → select product + tier → set duration (7/14/30 days)
- Creates a `billing_subscriptions` row with `status='trial'` and `expires_at` timestamp
- When trial expires, user reverts to their base tier (Explorer or whatever they're paying for)
- Trials are visible in the user's Profile Subscription tab
- No Stripe involvement for trials — purely internal

---

## Module Access Map

### Access Levels

| Level | Meaning |
|-------|---------|
| **Hidden** | Module not rendered on dashboard at all (Admin Ops, AI Command) |
| **Gated** | Module card visible but blurred + "UPGRADE" diagonal banner |
| **Accessible** | Module card active, user can click through to use it |

### Per-Module Tier Requirements

#### Hidden (Staff Only) — Not Shown to Any Customer

| Category | Module | Notes |
|----------|--------|-------|
| Admin Operations | Backup Manager | Infrastructure admin |
| Admin Operations | Security & Network | Infrastructure admin |
| Admin Operations | Account Center | User management admin |
| AI Command | Department HQ | Agent management internal |
| AI Command | Consciousness | Knowledge analytics internal |
| AI Command | Repair Bay | Self-healing pipeline internal |
| AI Command | Agent Academy | Agent training internal |
| AI Command | A.R.C.H.I.E. Chat | Internal AI assistant |

#### SaaS Services — Subscription Gated

| Module | Explorer | Starter | Professional | Enterprise |
|--------|----------|---------|-------------|------------|
| CRM | Gated | ✓ | ✓ | ✓ |
| Invoicing | Gated | ✓ | ✓ | ✓ |
| Store Builder | Gated | ✓ | ✓ | ✓ |
| Content Studio | Gated | ✓ | ✓ | ✓ |
| Website Designer | Gated | Gated | ✓ | ✓ |
| Social Media | Gated | Gated | ✓ | ✓ |
| Call Center | Gated | Gated | ✓ | ✓ |
| Google Work Suite | Gated | Gated | ✓ | ✓ |
| StockBot | Gated | Gated | ✓ | ✓ |

#### Applications & Concepts

| Module | Explorer | Starter | Professional | Enterprise | Notes |
|--------|----------|---------|-------------|------------|-------|
| Fitness | Hidden | Hidden | Hidden | Hidden | Staff only — early stage placeholder |
| Therapy | Hidden | Hidden | Hidden | Hidden | Staff only — early stage placeholder |
| DOC | Hidden | Hidden | Hidden | Hidden | Staff only — early stage placeholder |
| Family Tree | Gated | Gated | Gated | ✓ | Has real features (D3.js charts, archives, DNA) |
| Media Hub | Hidden | Hidden | Hidden | Hidden | VIP/Staff only — personal Plex/Jellyfin |

#### Creative Studios

| Module | Explorer | Starter | Professional | Enterprise |
|--------|----------|---------|-------------|------------|
| Media Studio | Gated | Gated | Gated | ✓ |
| Game Studio | Gated | Gated | Gated | ✓ |

#### Crypto

| Module | Explorer | Starter | Professional | Enterprise | Notes |
|--------|----------|---------|-------------|------------|-------|
| Archie Pool | Gated | Gated | Gated | ✓ | Mining pool admin |
| Pool Management | Gated | Gated | Gated | ✓ | Mining pool management |
| **Crypto Watch** (future) | Free tier | Viewer | Pro | All | New module — crypto news, trends, market data |

Crypto Watch will be a new standalone product in the Media Outreach category, following the same pattern as Legal/Civic/Market/Gov Watch with Free/Viewer/Pro tiers and individual subscription pricing.

#### Media Outreach (Standalone Products)

These have their own subscription tiers independent of platform membership. Membership includes bundled access:

| Product | Free Tier | Viewer | Pro | Bundled With |
|---------|-----------|--------|-----|-------------|
| Civic Watch | ✓ | $19/mo | $49/mo | Starter: pick 1, Pro: pick 2, Enterprise: all |
| Legal Watch | ✓ | $29/mo | $79/mo | Starter: pick 1, Pro: pick 2, Enterprise: all |
| Market Watch | ✓ | $29/mo | $99/mo (AI Trader) | Starter: pick 1, Pro: pick 2, Enterprise: all |
| Gov Watch | ✓ | $29/mo | $79/mo | Starter: pick 1, Pro: pick 2, Enterprise: all |

**Watch product selection for memberships:** During checkout or in the KBS subscription management UI, membership subscribers choose which Watch products to include. Selection is stored in `billing_subscriptions` metadata (JSONB `selected_watches` array). Users can change their picks once per billing cycle. Bundled Watch access grants the Viewer tier for the selected products; users can upgrade individual Watch products to Pro by paying the difference.
| The News | TBD | TBD | TBD | Future — merging with what-the-fact.com |
| C.R.E.E.D. Institute | — | — | — | Nonprofit — separate domain (creed-ai.org) |

---

## Profile Page Changes

### Current State
6 tabs: Overview, Activity, Security, Connections, Preferences, Data
- Blue LCARS header with back-to-dashboard button
- Profile modal with race condition fix (last session)
- Appearance tab removed (last session)
- Connections API and Activity feed have known issues

### Changes

#### New Tab: Subscription (7th tab)
Shows full subscription details:
- Current membership tier with badge
- List of all product entitlements with source (membership bundle vs individual subscription vs trial vs admin override)
- Renewal date and billing amount
- "Manage Billing" button → redirects to `business.kytranempowerment.com/billing`
- Trial status if active (shows expiration countdown)
- Subscription history (upgrades, downgrades, cancellations)

#### Overview Tab Enhancement
Add a "Your Plan" card alongside existing name/email/avatar:
- Tier badge (Explorer/Starter/Professional/Enterprise/VIP)
- Quick product count ("5 modules, 1 Watch product")
- "View Plan" link → switches to Subscription tab
- If Explorer: "Upgrade" CTA button

#### Connections Tab (Fix + Define)
Currently broken. Will show three sections:
1. **OAuth Providers** — Google, LinkedIn, etc. (which OAuth providers are linked to this account)
2. **Product Connections** — which standalone products (Watch, KSO, KBS) the account is connected to, with status (active/expired/never connected)
3. **API Keys** — for Pro-tier API access to Watch products and platform APIs. Generate, revoke, view usage.

All scoped per-user, stored in their profile.

#### Activity Tab (Fix)
Fix the backend API to properly return user activity feed.

---

## Account Center Admin Powers

Account Center (Admin Ops, staff-only module) gets these new capabilities:

### Subscription Management (Read + Admin Actions)
- **View any user's subscriptions** — read from `billing_subscriptions` table
- **View entitlements summary** — computed view showing what products/tiers a user has and why (membership vs individual vs trial vs override)
- **"Manage Billing" link** → redirects to KBS billing dashboard for that user

### Trial Grants
- **Grant trial** — admin picks a user, selects product + tier, sets duration (7/14/30 days)
- Creates `billing_subscriptions` row with `status='trial'`, `expires_at` timestamp
- No Stripe involvement
- Shows in user's Profile Subscription tab

### Tier Overrides
- **Override tier** — admin manually sets a user's tier for a product
- Use cases: VIP invitations, partner access, comp accounts, support escalations
- Creates `billing_subscriptions` row with `status='admin_override'`, no `expires_at` (permanent until removed)
- Logged in `audit_log` table

### Trial/Override Revocation
- **Revoke trial/override** — sets `status='revoked'`, `revoked_at` timestamp
- User access reverts immediately

---

## Dashboard Gating

### Visual Treatment for Locked Modules

Modules stay in their existing category layout on the dashboard. Locked modules get:
- **Blurred module card** — module image/icon dimmed with backdrop-filter blur
- **Diagonal banner** — "UPGRADE" in amber for Starter/Pro modules, "ENTERPRISE" in purple for Enterprise-only modules
- **Tier badge** — small label at bottom showing minimum tier required (e.g., "Starter+", "Pro+", "Enterprise")
- **Clickable** — clicking a locked module navigates to its product landing page

### Upgrade Funnel (Click → Landing → Upsell → Stripe)

```
Step 1: User clicks locked module on dashboard
Step 2: → /subscribe/{module-id} (product landing page, on platform)
Step 3: Landing page shows: features, screenshots, tier comparison table
Step 4: User clicks "Subscribe to [tier]"
Step 5: → Upsell interstitial (if applicable)
         "You picked Starter — for just $500 more/mo, get Professional with 20 AI agents and all modules"
Step 6: User confirms or upgrades
Step 7: → Redirect to business.kytranempowerment.com/billing/checkout
         ?product={module}&tier={tier}&return_url=https://platform.kytranempowerment.com/dashboard
Step 8: Stripe Checkout
Step 9: → Redirect back to platform, access unlocked
```

### Product Landing Pages

Located on the platform at `/subscribe/{module-id}`. LCARS-styled, modeled after the Watch product landing pages (hero section, features grid, tier comparison, CTA).

Each landing page includes:
- Module name, icon, description
- Feature breakdown by tier (what's included at each level)
- Screenshots or mockups of the module
- Tier comparison table
- Primary CTA: "Subscribe to [recommended tier]"
- Secondary CTA: "See all plans" → membership.html

---

## Platform Stats API

Public endpoint so the website can pull live numbers instead of hardcoding:

```
GET https://platform.kytranempowerment.com/api/public/stats
```

Response:
```json
{
  "agents": {
    "total": 131,
    "ai": 34,
    "internal": 90,
    "contractor": 5,
    "departments": 17
  },
  "platform": {
    "modules": 36,
    "knowledge_entries": 25788,
    "autonomous_jobs": 118,
    "languages": 8
  },
  "updated_at": "2026-04-16T11:00:00Z"
}
```

- No auth required — aggregate counts only, nothing sensitive
- Cache for 5 minutes (avoid DB hit on every page load)
- Website pages (platform.html, membership.html, services.html) fetch on load and populate stat cards dynamically
- Fallback: if API unreachable, show last known values from a static data attribute

---

## Website Alignment

### Pages to Update

| Page | Action |
|------|--------|
| `services.html` | Fix pricing table: $499/$1,499/$3,999 → align with membership rates or remove table entirely (link to membership.html instead) |
| `membership.html` | Add cancellation policy section. Add "Kytran Staff" note (internal, not shown). Wire CTA buttons to KBS checkout. |
| `platform.html` | Update stats: 16→17 departments, 129→live API. Replace "Starbase Command" with "Fleet Compute (Dept HQ)". |
| `compliance.html` | Remove — duplicate of compliance-services.html |
| `books.html` | Redesign as "Coming Soon" placeholder |
| `submit-story.html` | Redesign as "Coming Soon" placeholder |
| `tips.html` | Redesign as Explorer community content |
| All product pages | Wire CTA buttons to KBS checkout flow |

### Pages to Add

| Page | Purpose |
|------|---------|
| The News / What The Fact | Future — product page for what-the-fact.com when ready |
| Crypto Watch | Future — when module is built |

### Professional Services — Pricing to Determine

All service pages need pricing added. Services with "Get a Quote" option available for custom work.

| Service | Page | Type | Recommended Price Range | AI Director |
|---------|------|------|------------------------|-------------|
| Website Design & Development | website-services.html | One-time | $2,000 - $10,000 | M.U.S.E. |
| Penetration Testing | security-services.html | One-time | $1,500 - $5,000 | V.I.G.I.L. |
| Network Security Assessment | security-services.html | One-time | $500 - $2,000 | V.I.G.I.L. |
| Infrastructure Hardening | security-services.html | One-time | $1,000 - $3,000 | V.I.G.I.L. |
| Managed Compliance Assessment | compliance-services.html | One-time | $499 | V.I.G.I.L. |
| Continuous Compliance Monitoring | compliance-services.html | Monthly | $299/mo | S.H.I.E.L.D. |
| Full Compliance Program | compliance-services.html | Annual | $4,999/yr | V.I.G.I.L. |
| Custom AI Agent Development | ai-services.html | One-time | $3,000 - $15,000 | D.A.R.W.I.N. |
| Business Automation Consulting | ai-services.html | One-time | $1,000 - $5,000 | B.A.S.E. |
| AI Workflow Automation | ai-services.html | Recurring | $500 - $2,000/mo | F.O.R.G.E. |
| AI Training & Education | ai-services.html | One-time | $500 - $2,000 | D.A.R.W.I.N. |

Fixed-price services show the price on the page. Quote-based services show starting price + "Get a Quote" CTA.

---

## Database Changes

### Existing Tables (No Schema Changes)

| Table | Owner | Used For |
|-------|-------|----------|
| `users` | Account Center | Identity, role, admin flag |
| `billing_subscriptions` | KBS (write) / OAuth (read) | Active subscriptions per user per product |
| `billing_customers` | KBS | Stripe customer ID mapping |
| `billing_products` | KBS | Product catalog with Stripe price IDs |
| `billing_events` | KBS | Webhook event log |
| `oauth_clients` | Platform | OAuth client registrations |

### New/Modified Fields

| Table | Field | Type | Purpose |
|-------|-------|------|---------|
| `billing_subscriptions` | `status` | VARCHAR | Add values: `'trial'`, `'admin_override'`, `'revoked'` (existing: active, canceling, canceled) |
| `billing_subscriptions` | `expires_at` | TIMESTAMP | Trial expiration (NULL for permanent subscriptions) |
| `billing_subscriptions` | `granted_by` | INTEGER (FK users) | Admin who granted trial/override (NULL for Stripe subscriptions) |
| `billing_subscriptions` | `revoked_at` | TIMESTAMP | When trial/override was revoked (NULL if active) |
| `users` | `api_keys` | — | New table: `user_api_keys` (user_id, key_hash, product, created_at, last_used, revoked_at) |

### New Table: `user_api_keys`

```sql
CREATE TABLE user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key_hash VARCHAR(128) NOT NULL,
    key_prefix VARCHAR(8) NOT NULL,  -- first 8 chars for display (ke_xxxx...)
    product VARCHAR(64) NOT NULL,     -- which product this key is for
    name VARCHAR(128),                -- user-given label
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    revoked_at TIMESTAMP,
    UNIQUE(key_hash)
);
```

### New Table: `user_oauth_connections`

```sql
CREATE TABLE user_oauth_connections (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    provider VARCHAR(64) NOT NULL,    -- google, linkedin, github, etc.
    provider_user_id VARCHAR(256),
    email VARCHAR(256),
    display_name VARCHAR(256),
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMP,
    connected_at TIMESTAMP DEFAULT NOW(),
    disconnected_at TIMESTAMP,
    UNIQUE(user_id, provider)
);
```

---

## Implementation Phases

### Phase 1: Profile Page Backend Fixes (Task #1992)
- Fix Connections API — implement `user_oauth_connections` table + CRUD routes
- Fix Activity feed API — return proper user activity
- Add Subscription tab — read from `billing_subscriptions`
- Add "Your Plan" card to Overview tab
- Platform Stats API endpoint (`/api/public/stats`)

### Phase 2: Account Center Integration (Task #1993)
- Subscription view for admins (read billing_subscriptions per user)
- Trial grant/revoke UI
- Tier override UI
- Entitlements summary view
- Audit logging for all admin subscription actions

### Phase 3: Dashboard Gating + Upgrade Funnel
- Module gating visual treatment (blur + diagonal banner + tier badge)
- Product landing pages at `/subscribe/{module-id}`
- Upsell interstitial component
- Redirect to KBS checkout with return URL

### Phase 4: KBS Billing Integration (Task #1994 — from Project #264)
- Stripe checkout endpoint in KBS
- Stripe webhook handler
- billing_subscriptions write pipeline
- Subscription management UI (upgrade/downgrade/cancel)

### Phase 5: Website Alignment (Task #1955 + Project #268)
- Fix services.html pricing
- Update platform.html to use Stats API
- Wire all CTA buttons to KBS checkout
- Remove compliance.html duplicate
- Redesign books.html + submit-story.html as "Coming Soon"
- Redesign tips.html as Explorer community content
- Add professional service pricing to all service pages

### Phase 6: Content Protection (Task #1995)
- `@tier_required()` decorator on platform module routes
- Dashboard generator reads user tier and applies gating
- Module registry gets `minimum_tier` field
- Watch products already have gating — verify and align

### Phase 7: Language Preference Persistence (Task #1996)
- Save language preference to user profile in DB
- Load on login, apply across platform
- Sync with standalone products via OAuth userinfo

---

## Future Work (Not In This Spec)

- **Crypto Watch module** — new standalone product for crypto news/trends/market data
- **The News / What The Fact** — merge into unified news platform
- **Annual pricing** — discounted yearly plans
- **Team/enterprise billing** — multi-seat subscriptions
- **shop.kytranempowerment.com** — KBS storefront integration
- **Embedded Stripe checkout** — modal inside platform instead of redirect
- **API key marketplace** — rate-limited API access as a product
