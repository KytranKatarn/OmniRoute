# Unified Pricing Infrastructure — Phase 1 Design
**Dev HQ Task #3027 | Status: Design Complete | Date: 2026-05-25**

## Key Finding: Infrastructure Is 80% Built

Before building anything, read these existing files:

| File | What it already does |
|------|---------------------|
| `platform_v2/services/stripe_service.py` | Full Stripe SDK: customer, checkout, portal, subscription CRUD |
| `platform_v2/services/subscription_service.py` | `get_user_entitlements()`, `get_user_membership_tier()` — reads `billing_subscriptions` |
| `platform_v2/services/billing_webhook.py` | Idempotent webhook pipeline — verify sig → dedupe → prefix-dispatch |
| `platform_v2/services/ksm_billing_handler.py` | KSM pattern: webhook → resolve tier → `_push_tier_to_standalone()` via HTTP |
| `platform_v2/tools/account_center/bundle_checkout_service.py` | `watch_bundle` ($12.99 CAD/mo) + `intelligence_bundle` ($19.99) already in `BUNDLE_CATALOG` |
| `platform_v2/oauth_userinfo.py` | Already returns `entitlements` + `product_tiers` dict with bundle expansion |

**Existing billing schema tables (already exist):**
- `billing_customers` — `(user_id, stripe_customer_id, email, name)`
- `billing_products` — `(stripe_product_id, stripe_price_id, module, name, amount_cents, currency, billing_interval, is_active)`
- `billing_subscriptions` — `(user_id, stripe_subscription_id, stripe_price_id, module, status, billing_cycle, bundle_id, ...)`
- `billing_bundle_products` — `(bundle_id, product_id)`
- `billing_events` — idempotency log for webhooks

## The 3 Actual Gaps

1. **No `subscription_plans` canonical table** — tier vocabulary is fragile keyword matching in `subscription_service.py:23` (`_resolve_tier_from_price`). Fix: add the table.
2. **Vocabulary mismatch** — gov-watch uses `free/solo/team/agency`; `oauth_userinfo.py` resolves to `enterprise/business/pro`; `subscription_service.py` uses `viewer/starter/professional/enterprise/vip`. Fix: standardize to `free/starter/solo/team/agency/enterprise` everywhere.
3. **Standalones read flat `subscription_tier`** instead of `product_tiers["own_product_id"]` from OAuth payload. Fix: update each standalone's `_sync_user_tier`.

## Phase 1 Architecture Decision

**Approach:** Add `subscription_plans` canonical table + extend `billing_subscriptions` with `tier_name`/`product_id` columns + standardize vocabulary in `oauth_userinfo.py` + one billing handler per product group following KSM pattern.

Do NOT rebuild the webhook infrastructure, bundle system, or OAuth entitlements payload — they are correct in design.

---

## Migration SQL

**File:** `platform_v2/database/migrations/395_unified_pricing_plans.sql`

