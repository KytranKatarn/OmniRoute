# Phase 1 — KBS Billing Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the KBS `/billing/dashboard` — users view active subscriptions, change plans with proration preview, cancel at period end, and download invoice history.

**Architecture:** New `/billing/dashboard` route backed by `billing_subscriptions` + `billing_customers` tables (currently missing despite being referenced in code). Plan picker calls Stripe `subscription.update` with `proration_behavior: create_prorations`. Cancel sets `cancel_at_period_end=True`. Invoice list pulls from Stripe API.

**Tech Stack:** Flask, PostgreSQL (kbs_postgres), Stripe Python SDK, Jinja2, vanilla JS (no innerHTML with dynamic data)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `kytran-business-suite/migrations/012_billing_tables.sql` | billing_subscriptions + billing_customers tables |
| Create | `kytran-business-suite/core/billing_service.py` | get_subscription_summary, calculate_proration, change_plan, cancel, list_invoices |
| Modify | `kytran-business-suite/core/billing_routes.py` | Add GET /billing/dashboard, GET /billing/api/proration, POST /billing/api/change-plan, POST /billing/api/cancel |
| Create | `kytran-business-suite/shared/templates/billing_dashboard.html` | LCARS billing dashboard UI |
| Create | `kytran-business-suite/tests/test_billing_service.py` | Unit tests for billing_service |

---

## Task 1: Create missing billing tables

**Files:**
- Create: `kytran-business-suite/migrations/012_billing_tables.sql`

- [ ] **Step 1.1: Write migration**

```sql
-- kytran-business-suite/migrations/012_billing_tables.sql
CREATE TABLE IF NOT EXISTS billing_customers (
    id                   SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id            INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_customer_id   VARCHAR(100) UNIQUE NOT NULL,
    email                VARCHAR(255),
    created_at           TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_customers_user_id   ON billing_customers (user_id);
CREATE INDEX IF NOT EXISTS idx_billing_customers_stripe_id ON billing_customers (stripe_customer_id);

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id               INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_subscription_id  VARCHAR(100) UNIQUE NOT NULL,
    stripe_customer_id      VARCHAR(100) NOT NULL,
    product_slug            VARCHAR(100) NOT NULL,
    stripe_price_id         VARCHAR(100),
    status                  VARCHAR(50) NOT NULL DEFAULT 'active',
    current_period_start    TIMESTAMP WITHOUT TIME ZONE,
    current_period_end      TIMESTAMP WITHOUT TIME ZONE,
    cancel_at_period_end    BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at             TIMESTAMP WITHOUT TIME ZONE,
    amount_cents            INTEGER,
    currency                VARCHAR(10) DEFAULT 'cad',
    created_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_subs_user_id   ON billing_subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_stripe_id ON billing_subscriptions (stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_status    ON billing_subscriptions (status);
```

- [ ] **Step 1.2: Run migration**

```bash
docker exec -i kbs_postgres psql -U kbs -d kbs < kytran-business-suite/migrations/012_billing_tables.sql
```

Expected: `CREATE TABLE` x2, `CREATE INDEX` x5

- [ ] **Step 1.3: Verify**

```bash
docker exec kbs_postgres psql -U kbs -d kbs -c "\dt billing*"
```

Expected: `billing_customers` and `billing_subscriptions` listed.

- [ ] **Step 1.4: Commit**

```bash
git add kytran-business-suite/migrations/012_billing_tables.sql
git commit -m "feat(kbs): billing_customers + billing_subscriptions tables (012)"
```

---

## Task 2: billing_service.py — subscription data layer

**Files:**
- Create: `kytran-business-suite/core/billing_service.py`
- Create: `kytran-business-suite/tests/test_billing_service.py`

- [ ] **Step 2.1: Write failing tests**

