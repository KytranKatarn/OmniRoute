# KBS Store Public Storefront Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `store.kytranempowerment.com` to the KBS Store's existing public routes, fix a Stripe return-URL bug, and add branded HTML order-success/cancelled pages.

**Architecture:** KBS Store already has a complete public storefront (`shop_public.html`) and guest checkout via Stripe. The gaps are: (1) no NPM proxy host routing `store.kytranempowerment.com` to KBS port 8091; (2) Stripe success/cancel URLs point to wrong paths (returns 404); (3) order confirmation routes return JSON instead of HTML. Fix these three things and the store is live.

**Tech Stack:** Flask (KBS), Jinja2 templates, Stripe Checkout, NPM proxy (nginx), Docker.

---

## File Map

| File | Action |
|------|--------|
| `kytran-business-suite/.env` | Set `KBS_BASE_URL=https://store.kytranempowerment.com` |
| `kytran-business-suite/plugins/kbs_store/public_routes.py` | Fix `success_url`/`cancel_url` paths; render HTML in both order routes |
| `kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html` | **Create** |
| `kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html` | **Create** |
| NPM proxy host | **Create via API** — `store.kytranempowerment.com` → `192.168.1.200:8091` |

---

### Task 1: Fix Stripe return URLs + set KBS_BASE_URL

**Files:**
- Modify: `kytran-business-suite/plugins/kbs_store/public_routes.py` lines 72-73
- Modify: `kytran-business-suite/.env`

**Context:** `_BASE = os.getenv("KBS_BASE_URL", ...)` is used to build Stripe redirect URLs. Currently the paths are `/store/order-success` but the actual Flask routes are at `/plugins/store/public/order-success`. This means Stripe redirects to a 404 after payment.

- [ ] **Step 1: Read the current URL lines to confirm**

```bash
grep -n "success_url\|cancel_url\|KBS_BASE_URL" /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/public_routes.py | head -10
grep "KBS_BASE_URL" /mnt/archie_brain/kytran-business-suite/.env
```

Expected output includes lines like:
```
72:        success_url=f"{_BASE}/store/order-success?order={order_id}",
73:        cancel_url=f"{_BASE}/store/order-cancelled?order={order_id}",
```

- [ ] **Step 2: Fix the success_url and cancel_url**

In `kytran-business-suite/plugins/kbs_store/public_routes.py`, change lines 72-73:

From:
```python
        success_url=f"{_BASE}/store/order-success?order={order_id}",
        cancel_url=f"{_BASE}/store/order-cancelled?order={order_id}",
```

To:
```python
        success_url=f"{_BASE}/plugins/store/public/order-success?order={order_id}",
        cancel_url=f"{_BASE}/plugins/store/public/order-cancelled?order={order_id}",
```

- [ ] **Step 3: Set KBS_BASE_URL in .env**

Read `kytran-business-suite/.env`, find the `KBS_BASE_URL` line (or add it). Set to:
```
KBS_BASE_URL=https://store.kytranempowerment.com
```

If no `KBS_BASE_URL` line exists, append it to the file.

- [ ] **Step 4: Commit**

```bash
git add kytran-business-suite/plugins/kbs_store/public_routes.py kytran-business-suite/.env
git commit -m "fix(kbs-store): correct Stripe return URL paths + set KBS_BASE_URL"
```

---

### Task 2: Create shop_order_success.html

**Files:**
- Create: `kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html`

- [ ] **Step 1: Create the file**

Write `kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html`:

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
           text-decoration: none; font-size: 0.85rem;
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
    <a href="/plugins/store/public/" class="btn">&#8592; Continue Shopping</a>
  </div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html
git commit -m "feat(kbs-store): branded order success page"
```

---

### Task 3: Create shop_order_cancelled.html

**Files:**
- Create: `kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html`

- [ ] **Step 1: Create the file**

Write `kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html`:

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
           text-decoration: none; font-size: 0.85rem;
           font-family: 'IBM Plex Mono', monospace; transition: background 0.2s; }
    .btn:hover { background: rgba(0,212,255,0.2); }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#8617;&#65039;</div>
    <h1>Order Cancelled</h1>
    <p class="subtitle">
      Your order was cancelled and no payment was charged.<br>
      Your cart items are still available if you'd like to try again.
    </p>
    <a href="/plugins/store/public/" class="btn">&#8592; Back to Store</a>
  </div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html
git commit -m "feat(kbs-store): branded order cancelled page"
```

---

### Task 4: Update order routes to render HTML

**Files:**
- Modify: `kytran-business-suite/plugins/kbs_store/public_routes.py` lines 600-641

**Context:** `order_success()` (line 600) and `order_cancelled()` (line 634) currently return `jsonify(...)`. After this task they render the HTML templates created in Tasks 2-3.

- [ ] **Step 1: Replace order_success() function body**

Find the `order_success()` function (lines 600-632) and replace its entire body:

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

- [ ] **Step 2: Replace order_cancelled() function body**

Find the `order_cancelled()` function (lines 634-641) and replace its entire body:

