# Billing Infrastructure Rules

## Key Finding: 80% Already Built

Before adding anything, read these existing files:

| File | What it does |
|------|-------------|
| `platform_v2/services/stripe_service.py` | Full Stripe SDK: customer, checkout, portal, subscription CRUD |
| `platform_v2/services/subscription_service.py` | `get_user_entitlements()`, `get_user_membership_tier()`, `resolve_tier_for_product()` |
| `platform_v2/services/billing_webhook.py` | Idempotent webhook pipeline: verify sig → dedupe → prefix-dispatch |
| `platform_v2/services/ksm_billing_handler.py` | KSM pattern: webhook → resolve tier → `_push_tier_to_standalone()` |
| `platform_v2/services/watch_billing_handler.py` | Watch products pattern (created 2026-05-25) |
| `platform_v2/tools/account_center/bundle_checkout_service.py` | `watch_bundle` ($12.99/mo) + `intelligence_bundle` ($19.99/mo) |
| `platform_v2/oauth_userinfo.py` | Returns `entitlements` + `product_tiers` dict with bundle expansion |

## DB Schema (Billing Tables)

| Table | Key columns |
|-------|-------------|
| `billing_customers` | `user_id, stripe_customer_id, email, name` |
| `billing_products` | `stripe_product_id, stripe_price_id, module, name, amount_cents, currency, billing_interval, is_active` |
| `billing_subscriptions` | `user_id, stripe_subscription_id, stripe_price_id, module, status, billing_cycle, bundle_id, tier_name, product_id` |
| `billing_bundle_products` | `bundle_id, product_id` |
| `billing_events` | Idempotency log for webhooks |
| `billing_product_plans` | Canonical plan registry (migration 395): `product_id, tier_name, tier_rank, stripe_price_id, amount_cents` — NOTE: `subscription_plans` already exists with a different legacy schema (plan registry for `subscriptions` table), do NOT confuse |

## Canonical Tier Vocabulary (standardized 2026-05-25)

```
free → starter → solo → team → agency → enterprise
```

Tier ranks: `free=0, starter=10, solo=30, team=40, agency=50, enterprise=99`

**Do NOT use** `viewer / professional / vip / business` — these are legacy keyword-match artefacts in `_resolve_tier_from_price()`. New code uses `resolve_tier_for_product(stripe_price_id, product_id)` (DB-backed).

## Product ID Map

| product_id | Standalone | URL env var |
|------------|-----------|-------------|
| `gov_watch` | Gov Watch :8102 | `GOV_WATCH_URL` |
| `civic_watch` | Civic Watch :8099 | `CIVIC_WATCH_URL` |
| `legal_watch` | Legal Watch :8100 | `LEGAL_WATCH_URL` |
| `market_watch` | Market Watch :8101 | `MARKET_WATCH_URL` |
| `wtf` | WTF :8103 | `WTF_CONSUMER_URL` |
| `kbs` | Business Suite :8091 | `KBS_URL` |
| `bundle_watch` | 4-product bundle | — |
| `bundle_intelligence` | 5-product + WTF bundle | — |

## Bundle Pricing (CAD/month)

| Product | Free | Starter | Solo | Team | Agency |
|---------|------|---------|------|------|--------|
| Gov Watch | $0 | — | $9.99 | $29.99 | $79.99 |
| WTF | $0 | $4.99 | — | — | — |
| Civic/Legal/Market Watch | $0 | $4.99 each | — | — | — |
| Watch Bundle (4 products) | — | — | $12.99 | — | — |
| Intelligence Bundle (5+WTF) | — | — | — | $19.99 | — |

## Webhook Handler Pattern (CRITICAL)

**One handler per event prefix** — `billing_webhook.dispatch_event` uses longest-prefix matching. Registering two handlers for the same prefix = only last one fires.

```python
# Registration in billing_routes.py / app.py:
billing_webhook.register_handler("checkout.session.completed", watch_billing_handler.handle)
# NOT: register two handlers for "checkout.session.completed"
```

Watch handler routes internally via `_lookup_product_for_price()`:
```python
product_id, tier_name = _lookup_product_for_price(stripe_price_id)
```

## Standalone Tier Sync Pattern

All standalones must read `product_tiers["<product_id>"]` first, then fall back to `subscription_tier`:

```python
# In _sync_user_tier() of each standalone app.py:
product_tiers = user.get("product_tiers") or {}
incoming_tier = (product_tiers.get("gov_watch") or user.get("subscription_tier") or "free").lower()
```

**No-downgrade invariant:** Tier hierarchy is numeric. Only upgrade, never downgrade. A subscription cancellation pushing `free` is accepted only if no higher-tier subscription exists.

## Kytran's Tier

- `kytranempowerment@gmail.com` and all alias emails: ALWAYS `kytran` tier (rank 99+)
- `_sync_user_tier()` uses numeric hierarchy — any `kytran/owner` tier is NEVER overwritten by `free`
- See `gov-watch.md` for the numeric hierarchy lookup table

## Push Tier to Standalone

```python
def _push_tier_to_standalone(product_id: str, user_id: int, tier: str) -> bool:
    url = PRODUCT_STANDALONE_URLS.get(product_id)
    if not url:
        return False
    # Use mesh IP (100.64.0.1 for outpost), NOT public CDN hostname
    resp = requests.post(
        f"{url}/api/internal/set-tier",
        json={"user_id": user_id, "tier": tier},
        headers={"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")},
        timeout=10,
    )
    return resp.ok
```

## Gotchas

- **VPS network**: Use mesh IP `100.64.0.2` (Outpost) in `PRODUCT_STANDALONE_URLS` — NOT public CDN hostname (60s cap, bypasses queue)
- **KBS billing ≠ KBS invoicing**: `kbs_invoicing` plugin = client invoices. Hub `billing_subscriptions` = KBS access tiers. Never conflate.
- **Stripe IDs**: `subscription_plans.stripe_price_id` starts empty (`''`) — populate from Stripe dashboard. Check `WHERE stripe_price_id != ''` before doing price lookups.
- **Idempotency**: `billing_events` table dedupes webhooks by `stripe_event_id`. All webhook handlers must check this first via `billing_webhook.is_processed(event_id)`.
- **Annual billing**: Not yet implemented. `billing_interval='month'` is the only active interval. Annual rows can be seeded later.
