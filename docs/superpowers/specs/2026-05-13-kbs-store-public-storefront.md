# KBS Store: Public Storefront at store.kytranempowerment.com

**Date:** 2026-05-13
**Task:** #2689 — Project Alpha
**Scope:** Wire `store.kytranempowerment.com` to the KBS Store public routes, fix the Stripe return URL bug, and add branded HTML order-success/cancelled pages.

---

## Context

- `shop_public.html` is already complete (301 lines): dark LCARS theme, product grid, cart drawer, Stripe checkout call — no redesign needed
- KBS Store public routes mount at `/plugins/store/public/` (plugin loader prefix `/plugins/{slug}/` + sub-blueprint `/public`)
- `store.kytranempowerment.com` DNS A record exists → hub (153.68.195.85); no NPM proxy host yet
- KBS runs on port 8091 on the hub
- `_BASE = os.getenv("KBS_BASE_URL", "https://app.kytranempowerment.com")`
- **Bug:** `success_url = f"{_BASE}/store/order-success"` but actual route is `/plugins/store/public/order-success` — Stripe redirects to a 404
- `order_success` and `order_cancelled` routes return JSON only — need HTML templates

---

## Changes

### 1. NPM proxy host

Create via NPM API (`POST /api/nginx/proxy-hosts`):
- `domain_names`: `["store.kytranempowerment.com"]`
- `forward_host`: `kbs_app` (or `192.168.1.200`)
- `forward_port`: `8091`
- `ssl_forced`: true
- `hsts_enabled`: true
- `advanced_config` (custom nginx location block to redirect bare root to the store):
  ```nginx
  location = / {
      return 302 /plugins/store/public/;
  }
  ```

SSL: request Let's Encrypt cert via NPM UI after proxy host is created.

### 2. Fix Stripe return URLs in `public_routes.py`

**File:** `kytran-business-suite/plugins/kbs_store/public_routes.py`

Change lines 72-73 from:
```python
success_url=f"{_BASE}/store/order-success?order={order_id}",
cancel_url=f"{_BASE}/store/order-cancelled?order={order_id}",
```
To:
```python
success_url=f"{_BASE}/plugins/store/public/order-success?order={order_id}",
cancel_url=f"{_BASE}/plugins/store/public/order-cancelled?order={order_id}",
```

Also set `KBS_BASE_URL=https://store.kytranempowerment.com` in the KBS `.env` file.

### 3. Update `order_success` route to return HTML

**File:** `kytran-business-suite/plugins/kbs_store/public_routes.py`

Replace the current `order_success()` function:

```python
@bp.route("/order-success", methods=["GET"])
def order_success():
    """Branded order confirmation page after successful payment."""
    order_id = request.args.get("order")
    order = None

    if order_id:
        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if tenant:
            try:
                with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
                    set_tenant_search_path(cur, tenant["id"])
                    cur.execute(
                        """
                        SELECT id, order_number, total, status, payment_status,
                               customer_email, created_at
                        FROM store_orders WHERE id = %s
                        """,
                        (int(order_id),),
                    )
                    order = cur.fetchone()
            except Exception:
                logger.exception("Error fetching order %s for success page", order_id)

    return render_template("shop_order_success.html", order=order)
```

### 4. Update `order_cancelled` route to return HTML

```python
@bp.route("/order-cancelled", methods=["GET"])
def order_cancelled():
    """Branded order cancellation page."""
    return render_template("shop_order_cancelled.html")
```

### 5. Create `shop_order_success.html`