```python
# kytran-business-suite/tests/test_billing_service.py
from unittest.mock import patch, MagicMock
from core.billing_service import get_subscription_summary, calculate_proration


def test_get_subscription_summary_returns_empty_when_no_sub():
    with patch("core.billing_service.get_db") as mock_get_db:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_get_db.return_value = conn
        result = get_subscription_summary(user_id=999)
        assert result["subscriptions"] == []
        assert result["total_monthly"] == 0


def test_calculate_proration_returns_expected_keys():
    with patch("core.billing_service.stripe") as mock_stripe:
        mock_stripe.SubscriptionItem.list.return_value = MagicMock(
            data=[MagicMock(id="si_123")]
        )
        mock_stripe.Invoice.upcoming.return_value = MagicMock(
            amount_due=5000,
            currency="cad",
            lines=MagicMock(data=[]),
        )
        result = calculate_proration(
            subscription_id="sub_123", new_price_id="price_456"
        )
        assert "amount_due_cents" in result
        assert "currency" in result
```

- [ ] **Step 2.2: Run to verify fail**

```bash
docker exec kbs_app python3 -c "
import sys; sys.path.insert(0, '/app')
import pytest
raise SystemExit(pytest.main(['/app/tests/test_billing_service.py', '-v', '--tb=short']))
" 2>&1 | tail -8
```

Expected: `ImportError: cannot import name 'get_subscription_summary'`

- [ ] **Step 2.3: Write billing_service.py**

```python
# kytran-business-suite/core/billing_service.py
"""
Billing service — read subscription data and call Stripe API for
plan changes, cancellations, and invoice retrieval.
"""
import os
import logging
import stripe
from core.db import get_db

logger = logging.getLogger(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


def get_subscription_summary(user_id: int) -> dict:
    """Return active subscriptions for a user with product details."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT bs.stripe_subscription_id, bs.product_slug, bs.status,
                   bs.current_period_end, bs.cancel_at_period_end,
                   bs.amount_cents, bs.currency, bs.stripe_price_id,
                   mr.name AS product_name, mr.url AS product_url, mr.icon
            FROM billing_subscriptions bs
            LEFT JOIN marketplace_registry mr ON mr.slug = bs.product_slug
            WHERE bs.user_id = %s AND bs.status IN ('active', 'trialing', 'past_due')
            ORDER BY bs.created_at
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    subscriptions = [
        {
            "subscription_id": r[0],
            "product_slug": r[1],
            "status": r[2],
            "renews_at": r[3].isoformat() if r[3] else None,
            "cancel_at_period_end": bool(r[4]),
            "amount_cents": int(r[5] or 0),
            "currency": (r[6] or "cad").upper(),
            "price_id": r[7] or "",
            "product_name": r[8] or r[1],
            "product_url": r[9] or "",
            "icon": r[10] or "📦",
        }
        for r in rows
    ]
    total_monthly = sum(s["amount_cents"] for s in subscriptions) / 100
    return {"subscriptions": subscriptions, "total_monthly": total_monthly}


def calculate_proration(subscription_id: str, new_price_id: str) -> dict:
    """Preview proration amount for changing to a new price."""
    try:
        items = stripe.SubscriptionItem.list(subscription=subscription_id, limit=10)
        if not items.data:
            return {"error": "subscription items not found"}
        item_id = items.data[0].id
        preview = stripe.Invoice.upcoming(
            subscription=subscription_id,
            subscription_items=[{"id": item_id, "price": new_price_id}],
            subscription_proration_behavior="create_prorations",
        )
        return {
            "amount_due_cents": preview.amount_due,
            "currency": preview.currency.upper(),
        }
    except stripe.error.StripeError as e:
        logger.warning("calculate_proration: %s", e)
        return {"error": str(e)}


def change_plan(subscription_id: str, new_price_id: str) -> dict:
    """Change subscription to a new price with immediate proration."""
    try:
        items = stripe.SubscriptionItem.list(subscription=subscription_id, limit=10)
        if not items.data:
            return {"success": False, "error": "subscription items not found"}
        item_id = items.data[0].id
        updated = stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="create_prorations",
        )
        return {"success": True, "status": updated.status}
    except stripe.error.StripeError as e:
        logger.error("change_plan: %s", e)
        return {"success": False, "error": str(e)}


def cancel_subscription(subscription_id: str) -> dict:
    """Cancel at period end — user keeps access until expiry."""
    try:
        updated = stripe.Subscription.modify(
            subscription_id, cancel_at_period_end=True
        )
        return {
            "success": True,
            "cancel_at_period_end": updated.cancel_at_period_end,
            "current_period_end": updated.current_period_end,
        }
    except stripe.error.StripeError as e:
        logger.error("cancel_subscription: %s", e)
        return {"success": False, "error": str(e)}


def list_invoices(stripe_customer_id: str, limit: int = 12) -> list:
    """Return recent invoices for a customer."""
    try:
        invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=limit)
        return [
            {
                "invoice_id": inv.id,
                "number": inv.number or "",
                "amount_paid_cents": inv.amount_paid,
                "currency": inv.currency.upper(),
                "status": inv.status,
                "created": inv.created,
                "invoice_pdf": inv.invoice_pdf or "",
                "period_start": inv.period_start,
            }
            for inv in invoices.data
        ]
    except stripe.error.StripeError as e:
        logger.warning("list_invoices: %s", e)
        return []


def resolve_price_id(product_slug: str) -> str | None:
    """Look up Stripe price ID for a product slug from marketplace_registry."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT stripe_price_id FROM marketplace_registry WHERE slug = %s",
            (product_slug,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()
```

