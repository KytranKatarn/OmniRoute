# Stripe Core — Shared Billing Foundation

**Date**: 2026-03-26
**Project**: #195 — Unified Stripe Billing — Platform-Wide Payment Integration
**Status**: Design Approved
**Scope**: Sub-Project 1 — Stripe Core (webhook handler, customer model, event dispatcher, API client, Docker secrets)
**Depends on**: Existing user system, Docker secrets pattern (db_password)

---

## Problem Statement

A.R.C.H.I.E. has 5 modules that need billing (KSM subscriptions, Store Builder products, Invoicing, Account Center management, CRM analytics). Each needs Stripe integration but they must share one Stripe account, one webhook URL, one customer model, and one event pipeline. Stripe Core provides this shared foundation.

---

## Architecture

```
Stripe API
  │
  ├── POST /api/billing/webhook (ARCHIE platform, port 3000)
  │     ├── Verify signature (webhook secret from Docker secret)
  │     ├── Log to billing_events (idempotency on stripe_event_id)
  │     └── Dispatch to registered handler by event type:
  │           ├── customer.subscription.* → KSM handler
  │           ├── checkout.session.* → Checkout handler (KSM or Store)
  │           ├── invoice.* → Invoicing handler
  │           ├── payment_intent.* → Store handler
  │           └── customer.* → Account Center handler
  │
  ├── billing_customers (user_id ↔ stripe_customer_id, lazy creation)
  ├── billing_events (audit log, every webhook event)
  ├── billing_products (registered Stripe products per module)
  │
  └── Docker secrets: stripe_secret_key, stripe_webhook_secret, stripe_publishable_key
```

---

## Deliverable 1: Docker Secrets

### Secret Files

Location: `/mnt/archie_brain/secrets/stripe/`

```
secrets/stripe/
  ├── secret_key.txt      # sk_live_... or sk_test_...
  ├── webhook_secret.txt  # whsec_...
  └── publishable_key.txt # pk_live_... or pk_test_...
```

### docker-compose.yml Changes

Add to secrets section:

```yaml
secrets:
  db_password:
    file: ./secrets/database/password.txt
  stripe_secret_key:
    file: ./secrets/stripe/secret_key.txt
  stripe_webhook_secret:
    file: ./secrets/stripe/webhook_secret.txt
  stripe_publishable_key:
    file: ./secrets/stripe/publishable_key.txt
```

Add to `archie_platform` service:

```yaml
    secrets:
      - db_password
      - stripe_secret_key
      - stripe_webhook_secret
      - stripe_publishable_key
```

Mounted at `/run/secrets/stripe_secret_key`, etc. inside the container.

---

## Deliverable 2: Database Schema

### billing_customers

Links ARCHIE users to Stripe customers (lazy creation — only when user first interacts with billing).

```sql
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
```

### billing_events

Audit log of every Stripe webhook event. Enables idempotency (skip duplicates) and debugging.

```sql
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
```

### billing_products

Stripe products/prices registered per module. Populated during module setup, not by webhooks.

```sql
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

---

## Deliverable 3: Stripe Service (API Client)

**File**: `platform_v2/services/stripe_service.py`

Thin wrapper around the Stripe Python SDK. All Stripe API calls go through this service.

### Secret Loading

```python
def _read_secret(name):
    """Read a Docker secret from /run/secrets/."""
    path = f"/run/secrets/{name}"
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return os.getenv(f"STRIPE_{name.upper()}", "")
```

Falls back to env vars for development (e.g., `STRIPE_SECRET_KEY`). Production uses Docker secrets.

### Functions

| Function | What |
|----------|------|
| `init_stripe()` | Initialize stripe.api_key from secret, call once at app startup |
| `get_or_create_customer(user_id, email, name)` | Lookup in billing_customers, create Stripe customer if not found, return stripe_customer_id |
| `create_checkout_session(customer_id, price_id, success_url, cancel_url, metadata)` | Create Stripe Checkout Session, return URL |
| `create_customer_portal_session(customer_id, return_url)` | Create Stripe Customer Portal session, return URL |
| `get_customer(user_id)` | Lookup billing_customers by user_id, return stripe_customer_id or None |
| `list_module_products(module)` | Query billing_products for a module |
| `register_product(module, stripe_product_id, stripe_price_id, name, amount_cents, interval)` | Insert into billing_products |
| `get_publishable_key()` | Read publishable key from secret (for frontend Checkout.js) |

---

## Deliverable 4: Webhook Handler + Event Dispatcher

**File**: `platform_v2/services/billing_webhook.py`

### Webhook Verification

```python
def verify_webhook(payload, sig_header):
    """Verify Stripe webhook signature."""
    secret = _read_secret("stripe_webhook_secret")
    return stripe.Webhook.construct_event(payload, sig_header, secret)