```python
    @bp.route("/order-cancelled", methods=["GET"])
    def order_cancelled():
        """Branded order cancellation page."""
        return render_template("shop_order_cancelled.html")
```

- [ ] **Step 3: Commit**

```bash
git add kytran-business-suite/plugins/kbs_store/public_routes.py
git commit -m "feat(kbs-store): order_success + order_cancelled render HTML templates"
```

---

### Task 5: Deploy changes to KBS container

**Context:** KBS runs as `kbs_app` container. Its Dockerfile uses `COPY .` so a full rebuild picks up code changes. Hot-patching with `docker cp` + restart is faster and sufficient for Python/template changes.

- [ ] **Step 1: Hot-patch changed files into the container**

```bash
docker cp /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/public_routes.py \
    kbs_app:/app/plugins/kbs_store/public_routes.py

docker cp /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/templates/shop_order_success.html \
    kbs_app:/app/plugins/kbs_store/templates/shop_order_success.html

docker cp /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/templates/shop_order_cancelled.html \
    kbs_app:/app/plugins/kbs_store/templates/shop_order_cancelled.html
```

- [ ] **Step 2: Restart KBS**

```bash
docker compose restart kbs_app && sleep 6
```

- [ ] **Step 3: Verify order-success renders HTML**

```bash
docker exec kbs_app python3 -c "
import sys; sys.path.insert(0, '/app')
from core.app import create_app
app = create_app()
with app.test_client() as c:
    r = c.get('/plugins/store/public/order-success')
    print('Status:', r.status_code)
    print('Content-Type:', r.content_type)
    print('Has HTML:', b'Order Confirmed' in r.data)
"
```

Expected:
```
Status: 200
Content-Type: text/html; charset=utf-8
Has HTML: True
```

- [ ] **Step 4: Verify order-cancelled renders HTML**

```bash
docker exec kbs_app python3 -c "
import sys; sys.path.insert(0, '/app')
from core.app import create_app
app = create_app()
with app.test_client() as c:
    r = c.get('/plugins/store/public/order-cancelled')
    print('Status:', r.status_code)
    print('Has HTML:', b'Order Cancelled' in r.data)
"
```

Expected: `Status: 200`, `Has HTML: True`

- [ ] **Step 5: Verify success_url in source is correct**

```bash
grep "success_url\|cancel_url" /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/public_routes.py
```

Expected: both lines contain `/plugins/store/public/order-success` and `/plugins/store/public/order-cancelled`.

---

### Task 6: Create NPM proxy host for store.kytranempowerment.com

**Context:** NPM (nginx-proxy-manager) runs as `nginx_proxy_manager` container, management API at `http://nginx_proxy_manager:81` (from within Docker network) or `http://192.168.1.200:81` (from host). DNS A record for `store` already points to hub IP.

- [ ] **Step 1: Get NPM JWT token**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json, os
base = 'http://nginx_proxy_manager:81/api'
email = os.getenv('NPM_ADMIN_EMAIL', '')
password = os.getenv('NPM_ADMIN_PASSWORD', '')
if not email or not password:
    print('ERROR: NPM_ADMIN_EMAIL or NPM_ADMIN_PASSWORD not set in environment')
    exit(1)
data = json.dumps({'identity': email, 'secret': password}).encode()
req = urllib.request.Request(f'{base}/tokens', data=data,
    headers={'Content-Type': 'application/json'}, method='POST')
resp = urllib.request.urlopen(req, timeout=10)
tok = json.loads(resp.read())['token']
print('Token OK — first 20 chars:', tok[:20])
"
```

Expected: `Token OK — first 20 chars: <jwt_prefix>`

If `NPM_ADMIN_EMAIL`/`NPM_ADMIN_PASSWORD` not set, check `.env` and set them. The NPM admin email is typically `admin@kytranempowerment.com` and password from the `.env` file.

- [ ] **Step 2: Create proxy host via API**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json, os
base = 'http://nginx_proxy_manager:81/api'
email = os.getenv('NPM_ADMIN_EMAIL', '')
password = os.getenv('NPM_ADMIN_PASSWORD', '')
# Get token
data = json.dumps({'identity': email, 'secret': password}).encode()
req = urllib.request.Request(f'{base}/tokens', data=data,
    headers={'Content-Type': 'application/json'}, method='POST')
tok = json.loads(urllib.request.urlopen(req, timeout=10).read())['token']
headers = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}

# Create proxy host
payload = {
    'domain_names': ['store.kytranempowerment.com'],
    'forward_scheme': 'http',
    'forward_host': '192.168.1.200',
    'forward_port': 8091,
    'ssl_forced': False,
    'allow_websocket_upgrade': False,
    'advanced_config': 'location = / {\n    return 302 /plugins/store/public/;\n}',
}
req2 = urllib.request.Request(f'{base}/nginx/proxy-hosts',
    data=json.dumps(payload).encode(), headers=headers, method='POST')
resp = json.loads(urllib.request.urlopen(req2, timeout=10).read())
print('Created proxy host ID:', resp.get('id'))
print('Domains:', resp.get('domain_names'))
"
```