- [ ] **Step 2.4: Run tests**

```bash
docker exec kbs_app python3 -c "
import sys; sys.path.insert(0, '/app')
import pytest
raise SystemExit(pytest.main(['/app/tests/test_billing_service.py', '-v']))
" 2>&1 | tail -5
```

Expected: 2 PASS

- [ ] **Step 2.5: Commit**

```bash
git add kytran-business-suite/core/billing_service.py \
        kytran-business-suite/tests/test_billing_service.py
git commit -m "feat(kbs): billing_service — subscription summary, proration, cancel, invoices"
```

---

## Task 3: Add /billing routes

**Files:**
- Modify: `kytran-business-suite/core/billing_routes.py`

- [ ] **Step 3.1: Read existing file structure**

```bash
grep -n "^@billing_bp\|^def \|^from\|^import" kytran-business-suite/core/billing_routes.py | head -20
```

Note blueprint name, existing imports, and auth pattern (does it use `@login_required` or manual check?).

- [ ] **Step 3.2: Add imports at top**

Alongside existing imports in `billing_routes.py`, add:
```python
from core.billing_service import (
    get_subscription_summary,
    calculate_proration,
    change_plan,
    cancel_subscription,
    list_invoices,
    resolve_price_id,
)
from core.db import get_db
```

- [ ] **Step 3.3: Add four routes**

Append to `billing_routes.py`:
```python
@billing_bp.route("/dashboard", methods=["GET"])
def billing_dashboard():
    from flask_login import current_user
    if not current_user.is_authenticated:
        return redirect("/login")
    summary = get_subscription_summary(user_id=current_user.id)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s LIMIT 1",
            (current_user.id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    invoices = list_invoices(stripe_customer_id=row[0]) if row else []
    conn2 = get_db()
    cur2 = conn2.cursor()
    try:
        cur2.execute(
            "SELECT slug, name, description, price_monthly, icon FROM marketplace_registry "
            "WHERE is_active = TRUE ORDER BY sort_order"
        )
        all_products = [
            {
                "slug": r[0], "name": r[1], "description": r[2] or "",
                "price_monthly": float(r[3] or 0), "icon": r[4] or "📦",
            }
            for r in cur2.fetchall()
        ]
    finally:
        conn2.close()
    return render_template(
        "billing_dashboard.html",
        subscriptions=summary["subscriptions"],
        total_monthly=summary["total_monthly"],
        invoices=invoices,
        all_products=all_products,
    )


@billing_bp.route("/api/proration", methods=["GET"])
def get_proration():
    subscription_id = request.args.get("subscription_id", "").strip()
    new_price_slug = request.args.get("new_price_slug", "").strip()
    if not subscription_id or not new_price_slug:
        return jsonify({"error": "subscription_id and new_price_slug required"}), 400
    price_id = resolve_price_id(new_price_slug)
    if not price_id:
        return jsonify({"error": f"no stripe_price_id configured for {new_price_slug}"}), 400
    result = calculate_proration(subscription_id=subscription_id, new_price_id=price_id)
    return jsonify(result)


@billing_bp.route("/api/change-plan", methods=["POST"])
def api_change_plan():
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    subscription_id = str(data.get("subscription_id", "")).strip()
    new_price_slug = str(data.get("new_price_slug", "")).strip()
    if not subscription_id or not new_price_slug:
        return jsonify({"error": "subscription_id and new_price_slug required"}), 400
    price_id = resolve_price_id(new_price_slug)
    if not price_id:
        return jsonify({"error": f"no stripe_price_id configured for {new_price_slug}"}), 400
    result = change_plan(subscription_id=subscription_id, new_price_id=price_id)
    return jsonify(result)


@billing_bp.route("/api/cancel", methods=["POST"])
def api_cancel():
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    subscription_id = str(data.get("subscription_id", "")).strip()
    if not subscription_id:
        return jsonify({"error": "subscription_id required"}), 400
    result = cancel_subscription(subscription_id=subscription_id)
    return jsonify(result)
```

