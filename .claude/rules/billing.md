# Billing Infrastructure Rules

## Stripe Account — Source of Truth

**All Stripe credentials come from KBS.** The `KBS_STRIPE_SECRET_KEY` in `/mnt/archie_brain/kytran-business-suite/.env` is the live restricted key for the `51RiHp80` account. The platform `.env` files mirror it as `STRIPE_SECRET_KEY`.

| File | Key name | Value source |
|------|----------|-------------|
| `kytran-business-suite/.env` | `KBS_STRIPE_SECRET_KEY` | **Canonical source** — update here first |
| `platform_v2/.env` | `STRIPE_SECRET_KEY` | Copy from KBS |
| `.env` (root) | `STRIPE_SECRET_KEY` | Copy from KBS |

**KBS Stripe interface (future task)** — KBS should expose a Stripe management UI (products, prices, subscriptions, webhooks) so Kytran can manage billing from the business suite rather than the Stripe dashboard. Task to be created.

## Stripe Price Registry (billing_product_plans — populated 2026-05-25)

| product_id | tier_name | stripe_price_id | amount_cents (CAD) |
|------------|-----------|-----------------|-------------------|
| wtf | starter | price_1Tb2ye06cZ0yWDKJSRwxJHxu | 499 |
| civic_watch | starter | price_1Tb2ye06cZ0yWDKJgvsB0lBq | 499 |
| legal_watch | starter | price_1Tb2yf06cZ0yWDKJzG9kGVK2 | 499 |
| market_watch | starter | price_1Tb2yf06cZ0yWDKJGtwPQy90 | 499 |
| gov_watch | solo | price_1Tb2yg06cZ0yWDKJ14dX1JYP | 999 |
| gov_watch | team | price_1Tb2yg06cZ0yWDKJgfjyosWD | 2999 |
| gov_watch | agency | price_1Tb2yh06cZ0yWDKJ4O4Bp6Uc | 7999 |
| bundle_watch | solo | price_1Taji206cZ0yWDKJi7GavKYw | 1299 |
| bundle_intelligence | team | price_1Taji206cZ0yWDKJcZB1qYc6 | 1999 |

Free tiers have no Stripe price (gated at app layer). All prices are CAD, monthly recurring.
New prices: created 2026-05-25 via API. Bundles reuse existing prices from WTF Bundle Subscriptions product.

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

**Endpoint status** — which standalones have `/api/internal/set-tier` implemented:

| Standalone | Endpoint | INTERNAL_API_KEY in VPS .env | Verified |
|-----------|---------|------------------------------|---------|
| `gov_watch` | ✅ Added 2026-05-26 | ✅ Added 2026-05-26 | ✅ Live test passed |
| `civic_watch` | ✅ Added 2026-05-26 | ✅ Added 2026-05-26 | ✅ Live test passed |
| `legal_watch` | ✅ Added 2026-05-26 | ✅ Added 2026-05-26 | ✅ Live test passed |
| `market_watch` | ✅ Added 2026-05-26 | ✅ Added 2026-05-26 | ✅ Live test passed |
| `wtf` | ✅ Added 2026-05-26 | ✅ Added 2026-05-26 | ✅ Live test passed |

**Note**: civic_watch and market_watch docker-compose.yml required explicit `INTERNAL_API_KEY=${INTERNAL_API_KEY:-}` in `environment:` block (no `env_file:` directive). Always add new internal keys to both `.env` AND the `environment:` block for these two products.

Local tier mapping per standalone (canonical → local):
- `gov_watch`: PostgreSQL `user_profiles`, canonical tiers (kytran/owner/admin=99… free=0)
- `civic_watch`, `legal_watch`: non-free → `"pro"` | free → `"free"`
- `market_watch`: non-free → `"ai"` | free → `"free"`
- `wtf`: canonical tier stored as-is (starter/solo/etc. all valid in `_SUBSCRIBED_TIERS`)

**Implementation pattern** (copy from gov-watch `app.py` `internal_set_tier()`):
- Auth: `X-Internal-Key` header == `INTERNAL_API_KEY` env var
- Payload: `{"email": "...", "tier": "..."}` — use **email** as the key, not user_id
- No-downgrade enforced on each standalone's tier store
- Valid tiers: `kytran, owner, admin, pro, agency, team, solo, starter, free`