```sql
-- 395_unified_pricing_plans.sql
-- Canonical plan registry for all Kytran products. Idempotent.

CREATE TABLE IF NOT EXISTS subscription_plans (
    id                  SERIAL PRIMARY KEY,
    product_id          TEXT        NOT NULL,  -- 'gov_watch', 'wtf', 'civic_watch', 'legal_watch', 'market_watch', 'kbs'
    tier_name           TEXT        NOT NULL,  -- 'free', 'starter', 'solo', 'team', 'agency', 'enterprise'
    tier_rank           INTEGER     NOT NULL,  -- 0=free, 10=starter, 30=solo, 40=team, 50=agency, 99=enterprise
    stripe_price_id     TEXT        NOT NULL DEFAULT '',
    stripe_product_id   TEXT        NOT NULL DEFAULT '',
    amount_cents        INTEGER     NOT NULL DEFAULT 0,
    currency            TEXT        NOT NULL DEFAULT 'cad',
    billing_interval    TEXT        NOT NULL DEFAULT 'month',
    display_name        TEXT        NOT NULL DEFAULT '',
    features            JSONB       NOT NULL DEFAULT '[]',
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, tier_name, billing_interval)
);

CREATE INDEX IF NOT EXISTS idx_subscription_plans_product ON subscription_plans (product_id, is_active);
CREATE INDEX IF NOT EXISTS idx_subscription_plans_stripe_price ON subscription_plans (stripe_price_id) WHERE stripe_price_id != '';

-- Extend billing_subscriptions
ALTER TABLE billing_subscriptions ADD COLUMN IF NOT EXISTS tier_name TEXT;
ALTER TABLE billing_subscriptions ADD COLUMN IF NOT EXISTS product_id TEXT;

-- Seed free tiers + paid plans (Stripe IDs populated later)
INSERT INTO subscription_plans (product_id, tier_name, tier_rank, amount_cents, display_name)
VALUES
  ('gov_watch',    'free',       0,  0,     'Gov Watch Free'),
  ('gov_watch',    'solo',      30,  999,   'Gov Watch Solo'),
  ('gov_watch',    'team',      40,  2999,  'Gov Watch Team'),
  ('gov_watch',    'agency',    50,  7999,  'Gov Watch Agency'),
  ('wtf',          'free',       0,  0,     'What The Fact Free'),
  ('wtf',          'starter',   10,  499,   'What The Fact Starter'),
  ('civic_watch',  'free',       0,  0,     'Civic Watch Free'),
  ('civic_watch',  'starter',   10,  499,   'Civic Watch Starter'),
  ('legal_watch',  'free',       0,  0,     'Legal Watch Free'),
  ('legal_watch',  'starter',   10,  499,   'Legal Watch Starter'),
  ('market_watch', 'free',       0,  0,     'Market Watch Free'),
  ('market_watch', 'starter',   10,  499,   'Market Watch Starter'),
  ('kbs',          'free',       0,  0,     'Business Suite Free'),
  ('kbs',          'solo',      30,  2999,  'Business Suite Solo'),
  ('kbs',          'team',      40,  7999,  'Business Suite Team'),
  ('kbs',          'agency',    50,  14999, 'Business Suite Agency')
ON CONFLICT (product_id, tier_name, billing_interval) DO NOTHING;

-- Bundle rows
INSERT INTO subscription_plans (product_id, tier_name, tier_rank, amount_cents, display_name, features)
VALUES
  ('bundle_watch',        'active', 30, 1299,  'Watch Bundle',        '["gov_watch","civic_watch","legal_watch","market_watch"]'),
  ('bundle_intelligence', 'active', 40, 1999,  'Intelligence Bundle', '["gov_watch","civic_watch","legal_watch","market_watch","wtf"]')
ON CONFLICT (product_id, tier_name, billing_interval) DO NOTHING;
```

---

## New Files to Create

### `platform_v2/services/watch_billing_handler.py`

Follow `ksm_billing_handler.py` exactly. Key additions:

```python
PRODUCT_STANDALONE_URLS = {
    "gov_watch":    os.getenv("GOV_WATCH_URL",    "http://100.64.0.1:8102"),  # mesh IP for VPS
    "civic_watch":  os.getenv("CIVIC_WATCH_URL",  "http://100.64.0.1:8099"),
    "legal_watch":  os.getenv("LEGAL_WATCH_URL",  "http://100.64.0.1:8100"),
    "market_watch": os.getenv("MARKET_WATCH_URL", "http://100.64.0.1:8101"),
    "wtf":          os.getenv("WTF_CONSUMER_URL", "http://100.64.0.1:8103"),
    "kbs":          os.getenv("KBS_URL",           "http://192.168.1.200:8091"),  # hub
}

def _lookup_product_for_price(stripe_price_id: str) -> tuple[str | None, str | None]:
    """Returns (product_id, tier_name) for a Stripe price ID."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT product_id, tier_name FROM subscription_plans WHERE stripe_price_id = %s LIMIT 1",
            (stripe_price_id,),
        )
        row = cur.fetchone()
        return (row["product_id"], row["tier_name"]) if row else (None, None)
```

**CRITICAL:** Register ONE handler for `checkout.session.completed` that internally routes via `_lookup_product_for_price()`. Do NOT register two handlers for the same prefix — `billing_webhook.dispatch_event` uses longest-prefix matching.

---

## Files to Modify

### `platform_v2/services/subscription_service.py`

Add after line 42:
```python
def resolve_tier_for_product(stripe_price_id: str, product_id: str) -> str:
    """DB-backed tier resolution. Falls back to keyword heuristic."""
    if not stripe_price_id:
        return "free"
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT tier_name FROM subscription_plans WHERE stripe_price_id = %s AND product_id = %s LIMIT 1",
                (stripe_price_id, product_id),
            )
            row = cur.fetchone()
            if row:
                return row["tier_name"]
    except Exception:
        logger.exception("resolve_tier_for_product failed")
    # Fallback keyword heuristic
    pid = stripe_price_id.lower()
    for keyword in ("enterprise", "agency", "team", "solo", "starter"):
        if keyword in pid:
            return keyword
    return "free"
```