- [ ] **Step 3.4: Restart and verify routes**

```bash
docker compose up -d --force-recreate kbs_app && sleep 10
docker exec kbs_app python3 -c "
import sys; sys.path.insert(0, '/app')
from app import app
rules = sorted(str(r) for r in app.url_map.iter_rules() if 'billing' in str(r))
print('\n'.join(rules))
" 2>&1
```

Expected: `/billing/api/cancel`, `/billing/api/change-plan`, `/billing/api/proration`, `/billing/dashboard` listed.

- [ ] **Step 3.5: Commit**

```bash
git add kytran-business-suite/core/billing_routes.py
git commit -m "feat(kbs): /billing/dashboard + proration, change-plan, cancel API routes"
```

---

## Task 4: billing_dashboard.html — LCARS UI

**Files:**
- Create: `kytran-business-suite/shared/templates/billing_dashboard.html`

- [ ] **Step 4.1: Read billing_success.html to get base template name**

```bash
head -5 kytran-business-suite/shared/templates/billing_success.html
```

Note the `{% extends "..." %}` line — use the same base.

- [ ] **Step 4.2: Add timestamp filter to KBS app.py**

Read `kytran-business-suite/app.py` first to find where filters are registered, then add:
```python
from datetime import datetime

@app.template_filter("ts_date")
def ts_date(ts):
    """Convert Unix timestamp to YYYY-MM-DD string."""
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return "—"
```

- [ ] **Step 4.3: Write billing_dashboard.html**

The template must NOT use `innerHTML` with dynamic data. All dynamic content is rendered server-side via Jinja2 (safe) or constructed via `textContent`/`createElement` in JS.