```

### Event Dispatcher

```python
_handlers = {}  # event_prefix → handler_function

def register_billing_handler(event_prefix, handler_fn):
    """Register a module's handler for a Stripe event type prefix."""
    _handlers[event_prefix] = handler_fn

def dispatch_event(event):
    """Route a Stripe event to the registered handler."""
    event_type = event["type"]
    for prefix, handler in _handlers.items():
        if event_type.startswith(prefix):
            return handler(event)
    return "no_handler"
```

### Handler Registration Pattern

Modules register their handlers at app startup:

```python
# In app.py or module init:
from services.billing_webhook import register_billing_handler

# KSM registers:
register_billing_handler("customer.subscription", ksm_subscription_handler)
register_billing_handler("checkout.session.completed", ksm_checkout_handler)

# Store Builder registers:
register_billing_handler("payment_intent.succeeded", store_payment_handler)
```

Handlers are simple functions: `def handler(event) -> str` returning "success" or error message.

### Processing Flow

1. Receive POST → verify signature
2. Check `billing_events` for `stripe_event_id` — skip if exists (idempotency)
3. Insert into `billing_events` with `processed=False`
4. Call `dispatch_event(event)`
5. Update `billing_events`: `processed=True`, `handler_result=result`
6. Return 200 to Stripe (always, even on handler error — prevents Stripe retries flooding)

---

## Deliverable 5: Billing Routes

**File**: `platform_v2/billing_routes.py`

### Endpoints

| Method | Path | Auth | What |
|--------|------|------|------|
| POST | `/api/billing/webhook` | Stripe signature | Webhook receiver |
| GET | `/api/billing/publishable-key` | Login | Return Stripe publishable key for frontend |
| GET | `/api/billing/customer` | Login | Get current user's billing customer info |
| POST | `/api/billing/customer` | Login | Create billing customer for current user |
| POST | `/api/billing/checkout` | Login | Create Checkout session, return URL |
| POST | `/api/billing/portal` | Login | Create Customer Portal session, return URL |
| GET | `/api/billing/products/<module>` | Login | List products for a module |
| GET | `/api/billing/events` | Admin | List recent webhook events (debug) |

### Registration

```python
from billing_routes import init_billing_routes
init_billing_routes(app)
```

---

## Deliverable 6: Stripe Python SDK

**Install**: Add `stripe` to requirements / pip install in Docker.

```bash
docker exec archie_platform pip install stripe
```

Or add to Dockerfile/requirements.txt for persistence across rebuilds.

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `secrets/stripe/secret_key.txt` | Stripe secret key |
| Create | `secrets/stripe/webhook_secret.txt` | Webhook signing secret |
| Create | `secrets/stripe/publishable_key.txt` | Publishable key for frontend |
| Modify | `docker-compose.yml` | Add Stripe secrets + mount in platform |
| Create | `database/migrations/204_billing_core.sql` | 3 billing tables |
| Create | `platform_v2/services/stripe_service.py` | Stripe API client wrapper |
| Create | `platform_v2/services/billing_webhook.py` | Webhook handler + event dispatcher |
| Create | `platform_v2/billing_routes.py` | Billing API endpoints |
| Modify | `platform_v2/app.py` | Register billing routes + init Stripe |
| Modify | `.gitignore` | Ensure secrets/stripe/ is ignored |

---

## Security

- Stripe secret key: Docker secret only, never in env vars or code
- Webhook signature verified on every event (Stripe SDK handles this)
- Publishable key: safe for frontend (it's designed to be public)
- All billing endpoints require login except webhook (Stripe signature instead)
- Admin-only access for event log viewing
- `billing_events.data` stores full JSONB payload — contains PII, treat as sensitive
- No Stripe keys in git — `secrets/stripe/` added to `.gitignore`

---

## Out of Scope (Handled by Module Sub-Projects)

- KSM subscription products/prices creation (Sub-Project 2)
- Store Builder product catalog (Sub-Project 3)
- Invoice creation/sending (Sub-Project 4)
- Customer Portal UI in Account Center (Sub-Project 5)
- Revenue dashboards in CRM (Sub-Project 6)
- Tax calculation (Stripe Tax — future)
- Multi-currency support (future)
- Refund handling (future, per-module)

---

## Success Criteria

1. Stripe SDK initialized from Docker secret on platform startup
2. `/api/billing/webhook` receives events, verifies signature, logs to `billing_events`
3. Event dispatcher routes events to registered handlers by type prefix
4. `get_or_create_customer()` creates Stripe customer on first call, returns cached on subsequent
5. Checkout session creation returns valid Stripe URL
6. Customer Portal session creation returns valid Stripe URL
7. `billing_products` table accepts product registrations per module
8. All billing endpoints protected (login or Stripe signature)
9. Idempotency: duplicate webhook events are skipped
10. Secret keys never appear in logs, git, or env vars
