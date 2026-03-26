# KSM Stripe Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire KSM feature gating to Stripe subscriptions — product registration, checkout flow, webhook-driven tier updates.

**Architecture:** Standalone initiates checkout via ARCHIE hub API. Stripe processes payment. ARCHIE webhook handler maps price to tier and pushes update back to standalone via authenticated API call. Standalone's `set_user_tier()` unlocks features immediately.

**Tech Stack:** Python/Flask, Stripe SDK, hub_client (existing), subscription_service (existing)

---

## File Map

### ARCHIE
| Action | File | What |
|--------|------|------|
| Create | `platform_v2/services/ksm_billing_handler.py` | Webhook handler + tier push |
| Create | `scripts/register_ksm_stripe_products.py` | One-time product registration |
| Modify | `platform_v2/app.py` | Register KSM handler at startup |

### Standalone
| Action | File | What |
|--------|------|------|
| Modify | `services/hub_client.py` | Add create_checkout_session() |
| Create | `routes/billing_routes.py` | Tier update receiver + success/cancel |
| Modify | `routes/__init__.py` | Register billing routes |
| Modify | `templates/upgrade_required.html` | Real checkout buttons |
| Modify | `templates/settings.html` | Upgrade section |

---

### Task 1: Register KSM Products in Stripe + billing_products

**Files:**
- Create: `scripts/register_ksm_stripe_products.py`

- [ ] **Step 1: Create product registration script**

```python
#!/usr/bin/env python3
"""Register KSM subscription products in Stripe and billing_products table.

Run once: docker exec archie_platform python3 /mnt/archie_brain/scripts/register_ksm_stripe_products.py
"""
import sys
sys.path.insert(0, "/app")

from services.stripe_service import init_stripe, register_product, is_stripe_configured
import stripe

init_stripe()

if not is_stripe_configured():
    print("ERROR: Stripe not configured. Add real API keys to secrets/stripe/")
    sys.exit(1)

PRODUCTS = [
    {"name": "KSM Pro", "amount": 2900, "tier": "pro"},
    {"name": "KSM Business", "amount": 4900, "tier": "business"},
    {"name": "KSM Enterprise", "amount": 9900, "tier": "enterprise"},
]

for p in PRODUCTS:
    # Create Stripe product
    product = stripe.Product.create(
        name=p["name"],
        description=f"Kytran System Operations — {p['tier'].title()} tier",
        metadata={"module": "ksm", "tier": p["tier"]},
    )
    print(f"Created product: {product.id} ({p['name']})")

    # Create Stripe price
    price = stripe.Price.create(
        product=product.id,
        unit_amount=p["amount"],
        currency="usd",
        recurring={"interval": "month"},
        metadata={"tier": p["tier"]},
    )
    print(f"  Price: {price.id} (${p['amount']/100}/mo)")

    # Register in billing_products
    register_product(
        module="ksm",
        stripe_product_id=product.id,
        stripe_price_id=price.id,
        name=p["name"],
        amount_cents=p["amount"],
        billing_interval="month",
        description=f"{p['tier'].title()} tier — ${p['amount']/100}/month",
    )
    print(f"  Registered in billing_products")

print("\nDone! 3 KSM products registered.")
```

- [ ] **Step 2: Run the script (only after real Stripe keys are configured)**

```bash
docker exec archie_platform python3 /mnt/archie_brain/scripts/register_ksm_stripe_products.py
```

NOTE: This requires real Stripe API keys. If still using placeholders, skip this step — products will be created when keys are provided.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add scripts/register_ksm_stripe_products.py
git commit -m "feat(ksm-billing): add KSM product registration script for Stripe"
```

---

### Task 2: KSM Webhook Handler on ARCHIE

**Files:**
- Create: `platform_v2/services/ksm_billing_handler.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Create ksm_billing_handler.py**