```html
{% extends "base.html" %}
{% block title %}Billing — KBS{% endblock %}
{% block content %}
<div style="max-width:900px;margin:0 auto;padding:24px;font-family:sans-serif">

  <h1 style="color:#7c3aed;font-size:20px;margin-bottom:4px">Billing &amp; Subscriptions</h1>
  <p style="color:#888;font-size:13px;margin-bottom:24px">Manage your active products and payment history.</p>

  <!-- Active Subscriptions -->
  <section style="margin-bottom:32px">
    <h2 style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:12px">Active Products</h2>
    {% if subscriptions %}
      {% for sub in subscriptions %}
      <div style="border:1px solid #333;border-radius:8px;padding:16px;background:#050509;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-size:15px;font-weight:600">{{ sub.icon | e }} {{ sub.product_name | e }}</div>
          <div style="color:#aaa;font-size:13px;margin-top:4px">
            ${{ "%.2f" | format(sub.amount_cents / 100) }} {{ sub.currency }}/mo
            {% if sub.cancel_at_period_end %}
              &middot; <span style="color:#f59e0b">Cancels {{ sub.renews_at[:10] if sub.renews_at else "soon" }}</span>
            {% else %}
              &middot; Renews {{ sub.renews_at[:10] if sub.renews_at else "—" }}
            {% endif %}
          </div>
        </div>
        <div style="display:flex;gap:8px">
          {% if not sub.cancel_at_period_end %}
          <button
            data-sub-id="{{ sub.subscription_id | e }}"
            data-price-id="{{ sub.price_id | e }}"
            class="btn-change-plan"
            style="background:#7c3aed;color:#fff;border:none;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:12px">
            Change Plan
          </button>
          <button
            data-sub-id="{{ sub.subscription_id | e }}"
            data-end-date="{{ sub.renews_at[:10] if sub.renews_at else '' }}"
            class="btn-cancel"
            style="background:transparent;color:#ef4444;border:1px solid #ef4444;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:12px">
            Cancel
          </button>
          {% else %}
          <span style="color:#f59e0b;font-size:12px;padding:7px 0">Cancelling at period end</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
      <div style="text-align:right;color:#888;font-size:13px;margin-top:8px">
        Total: <strong style="color:#7c3aed">${{ "%.2f" | format(total_monthly) }}/mo</strong>
      </div>
    {% else %}
      <div style="border:1px solid #222;border-radius:8px;padding:24px;text-align:center;color:#555;font-size:13px">
        No active subscriptions.
        <a href="/marketplace" style="color:#7c3aed">Browse products &rarr;</a>
      </div>
    {% endif %}
  </section>

  <!-- Invoice History -->
  <section>
    <h2 style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:12px">Invoice History</h2>
    {% if invoices %}
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="border-bottom:1px solid #333;color:#888">
          <th style="padding:8px 12px;text-align:left;font-weight:500">Date</th>
          <th style="padding:8px 12px;text-align:left;font-weight:500">Invoice #</th>
          <th style="padding:8px 12px;text-align:right;font-weight:500">Amount</th>
          <th style="padding:8px 12px;text-align:center;font-weight:500">Status</th>
          <th style="padding:8px 12px;text-align:center;font-weight:500">PDF</th>
        </tr>
      </thead>
      <tbody>
        {% for inv in invoices %}
        <tr style="border-bottom:1px solid #111">
          <td style="padding:8px 12px;color:#aaa">{{ inv.period_start | ts_date if inv.period_start else "—" }}</td>
          <td style="padding:8px 12px">{{ inv.number | e or inv.invoice_id[:12] | e }}</td>
          <td style="padding:8px 12px;text-align:right">${{ "%.2f" | format(inv.amount_paid_cents / 100) }} {{ inv.currency }}</td>
          <td style="padding:8px 12px;text-align:center">
            {% if inv.status == 'paid' %}
              <span style="color:#22c55e;font-size:11px">&#10003; Paid</span>
            {% else %}
              <span style="color:#f59e0b;font-size:11px">{{ inv.status | e }}</span>
            {% endif %}
          </td>
          <td style="padding:8px 12px;text-align:center">
            {% if inv.invoice_pdf %}
            <a href="{{ inv.invoice_pdf | e }}" target="_blank" rel="noopener noreferrer"
               style="color:#7c3aed;font-size:11px">PDF</a>
            {% else %}—{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <p style="color:#555;font-size:13px">No invoices yet.</p>
    {% endif %}
  </section>
</div>

<!-- Change Plan Modal -->
<div id="changePlanModal" role="dialog" aria-modal="true" aria-labelledby="changePlanTitle"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#0a0a14;border:1px solid #7c3aed;border-radius:10px;padding:24px;max-width:580px;width:90%">
    <h3 id="changePlanTitle" style="color:#7c3aed;margin:0 0 16px;font-size:15px">Choose a Plan</h3>
    <div id="planPickerList" style="display:flex;flex-direction:column;gap:8px"></div>
    <div id="prorationMsg" style="margin-top:12px;padding:10px;background:#050509;border-radius:6px;font-size:12px;color:#aaa;display:none"></div>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">
      <button id="btnCloseChangePlan" style="background:transparent;color:#888;border:1px solid #333;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:13px">Cancel</button>
      <button id="btnConfirmChange" style="background:#7c3aed;color:#fff;border:none;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:13px;display:none">Confirm Change</button>
    </div>
  </div>
</div>

<!-- Cancel Modal -->
<div id="cancelModal" role="dialog" aria-modal="true" aria-labelledby="cancelTitle"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#0a0a14;border:1px solid #ef4444;border-radius:10px;padding:24px;max-width:400px;width:90%">
    <h3 id="cancelTitle" style="color:#ef4444;margin:0 0 10px;font-size:15px">Cancel Subscription?</h3>
    <p style="color:#aaa;font-size:13px;margin-bottom:20px">
      Your access continues until <strong id="cancelEndDate" style="color:#fff"></strong>. After that, the product will be locked.
    </p>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button id="btnCloseCancelModal" style="background:transparent;color:#888;border:1px solid #333;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:13px">Keep Plan</button>
      <button id="btnConfirmCancel" style="background:#ef4444;color:#fff;border:none;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:13px">Yes, Cancel</button>
    </div>
  </div>
</div>

<script>
(function () {
  'use strict';

  // All product data is embedded server-side — no dynamic HTML construction from user input
  var allProducts = {{ all_products | tojson }};
  var currentSubId = null;
  var selectedSlug = null;

  // --- Plan change flow ---
  document.querySelectorAll('.btn-change-plan').forEach(function (btn) {
    btn.addEventListener('click', function () {
      currentSubId = btn.getAttribute('data-sub-id');
      selectedSlug = null;
      document.getElementById('btnConfirmChange').style.display = 'none';
      document.getElementById('prorationMsg').style.display = 'none';
      buildPlanList();
      showModal('changePlanModal');
    });
  });

  function buildPlanList() {
    var list = document.getElementById('planPickerList');
    // Clear safely via DOM
    while (list.firstChild) list.removeChild(list.firstChild);
    allProducts.forEach(function (p) {
      var row = document.createElement('div');
      row.style.cssText = 'border:1px solid #333;border-radius:6px;padding:10px;cursor:pointer;display:flex;justify-content:space-between;align-items:center';
      row.setAttribute('data-slug', p.slug);

      var left = document.createElement('div');
      var title = document.createElement('strong');
      title.textContent = (p.icon || '') + ' ' + p.name;
      var desc = document.createElement('div');
      desc.style.cssText = 'color:#888;font-size:11px';
      desc.textContent = p.description || '';
      left.appendChild(title);
      left.appendChild(desc);

      var price = document.createElement('div');
      price.style.cssText = 'color:#7c3aed;font-weight:600;font-size:13px';
      price.textContent = '$' + p.price_monthly.toFixed(2) + '/mo';

      row.appendChild(left);
      row.appendChild(price);
      row.addEventListener('click', function () { selectPlan(p.slug); });
      list.appendChild(row);
    });
  }

  function selectPlan(slug) {
    selectedSlug = slug;
    var msg = document.getElementById('prorationMsg');
    msg.textContent = 'Calculating proration…';
    msg.style.display = 'block';
    document.getElementById('btnConfirmChange').style.display = 'none';

    fetch('/billing/api/proration?subscription_id=' + encodeURIComponent(currentSubId) + '&new_price_slug=' + encodeURIComponent(slug))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          msg.textContent = 'Could not calculate: ' + data.error;
        } else {
          var amt = (data.amount_due_cents / 100).toFixed(2);
          msg.textContent = 'Prorated charge today: $' + amt + ' ' + data.currency;
          document.getElementById('btnConfirmChange').style.display = 'inline-block';
        }
      })
      .catch(function () { msg.textContent = 'Failed to calculate proration.'; });
  }

  document.getElementById('btnConfirmChange').addEventListener('click', function () {
    if (!currentSubId || !selectedSlug) return;
    fetch('/billing/api/change-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription_id: currentSubId, new_price_slug: selectedSlug }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) { location.reload(); }
        else { alert('Could not change plan: ' + data.error); }
      })
      .catch(function () { alert('Request failed. Please try again.'); });
  });

  document.getElementById('btnCloseChangePlan').addEventListener('click', function () { hideModal('changePlanModal'); });

  // --- Cancel flow ---
  document.querySelectorAll('.btn-cancel').forEach(function (btn) {
    btn.addEventListener('click', function () {
      currentSubId = btn.getAttribute('data-sub-id');
      document.getElementById('cancelEndDate').textContent = btn.getAttribute('data-end-date') || 'end of billing period';
      showModal('cancelModal');
    });
  });

  document.getElementById('btnConfirmCancel').addEventListener('click', function () {
    if (!currentSubId) return;
    fetch('/billing/api/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription_id: currentSubId }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) { location.reload(); }
        else { alert('Could not cancel: ' + data.error); }
      })
      .catch(function () { alert('Request failed. Please try again.'); });
  });

  document.getElementById('btnCloseCancelModal').addEventListener('click', function () { hideModal('cancelModal'); });

  function showModal(id) { document.getElementById(id).style.display = 'flex'; }
  function hideModal(id) { document.getElementById(id).style.display = 'none'; }
}());
</script>
{% endblock %}
```

