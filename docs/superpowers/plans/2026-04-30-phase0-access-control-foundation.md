# Phase 0 — Access Control Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the access control foundation that every Kytran product gates against — `access_grants` table, `marketplace_registry`, Account Center grant/revoke/check API, KBS webhook integration, and auto bundle discounts.

**Architecture:** Three-layer model: Identity (Account Center) owns `access_grants` and exposes a REST API. Billing (KBS) calls that API after Stripe events. Products check `GET /api/access/check?product=X` on login. Bundle discounts are calculated in KBS and applied as Stripe coupons automatically.

**Tech Stack:** PostgreSQL, Flask, Python 3.11, Stripe SDK, requests (HTTP client), pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/database/migrations/172_access_grants.sql` | access_grants + marketplace_registry_cache tables |
| Create | `platform_v2/tools/account_center/access_routes.py` | grant / revoke / check / list endpoints |
| Modify | `platform_v2/tools/account_center/__init__.py` | register access_routes blueprint |
| Create | `platform_v2/tests/tools/account_center/test_access_routes.py` | tests for all 4 AC endpoints |
| Create | `kytran-business-suite/migrations/011_marketplace_registry.sql` | marketplace_registry table |
| Create | `kytran-business-suite/core/access_client.py` | HTTP client: call AC API from KBS |
| Modify | `kytran-business-suite/core/stripe_billing.py` | call access_client after subscription events |
| Create | `kytran-business-suite/tests/test_access_client.py` | mock tests for access_client |
| Create | `kytran-business-suite/core/bundle_discount.py` | calculate + apply Stripe bundle coupon |
| Modify | `kytran-business-suite/core/billing_routes.py` | call bundle recalc after subscription change |
| Create | `kytran-business-suite/tests/test_bundle_discount.py` | discount tier calculation tests |

---

## Task 1: ARCHIE — access_grants migration

**Files:**
- Create: `platform_v2/database/migrations/172_access_grants.sql`

- [ ] **Step 1.1: Write migration**

```sql
-- platform_v2/database/migrations/172_access_grants.sql
-- Access grants: which users can access which products
CREATE TABLE IF NOT EXISTS access_grants (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_slug VARCHAR(100) NOT NULL,
    source      VARCHAR(50) NOT NULL DEFAULT 'stripe',
    valid_from  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_access_grants_user_product
    ON access_grants (user_id, product_slug)
    WHERE valid_until IS NULL OR valid_until > NOW();

CREATE INDEX IF NOT EXISTS idx_access_grants_user_id ON access_grants (user_id);
CREATE INDEX IF NOT EXISTS idx_access_grants_product ON access_grants (product_slug);

-- Product registry cache (synced from KBS marketplace_registry)
CREATE TABLE IF NOT EXISTS marketplace_products (
    slug        VARCHAR(100) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    url         VARCHAR(500),
    icon        VARCHAR(100),
    category    VARCHAR(100),
    price_monthly NUMERIC(10, 2),
    is_free     BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Seed known products
INSERT INTO marketplace_products (slug, name, url, icon, category, price_monthly, is_free) VALUES
    ('archie-platform',   'ARCHIE Platform',         'http://192.168.1.200:3000',       '🧠', 'core',        149.00, FALSE),
    ('kbs-core',          'KBS Core',                 'http://192.168.1.200:8091',        '💼', 'core',         79.00, FALSE),
    ('signal-linkedin',   'S.I.G.N.A.L. LinkedIn AI', 'http://192.168.1.200:3000/tools/department-hq#social', '📣', 'social', 99.00, FALSE),
    ('wtf-free',          'What The Fact',            'https://what-the-fact.com',        '📰', 'intelligence',  0.00, TRUE),
    ('wtf-premium',       'WTF Premium',              'https://what-the-fact.com',        '📰', 'intelligence', 39.00, FALSE),
    ('kso-compliance',    'Kytran System Operations', 'http://192.168.1.200:8085',        '🛡', 'compliance',  129.00, FALSE),
    ('civic-watch',       'Civic Watch',              'https://civic.kytranempowerment.com', '🏙', 'intelligence', 99.00, FALSE),
    ('legal-watch',       'Legal Watch',              'https://legal.kytranempowerment.com', '⚖️', 'intelligence', 99.00, FALSE),
    ('market-watch',      'Market Watch',             'https://market.kytranempowerment.com', '📈', 'intelligence', 99.00, FALSE),
    ('gov-watch',         'Gov Watch',                'https://gov.kytranempowerment.com', '🏛', 'intelligence', 199.00, FALSE),
    ('gov-watch-alerts',  'Gov Watch Starter Alerts', 'https://gov.kytranempowerment.com', '🏛', 'intelligence', 49.00, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name, url = EXCLUDED.url, price_monthly = EXCLUDED.price_monthly,
    is_free = EXCLUDED.is_free, updated_at = NOW();
```

- [ ] **Step 1.2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/platform_v2/database/migrations/172_access_grants.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX` (×3), `CREATE TABLE`, `INSERT 11`

- [ ] **Step 1.3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt access_grants marketplace_products"
```

Expected: both tables listed.

- [ ] **Step 1.4: Commit**

```bash
git add platform_v2/database/migrations/172_access_grants.sql
git commit -m "feat(ac): access_grants + marketplace_products migration (172)"
```

---

## Task 2: KBS — marketplace_registry migration

**Files:**
- Create: `kytran-business-suite/migrations/011_marketplace_registry.sql`

- [ ] **Step 2.1: Write migration**

```sql
-- kytran-business-suite/migrations/011_marketplace_registry.sql
CREATE TABLE IF NOT EXISTS marketplace_registry (
    slug            VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    url             VARCHAR(500),
    icon            VARCHAR(100),
    category        VARCHAR(100),
    price_monthly   NUMERIC(10, 2),
    is_free         BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_price_id VARCHAR(100),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO marketplace_registry
    (slug, name, description, url, icon, category, price_monthly, is_free, sort_order)
VALUES
    ('archie-platform', 'ARCHIE Platform',
     'AI agent orchestration, Department HQ, Consciousness KB, Repair Bay.',
     'http://192.168.1.200:3000', '🧠', 'core', 149.00, FALSE, 1),
    ('kbs-core', 'KBS Core',
     'CRM, invoicing, contracts, communications.',
     'http://192.168.1.200:8091', '💼', 'core', 79.00, FALSE, 2),
    ('signal-linkedin', 'S.I.G.N.A.L. LinkedIn AI',
     'AI drafts, approves, and publishes your LinkedIn content.',
     'http://192.168.1.200:3000/tools/department-hq#social', '📣', 'social', 99.00, FALSE, 3),
    ('wtf-premium', 'What The Fact Premium',
     'Full audit trails, 30-day history, API access, transparency dashboard.',
     'https://what-the-fact.com', '📰', 'intelligence', 39.00, FALSE, 4),
    ('kso-compliance', 'Kytran System Operations',
     'STIG/HIPAA/CIS compliance scanning and 1-click remediation.',
     'http://192.168.1.200:8085', '🛡', 'compliance', 129.00, FALSE, 5),
    ('civic-watch', 'Civic Watch', 'Municipal decisions and bylaw monitoring.',
     'https://civic.kytranempowerment.com', '🏙', 'intelligence', 99.00, FALSE, 10),
    ('legal-watch', 'Legal Watch', 'Legal changes and regulatory monitoring.',
     'https://legal.kytranempowerment.com', '⚖️', 'intelligence', 99.00, FALSE, 11),
    ('market-watch', 'Market Watch', 'Stock intelligence and portfolio alerts.',
     'https://market.kytranempowerment.com', '📈', 'intelligence', 99.00, FALSE, 12),
    ('gov-watch', 'Gov Watch', 'P.R.O.C.U.R.E. federal tender intelligence.',
     'https://gov.kytranempowerment.com', '🏛', 'intelligence', 199.00, FALSE, 13),
    ('gov-watch-alerts', 'Gov Watch Starter Alerts', 'Weekly federal tender digest email.',
     'https://gov.kytranempowerment.com', '🏛', 'intelligence', 49.00, FALSE, 14)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name, price_monthly = EXCLUDED.price_monthly, updated_at = NOW();
```

- [ ] **Step 2.2: Run migration**

```bash
docker exec kbs_postgres psql -U kbs -d kbs \
  -f /mnt/archie_brain/kytran-business-suite/migrations/011_marketplace_registry.sql
```

Expected: `CREATE TABLE`, `INSERT 10`

- [ ] **Step 2.3: Verify**

```bash
docker exec kbs_postgres psql -U kbs -d kbs \
  -c "SELECT slug, price_monthly FROM marketplace_registry ORDER BY sort_order;"
```

Expected: 10 rows with correct slugs and prices.

- [ ] **Step 2.4: Commit**

```bash
git add kytran-business-suite/migrations/011_marketplace_registry.sql
git commit -m "feat(kbs): marketplace_registry migration (011)"
```

---

## Task 3: Account Center — access API endpoints

**Files:**
- Create: `platform_v2/tools/account_center/access_routes.py`
- Create: `platform_v2/tests/tools/account_center/test_access_routes.py`

- [ ] **Step 3.1: Write failing tests**

```python
# platform_v2/tests/tools/account_center/test_access_routes.py
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def client(app):
    return app.test_client()

def test_grant_access_creates_record(client, db_cursor):
    resp = client.post("/tools/account-center/api/access/grant",
                       json={"user_id": 1, "product_slug": "civic-watch", "source": "stripe"},
                       headers={"X-Internal-Token": "test-token"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["granted"] is True

def test_check_access_returns_true_when_granted(client, db_cursor):
    # First grant
    client.post("/tools/account-center/api/access/grant",
                json={"user_id": 1, "product_slug": "civic-watch", "source": "stripe"},
                headers={"X-Internal-Token": "test-token"})
    resp = client.get("/tools/account-center/api/access/check?user_id=1&product=civic-watch")
    assert resp.status_code == 200
    assert resp.get_json()["has_access"] is True

def test_check_access_returns_false_when_not_granted(client):
    resp = client.get("/tools/account-center/api/access/check?user_id=999&product=gov-watch")
    assert resp.status_code == 200
    assert resp.get_json()["has_access"] is False

def test_revoke_access_sets_valid_until(client, db_cursor):
    client.post("/tools/account-center/api/access/grant",
                json={"user_id": 1, "product_slug": "civic-watch", "source": "stripe"},
                headers={"X-Internal-Token": "test-token"})
    resp = client.post("/tools/account-center/api/access/revoke",
                       json={"user_id": 1, "product_slug": "civic-watch"},
                       headers={"X-Internal-Token": "test-token"})
    assert resp.status_code == 200
    assert resp.get_json()["revoked"] is True
    # Check access now returns False
    check = client.get("/tools/account-center/api/access/check?user_id=1&product=civic-watch")
    assert check.get_json()["has_access"] is False

def test_list_access_returns_active_grants(client, db_cursor):
    client.post("/tools/account-center/api/access/grant",
                json={"user_id": 1, "product_slug": "civic-watch", "source": "stripe"},
                headers={"X-Internal-Token": "test-token"})
    resp = client.get("/tools/account-center/api/access/list?user_id=1")
    assert resp.status_code == 200
    products = resp.get_json()["products"]
    assert "civic-watch" in products

def test_grant_requires_internal_token(client):
    resp = client.post("/tools/account-center/api/access/grant",
                       json={"user_id": 1, "product_slug": "civic-watch"})
    assert resp.status_code == 401
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
docker exec archie_platform python3 -m pytest \
  tests/tools/account_center/test_access_routes.py -v 2>&1 | head -30
```

Expected: `ImportError` or `404` errors — routes don't exist yet.

- [ ] **Step 3.3: Write the access routes**

```python
# platform_v2/tools/account_center/access_routes.py
"""
Access grant/revoke/check API.
Called by KBS after Stripe events to control product access per user.
Internal endpoints — require X-Internal-Token header.
"""
import os
import logging
from flask import Blueprint, request, jsonify
from database import get_db_cursor

logger = logging.getLogger(__name__)
access_bp = Blueprint("access", __name__, url_prefix="/tools/account-center/api/access")

_INTERNAL_TOKEN = os.getenv("AC_INTERNAL_TOKEN", "")


def _check_token():
    if not _INTERNAL_TOKEN:
        return True  # dev mode — no token required
    return request.headers.get("X-Internal-Token") == _INTERNAL_TOKEN


@access_bp.route("/grant", methods=["POST"])
def grant_access():
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    product_slug = data.get("product_slug")
    source = data.get("source", "stripe")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product_slug required"}), 400
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            INSERT INTO access_grants (user_id, product_slug, source, valid_until)
            VALUES (%s, %s, %s, NULL)
            ON CONFLICT (user_id, product_slug)
                WHERE valid_until IS NULL OR valid_until > NOW()
            DO UPDATE SET source = EXCLUDED.source, updated_at = NOW()
            """,
            (user_id, product_slug, source),
        )
    logger.info("access.grant: user=%s product=%s source=%s", user_id, product_slug, source)
    return jsonify({"granted": True, "user_id": user_id, "product_slug": product_slug})


@access_bp.route("/revoke", methods=["POST"])
def revoke_access():
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    product_slug = data.get("product_slug")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product_slug required"}), 400
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            UPDATE access_grants SET valid_until = NOW(), updated_at = NOW()
            WHERE user_id = %s AND product_slug = %s
              AND (valid_until IS NULL OR valid_until > NOW())
            """,
            (user_id, product_slug),
        )
    logger.info("access.revoke: user=%s product=%s", user_id, product_slug)
    return jsonify({"revoked": True, "user_id": user_id, "product_slug": product_slug})


@access_bp.route("/check", methods=["GET"])
def check_access():
    user_id = request.args.get("user_id", type=int)
    product_slug = request.args.get("product")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product required"}), 400
    with get_db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT 1 FROM access_grants
            WHERE user_id = %s AND product_slug = %s
              AND (valid_until IS NULL OR valid_until > NOW())
            LIMIT 1
            """,
            (user_id, product_slug),
        )
        has_access = cur.fetchone() is not None
    return jsonify({"has_access": has_access, "user_id": user_id, "product": product_slug})


@access_bp.route("/list", methods=["GET"])
def list_access():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    with get_db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT product_slug, source, valid_from, valid_until
            FROM access_grants
            WHERE user_id = %s
              AND (valid_until IS NULL OR valid_until > NOW())
            ORDER BY valid_from
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    products = [r["product_slug"] for r in rows]
    grants = [
        {
            "product_slug": r["product_slug"],
            "source": r["source"],
            "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
            "valid_until": r["valid_until"].isoformat() if r["valid_until"] else None,
        }
        for r in rows
    ]
    return jsonify({"user_id": user_id, "products": products, "grants": grants})
```

- [ ] **Step 3.4: Register blueprint in `__init__.py`**

Read `platform_v2/tools/account_center/__init__.py` first, then add:
```python
from .access_routes import access_bp
# in register_routes() or equivalent:
app.register_blueprint(access_bp)
```

- [ ] **Step 3.5: Add `AC_INTERNAL_TOKEN` to platform `.env`**

```bash
grep -q AC_INTERNAL_TOKEN /mnt/archie_brain/platform_v2/.env \
  || echo "AC_INTERNAL_TOKEN=archie-ac-internal-$(openssl rand -hex 16)" \
     >> /mnt/archie_brain/platform_v2/.env
```

- [ ] **Step 3.6: Restart platform and run tests**

```bash
docker compose restart archie_platform
sleep 15
docker exec archie_platform python3 -m pytest \
  tests/tools/account_center/test_access_routes.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 3.7: Smoke test via curl**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json
r = urllib.request.urlopen(
  'http://localhost:3000/tools/account-center/api/access/check?user_id=1&product=wtf-premium',
  timeout=5)
print(json.loads(r.read()))
"
```

Expected: `{'has_access': False, 'user_id': 1, 'product': 'wtf-premium'}`

- [ ] **Step 3.8: Commit**

```bash
git add platform_v2/tools/account_center/access_routes.py \
        platform_v2/tools/account_center/__init__.py \
        platform_v2/tests/tools/account_center/test_access_routes.py
git commit -m "feat(ac): access grant/revoke/check API (#2486)"
```

---

## Task 4: KBS — access_client.py

**Files:**
- Create: `kytran-business-suite/core/access_client.py`
- Create: `kytran-business-suite/tests/test_access_client.py`

- [ ] **Step 4.1: Write failing tests**

```python
# kytran-business-suite/tests/test_access_client.py
from unittest.mock import patch, MagicMock
from core.access_client import grant_access, revoke_access

def test_grant_access_calls_correct_endpoint():
    with patch("core.access_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200,
                                            json=lambda: {"granted": True})
        result = grant_access(user_id=1, product_slug="civic-watch", source="stripe")
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "access/grant" in call_args[0][0]
        assert call_args[1]["json"]["user_id"] == 1
        assert call_args[1]["json"]["product_slug"] == "civic-watch"

def test_revoke_access_calls_correct_endpoint():
    with patch("core.access_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200,
                                            json=lambda: {"revoked": True})
        result = revoke_access(user_id=1, product_slug="civic-watch")
        assert result is True
        call_args = mock_post.call_args
        assert "access/revoke" in call_args[0][0]

def test_grant_access_returns_false_on_error():
    with patch("core.access_client.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        result = grant_access(user_id=1, product_slug="civic-watch", source="stripe")
        assert result is False
```

- [ ] **Step 4.2: Run to verify fail**

```bash
cd /mnt/archie_brain/kytran-business-suite
python3 -m pytest tests/test_access_client.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'grant_access'`

- [ ] **Step 4.3: Write access_client.py**

```python
# kytran-business-suite/core/access_client.py
"""
HTTP client for calling the Account Center access API.
KBS calls these after Stripe subscription events to grant/revoke product access.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

_AC_BASE_URL = os.getenv("AC_API_URL", "http://192.168.1.200:3000")
_AC_TOKEN = os.getenv("AC_INTERNAL_TOKEN", "")
_TIMEOUT = 10


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if _AC_TOKEN:
        h["X-Internal-Token"] = _AC_TOKEN
    return h


def grant_access(user_id: int, product_slug: str, source: str = "stripe") -> bool:
    """Grant a user access to a product. Returns True on success."""
    try:
        resp = requests.post(
            f"{_AC_BASE_URL}/tools/account-center/api/access/grant",
            json={"user_id": user_id, "product_slug": product_slug, "source": source},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            logger.info("access_client.grant: user=%s product=%s", user_id, product_slug)
            return True
        logger.warning("access_client.grant failed: %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("access_client.grant error: user=%s product=%s err=%s", user_id, product_slug, e)
        return False


def revoke_access(user_id: int, product_slug: str) -> bool:
    """Revoke a user's access to a product. Returns True on success."""
    try:
        resp = requests.post(
            f"{_AC_BASE_URL}/tools/account-center/api/access/revoke",
            json={"user_id": user_id, "product_slug": product_slug},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            logger.info("access_client.revoke: user=%s product=%s", user_id, product_slug)
            return True
        logger.warning("access_client.revoke failed: %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("access_client.revoke error: user=%s product=%s err=%s", user_id, product_slug, e)
        return False
```

- [ ] **Step 4.4: Run tests**

```bash
cd /mnt/archie_brain/kytran-business-suite
python3 -m pytest tests/test_access_client.py -v
```

Expected: 3 PASS.

- [ ] **Step 4.5: Add env vars to KBS .env**

```bash
grep -q AC_INTERNAL_TOKEN /mnt/archie_brain/kytran-business-suite/.env \
  || cat /mnt/archie_brain/platform_v2/.env | grep AC_INTERNAL_TOKEN \
     >> /mnt/archie_brain/kytran-business-suite/.env
echo "AC_API_URL=http://192.168.1.200:3000" >> /mnt/archie_brain/kytran-business-suite/.env
```

- [ ] **Step 4.6: Commit**

```bash
git add kytran-business-suite/core/access_client.py \
        kytran-business-suite/tests/test_access_client.py
git commit -m "feat(kbs): access_client — grant/revoke calls to Account Center API"
```

---

## Task 5: KBS — wire stripe_billing.py to call access_client

**Files:**
- Modify: `kytran-business-suite/core/stripe_billing.py` (add access_client calls in `_handle_subscription_created`, `_handle_subscription_updated`, `_handle_subscription_deleted`)

- [ ] **Step 5.1: Read the file first**

```bash
sed -n '410,480p' /mnt/archie_brain/kytran-business-suite/core/stripe_billing.py
```

Note the exact line numbers of `_handle_subscription_created`, `_handle_subscription_updated`, `_handle_subscription_deleted`.

- [ ] **Step 5.2: Add the import at top of stripe_billing.py**

Find the existing imports section and add:
```python
from core.access_client import grant_access, revoke_access
```

- [ ] **Step 5.3: In `_handle_subscription_created` — call grant_access after activate_module**

Find where `activate_module` or `_set_tenant_tier` is called. After the existing logic, add:
```python
# Grant access in Account Center for each active product slug
_sync_access_grants(tenant_id=tenant_id, action="grant",
                    product_slugs=_get_product_slugs_for_subscription(subscription))
```

- [ ] **Step 5.4: Add helper functions to stripe_billing.py**

Add after the existing helper functions:
```python
# Product slug mapping: Stripe product/price ID → access_grants product_slug
# Update this dict when adding new products to Stripe.
_STRIPE_PRODUCT_SLUG_MAP = {
    # slug: list of Stripe price IDs that grant access to this product
    # These are populated from env vars so they can be updated without code changes.
}

def _get_product_slugs_for_subscription(subscription: dict) -> list:
    """Return list of product_slugs that this subscription grants access to."""
    slugs = []
    for item in subscription.get("items", {}).get("data", []):
        price_id = item.get("price", {}).get("id", "")
        # Check env var mapping first: STRIPE_PRICE_<PRICE_ID>=<product_slug>
        env_key = f"STRIPE_PRICE_{price_id.replace('-', '_').upper()}"
        slug = os.getenv(env_key)
        if slug:
            slugs.append(slug)
        # Fallback: check subscription metadata for product_slug
    metadata = subscription.get("metadata", {})
    if metadata.get("product_slug"):
        slugs.append(metadata["product_slug"])
    return list(set(slugs))


def _sync_access_grants(tenant_id: int, action: str, product_slugs: list) -> None:
    """Grant or revoke access for all product slugs for a tenant's primary user."""
    if not product_slugs:
        return
    # Look up the primary user for this tenant
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id FROM users WHERE tenant_id = %s ORDER BY id LIMIT 1",
                (tenant_id,)
            )
            row = cur.fetchone()
            if not row:
                logger.warning("_sync_access_grants: no user for tenant %s", tenant_id)
                return
            user_id = row["id"]
    except Exception as e:
        logger.error("_sync_access_grants: DB error tenant=%s: %s", tenant_id, e)
        return
    for slug in product_slugs:
        if action == "grant":
            grant_access(user_id=user_id, product_slug=slug, source="stripe")
        elif action == "revoke":
            revoke_access(user_id=user_id, product_slug=slug)
```

- [ ] **Step 5.5: Wire `_handle_subscription_deleted`**

Find `_handle_subscription_deleted` and add at the end:
```python
_sync_access_grants(tenant_id=tenant_id, action="revoke",
                    product_slugs=_get_product_slugs_for_subscription(subscription))
```

- [ ] **Step 5.6: Restart KBS and verify webhook still processes**

```bash
docker compose restart kbs_app
sleep 10
docker logs kbs_app --tail 20 2>&1 | grep -E "ERROR|WARNING|stripe|billing"
```

Expected: clean startup, no import errors.

- [ ] **Step 5.7: Commit**

```bash
git add kytran-business-suite/core/stripe_billing.py
git commit -m "feat(kbs): wire Stripe webhook to call AC access grant/revoke (#2486)"
```

---

## Task 6: KBS — bundle discount logic

**Files:**
- Create: `kytran-business-suite/core/bundle_discount.py`
- Create: `kytran-business-suite/tests/test_bundle_discount.py`
- Modify: `kytran-business-suite/core/billing_routes.py`

- [ ] **Step 6.1: Write failing tests**

```python
# kytran-business-suite/tests/test_bundle_discount.py
from core.bundle_discount import get_bundle_discount_pct

def test_no_discount_for_one_product():
    assert get_bundle_discount_pct(1) == 0

def test_no_discount_for_two_products():
    assert get_bundle_discount_pct(2) == 0

def test_fifteen_pct_for_three_products():
    assert get_bundle_discount_pct(3) == 15

def test_fifteen_pct_for_four_products():
    assert get_bundle_discount_pct(4) == 15

def test_twenty_five_pct_for_five_plus():
    assert get_bundle_discount_pct(5) == 25
    assert get_bundle_discount_pct(10) == 25
```

- [ ] **Step 6.2: Run to verify fail**

```bash
cd /mnt/archie_brain/kytran-business-suite
python3 -m pytest tests/test_bundle_discount.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'get_bundle_discount_pct'`

- [ ] **Step 6.3: Write bundle_discount.py**

```python
# kytran-business-suite/core/bundle_discount.py
"""
Bundle discount logic — auto-apply Stripe coupon based on active subscription count.
Discount tiers: 3-4 products = 15% off, 5+ = 25% off.
Recalculated after every subscription change.
"""
import os
import logging
import stripe

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Stripe coupon IDs — create these once in Stripe dashboard and set env vars.
_COUPON_15 = os.getenv("STRIPE_BUNDLE_COUPON_15PCT", "")  # 15% off coupon ID
_COUPON_25 = os.getenv("STRIPE_BUNDLE_COUPON_25PCT", "")  # 25% off coupon ID


def get_bundle_discount_pct(active_subscription_count: int) -> int:
    """Return discount percentage for a given number of active subscriptions."""
    if active_subscription_count >= 5:
        return 25
    if active_subscription_count >= 3:
        return 15
    return 0


def count_active_subscriptions(stripe_customer_id: str) -> int:
    """Count active Stripe subscription items for a customer."""
    try:
        subs = stripe.Subscription.list(
            customer=stripe_customer_id,
            status="active",
            limit=100,
        )
        count = sum(
            len(sub["items"]["data"])
            for sub in subs.auto_paging_iter()
        )
        return count
    except Exception as e:
        logger.error("bundle_discount.count: customer=%s err=%s", stripe_customer_id, e)
        return 0


def apply_bundle_discount(stripe_customer_id: str, subscription_id: str) -> bool:
    """
    Recalculate and apply the correct bundle discount coupon to a subscription.
    Removes old bundle coupon if discount no longer applies.
    Returns True if coupon state changed.
    """
    count = count_active_subscriptions(stripe_customer_id)
    target_pct = get_bundle_discount_pct(count)

    if target_pct == 0:
        target_coupon = None
    elif target_pct == 15:
        target_coupon = _COUPON_15
    else:
        target_coupon = _COUPON_25

    if not target_coupon and target_pct > 0:
        logger.warning("bundle_discount: coupon ID not configured for %d%%", target_pct)
        return False

    try:
        if target_coupon:
            stripe.Subscription.modify(subscription_id, coupon=target_coupon)
            logger.info("bundle_discount: applied %d%% coupon to sub=%s", target_pct, subscription_id)
        else:
            stripe.Subscription.modify(subscription_id, coupon="")
            logger.info("bundle_discount: removed coupon from sub=%s", subscription_id)
        return True
    except Exception as e:
        logger.error("bundle_discount.apply: sub=%s err=%s", subscription_id, e)
        return False
```

- [ ] **Step 6.4: Run tests**

```bash
cd /mnt/archie_brain/kytran-business-suite
python3 -m pytest tests/test_bundle_discount.py -v
```

Expected: 5 PASS.

- [ ] **Step 6.5: Add env vars for bundle coupons to KBS .env**

```bash
# Create these in Stripe dashboard first, then add the coupon IDs:
echo "# Bundle discount coupon IDs (create in Stripe dashboard)" \
  >> /mnt/archie_brain/kytran-business-suite/.env
echo "STRIPE_BUNDLE_COUPON_15PCT=" >> /mnt/archie_brain/kytran-business-suite/.env
echo "STRIPE_BUNDLE_COUPON_25PCT=" >> /mnt/archie_brain/kytran-business-suite/.env
```

**Note for Kytran:** Create two coupons in Stripe dashboard (test mode):
1. "BUNDLE15" — 15% off, forever, applies to subscription
2. "BUNDLE25" — 25% off, forever, applies to subscription
Then add their IDs to .env.

- [ ] **Step 6.6: Wire bundle recalc into billing_routes.py**

In `billing_routes.py`, find the webhook handler and add after each successful subscription event:
```python
from core.bundle_discount import apply_bundle_discount
# After subscription created/updated/deleted:
apply_bundle_discount(
    stripe_customer_id=customer_id,
    subscription_id=subscription_id
)
```

- [ ] **Step 6.7: Commit**

```bash
git add kytran-business-suite/core/bundle_discount.py \
        kytran-business-suite/tests/test_bundle_discount.py \
        kytran-business-suite/core/billing_routes.py
git commit -m "feat(kbs): bundle discount logic — 15%/25% auto-coupon (#2486)"
```

---

## Task 7: Create billing-gate skill for future product gating

**Files:**
- Create: `.claude/skills/billing-gate/README.md`

- [ ] **Step 7.1: Write the billing-gate skill**

```markdown
<!-- .claude/skills/billing-gate/README.md -->
---
name: billing-gate
description: Add a subscription paywall to any Kytran product. Checks access_grants via Account Center API and shows upgrade CTA if not subscribed. Use when adding a new product to the billing system.
---

# Billing Gate Skill

## What this does
Adds a paywall check to a product. Unauthenticated or unsubscribed users see an upgrade CTA.
Subscribed users pass through to the product.

## Steps

1. **Register product in marketplace_registry** (KBS migration or seed):
   ```sql
   INSERT INTO marketplace_registry (slug, name, description, url, icon, category, price_monthly)
   VALUES ('<slug>', '<name>', '<description>', '<url>', '<icon>', '<category>', <price>);
   ```

2. **Register product in marketplace_products** (ARCHIE AC migration or seed):
   ```sql
   INSERT INTO marketplace_products (slug, name, url, price_monthly)
   VALUES ('<slug>', '<name>', '<url>', <price>);
   ```

3. **Add access check to product login/entry route**:
   ```python
   import requests, os
   AC_BASE = os.getenv("AC_API_URL", "http://192.168.1.200:3000")
   def has_product_access(user_id: int, product_slug: str) -> bool:
       try:
           r = requests.get(f"{AC_BASE}/tools/account-center/api/access/check",
                            params={"user_id": user_id, "product": product_slug}, timeout=5)
           return r.json().get("has_access", False)
       except Exception:
           return False  # fail open in dev, fail closed in prod
   ```

4. **Show upgrade CTA if no access**:
   ```python
   if not has_product_access(current_user.id, "<slug>"):
       return redirect(f"https://business.kytranempowerment.com/billing/checkout"
                       f"?product=<slug>&return_url={request.url}")
   ```

5. **Map Stripe price ID to product slug** in KBS .env:
   ```
   STRIPE_PRICE_<PRICE_ID_UPPER>=<product-slug>
   ```

6. **Test**: Subscribe in Stripe test mode → verify access_grants row created → verify product accessible.
```

- [ ] **Step 7.2: Commit the skill**

```bash
mkdir -p /mnt/archie_brain/.claude/skills/billing-gate
git add .claude/skills/billing-gate/README.md
git commit -m "feat(skills): billing-gate skill — reusable paywall pattern for any product"
```

---

## Task 8: Delegate — F.O.R.G.E. code review + C.O.D.E.X. documentation

- [ ] **Step 8.1: Delegate code review to F.O.R.G.E.**

```python
# Run from ARCHIE MCP:
mcp__archie__delegate_task(
    capability="code_review",
    reason="Review Phase 0 access control implementation: access_routes.py, access_client.py, bundle_discount.py. Check for security gaps in token validation, SQL injection risks, and error handling.",
    delegation_source="claude"
)
```

- [ ] **Step 8.2: Delegate documentation to C.O.D.E.X.**

```python
mcp__archie__delegate_task(
    capability="documentation",
    reason="Document the new access control API. Endpoints: POST /api/access/grant, POST /api/access/revoke, GET /api/access/check, GET /api/access/list. Include request/response schemas and the billing-gate integration pattern.",
    delegation_source="claude"
)
```

- [ ] **Step 8.3: Push branch and open PR**

```bash
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✅ `access_grants` table — Task 1
- ✅ `marketplace_registry` — Task 2
- ✅ AC grant/revoke/check API — Task 3
- ✅ KBS webhook → AC integration — Tasks 4 + 5
- ✅ Bundle discount logic — Task 6
- ✅ billing-gate skill for reuse — Task 7
- ✅ F.O.R.G.E. + C.O.D.E.X. delegation — Task 8

**Gaps identified:**
- Stripe coupon IDs must be created manually in dashboard before Task 6 is fully live — noted in Step 6.5
- `users.tenant_id` column assumed in Task 5 — verify exists with `\d users` before running

**Type consistency:** All functions use `user_id: int`, `product_slug: str` consistently across Tasks 3–6. `grant_access` and `revoke_access` in access_client.py match usage in stripe_billing.py Task 5.
