# Stripe Core — Billing Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared Stripe billing foundation — Docker secrets, database tables, API client, webhook handler with event dispatcher, and billing API endpoints — so all modules can plug in their billing logic.

**Architecture:** Docker secrets store Stripe keys. A `stripe_service.py` wraps the Stripe SDK. A webhook handler verifies signatures and dispatches events to registered module handlers. Three DB tables (billing_customers, billing_events, billing_products) provide the shared data model. Routes expose checkout, portal, and webhook endpoints.

**Tech Stack:** Python/Flask, Stripe SDK (v7.4.0, already installed), PostgreSQL, Docker secrets

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `secrets/stripe/secret_key.txt` | Stripe secret API key |
| Create | `secrets/stripe/webhook_secret.txt` | Webhook signing secret |
| Create | `secrets/stripe/publishable_key.txt` | Publishable key for frontend |
| Modify | `docker-compose.yml` | Add Stripe secrets + mount |
| Create | `database/migrations/204_billing_core.sql` | 3 billing tables |
| Create | `platform_v2/services/stripe_service.py` | Stripe API client |
| Create | `platform_v2/services/billing_webhook.py` | Webhook handler + dispatcher |
| Create | `platform_v2/billing_routes.py` | Billing API endpoints |
| Modify | `platform_v2/app.py` | Register billing routes + init Stripe |

---

### Task 1: Docker Secrets for Stripe

**Files:**
- Create: `secrets/stripe/secret_key.txt`
- Create: `secrets/stripe/webhook_secret.txt`
- Create: `secrets/stripe/publishable_key.txt`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create secrets directory and placeholder files**

```bash
mkdir -p /mnt/archie_brain/secrets/stripe
```

The user needs to provide their actual Stripe API keys. For now, create files with test-mode placeholders that the user will replace:

```bash
echo "sk_test_REPLACE_WITH_YOUR_KEY" > /mnt/archie_brain/secrets/stripe/secret_key.txt
echo "whsec_REPLACE_WITH_YOUR_SECRET" > /mnt/archie_brain/secrets/stripe/webhook_secret.txt
echo "pk_test_REPLACE_WITH_YOUR_KEY" > /mnt/archie_brain/secrets/stripe/publishable_key.txt
```

- [ ] **Step 2: Verify .gitignore covers secrets**

```bash
grep "secrets/" /mnt/archie_brain/.gitignore
```

Expected: `secrets/` is listed. If not, add it.

- [ ] **Step 3: Read docker-compose.yml secrets section**

Read `/mnt/archie_brain/docker-compose.yml` — find the existing `secrets:` block (at the bottom, around line 440) and the `archie_platform` service's `secrets:` list.

- [ ] **Step 4: Add Stripe secrets to docker-compose.yml**

In the root-level `secrets:` block, add after `db_password`:

```yaml
  stripe_secret_key:
    file: ./secrets/stripe/secret_key.txt
  stripe_webhook_secret:
    file: ./secrets/stripe/webhook_secret.txt
  stripe_publishable_key:
    file: ./secrets/stripe/publishable_key.txt
```

In the `archie_platform` service's `secrets:` list, add:

```yaml
      - stripe_secret_key
      - stripe_webhook_secret
      - stripe_publishable_key
```

**WARNING**: docker-compose.yml changes require container recreate. This is expected — the new secrets need mounting.

- [ ] **Step 5: Commit**