Deprecate `_resolve_tier_from_price` (keep as fallback, don't delete yet).

### `platform_v2/oauth_userinfo.py` lines 99-105

Replace keyword tier resolution with `resolve_tier_for_product(price_id, module)`. The `product_tiers` dict shape stays the same — just the resolution logic becomes DB-backed with canonical vocabulary.

### `mnt/standalone/kytran-gov-watch/app.py` line ~1438

```python
# BEFORE:
incoming_tier = (user.get("subscription_tier") or "free").lower()

# AFTER:
product_tiers = user.get("product_tiers") or {}
incoming_tier = (product_tiers.get("gov_watch") or user.get("subscription_tier") or "free").lower()
```

Apply same pattern to civic-watch, legal-watch, market-watch, wtf standalones.

---

## Data Flow (Post-Phase-1)

```
User subscribes → hub /subscribe/bundle/watch_bundle
  → Stripe checkout → webhook checkout.session.completed
  → watch_billing_handler → _lookup_product_for_price() → (bundle_watch, active)
  → billing_bundle_products → [gov_watch, civic_watch, legal_watch, market_watch]
  → for each: _push_tier_to_standalone(product_id, user_id, 'starter')
  → update billing_subscriptions.tier_name, .product_id

User logs into gov-watch via SSO
  → oauth_userinfo → {product_tiers: {gov_watch: "starter"}, entitlements: [...]}
  → _sync_user_tier reads product_tiers["gov_watch"] = "starter"
  → user_profiles.tier = "starter" (never downgraded if already higher)
  → Feature gates read local user_profiles.tier — no live hub call per request
```

---

## Bundle Pricing (CAD/month)

| Product | Free | Starter | Solo | Team | Agency |
|---------|------|---------|------|------|--------|
| Gov Watch | $0 | — | $9.99 | $29.99 | $79.99 |
| WTF | $0 | $4.99 | — | — | — |
| Civic Watch | $0 | $4.99 | — | — | — |
| Legal Watch | $0 | $4.99 | — | — | — |
| Market Watch | $0 | $4.99 | — | — | — |
| KBS | $0 | — | $29.99 | $79.99 | $149.99 |
| **Watch Bundle** | — | — | **$12.99** (4 products) | — | — |
| **Intelligence Bundle** | — | — | — | **$19.99** (5 products + WTF) | — |

Both bundle prices already coded in `bundle_checkout_service.py`. Just need Stripe price IDs.

---

## Build Sequence

- [ ] **1A — Schema**: Run `395_unified_pricing_plans.sql`
- [ ] **1B — Backend**: Add `resolve_tier_for_product()` to `subscription_service.py`; create `watch_billing_handler.py`; register in `app.py` + `billing_routes.py`
- [ ] **1C — OAuth fix**: Update `oauth_userinfo.py` lines 99-105 to use DB-backed resolution
- [ ] **1D — Standalone sync fix**: Update `_sync_user_tier` in all 5 standalones to read `product_tiers["<product_id>"]`
- [ ] **1E — Stripe products**: Create products + prices in Stripe dashboard; populate `stripe_price_id` in `subscription_plans`
- [ ] **1F — Validate**: `stripe trigger checkout.session.completed` → verify `billing_subscriptions.tier_name` populated → login to gov-watch → verify `user_profiles.tier`

---

## Open Questions (Business Decisions Required)

1. Should WTF have a `team` tier (multi-seat newsroom access)?
2. Annual billing discount — 20% off? Needs annual price IDs in `subscription_plans`.
3. Does Watch Bundle grant `starter` or `solo` tier on gov-watch? (Starter has fewer features)
4. KBS billing: hub Stripe account or separate KBS Stripe connect?
5. Proration behavior on mid-cycle upgrades — use `create_prorations` or `none`?

---

## Key Gotchas

- **Webhook handler registration**: One handler per event prefix — `checkout.session.completed` must have ONE unified handler that routes internally. Two handlers for same prefix = only the last registered fires.
- **VPS network path**: Use mesh IP `100.64.0.1` (Outpost) for VPS-hosted standalones in `_push_tier_to_standalone()`, NOT public CDN hostname (60s cap). KSM uses public URL — fix this in Watch handler.
- **No-downgrade invariant**: The numeric tier hierarchy in `_sync_user_tier` must be preserved. A bundle cancellation pushing `free` should be accepted only if no other active subscription exists for that product.
- **KBS invoice payments ≠ KBS subscription billing**: `kbs_invoicing` plugin handles client invoices; hub `billing_subscriptions` handles KBS access tiers. Do not conflate.