```python
"""KSM-specific Stripe webhook handler — pushes tier updates to standalone."""

import os
import logging
import base64
import requests
from database import get_db_cursor

logger = logging.getLogger(__name__)

STANDALONE_URL = os.getenv("STANDALONE_SYSOPS_URL", "http://192.168.1.200:8085")


def _get_tier_for_price(price_id):
    """Look up tier for a Stripe price ID from billing_products."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT name, amount_cents FROM billing_products WHERE stripe_price_id = %s AND module = 'ksm'",
            (price_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        # Derive tier from product name
        name_lower = row["name"].lower()
        if "enterprise" in name_lower:
            return "enterprise"
        elif "business" in name_lower:
            return "business"
        elif "pro" in name_lower:
            return "pro"
        return None


def _get_standalone_auth():
    """Build auth header for standalone API calls."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT client_id, client_secret FROM oauth_clients WHERE client_id = 'kytran-sysops' AND is_active = TRUE"
        )
        row = cur.fetchone()
        if not row:
            return {}
    credentials = f"{row['client_id']}:{row['client_secret']}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Bearer {encoded}"}


def _push_tier_to_standalone(user_id, tier):
    """Push tier update to standalone via API."""
    url = f"{STANDALONE_URL}/api/billing/tier-update"
    try:
        resp = requests.post(
            url,
            json={"user_id": user_id, "tier": tier},
            headers=_get_standalone_auth(),
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("[KSM Billing] Tier pushed: user %s → %s", user_id, tier)
            return True
        else:
            logger.warning("[KSM Billing] Tier push failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.error("[KSM Billing] Tier push error: %s", e)
        return False


def _get_user_id_for_stripe_customer(stripe_customer_id):
    """Look up ARCHIE user_id from billing_customers."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT user_id FROM billing_customers WHERE stripe_customer_id = %s",
            (stripe_customer_id,),
        )
        row = cur.fetchone()
        return row["user_id"] if row else None


def handle_ksm_checkout_completed(event):
    """checkout.session.completed — determine tier from price, push to standalone."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")
    mode = obj.get("mode", "")

    if mode != "subscription":
        return "not_subscription"

    subscription_id = obj.get("subscription", "")
    if not subscription_id:
        return "no_subscription_id"

    # Fetch subscription to get price
    try:
        import stripe
        sub = stripe.Subscription.retrieve(subscription_id)
        price_id = sub["items"]["data"][0]["price"]["id"] if sub.get("items", {}).get("data") else None
    except Exception as e:
        logger.error("[KSM Billing] Failed to retrieve subscription: %s", e)
        return f"error: {e}"

    if not price_id:
        return "no_price_id"

    tier = _get_tier_for_price(price_id)
    if not tier:
        return f"unknown_price: {price_id}"

    user_id = _get_user_id_for_stripe_customer(customer_id)
    if not user_id:
        logger.warning("[KSM Billing] No user found for Stripe customer %s", customer_id)
        return "no_user_found"

    _push_tier_to_standalone(user_id, tier)
    return f"tier_set:{tier}"


def handle_ksm_subscription_updated(event):
    """customer.subscription.updated — detect tier change, push new tier."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")
    status = obj.get("status", "")

    if status not in ("active", "trialing"):
        return f"status:{status}"

    price_id = None
    items = obj.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")

    if not price_id:
        return "no_price_id"

    tier = _get_tier_for_price(price_id)
    if not tier:
        return f"unknown_price: {price_id}"

    user_id = _get_user_id_for_stripe_customer(customer_id)
    if user_id:
        _push_tier_to_standalone(user_id, tier)
    return f"tier_updated:{tier}"


def handle_ksm_subscription_deleted(event):
    """customer.subscription.deleted — revert to free tier."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")

    user_id = _get_user_id_for_stripe_customer(customer_id)
    if user_id:
        _push_tier_to_standalone(user_id, "free")
    return "tier_reverted:free"


def register_ksm_billing_handlers():
    """Register KSM webhook handlers with Stripe Core dispatcher."""
    from services.billing_webhook import register_billing_handler

    register_billing_handler("checkout.session.completed", handle_ksm_checkout_completed)
    register_billing_handler("customer.subscription.updated", handle_ksm_subscription_updated)
    register_billing_handler("customer.subscription.deleted", handle_ksm_subscription_deleted)

    logger.info("KSM billing handlers registered (3 event types)")
```

- [ ] **Step 2: Register in app.py**

Read `app.py`, find where billing routes or CRM handlers are registered. Add:

```python
from services.ksm_billing_handler import register_ksm_billing_handlers  # noqa: E402
register_ksm_billing_handlers()
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/ksm_billing_handler.py platform_v2/app.py
git commit -m "feat(ksm-billing): add webhook handler — push tier updates to standalone"
```