Do NOT commit the secret files (they're gitignored). Only commit docker-compose.yml:

```bash
cd /mnt/archie_brain
git add docker-compose.yml
git commit -m "feat(billing): add Stripe Docker secrets to docker-compose.yml"
```

---

### Task 2: Database Migration — Billing Core Tables

**Files:**
- Create: `database/migrations/204_billing_core.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Stripe Core billing tables
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/204_billing_core.sql

-- Links ARCHIE users to Stripe customers (lazy creation)
CREATE TABLE IF NOT EXISTS billing_customers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    stripe_customer_id VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(256),
    name VARCHAR(256),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_customers_stripe ON billing_customers(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_customers_user ON billing_customers(user_id);

-- Audit log of every Stripe webhook event (idempotency + debugging)
CREATE TABLE IF NOT EXISTS billing_events (
    id SERIAL PRIMARY KEY,
    stripe_event_id VARCHAR(64) NOT NULL UNIQUE,
    event_type VARCHAR(128) NOT NULL,
    data JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    handler_result TEXT,
    received_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_events_type ON billing_events(event_type);
CREATE INDEX IF NOT EXISTS idx_billing_events_received ON billing_events(received_at);

-- Stripe products/prices registered per module
CREATE TABLE IF NOT EXISTS billing_products (
    id SERIAL PRIMARY KEY,
    stripe_product_id VARCHAR(64) NOT NULL,
    stripe_price_id VARCHAR(64) NOT NULL UNIQUE,
    module VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) DEFAULT 'usd',
    billing_interval VARCHAR(16) DEFAULT 'month' CHECK(billing_interval IN ('month', 'year', 'one_time')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_products_module ON billing_products(module);
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/204_billing_core.sql
```

- [ ] **Step 3: Verify tables**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt billing_*"
```

Expected: 3 tables listed.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/204_billing_core.sql
git commit -m "feat(billing): add billing_customers, billing_events, billing_products tables"
```

---

### Task 3: Stripe Service (API Client)

**Files:**
- Create: `platform_v2/services/stripe_service.py`

- [ ] **Step 1: Create stripe_service.py**

```python
"""Stripe API client — shared billing service for all modules.

Reads API keys from Docker secrets (/run/secrets/).
Falls back to environment variables for development.
"""

import os
import logging
import stripe
from database import get_db_cursor

logger = logging.getLogger(__name__)

_initialized = False


def _read_secret(name, env_fallback=None):
    """Read a Docker secret. Falls back to env var for development."""
    path = f"/run/secrets/{name}"
    try:
        with open(path) as f:
            value = f.read().strip()
            if value and not value.startswith("REPLACE"):
                return value
    except FileNotFoundError:
        pass
    return os.getenv(env_fallback or f"STRIPE_{name.upper()}", "")


def init_stripe():
    """Initialize Stripe SDK with secret key. Call once at app startup."""
    global _initialized
    key = _read_secret("stripe_secret_key", "STRIPE_SECRET_KEY")
    if key:
        stripe.api_key = key
        _initialized = True
        logger.info("Stripe initialized (key ending ...%s)", key[-4:] if len(key) > 4 else "****")
    else:
        logger.warning("Stripe not configured — no secret key found")


def is_stripe_configured():
    """Check if Stripe is initialized."""
    return _initialized and bool(stripe.api_key)


def get_publishable_key():
    """Return Stripe publishable key for frontend."""
    return _read_secret("stripe_publishable_key", "STRIPE_PUBLISHABLE_KEY")


def get_webhook_secret():
    """Return Stripe webhook signing secret."""
    return _read_secret("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET")


def get_or_create_customer(user_id, email=None, name=None):
    """Get existing or create new Stripe customer for an ARCHIE user.

    Returns stripe_customer_id or None on error.
    """
    if not is_stripe_configured():
        logger.warning("Stripe not configured, cannot create customer")
        return None

    # Check local DB first
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return row["stripe_customer_id"]

    # Create in Stripe
    try:
        params = {}
        if email:
            params["email"] = email
        if name:
            params["name"] = name
        params["metadata"] = {"archie_user_id": str(user_id)}

        customer = stripe.Customer.create(**params)

        # Store locally
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO billing_customers (user_id, stripe_customer_id, email, name)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET stripe_customer_id = %s, updated_at = NOW()""",
                (user_id, customer.id, email, name, customer.id),
            )

        logger.info("Created Stripe customer %s for user %s", customer.id, user_id)
        return customer.id

    except stripe.error.StripeError as e:
        logger.error("Stripe customer creation failed: %s", e)
        return None


def get_customer(user_id):
    """Lookup billing customer by user_id. Returns stripe_customer_id or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return row["stripe_customer_id"] if row else None


def create_checkout_session(customer_id, price_id, success_url, cancel_url, metadata=None):
    """Create a Stripe Checkout Session. Returns session URL or None."""
    if not is_stripe_configured():
        return None
    try:
        params = {
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if metadata:
            params["metadata"] = metadata

        session = stripe.checkout.Session.create(**params)
        return session.url

    except stripe.error.StripeError as e:
        logger.error("Checkout session creation failed: %s", e)
        return None


def create_portal_session(customer_id, return_url):
    """Create a Stripe Customer Portal session. Returns URL or None."""
    if not is_stripe_configured():
        return None
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url

    except stripe.error.StripeError as e:
        logger.error("Portal session creation failed: %s", e)
        return None


def list_module_products(module):
    """List billing products registered for a module."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT stripe_product_id, stripe_price_id, name, description,
                      amount_cents, currency, billing_interval, is_active
               FROM billing_products WHERE module = %s AND is_active = TRUE
               ORDER BY amount_cents""",
            (module,),
        )
        return [dict(r) for r in cur.fetchall()]


def register_product(module, stripe_product_id, stripe_price_id, name, amount_cents, billing_interval="month", description="", currency="usd"):
    """Register a Stripe product/price for a module."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO billing_products
               (stripe_product_id, stripe_price_id, module, name, description, amount_cents, currency, billing_interval)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (stripe_price_id) DO UPDATE SET
               name = EXCLUDED.name, amount_cents = EXCLUDED.amount_cents, is_active = TRUE""",
            (stripe_product_id, stripe_price_id, module, name, description, amount_cents, currency, billing_interval),
        )
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/stripe_service.py
git commit -m "feat(billing): add Stripe service — API client with Docker secret loading"
```

---

### Task 4: Webhook Handler + Event Dispatcher

**Files:**
- Create: `platform_v2/services/billing_webhook.py`

- [ ] **Step 1: Create billing_webhook.py**

```python
"""Stripe webhook handler with fan-out event dispatcher.

Modules register handlers at startup. When Stripe sends a webhook event,
it's verified, logged, and dispatched to the matching handler.
"""

import logging
import json
import stripe
from database import get_db_cursor
from services.stripe_service import get_webhook_secret

logger = logging.getLogger(__name__)

# Module handlers registered by event type prefix
_handlers = {}


def register_billing_handler(event_prefix, handler_fn):
    """Register a module's handler for a Stripe event type prefix.

    Example:
        register_billing_handler("customer.subscription", ksm_handler)
        register_billing_handler("checkout.session.completed", checkout_handler)
    """
    _handlers[event_prefix] = handler_fn
    logger.info("Billing handler registered: %s -> %s", event_prefix, handler_fn.__name__)


def verify_and_construct_event(payload, sig_header):
    """Verify Stripe webhook signature and construct event object.

    Returns (event, None) on success, (None, error_message) on failure.
    """
    secret = get_webhook_secret()
    if not secret:
        return None, "Webhook secret not configured"

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event, None
    except stripe.error.SignatureVerificationError:
        return None, "Invalid signature"
    except ValueError:
        return None, "Invalid payload"


def _is_duplicate(stripe_event_id):
    """Check if event was already processed (idempotency)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM billing_events WHERE stripe_event_id = %s",
            (stripe_event_id,),
        )
        return cur.fetchone() is not None


def _log_event(stripe_event_id, event_type, data):
    """Log webhook event to billing_events table."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO billing_events (stripe_event_id, event_type, data, processed)
               VALUES (%s, %s, %s, FALSE)
               ON CONFLICT (stripe_event_id) DO NOTHING""",
            (stripe_event_id, event_type, json.dumps(data)),
        )


def _update_event_result(stripe_event_id, result):
    """Mark event as processed with handler result."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE billing_events SET processed = TRUE, handler_result = %s WHERE stripe_event_id = %s",
            (result, stripe_event_id),
        )


def dispatch_event(event):
    """Route a Stripe event to the matching registered handler.

    Returns handler result string.
    """
    event_type = event["type"]

    # Find matching handler (longest prefix match)
    matched_handler = None
    matched_prefix = ""
    for prefix, handler in _handlers.items():
        if event_type.startswith(prefix) and len(prefix) > len(matched_prefix):
            matched_handler = handler
            matched_prefix = prefix

    if not matched_handler:
        return "no_handler"

    try:
        result = matched_handler(event)
        return result or "success"
    except Exception as e:
        logger.error("Billing handler error for %s: %s", event_type, e)
        return f"error: {str(e)[:200]}"


def process_webhook(payload, sig_header):
    """Full webhook processing pipeline: verify → log → dispatch → update.

    Returns (status_code, response_dict).
    """
    # 1. Verify signature
    event, error = verify_and_construct_event(payload, sig_header)
    if error:
        logger.warning("Webhook verification failed: %s", error)
        return 400, {"error": error}

    stripe_event_id = event["id"]
    event_type = event["type"]

    # 2. Idempotency check
    if _is_duplicate(stripe_event_id):
        logger.debug("Duplicate webhook event skipped: %s", stripe_event_id)
        return 200, {"status": "duplicate"}

    # 3. Log event
    _log_event(stripe_event_id, event_type, event["data"])
    logger.info("Webhook received: %s (%s)", event_type, stripe_event_id)

    # 4. Dispatch to handler
    result = dispatch_event(event)

    # 5. Update result
    _update_event_result(stripe_event_id, result)

    # Always return 200 to prevent Stripe retries
    return 200, {"status": "processed", "handler_result": result}
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/billing_webhook.py
git commit -m "feat(billing): add webhook handler with event dispatcher and idempotency"
```

---

### Task 5: Billing Routes

**Files:**
- Create: `platform_v2/billing_routes.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Read app.py registration pattern**

Read `/mnt/archie_brain/platform_v2/app.py` — find where `oauth_bp` and `standalone_bp` are registered (around line 1777-1791) to know where to add billing init.

- [ ] **Step 2: Create billing_routes.py**

```python
"""Billing API routes — webhook receiver, checkout, portal, product listing."""

import logging
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/api/billing/webhook", methods=["POST"])
def billing_webhook():
    """Stripe webhook receiver. Verified by signature, not login."""
    from services.billing_webhook import process_webhook

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    status_code, response = process_webhook(payload, sig_header)
    return jsonify(response), status_code


@billing_bp.route("/api/billing/publishable-key")
@login_required
def billing_publishable_key():
    """Return Stripe publishable key for frontend Checkout.js."""
    from services.stripe_service import get_publishable_key

    key = get_publishable_key()
    if not key:
        return jsonify({"error": "Stripe not configured"}), 503
    return jsonify({"publishable_key": key})


@billing_bp.route("/api/billing/customer")
@login_required
def billing_customer_info():
    """Get current user's billing customer info."""
    from services.stripe_service import get_customer

    customer_id = get_customer(current_user.id)
    return jsonify({
        "has_billing": customer_id is not None,
        "stripe_customer_id": customer_id,
    })


@billing_bp.route("/api/billing/customer", methods=["POST"])
@login_required
def billing_customer_create():
    """Create billing customer for current user."""
    from services.stripe_service import get_or_create_customer

    customer_id = get_or_create_customer(
        user_id=current_user.id,
        email=getattr(current_user, "email", None),
        name=getattr(current_user, "username", None),
    )
    if not customer_id:
        return jsonify({"error": "Failed to create billing customer"}), 500
    return jsonify({"success": True, "stripe_customer_id": customer_id})


@billing_bp.route("/api/billing/checkout", methods=["POST"])
@login_required
def billing_checkout():
    """Create Stripe Checkout session. Returns redirect URL."""
    from services.stripe_service import get_or_create_customer, create_checkout_session

    data = request.get_json() or {}
    price_id = data.get("price_id")
    success_url = data.get("success_url", request.host_url + "billing/success")
    cancel_url = data.get("cancel_url", request.host_url + "billing/cancel")

    if not price_id:
        return jsonify({"error": "price_id required"}), 400

    customer_id = get_or_create_customer(
        user_id=current_user.id,
        email=getattr(current_user, "email", None),
        name=getattr(current_user, "username", None),
    )
    if not customer_id:
        return jsonify({"error": "Failed to create billing customer"}), 500

    url = create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"archie_user_id": str(current_user.id)},
    )
    if not url:
        return jsonify({"error": "Failed to create checkout session"}), 500

    return jsonify({"success": True, "checkout_url": url})