Expected: `Created proxy host ID: <N>` and `Domains: ['store.kytranempowerment.com']`

- [ ] **Step 3: Request SSL certificate**

In the NPM web UI at `http://192.168.1.200:81`:
1. Find the newly created `store.kytranempowerment.com` proxy host
2. Click Edit → SSL tab
3. Select "Let's Encrypt" → enter `admin@kytranempowerment.com` → Force SSL ON → Save

Or via API (if you prefer to avoid the UI):
```bash
docker exec archie_platform python3 -c "
import urllib.request, json, os
base = 'http://nginx_proxy_manager:81/api'
email = os.getenv('NPM_ADMIN_EMAIL', '')
password = os.getenv('NPM_ADMIN_PASSWORD', '')
data = json.dumps({'identity': email, 'secret': password}).encode()
req = urllib.request.Request(f'{base}/tokens', data=data,
    headers={'Content-Type': 'application/json'}, method='POST')
tok = json.loads(urllib.request.urlopen(req, timeout=10).read())['token']
headers = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}

# Find host ID
req2 = urllib.request.Request(f'{base}/nginx/proxy-hosts', headers=headers)
hosts = json.loads(urllib.request.urlopen(req2, timeout=10).read())
host_id = next((h['id'] for h in hosts if 'store.kytranempowerment.com' in h.get('domain_names', [])), None)
print('Host ID:', host_id)
if host_id:
    # Request cert
    cert_payload = {
        'domain_names': ['store.kytranempowerment.com'],
        'meta': {'letsencrypt_email': 'admin@kytranempowerment.com', 'letsencrypt_agree': True},
        'provider': 'letsencrypt',
    }
    req3 = urllib.request.Request(f'{base}/nginx/certificates',
        data=json.dumps(cert_payload).encode(), headers=headers, method='POST')
    try:
        cert = json.loads(urllib.request.urlopen(req3, timeout=60).read())
        print('Cert ID:', cert.get('id'))
    except Exception as e:
        print('Cert error (may need UI):', e)
"
```

---

### Task 7: End-to-end verify

- [ ] **Step 1: Test root redirect**

```bash
docker exec archie_platform python3 -c "
import urllib.request
r = urllib.request.urlopen('http://192.168.1.200:8091/', timeout=8)
print('Final URL:', r.url)
print('Status:', r.status)
"
```

Expected: URL ends with `/plugins/store/public/` (followed the redirect)

- [ ] **Step 2: Test public product listing**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json
r = urllib.request.urlopen('http://192.168.1.200:8091/plugins/store/public/products', timeout=8)
data = json.loads(r.read())
print('Products count:', len(data.get('products', [])))
print('Status:', r.status)
"
```

Expected: `Status: 200`, products list (may be empty if no products added yet — that's fine)

- [ ] **Step 3: Test order-success HTML**

```bash
docker exec archie_platform python3 -c "
import urllib.request
r = urllib.request.urlopen('http://192.168.1.200:8091/plugins/store/public/order-success', timeout=8)
body = r.read()
print('Status:', r.status)
print('Is HTML:', b'Order Confirmed' in body)
print('Has back link:', b'Continue Shopping' in body)
"
```

Expected: `Status: 200`, both True.

- [ ] **Step 4: Test order-cancelled HTML**

```bash
docker exec archie_platform python3 -c "
import urllib.request
r = urllib.request.urlopen('http://192.168.1.200:8091/plugins/store/public/order-cancelled', timeout=8)
body = r.read()
print('Status:', r.status)
print('Is HTML:', b'Order Cancelled' in body)
"
```

Expected: `Status: 200`, True.

- [ ] **Step 5: Verify Stripe URLs in code**

```bash
grep "success_url\|cancel_url" /mnt/archie_brain/kytran-business-suite/plugins/kbs_store/public_routes.py
```

Expected output:
```
        success_url=f"{_BASE}/plugins/store/public/order-success?order={order_id}",
        cancel_url=f"{_BASE}/plugins/store/public/order-cancelled?order={order_id}",
```

- [ ] **Step 6: Final commit + push**

```bash
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✅ NPM proxy host for `store.kytranempowerment.com` → port 8091 (Task 6)
- ✅ Root redirect `GET /` → `/plugins/store/public/` (Task 6, advanced_config)
- ✅ `KBS_BASE_URL` set to `https://store.kytranempowerment.com` (Task 1)
- ✅ Fix `success_url`/`cancel_url` to correct paths (Task 1)
- ✅ `order_success` renders `shop_order_success.html` (Task 4)
- ✅ `order_cancelled` renders `shop_order_cancelled.html` (Task 4)
- ✅ `shop_order_success.html` created (Task 2)
- ✅ `shop_order_cancelled.html` created (Task 3)

**No placeholders:** All code blocks are complete.

**Type consistency:** `render_template("shop_order_success.html", order=order)` passes `order` dict — template accesses `order.order_number`, `order.customer_email`, `order.total`, `order.payment_status` — all fetched by the SELECT in Task 4. ✅