---

### Task 3: Standalone Tier Update Receiver + Checkout Client

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/billing_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/services/hub_client.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Read hub_client.py and routes/__init__.py**

Read both files to understand patterns.

- [ ] **Step 2: Add create_checkout_session to hub_client.py**

```python
def create_checkout_session(price_id, success_url, cancel_url, user_id):
    """Create Stripe Checkout session via ARCHIE hub."""
    cfg = _get_hub_config()
    if not cfg["hub_url"] or not cfg["client_secret"]:
        return None

    url = f"{cfg['hub_url']}/api/billing/checkout"
    try:
        resp = requests.post(url, json={
            "price_id": price_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }, headers=_hub_auth_header(), timeout=10)
        if resp.status_code == 200:
            return resp.json().get("checkout_url")
        return None
    except Exception as e:
        logger.warning(f"Checkout session failed: {e}")
        return None
```

IMPORTANT: Read the file first — match the existing auth function name and config access pattern.

- [ ] **Step 3: Create billing_routes.py on standalone**

```python
"""Billing routes — tier update receiver, checkout flow, success/cancel pages."""

import logging
import base64
from flask import jsonify, request, render_template_string, redirect, current_app
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)

TIER_UPDATE_HTML = """<!DOCTYPE html>
<html><head><title>%(title)s</title>
<style>body{background:#0a0a0f;color:#F8FAFC;font-family:'IBM Plex Mono',monospace;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.card{text-align:center;padding:40px;border:1px solid rgba(139,92,246,0.3);border-radius:12px;background:rgba(15,23,42,0.6);max-width:400px;}
h1{color:%(color)s;font-size:1.5rem;margin:0 0 12px;}
p{color:rgba(255,255,255,0.6);font-size:14px;line-height:1.6;}
a{color:#8b5cf6;text-decoration:none;display:inline-block;margin-top:16px;padding:10px 24px;border:1px solid rgba(139,92,246,0.4);border-radius:8px;}
a:hover{background:rgba(139,92,246,0.15);}</style></head>
<body><div class="card"><h1>%(title)s</h1><p>%(message)s</p><a href="/dashboard/">Go to Dashboard</a></div></body></html>"""


def _validate_hub_auth():
    """Validate hub client credentials from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    try:
        decoded = base64.b64decode(auth[7:]).decode()
        client_id, client_secret = decoded.split(":", 1)
    except Exception:
        return False

    # Validate against configured credentials
    config = current_app.config
    expected_id = config.get("ARCHIE_CLIENT_ID", "kytran-sysops")
    expected_secret = config.get("ARCHIE_CLIENT_SECRET", "")
    return client_id == expected_id and client_secret == expected_secret and expected_secret


def register_billing_routes(bp, admin_required):

    @bp.route("/api/billing/tier-update", methods=["POST"])
    def billing_tier_update():
        """Receive tier update push from ARCHIE hub."""
        if not _validate_hub_auth():
            return jsonify({"error": "unauthorized"}), 401

        data = request.get_json() or {}
        user_id = data.get("user_id")
        tier = data.get("tier")

        if not user_id or not tier:
            return jsonify({"error": "user_id and tier required"}), 400

        try:
            from ..services.subscription_service import set_user_tier
            set_user_tier(user_id, tier)
            logger.info("Tier updated via hub push: user %s → %s", user_id, tier)
            return jsonify({"success": True, "user_id": user_id, "tier": tier})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/billing/checkout", methods=["POST"])
    @login_required
    def billing_checkout():
        """Create Stripe Checkout session via hub."""
        from ..services.hub_client import create_checkout_session, is_hub_configured

        if not is_hub_configured():
            return jsonify({"error": "Hub not configured"}), 503

        data = request.get_json() or {}
        price_id = data.get("price_id")
        if not price_id:
            return jsonify({"error": "price_id required"}), 400

        base_url = request.url_root.rstrip("/")
        success_url = f"{base_url}/dashboard/billing/success"
        cancel_url = f"{base_url}/dashboard/billing/cancel"

        checkout_url = create_checkout_session(price_id, success_url, cancel_url, current_user.id)
        if not checkout_url:
            return jsonify({"error": "Failed to create checkout session"}), 500

        return jsonify({"success": True, "checkout_url": checkout_url})

    @bp.route("/billing/success")
    def billing_success():
        """Payment success page."""
        return TIER_UPDATE_HTML % {
            "title": "Payment Successful!",
            "message": "Your subscription has been activated. Features will unlock within moments.",
            "color": "#22c55e",
        }

    @bp.route("/billing/cancel")
    def billing_cancel():
        """Payment cancelled page."""
        return TIER_UPDATE_HTML % {
            "title": "Payment Cancelled",
            "message": "No worries — you can upgrade anytime from your settings page.",
            "color": "#f59e0b",
        }
```

