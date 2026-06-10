---
name: billing-gate
description: Add a subscription paywall to any Kytran product. Checks access_grants via Account Center API and shows upgrade CTA if user is not subscribed. Use when gating a new product behind billing.
version: 1.0
author: ARCHIE Platform Team
tags: [billing, paywall, subscription, access-control, kbs]
---

# Billing Gate Skill

Use this **6-step pattern** to add a paywall to any Kytran product (standalone or platform module).

## Prerequisites

Before applying this skill, verify:
- Product is registered in both `marketplace_registry` (KBS) and `marketplace_products` (ARCHIE)
- `access_grants` table exists in ARCHIE DB
- Account Center API is live at `/tools/account-center/api/access/`
- Stripe integration is configured (test or production mode)

## Step 1: Register product in both registries

### KBS Registry (kytran-business-suite)

Create migration: `kytran-business-suite/migrations/NNNNN_add_<product>_to_marketplace.sql`

```sql
INSERT INTO marketplace_registry (slug, name, description, url, icon, category, price_monthly)
VALUES ('<slug>', '<Product Name>', '<description>', '<url>', '<icon-file>', '<category>', <price>)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  price_monthly = EXCLUDED.price_monthly;
```

Example:
```sql
INSERT INTO marketplace_registry (slug, name, description, url, icon, category, price_monthly)
VALUES ('civic-watch', 'Civic Watch', 'Municipal tender intelligence and analysis', 'https://civic.kytranempowerment.com', 'icon-civic.png', 'government', 4999)
ON CONFLICT (slug) DO UPDATE SET price_monthly = EXCLUDED.price_monthly;
```

### ARCHIE Platform Registry

Create migration: `platform_v2/database/migrations/NNNNN_add_<product>_to_marketplace.sql`

```sql
INSERT INTO marketplace_products (slug, name, url, price_monthly, is_free)
VALUES ('<slug>', '<Product Name>', '<url>', <price>, FALSE)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  price_monthly = EXCLUDED.price_monthly;
```

Run migrations:
```bash
# KBS
docker exec archie_platform psql -U kbs_admin -d kbs -f migration.sql

# ARCHIE
docker exec archie_database psql -U archie -d archie -f migration.sql
```

## Step 2: Add access check helper to product

Add to your product's Python app (standalone or module):

```python
import requests
import os
import logging

logger = logging.getLogger(__name__)

# Access check via Account Center internal API
_AC_BASE = os.getenv("AC_API_URL", "http://192.168.1.200:3000")
_AC_INTERNAL_TOKEN = os.getenv("AC_INTERNAL_TOKEN", "")

def has_product_access(user_id: int, product_slug: str) -> bool:
    """
    Check if user has access to a product via subscription or free tier.

    Returns False on AC outage to avoid blocking users (fail-open pattern).
    Change to `return True` at end if you prefer fail-closed for high-security.
    """
    try:
        headers = {}
        if _AC_INTERNAL_TOKEN:
            headers["X-Internal-Token"] = _AC_INTERNAL_TOKEN

        response = requests.get(
            f"{_AC_BASE}/tools/account-center/api/access/check",
            params={"user_id": user_id, "product": product_slug},
            headers=headers,
            timeout=5
        )
        return response.json().get("has_access", False)
    except requests.RequestException as e:
        logger.warning(f"billing gate check failed for user {user_id}: {e}")
        return False  # fail open — never block user due to AC outage
```

## Step 3: Gate the product entry point

In your product's main route (login, index, or dashboard):

```python
from flask import render_template, request, url_for
from .billing_gate import has_product_access

@app.route("/")
@login_required
def index():
    product_slug = "civic-watch"  # your product

    if not has_product_access(current_user.id, product_slug):
        kbs_url = "https://business.kytranempowerment.com"
        checkout_url = (
            f"{kbs_url}/billing/checkout"
            f"?product={product_slug}"
            f"&return_url={request.url}"
        )
        return render_template("paywall.html", upgrade_url=checkout_url)

    # user has access — show product
    return render_template("dashboard.html")
```

Create `templates/paywall.html`:

