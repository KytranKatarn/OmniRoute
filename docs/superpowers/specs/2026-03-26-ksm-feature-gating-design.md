# KSM Feature Gating — Subscription Tier Enforcement

**Date**: 2026-03-26
**Project**: #193 — Kytran System Operations — Standalone Product + Compliance Engine
**Status**: Design Approved
**Scope**: Feature gating by subscription tier (free/pro/business/enterprise) with admin override
**Depends on**: Tier 2 (completed 2026-03-25)
**Deferred**: Stripe integration + product page — separate platform-wide project covering Store Builder, Account Center, CRM, Invoicing

---

## Problem Statement

KSM needs subscription tiers to differentiate free vs paid features before going public. The gating system must work without Stripe initially (tier set via admin/config), then later accept tier from Stripe webhooks when the platform-wide billing project is complete.

---

## Pricing Tiers

| Tier | Price | Code Value |
|------|-------|------------|
| Free | $0 | 0 |
| Pro | $29/mo per server | 1 |
| Business | $49/mo per server | 2 |
| Enterprise | $99/mo per server | 3 |

## Feature Matrix

| Feature | Free (0) | Pro (1) | Business (2) | Enterprise (3) |
|---------|:---:|:---:|:---:|:---:|
| System dashboard (CPU/RAM/disk/network) | Yes | Yes | Yes | Yes |
| Docker container management | Yes | Yes | Yes | Yes |
| Process management | Yes | Yes | Yes | Yes |
| Firewall view | Yes | Yes | Yes | Yes |
| CIS Ubuntu compliance pack | Yes | Yes | Yes | Yes |
| Themes | 2 | 3 | 5 | 5 |
| Compliance packs | 1 (CIS) | 3 (CIS+STIG+Network) | All 5 | All 5 + custom |
| Live SVG badges | No | Yes | Yes | Yes |
| Auto-remediation | No | No | Yes | Yes |
| PDF compliance reports | No | No | Yes | Yes |
| Hub connection (SSO) | No | Yes | Yes | Yes |
| Background scan schedule | 1/day (86400s) | Every 6h (21600s) | Every 1h (3600s) | Custom |
| Priority support | No | No | No | Yes |
| SLA guarantee | No | No | No | 99.9% |

---

## Deliverable 1: Subscriptions Table

**New SQLite table** in standalone:

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free', 'pro', 'business', 'enterprise')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'cancelled', 'past_due', 'trialing')),
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    current_period_end TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id)
);
```

- One subscription per user (UNIQUE constraint)
- `stripe_*` columns nullable — populated later when Stripe is integrated
- Default tier: `free`
- `current_period_end` for future Stripe period tracking

---

## Deliverable 2: Tier Resolution Logic

**Priority order for determining user's active tier:**

1. **Admin override**: `KSM_TIER_OVERRIDE` env var — when set, ALL users get this tier (for internal ARCHIE-connected instance)
2. **User subscription**: `subscriptions.tier` where `status = 'active'`
3. **Default**: `free`

```python
def get_user_tier(user_id=None):
    """Resolve the active tier for a user."""
    # 1. Admin override (internal instance)
    override = current_app.config.get("TIER_OVERRIDE")
    if override and override in ("free", "pro", "business", "enterprise"):
        return override

    # 2. User subscription
    if user_id:
        # query subscriptions table
        ...

    # 3. Default
    return "free"
```

**Tier numeric values** for comparison:

```python
TIER_LEVELS = {"free": 0, "pro": 1, "business": 2, "enterprise": 3}
```

---

## Deliverable 3: `require_tier()` Decorator

```python
def require_tier(minimum_tier):
    """Route decorator: block access if user's tier is below minimum."""