- [ ] **Step 4: Register in __init__.py**

```python
from .billing_routes import register_billing_routes
register_billing_routes(bp, admin_required_decorator)
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/billing_routes.py kytran_server_manager/routes/__init__.py kytran_server_manager/services/hub_client.py
git commit -m "feat(ksm-billing): add tier update receiver + checkout flow + hub client"
```

---

### Task 4: Upgrade Buttons in Templates

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/templates/upgrade_required.html`
- Modify: `kytran-server-manager/kytran_server_manager/templates/settings.html`

- [ ] **Step 1: Read both templates**

Read `upgrade_required.html` and `settings.html` to understand current structure.

- [ ] **Step 2: Add checkout buttons to upgrade_required.html**

Find the existing "Upgrade" button/link. Replace with a JS-powered checkout button:

```javascript
function startCheckout(priceId) {
    fetch('/dashboard/api/billing/checkout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({price_id: priceId})
    })
    .then(r => r.json())
    .then(d => {
        if (d.checkout_url) window.location.href = d.checkout_url;
        else alert(d.error || 'Checkout failed');
    })
    .catch(() => alert('Checkout unavailable'));
}
```

For each tier in the pricing table, the CTA button calls `startCheckout(priceId)`. The price IDs come from the billing products — pass them as data attributes or fetch from `/dashboard/api/subscription/status`.

IMPORTANT: Read the template first. It may already have an upgrade button — enhance it rather than replace.

- [ ] **Step 3: Add upgrade section to settings.html**

In the subscription card (added in FG9), add checkout buttons below the tier badge for users not on enterprise:

```html
{% if tier != 'enterprise' %}
<div style="margin-top:12px;">
    <button onclick="startCheckout('pro')" style="...">Upgrade to Pro — $29/mo</button>
    <button onclick="startCheckout('business')" style="...">Upgrade to Business — $49/mo</button>
</div>
{% endif %}
```

The `startCheckout` function fetches the actual price_id from the subscription status endpoint, then calls the checkout endpoint.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/upgrade_required.html kytran_server_manager/templates/settings.html
git commit -m "feat(ksm-billing): add Stripe checkout buttons to upgrade + settings pages"
```

---

### Task 5: Deploy + Verify

- [ ] **Step 1: Deploy both**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 2: Verify**

```bash
# ARCHIE — KSM handlers registered
docker logs archie_platform 2>&1 | grep "KSM billing" | tail -2

# Standalone — billing routes loaded
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:8085/dashboard/billing/success
# Expected: 200

# Tier update endpoint
curl -s -o /dev/null -w "%{http_code}" -X POST http://192.168.1.200:8085/api/billing/tier-update -H "Content-Type: application/json" -d '{}'
# Expected: 401 (auth required)
```

- [ ] **Step 3: Log decision**

```python
mcp__archie__log_decision(
    title="KSM Stripe Billing Complete — Checkout + Webhook Tier Push",
    decision="KSM subscriptions wired to Stripe. Checkout flow via hub, webhook pushes tier updates to standalone. 3 products: Pro $29, Business $49, Enterprise $99.",
    project_id=195
)
```

---

## Task Summary

| Task | Description | Codebase | Est. |
|------|-------------|----------|------|
| 1 | Register KSM products script | ARCHIE | 3 min |
| 2 | Webhook handler + tier push | ARCHIE | 5 min |
| 3 | Tier receiver + checkout client | Standalone | 5 min |
| 4 | Upgrade buttons in templates | Standalone | 5 min |
| 5 | Deploy + verify | Both | 5 min |

**Total: 5 tasks, ~23 minutes**