- [ ] **Step 4.4: Restart and smoke test**

```bash
docker compose up -d --force-recreate kbs_app && sleep 10
docker exec kbs_app python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://localhost:8091/billing/dashboard', timeout=5)
    print('Status:', r.status)
except urllib.error.HTTPError as e:
    print('HTTP', e.code, '(redirect to login is OK)')
" 2>&1
```

Expected: 200 or redirect to login (both confirm the route is live).

- [ ] **Step 4.5: Commit**

```bash
git add kytran-business-suite/shared/templates/billing_dashboard.html \
        kytran-business-suite/app.py
git commit -m "feat(kbs): billing_dashboard.html — LCARS subscription UI with safe DOM construction"
```

---

## Task 5: Nav link + Stripe price ID note

**Files:**
- Modify: nav template in `kytran-business-suite/shared/templates/`

- [ ] **Step 5.1: Find nav template**

```bash
grep -rl "nav\|navbar\|sidebar" kytran-business-suite/shared/templates/ | head -5
grep -rl "checkout\|billing" kytran-business-suite/shared/templates/ | head -5
```

- [ ] **Step 5.2: Add billing link to nav**

In the nav template, add a link using safe text only:
```html
<a href="/billing/dashboard" style="color:#aaa;text-decoration:none">&#x1F4B3; Billing</a>
```