```

**Behavior:**
- API routes (Accept: application/json): return `{"error": "upgrade_required", "required_tier": "pro", "current_tier": "free"}` with HTTP 403
- HTML routes: render an upgrade prompt page showing what the user needs and a CTA button
- The decorator reads tier via `get_user_tier(current_user.id)`

**Applied to routes:**

| Route Pattern | Minimum Tier |
|---------------|-------------|
| `/api/compliance/badge/*.svg` | pro |
| `/api/compliance/scan` (POST, packs beyond CIS) | pro |
| `/api/compliance/remediate` | business |
| `/api/compliance/report/pdf` | business |
| `/auth/sso` | pro |
| Theme selection (beyond 2 themes) | pro |

---

## Deliverable 4: Compliance Pack Gating

The compliance scanner needs to respect tier limits:

| Tier | Allowed Packs |
|------|--------------|
| Free | `cis-ubuntu` only |
| Pro | `cis-ubuntu`, `ubuntu-stig`, `network-stig` |
| Business+ | All: `cis-ubuntu`, `ubuntu-stig`, `network-stig`, `docker-stig`, `hipaa` |

**Implementation:**
- `compliance_service.run_scan()` filters `pack_ids` based on user tier
- If user requests a pack above their tier, return error with upgrade prompt
- Background scheduler uses the tier's allowed packs

---

## Deliverable 5: Scan Frequency Gating

Background scheduler interval varies by tier:

| Tier | Interval |
|------|----------|
| Free | 86400s (1/day) |
| Pro | 21600s (6h) |
| Business | 3600s (1h) |
| Enterprise | Configurable via `KSM_COMPLIANCE_SCAN_INTERVAL` |

**Implementation:**
- Scheduler reads tier on startup and sets interval accordingly
- Admin override (`KSM_TIER_OVERRIDE=enterprise`) + custom interval env var for internal use

---

## Deliverable 6: Theme Gating

| Tier | Available Themes |
|------|-----------------|
| Free | kytran, lcars |
| Pro | kytran, lcars, midnight |
| Business+ | All 5: kytran, lcars, midnight, arctic, ember |

**Implementation:**
- Settings page shows all themes but locks unavailable ones with upgrade prompt
- Theme selection API checks tier before applying

---

## Deliverable 7: Upgrade Prompt UI

When a user hits a gated feature, they see:

- What feature they tried to access
- What tier is required
- Feature comparison showing what they'd get
- "Upgrade" button (links to pricing page — placeholder URL until Stripe project)

Template: `templates/upgrade_required.html` — LCARS styled, matches standalone theme.

---

## Deliverable 8: Admin Settings + Tier Display

- Settings page shows current tier with badge (Free/Pro/Business/Enterprise)
- Admin can manually set user tiers (for testing, comps, internal users)
- API: `GET /api/subscription/status` — returns current tier, features unlocked, next billing date (when Stripe connected)
- API: `PUT /api/admin/subscription/<user_id>` — admin sets tier manually

---

## Config

```python
# In config.py (KSM_ prefix)
TIER_OVERRIDE = os.environ.get("KSM_TIER_OVERRIDE", "")  # Set to "enterprise" for internal instance
```

**Internal ARCHIE instance**: Set `KSM_TIER_OVERRIDE=enterprise` in systemd env — all features unlocked, no gating.

**External standalone**: No override — tier comes from subscriptions table (default: free).

---

## File Map

| Action | File | What |
|--------|------|------|
| Modify | `config.py` | Add `TIER_OVERRIDE` |
| Create | `services/subscription_service.py` | `get_user_tier()`, `TIER_LEVELS`, pack/theme/scan gating logic |
| Create | `middleware/tier_gate.py` | `require_tier()` decorator |
| Modify | `routes/compliance_routes.py` | Add `@require_tier` to gated endpoints |
| Modify | `routes/badge_routes.py` | Add `@require_tier("pro")` |
| Modify | `auth.py` | Add `@require_tier("pro")` to SSO |
| Modify | `services/compliance_service.py` | Filter packs by tier |
| Modify | `services/scheduler.py` | Set interval by tier |
| Create | `routes/subscription_routes.py` | Subscription status + admin management APIs |
| Create | `templates/upgrade_required.html` | Upgrade prompt page |
| Modify | `templates/settings.html` | Show tier badge + locked themes |
| Modify | `routes/__init__.py` | Register subscription routes |
| Modify | `app.py` | Init subscriptions table on startup |

---

## Out of Scope (Deferred to Stripe Platform Integration Project)

All Stripe/billing work merges into a single platform-wide project covering:
- **KSM**: Stripe Checkout, webhooks, Customer Portal, product page
- **Store Builder**: Product payments, Printful order billing
- **Account Center**: User billing management, plan upgrades/downgrades
- **CRM**: Customer payment history, revenue tracking
- **Invoicing**: Stripe Invoice integration, recurring billing

This unified project ensures one Stripe account, one webhook handler, one customer model across all modules. Feature gating (this spec) is designed to accept tier from any source — config override now, Stripe webhook later.

---

## Success Criteria

1. Internal instance (`KSM_TIER_OVERRIDE=enterprise`): all features unlocked, no prompts
2. Fresh standalone install: defaults to free tier, sees upgrade prompts on gated features
3. Admin can manually set user tier via API
4. Compliance scan only runs allowed packs for the tier
5. Badge endpoints return 403 for free tier users
6. Settings page shows correct tier and locked themes
7. Upgrade prompt page renders with feature comparison