```html
{% extends "base.html" %}

{% block content %}
<div class="paywall-container">
  <div class="paywall-card">
    <h1>Unlock Civic Watch</h1>
    <p>Government tender intelligence and analysis</p>

    <div class="pricing">
      <div class="price-tag">$49.99/month</div>
      <ul class="features">
        <li>Real-time tender alerts</li>
        <li>AI bid analysis</li>
        <li>Saved supplier profiles</li>
        <li>Deadline tracking</li>
      </ul>
    </div>

    <a href="{{ upgrade_url }}" class="btn btn-primary btn-lg">
      Start Your Free Trial
    </a>
  </div>
</div>
{% endblock %}
```

## Step 4: Map Stripe price ID to product slug

In your product's `.env` file (or KBS `.env`):

```bash
# Stripe product mapping — tells KBS which product to grant access for
STRIPE_PRICE_PRICE_ABC123=civic-watch
STRIPE_PRICE_PRICE_XYZ789=legal-watch
```

Replace `PRICE_ABC123` with your actual Stripe price ID from the Products dashboard.

KBS webhook handler (`kbs_app/webhooks.py`) uses this map:
```python
def handle_stripe_subscription_created(event):
    price_id = event['data']['object']['items']['data'][0]['price']['id']
    product_slug = os.getenv(f"STRIPE_PRICE_{price_id.upper().replace('-', '_')}")

    if product_slug:
        # Grant access in ARCHIE
        create_access_grant(user_id, product_slug)
```

## Step 5: Test the full flow (Stripe test mode)

1. **Without subscription:**
   - Log in with test account
   - Navigate to product URL
   - Should see upgrade CTA with "Start Free Trial" button

2. **Trigger checkout:**
   - Click upgrade button → redirects to KBS billing page
   - Use Stripe test card: `4242 4242 4242 4242` | exp `12/25` | CVC `123`
   - Complete checkout

3. **Verify access grant:**
   ```bash
   curl -H "X-Internal-Token: ${AC_INTERNAL_TOKEN}" \
     "http://192.168.1.200:3000/tools/account-center/api/access/check?user_id=123&product=civic-watch"
   ```
   Should return: `{"has_access": true}`

4. **With subscription:**
   - Log in again
   - Navigate to product URL
   - Should pass through paywall and show dashboard

## Step 6: Deploy

Restart the affected services:

```bash
# If product is a platform module
docker compose restart archie_platform

# If product is standalone + KBS
docker compose restart kbs_app archie_platform

# Verify logs
docker logs -f archie_platform | grep "access_grant\|billing"
```

## Notes

### Fail-open vs Fail-closed

Current implementation returns `False` on Account Center outage (fail-open). This prevents blocking users but temporarily allows unsubscribed users through if AC is down.

**Change to fail-closed** (block on outage) if the product is high-security:
```python
# At end of has_product_access():
except requests.RequestException:
    logger.error(f"Account Center unavailable — blocking access")
    return True  # change to False for fail-closed
```

### Bundle discounts

If KBS has multi-product bundles (e.g., "Gov Suite" = civic + legal + market), the access check automatically honors them. No extra code needed — Account Center handles bundle expansion internally.

### Free products

For free products (is_free=TRUE in marketplace_products):
```python
def has_product_access(user_id: int, product_slug: str) -> bool:
    # Query DB to check is_free flag
    product = db.query(MarketplaceProduct).filter_by(slug=product_slug).first()
    if product and product.is_free:
        return True

    # Otherwise run access check
    ...
```

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Paywall always shows | AC returns `has_access: false` | Check KBS webhook logs — Stripe event may not have fired |
| After checkout, still shows paywall | Access grant created but with wrong user_id | Verify session user ID matches Stripe customer user_id |
| 404 on checkout URL | KBS billing page doesn't exist | Verify KBS is running and `/billing/checkout` route exists |
| AC API timeout | AC is slow or down | Check `docker logs archie_platform` for errors; paywall fails open so user still gets through |

---

**Related Skills:** subscription-tiers, kbs-webhook-integration, stripe-test-mode

**KB Sources:** #256846 (module_capability index), #258674 (delegation bridge), #260092-260095 (email manager + compose phase)