- [ ] **Step 5.3: Document price ID requirement**

Append a comment to `kytran-business-suite/migrations/012_billing_tables.sql`:
```sql
-- REQUIRED DATA ENTRY: Populate stripe_price_id in marketplace_registry for each
-- product before plan changes will work. Example:
-- UPDATE marketplace_registry SET stripe_price_id = 'price_XXXX' WHERE slug = 'wtf-premium';
-- Create price IDs in Stripe Dashboard (test mode) first.
```

- [ ] **Step 5.4: Commit**

```bash
git add kytran-business-suite/shared/templates/ \
        kytran-business-suite/migrations/012_billing_tables.sql
git commit -m "feat(kbs): billing nav link + stripe_price_id data entry note"
```

---

## Task 6: Delegate + PR

- [ ] **Step 6.1: Delegate code review to F.O.R.G.E.**

Via ARCHIE MCP:
```
mcp__archie__delegate_task(
    capability="code_review",
    reason="Review Phase 1 KBS billing dashboard: billing_service.py, new billing_routes.py routes, billing_dashboard.html. Check Stripe API error handling, auth enforcement on POST routes, no innerHTML with dynamic data.",
    delegation_source="claude",
    project_id=302
)
```

- [ ] **Step 6.2: Push and open PR**

```bash
# From kytran-business-suite repo:
cd kytran-business-suite && git push origin feat/phase0-access-control-foundation
# From archie-platform repo:
git push origin feat/phase0-access-control-foundation
gh pr create --title "feat: Phase 1 — KBS Billing Dashboard (#302)" \
  --body "Subscription management UI at /billing/dashboard. Missing billing_customers + billing_subscriptions tables created. Plan picker with Stripe proration preview. Cancel at period end. Invoice history with PDF links. All JS uses safe DOM methods (no innerHTML with dynamic data)."
```

---

## Self-Review

**Spec coverage:**
- ✅ Dedicated `/billing/dashboard` in KBS nav — Tasks 3+5
- ✅ Plan card with Change Plan + Cancel buttons — Task 4
- ✅ Plan picker with proration preview (API + UI) — Tasks 2+3+4
- ✅ Cancel at period end — Tasks 2+3+4
- ✅ Invoice history with PDF download links — Tasks 2+4
- ✅ Missing `billing_customers` + `billing_subscriptions` tables — Task 1
- ✅ XSS safe — all dynamic HTML via Jinja2 server-side escaping or DOM `textContent`

**Data entry requirement (not code):**
`marketplace_registry.stripe_price_id` must be populated per product before plan changes work. Documented in migration comment.

**Type consistency:** `get_subscription_summary` returns `{"subscriptions": list[dict], "total_monthly": float}`. Route passes same keys to template. Template accesses `sub.subscription_id`, `sub.product_name`, `sub.icon`, `sub.renews_at`, `sub.cancel_at_period_end`, `sub.amount_cents`, `sub.currency` — all defined in billing_service.py.