@billing_bp.route("/api/billing/portal", methods=["POST"])
@login_required
def billing_portal():
    """Create Stripe Customer Portal session. Returns redirect URL."""
    from services.stripe_service import get_customer, create_portal_session

    customer_id = get_customer(current_user.id)
    if not customer_id:
        return jsonify({"error": "No billing customer found. Subscribe first."}), 404

    data = request.get_json() or {}
    return_url = data.get("return_url", request.host_url)

    url = create_portal_session(customer_id, return_url)
    if not url:
        return jsonify({"error": "Failed to create portal session"}), 500

    return jsonify({"success": True, "portal_url": url})


@billing_bp.route("/api/billing/products/<module>")
@login_required
def billing_products(module):
    """List billing products for a module."""
    from services.stripe_service import list_module_products

    products = list_module_products(module)
    return jsonify({"success": True, "products": products})


@billing_bp.route("/api/billing/events")
@login_required
def billing_events_list():
    """List recent webhook events (admin debug)."""
    from rbac import admin_required_api
    from database import get_db_cursor

    # Check admin manually since this isn't a standard route
    if not getattr(current_user, "role", "") == "admin":
        return jsonify({"error": "admin required"}), 403

    limit = request.args.get("limit", 50, type=int)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT stripe_event_id, event_type, processed, handler_result, received_at
               FROM billing_events ORDER BY received_at DESC LIMIT %s""",
            (min(limit, 200),),
        )
        events = [dict(r) for r in cur.fetchall()]
        for e in events:
            if e.get("received_at"):
                e["received_at"] = e["received_at"].isoformat()

    return jsonify({"success": True, "events": events})


def init_billing(app):
    """Initialize billing: register blueprint + init Stripe."""
    from services.stripe_service import init_stripe

    app.register_blueprint(billing_bp)
    init_stripe()
    logger.info("Billing routes registered, Stripe initialized")
```

- [ ] **Step 3: Register in app.py**

Read app.py, find where oauth/standalone API are registered. Add after them:

```python
from billing_routes import init_billing  # noqa: E402
init_billing(app)
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/billing_routes.py platform_v2/app.py
git commit -m "feat(billing): add billing API routes — webhook, checkout, portal, products"
```

---

### Task 6: Deploy + Verify

**Files:** None (deployment + testing)

- [ ] **Step 1: Recreate container with new secrets**

```bash
cd /mnt/archie_brain
docker compose up -d archie_platform
```

This recreates the container to pick up the new Docker secrets mounts.

- [ ] **Step 2: Verify Stripe initialization**

```bash
docker logs archie_platform 2>&1 | grep -i "stripe\|billing" | tail -5
```

Expected: "Stripe initialized" or "Stripe not configured" (if using placeholder keys).

- [ ] **Step 3: Verify billing tables**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt billing_*"
```

Expected: 3 tables.

- [ ] **Step 4: Test webhook endpoint**

```bash
curl -s -X POST http://192.168.1.200:3000/api/billing/webhook \
  -H "Content-Type: application/json" \
  -d '{"test": true}' | python3 -m json.tool
```

Expected: 400 with "Invalid signature" or "Invalid payload" (correct — no valid Stripe signature).

- [ ] **Step 5: Test billing API (authenticated)**

```bash
# Publishable key
curl -s http://192.168.1.200:3000/api/billing/publishable-key
# Expected: 302 redirect to login (requires auth) or 503 if keys are placeholders

# Products listing
curl -s http://192.168.1.200:3000/api/billing/products/ksm
# Expected: 302 redirect to login
```

- [ ] **Step 6: Log decision**

```python
mcp__archie__log_decision(
    title="Stripe Core Billing Foundation Complete",
    decision="Shared Stripe infrastructure with Docker secrets, webhook handler with fan-out dispatcher, billing_customers/events/products tables, checkout+portal session creation. Ready for module-specific billing (KSM, Store, Invoicing).",
    project_id=195
)
```

---

## Task Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | Docker secrets for Stripe (3 files + compose) | 5 min |
| 2 | Database migration (3 billing tables) | 3 min |
| 3 | Stripe service (API client wrapper) | 5 min |
| 4 | Webhook handler + event dispatcher | 5 min |
| 5 | Billing routes + app.py registration | 5 min |
| 6 | Deploy + verify | 5 min |

**Total: 6 tasks, ~28 minutes**

**Note**: After Stripe Core is deployed, the user needs to:
1. Replace placeholder keys in `secrets/stripe/*.txt` with real Stripe API keys
2. Configure the webhook URL in Stripe Dashboard → Developers → Webhooks → `https://archie.kytranempowerment.com/api/billing/webhook`
3. Then proceed to Sub-Project 2 (KSM Billing) to create products and wire subscriptions