```python
def _push_tier_to_standalone(product_id: str, user_id: int, tier: str, email: str | None = None) -> bool:
    url = PRODUCT_STANDALONE_URLS.get(product_id)
    if not url:
        return False
    payload: dict = {"user_id": user_id, "tier": tier}
    if email:
        payload["email"] = email.strip().lower()
    # Use mesh IP (100.64.0.2 for outpost), NOT public CDN hostname
    resp = requests.post(
        f"{url}/api/internal/set-tier",
        json=payload,
        headers={"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")},
        timeout=10,
    )
    return resp.ok
```

## Webhook Registration (updated 2026-05-26)

### Live endpoint
| Webhook ID | URL | Events | Secret env var |
|------------|-----|--------|----------------|
| `we_1TbKoa06cZ0yWDKJ6OZgkm5v` | `https://platform.kytranempowerment.com/api/billing/webhook` | `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted` | `STRIPE_WEBHOOK_SECRET` in root `.env` |

**`STRIPE_WEBHOOK_SECRET` source of truth**: root `.env` (not `platform_v2/.env` — container reads root via `env_file: .env`).

### Deleted standalone endpoints (cleaned up 2026-05-26)
These 7 dead endpoints were registered before standalones got `/api/internal/set-tier`. All deleted via API on 2026-05-26:
- `we_1TYDdh...` → what-the-fact.com/billing/webhook ✅ deleted
- `we_1TX8ue...` → civic.kytranempowerment.com/billing/webhook ✅ deleted
- `we_1TX8or...` (×2) → what-the-fact.com + market.kytranempowerment.com/billing/webhook ✅ deleted
- `we_1TX8oq...` → legal.kytranempowerment.com/billing/webhook ✅ deleted
- `we_1TX3Mi...` → civic.kytranempowerment.com/billing/webhook (dupe) ✅ deleted
- `we_1TX3GC...` → gov.kytranempowerment.com/billing/webhook ✅ deleted

## Gotchas

- **VPS network**: Use mesh IP `100.64.0.2` (Outpost) in `PRODUCT_STANDALONE_URLS` — NOT public CDN hostname (60s cap, bypasses queue)
- **KBS billing ≠ KBS invoicing**: `kbs_invoicing` plugin = client invoices. Hub `billing_subscriptions` = KBS access tiers. Never conflate.
- **Stripe IDs**: `subscription_plans.stripe_price_id` starts empty (`''`) — populate from Stripe dashboard. Check `WHERE stripe_price_id != ''` before doing price lookups.
- **Idempotency**: `billing_events` table dedupes webhooks by `stripe_event_id`. All webhook handlers must check this first via `billing_webhook.is_processed(event_id)`.
- **Annual billing**: Not yet implemented. `billing_interval='month'` is the only active interval. Annual rows can be seeded later.
- **Docker secrets override env vars**: Stripe keys are loaded from `secrets/stripe/*.txt` files (Docker secrets), NOT from `.env`. `_read_secret()` checks `/run/secrets/` first. To update Stripe keys: edit `secrets/stripe/webhook_secret.txt` + `secret_key.txt`, then `docker compose up -d --no-deps --force-recreate archie_platform` (KB #268834).
- **Env reload**: `docker compose restart` does NOT re-read `env_file:` — must use `docker compose up -d --no-deps archie_platform` after `.env` changes (KB #268829).
- **Container reads root `.env`**: `archie_platform` uses `env_file: .env` (root). Changes to `platform_v2/.env` alone do NOT affect the running container.
- **DB is read-only**: `docker cp` to `archie_database` fails. Use `docker exec -i archie_database psql -U archie -d archie < migration.sql` instead (KB #268830).
- **FK cleanup order**: To delete a test user: `billing_subscriptions` → `billing_customers` → `users`. No CASCADE is set (KB #268831).
- **RealDictCursor**: `get_db_cursor()` returns dict rows. Use `row['id']` not `row[0]` in simulation/admin scripts (KB #268832).