**File:** `kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Order Confirmed — Kytran Empowerment</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root { --bg: #0d1117; --surface: #161b22; --border: rgba(255,255,255,0.08);
            --accent: #00d4ff; --text: #e6edf3; --muted: #8b949e; --radius: 8px; }
    body { font-family: 'IBM Plex Mono', monospace; background: var(--bg); color: var(--text);
           min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 2rem; }
    .card { background: var(--surface); border: 1px solid var(--accent);
            border-radius: var(--radius); padding: 2.5rem; max-width: 500px; width: 100%; text-align: center; }
    .icon { font-size: 3rem; margin-bottom: 1rem; }
    h1 { font-family: 'Orbitron', monospace; color: var(--accent); font-size: 1.1rem;
         letter-spacing: 3px; text-transform: uppercase; margin-bottom: 0.75rem; }
    .subtitle { color: var(--muted); font-size: 0.85rem; line-height: 1.7; margin-bottom: 1.5rem; }
    .order-box { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
                 padding: 1rem; margin-bottom: 1.5rem; text-align: left; }
    .order-row { display: flex; justify-content: space-between; font-size: 0.82rem; padding: 0.3rem 0; }
    .order-label { color: var(--muted); }
    .order-value { color: var(--text); }
    .order-total { color: var(--accent); font-weight: 600; }
    .btn { display: inline-block; padding: 0.65rem 1.5rem; background: rgba(0,212,255,0.12);
           border: 1px solid rgba(0,212,255,0.35); color: var(--accent); border-radius: var(--radius);
           text-decoration: none; font-size: 0.85rem; cursor: pointer;
           font-family: 'IBM Plex Mono', monospace; transition: background 0.2s; }
    .btn:hover { background: rgba(0,212,255,0.2); }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Order Confirmed</h1>
    <p class="subtitle">
      Thank you for your order! You'll receive a confirmation email shortly.
      {% if order and order.get('payment_status') == 'paid' %}
      Your payment has been processed.
      {% endif %}
    </p>
    {% if order %}
    <div class="order-box">
      <div class="order-row">
        <span class="order-label">Order</span>
        <span class="order-value">#{{ order.order_number }}</span>
      </div>
      {% if order.customer_email %}
      <div class="order-row">
        <span class="order-label">Email</span>
        <span class="order-value">{{ order.customer_email }}</span>
      </div>
      {% endif %}
      <div class="order-row">
        <span class="order-label">Total</span>
        <span class="order-total">${{ "%.2f"|format(order.total|float) }}</span>
      </div>
    </div>
    {% endif %}
    <a href="/plugins/store/public/" class="btn">← Continue Shopping</a>
  </div>
</body>
</html>
```

### 6. Create `shop_order_cancelled.html`

**File:** `kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Order Cancelled — Kytran Empowerment</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root { --bg: #0d1117; --surface: #161b22; --border: rgba(255,255,255,0.08);
            --accent: #00d4ff; --text: #e6edf3; --muted: #8b949e; --radius: 8px; }
    body { font-family: 'IBM Plex Mono', monospace; background: var(--bg); color: var(--text);
           min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 2rem; }
    .card { background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 2.5rem; max-width: 460px; width: 100%; text-align: center; }
    .icon { font-size: 3rem; margin-bottom: 1rem; }
    h1 { font-family: 'Orbitron', monospace; color: var(--muted); font-size: 1rem;
         letter-spacing: 3px; text-transform: uppercase; margin-bottom: 0.75rem; }
    .subtitle { color: var(--muted); font-size: 0.85rem; line-height: 1.7; margin-bottom: 1.5rem; }
    .btn { display: inline-block; padding: 0.65rem 1.5rem; background: rgba(0,212,255,0.12);
           border: 1px solid rgba(0,212,255,0.35); color: var(--accent); border-radius: var(--radius);
           text-decoration: none; font-size: 0.85rem; cursor: pointer;
           font-family: 'IBM Plex Mono', monospace; transition: background 0.2s; }
    .btn:hover { background: rgba(0,212,255,0.2); }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">↩️</div>
    <h1>Order Cancelled</h1>
    <p class="subtitle">
      Your order was cancelled and no payment was charged.<br>
      Your cart items are still available if you'd like to try again.
    </p>
    <a href="/plugins/store/public/" class="btn">← Back to Store</a>
  </div>
</body>
</html>
```

---

## Files Changed

| File | Action |
|------|--------|
| NPM proxy host | **Create** via API — `store.kytranempowerment.com` → port 8091, root redirect |
| `kytran-business-suite/.env` | Set `KBS_BASE_URL=https://store.kytranempowerment.com` |
| `plugins/kbs_store/public_routes.py` | Fix `success_url`/`cancel_url` paths + render HTML in both order routes |
| `plugins/kbs_store/templates/shop_order_success.html` | **Create** |
| `plugins/kbs_store/templates/shop_order_cancelled.html` | **Create** |

---

## Out of Scope

- Redesign of `shop_public.html` — already complete
- Printful product sync UI (admin side)
- New Stripe key configuration
- Multi-tenant store at other subdomains

---

## Testing

1. Visit `https://store.kytranempowerment.com` → should redirect to store grid
2. Add products to cart, enter email, click Proceed to Checkout → Stripe checkout page loads
3. Complete test payment → lands on `shop_order_success.html` with order number
4. Cancel from Stripe → lands on `shop_order_cancelled.html` with "Back to Store" link
5. Visit `https://store.kytranempowerment.com/plugins/store/public/` directly → store grid renders
