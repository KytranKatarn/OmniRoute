# KSM Feature Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add subscription tier gating (free/pro/business/enterprise) to the Kytran System Operations standalone, with admin override for internal use.

**Architecture:** A `subscriptions` table stores per-user tier. A `require_tier()` decorator gates routes. A `subscription_service.py` resolves tier (override > DB > default). Compliance pack lists, scan frequency, theme access, and badge/SSO endpoints are all tier-gated.

**Tech Stack:** Python/Flask, SQLite, Jinja2 templates

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `config.py` | Add `TIER_OVERRIDE` env var |
| Modify | `db.py` | Add `subscriptions` table to `init_db()` |
| Create | `services/subscription_service.py` | Tier resolution, pack/theme/scan gating logic |
| Create | `middleware/__init__.py` | Package init |
| Create | `middleware/tier_gate.py` | `require_tier()` decorator |
| Create | `routes/subscription_routes.py` | Subscription status + admin tier management |
| Create | `templates/upgrade_required.html` | Upgrade prompt page |
| Modify | `routes/badge_routes.py` | Add tier gate to badge endpoints |
| Modify | `routes/compliance_routes.py` | Gate packs by tier, gate remediation |
| Modify | `services/compliance_service.py` | Filter packs by allowed list |
| Modify | `services/scheduler.py` | Set interval by tier |
| Modify | `auth.py` | Gate SSO by tier |
| Modify | `templates/settings.html` | Show tier badge + locked themes |
| Modify | `routes/__init__.py` | Register subscription routes |
| Modify | `app.py` | Pass tier context to templates |

---

## Task 1: Config + Database Schema

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/config.py`
- Modify: `kytran-server-manager/kytran_server_manager/db.py`

- [ ] **Step 1: Read config.py and db.py**

Read both files to understand current patterns.

- [ ] **Step 2: Add TIER_OVERRIDE to config.py**

Add to the Config class:

```python
    # Subscription tier override (set to "enterprise" for internal ARCHIE instance)
    TIER_OVERRIDE = os.environ.get("KSM_TIER_OVERRIDE", "")
```

- [ ] **Step 3: Add subscriptions table to db.py init_db()**

Find the `init_db()` function and add after the existing CREATE TABLE statements:

```python
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free', 'pro', 'business', 'enterprise')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'cancelled', 'past_due', 'trialing')),
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            current_period_end TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/config.py kytran_server_manager/db.py
git commit -m "feat(subscription): add TIER_OVERRIDE config + subscriptions table"
```

---

## Task 2: Subscription Service

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/subscription_service.py`

- [ ] **Step 1: Create subscription_service.py**

```python
"""Subscription tier resolution and feature gating logic."""

from flask import current_app

TIER_LEVELS = {"free": 0, "pro": 1, "business": 2, "enterprise": 3}

# Compliance packs allowed per tier
TIER_PACKS = {
    "free": ["cis-ubuntu"],
    "pro": ["cis-ubuntu", "ubuntu-stig", "network-stig"],
    "business": ["cis-ubuntu", "ubuntu-stig", "network-stig", "docker-stig", "hipaa"],
    "enterprise": ["cis-ubuntu", "ubuntu-stig", "network-stig", "docker-stig", "hipaa"],
}

# Themes allowed per tier
TIER_THEMES = {
    "free": ["kytran", "lcars"],
    "pro": ["kytran", "lcars", "midnight"],
    "business": ["kytran", "lcars", "midnight", "arctic", "ember"],
    "enterprise": ["kytran", "lcars", "midnight", "arctic", "ember"],
}

# Scan interval per tier (seconds)
TIER_SCAN_INTERVAL = {
    "free": 86400,
    "pro": 21600,
    "business": 3600,
    "enterprise": None,  # uses KSM_COMPLIANCE_SCAN_INTERVAL config
}


def get_user_tier(user_id=None):
    """Resolve the active tier for a user.

    Priority: 1) admin override, 2) user subscription, 3) default free.
    """
    override = current_app.config.get("TIER_OVERRIDE", "")
    if override in TIER_LEVELS:
        return override

    if user_id:
        try:
            from db import get_db
            conn = get_db()
            cur = conn.execute(
                "SELECT tier FROM subscriptions WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            row = cur.fetchone()
            conn.close()
            if row:
                return row[0] if isinstance(row, tuple) else row["tier"]
        except Exception:
            pass

    return "free"


def tier_at_least(user_tier, minimum_tier):
    """Check if user_tier meets or exceeds minimum_tier."""
    return TIER_LEVELS.get(user_tier, 0) >= TIER_LEVELS.get(minimum_tier, 0)


def get_allowed_packs(tier):
    """Return list of compliance pack IDs allowed for this tier."""
    return TIER_PACKS.get(tier, TIER_PACKS["free"])


def get_allowed_themes(tier):
    """Return list of theme names allowed for this tier."""
    return TIER_THEMES.get(tier, TIER_THEMES["free"])


def get_scan_interval(tier):
    """Return scan interval in seconds for this tier."""
    interval = TIER_SCAN_INTERVAL.get(tier)
    if interval is None:
        return current_app.config.get("COMPLIANCE_SCAN_INTERVAL", 21600)
    return interval


def set_user_tier(user_id, tier):
    """Set or update a user's subscription tier (admin use)."""
    if tier not in TIER_LEVELS:
        raise ValueError(f"Invalid tier: {tier}")
    from db import get_db
    conn = get_db()
    conn.execute(
        """INSERT INTO subscriptions (user_id, tier, status)
           VALUES (?, ?, 'active')
           ON CONFLICT(user_id) DO UPDATE SET tier = ?, updated_at = datetime('now')""",
        (user_id, tier, tier),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/subscription_service.py
git commit -m "feat(subscription): add subscription service with tier resolution and gating logic"
```

---

## Task 3: Tier Gate Decorator

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/middleware/__init__.py`
- Create: `kytran-server-manager/kytran_server_manager/middleware/tier_gate.py`

- [ ] **Step 1: Create middleware package**

Create empty `__init__.py`:

```python
```

- [ ] **Step 2: Create tier_gate.py**

```python
"""Subscription tier gate decorator for Flask routes."""

from functools import wraps
from flask import request, jsonify, render_template, current_app
from flask_login import current_user


def require_tier(minimum_tier):
    """Decorator: block access if user's tier is below minimum.

    For API requests (Accept: application/json): returns 403 JSON.
    For HTML requests: renders upgrade_required.html.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from services.subscription_service import get_user_tier, tier_at_least, TIER_LEVELS

            user_id = getattr(current_user, "id", None) if current_user and current_user.is_authenticated else None
            user_tier = get_user_tier(user_id)

            if tier_at_least(user_tier, minimum_tier):
                return f(*args, **kwargs)

            # Blocked — determine response format
            wants_json = (
                request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json"
                or request.path.startswith("/api/")
                or request.path.endswith(".svg")
            )

            if wants_json:
                return jsonify({
                    "error": "upgrade_required",
                    "message": f"This feature requires {minimum_tier} tier or higher.",
                    "required_tier": minimum_tier,
                    "current_tier": user_tier,
                    "upgrade_url": "/settings#subscription",
                }), 403

            return render_template(
                "upgrade_required.html",
                required_tier=minimum_tier,
                current_tier=user_tier,
                feature=request.endpoint or "this feature",
                tier_prices={"pro": 29, "business": 49, "enterprise": 99},
            ), 403

        return decorated_function
    return decorator
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/middleware/__init__.py kytran_server_manager/middleware/tier_gate.py
git commit -m "feat(subscription): add require_tier() decorator for route gating"
```

---

## Task 4: Upgrade Required Template

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/templates/upgrade_required.html`

- [ ] **Step 1: Read base.html for extends pattern**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/templates/base.html` to understand the template inheritance pattern.

- [ ] **Step 2: Create upgrade_required.html**

Create the upgrade prompt page matching the LCARS dark theme. It should show:
- What feature was blocked
- Current tier vs required tier
- Feature comparison table (what each tier gets)
- Pricing for each tier
- "Upgrade" button (placeholder link to /settings#subscription for now)

Use the LCARS frame styling (extend base.html, use `--frame-color` variables). Include the tier comparison from the spec's feature matrix.

IMPORTANT: Match the standalone's existing template style. Read base.html first.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/upgrade_required.html
git commit -m "feat(subscription): add upgrade required prompt page"
```

---

## Task 5: Subscription Routes (Status + Admin)

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/subscription_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Read routes/__init__.py**

Read to understand the registration pattern.

- [ ] **Step 2: Create subscription_routes.py**

```python
"""Subscription management routes."""

from flask import jsonify, request
from flask_login import login_required, current_user


def register_subscription_routes(bp, admin_required):
    @bp.route("/api/subscription/status", methods=["GET"])
    @login_required
    def subscription_status():
        """Return current user's subscription tier and features."""
        from services.subscription_service import (
            get_user_tier, get_allowed_packs, get_allowed_themes,
            get_scan_interval, TIER_LEVELS,
        )
        tier = get_user_tier(current_user.id)
        return jsonify({
            "tier": tier,
            "tier_level": TIER_LEVELS.get(tier, 0),
            "allowed_packs": get_allowed_packs(tier),
            "allowed_themes": get_allowed_themes(tier),
            "scan_interval": get_scan_interval(tier),
            "prices": {"pro": 29, "business": 49, "enterprise": 99},
        })

    @bp.route("/api/admin/subscription/<int:user_id>", methods=["PUT"])
    @login_required
    @admin_required
    def admin_set_tier(user_id):
        """Admin: manually set a user's subscription tier."""
        data = request.get_json() or {}
        tier = data.get("tier")
        if not tier:
            return jsonify({"error": "tier is required"}), 400

        try:
            from services.subscription_service import set_user_tier
            set_user_tier(user_id, tier)
            return jsonify({"success": True, "user_id": user_id, "tier": tier})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 3: Register in __init__.py**

Add import and call:

```python
from .subscription_routes import register_subscription_routes
```

```python
register_subscription_routes(bp, admin_required_decorator)
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/subscription_routes.py kytran_server_manager/routes/__init__.py
git commit -m "feat(subscription): add subscription status + admin tier management routes"
```

---

## Task 6: Gate Badge + SSO Routes

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/routes/badge_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/auth.py`

- [ ] **Step 1: Read badge_routes.py and auth.py**

Read both files to find the exact routes to gate.

- [ ] **Step 2: Gate badge endpoints**

In `badge_routes.py`, add the tier gate to the `compliance_badge` route. The badge endpoint is currently public (no auth). We need to make it require login + pro tier for per-pack badges, but keep `overall.svg` public for the dashboard.

Add import at top of the `register_badge_routes` function:

```python
from middleware.tier_gate import require_tier
from flask_login import login_required
```

Gate per-pack badges but keep overall public:

```python
    @bp.route("/api/compliance/badge/<pack_id>.svg", methods=["GET"])
    def compliance_badge(pack_id):
        # Overall badge stays public
        if pack_id != "overall":
            # Check if user is logged in and has pro tier
            if not current_user or not current_user.is_authenticated:
                return _generate_badge_svg(pack_id.replace("-", " ").upper(), None), 200, {"Content-Type": "image/svg+xml"}
            from services.subscription_service import get_user_tier, tier_at_least
            tier = get_user_tier(current_user.id)
            if not tier_at_least(tier, "pro"):
                return _generate_badge_svg("UPGRADE TO PRO", None), 200, {"Content-Type": "image/svg+xml"}
        # ... rest of existing logic
```

IMPORTANT: Read the existing function first. Don't break the overall badge. The approach above returns a "UPGRADE TO PRO" badge instead of a 403, which is better for SVG embeds.

- [ ] **Step 3: Gate SSO route**

In `auth.py`, find the `/auth/sso` route and add a tier check. SSO requires pro tier. If user is on free tier and tries SSO, redirect to upgrade page.

Add after the hub URL check:

```python
    # Check tier (SSO requires pro)
    if current_user and current_user.is_authenticated:
        from services.subscription_service import get_user_tier, tier_at_least
        tier = get_user_tier(current_user.id)
        if not tier_at_least(tier, "pro"):
            return render_template("upgrade_required.html",
                required_tier="pro", current_tier=tier,
                feature="Sign in with Kytran (SSO)",
                tier_prices={"pro": 29, "business": 49, "enterprise": 99}), 403
```

IMPORTANT: SSO is a pre-login feature — the user may not be logged in yet. Only gate it if the user IS logged in and on free tier. If not logged in, let the flow proceed (they'll authenticate via ARCHIE which handles its own auth).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/badge_routes.py kytran_server_manager/auth.py
git commit -m "feat(subscription): gate badges and SSO by tier"
```

---

## Task 7: Gate Compliance Packs + Remediation

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/routes/compliance_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/services/compliance_service.py`

- [ ] **Step 1: Read compliance_routes.py and compliance_service.py**

Read both to understand the scan trigger and remediation endpoints.

- [ ] **Step 2: Filter packs by tier in compliance_routes.py**

In the POST `/api/compliance/scan` route, after getting `pack_ids` from the request, filter them by allowed packs:

```python
        # Filter packs by subscription tier
        from services.subscription_service import get_user_tier, get_allowed_packs
        tier = get_user_tier(current_user.id)
        allowed = get_allowed_packs(tier)
        if pack_ids:
            blocked = [p for p in pack_ids if p not in allowed]
            if blocked:
                return jsonify({
                    "error": "upgrade_required",
                    "message": f"Pack(s) {blocked} require a higher tier.",
                    "allowed_packs": allowed,
                    "current_tier": tier,
                }), 403
            pack_ids = [p for p in pack_ids if p in allowed]
        else:
            pack_ids = allowed  # Default to all allowed packs for this tier
```

- [ ] **Step 3: Gate remediation endpoint**

Find the remediation route (if it exists) and add:

```python
from middleware.tier_gate import require_tier
```

Apply `@require_tier("business")` to the remediation endpoint.

If there's no separate remediation endpoint, check if `run_scan` handles remediation inline — read the code first.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/compliance_routes.py kytran_server_manager/services/compliance_service.py
git commit -m "feat(subscription): gate compliance packs and remediation by tier"
```

---

## Task 8: Tier-Based Scan Frequency

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/services/scheduler.py`

- [ ] **Step 1: Read scheduler.py**

Read the current scheduler to understand how the interval is configured.

- [ ] **Step 2: Update scheduler to use tier-based interval**

In the scheduler startup or loop function, resolve the scan interval from the tier:

```python
    # Resolve scan interval from tier
    from services.subscription_service import get_scan_interval, get_user_tier
    tier = get_user_tier()  # No user_id = uses override or default
    interval = get_scan_interval(tier)
```

Replace the hardcoded `COMPLIANCE_SCAN_INTERVAL` config read with this tier-aware version.

Also update the pack list used by the scheduled scan:

```python
    from services.subscription_service import get_allowed_packs, get_user_tier
    tier = get_user_tier()
    allowed_packs = get_allowed_packs(tier)
    result = run_scan(pack_ids=allowed_packs, triggered_by="scheduler")
```

IMPORTANT: Read the existing scheduler code. It runs outside of a user request context, so `get_user_tier()` will use the override or default — which is correct for the background scheduler.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/scheduler.py
git commit -m "feat(subscription): tier-based scan frequency and pack filtering in scheduler"
```

---

## Task 9: Settings Page — Tier Display + Theme Gating

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/templates/settings.html`
- Modify: `kytran-server-manager/kytran_server_manager/auth.py` (settings route)

- [ ] **Step 1: Read settings.html and the settings route**

Read both to understand current structure. The settings route is in `auth.py` (handles theme selection, logo upload, password change).

- [ ] **Step 2: Pass tier data to settings template**

In the settings route (in auth.py), add tier data to the render context:

```python
from services.subscription_service import get_user_tier, get_allowed_themes, TIER_LEVELS

tier = get_user_tier(current_user.id)
allowed_themes = get_allowed_themes(tier)
```

Pass `tier`, `allowed_themes`, and `TIER_LEVELS` to the template.

- [ ] **Step 3: Add subscription section to settings.html**

At the top of the settings page (before theme selection), add a subscription card:

```html
<!-- Subscription Tier -->
<div style="margin-bottom:24px;padding:16px;background:rgba(15,23,42,0.6);border:1px solid rgba(139,92,246,0.2);border-radius:8px;">
    <h3 style="color:#8b5cf6;margin:0 0 8px;font-size:14px;text-transform:uppercase;letter-spacing:1px;">Subscription</h3>
    <div style="display:flex;align-items:center;gap:12px;">
        <span style="padding:4px 12px;border-radius:6px;font-weight:700;font-size:13px;
            {% if tier == 'enterprise' %}background:rgba(139,92,246,0.2);color:#8b5cf6;border:1px solid #8b5cf6;
            {% elif tier == 'business' %}background:rgba(245,158,11,0.2);color:#f59e0b;border:1px solid #f59e0b;
            {% elif tier == 'pro' %}background:rgba(34,197,94,0.2);color:#22c55e;border:1px solid #22c55e;
            {% else %}background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.5);border:1px solid rgba(255,255,255,0.1);
            {% endif %}">{{ tier|upper }}</span>
        <span style="color:rgba(255,255,255,0.4);font-size:12px;">
            {% if tier == 'free' %}Upgrade to unlock compliance packs, badges, and more
            {% elif tier == 'pro' %}3 compliance packs, badges, SSO
            {% elif tier == 'business' %}All packs, remediation, PDF reports
            {% else %}Full access, custom packs, SLA
            {% endif %}
        </span>
    </div>
</div>
```

- [ ] **Step 4: Gate theme options**

In the theme selection section, mark locked themes:

```html
{% for theme_name in all_themes %}
<option value="{{ theme_name }}"
    {% if theme_name == current_theme %}selected{% endif %}
    {% if theme_name not in allowed_themes %}disabled{% endif %}>
    {{ theme_name|title }}{% if theme_name not in allowed_themes %} ({{ 'Pro' if theme_name == 'midnight' else 'Business' }} required){% endif %}
</option>
{% endfor %}
```

Pass `all_themes = ["kytran", "lcars", "midnight", "arctic", "ember"]` from the route.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/settings.html kytran_server_manager/auth.py
git commit -m "feat(subscription): show tier badge in settings, gate theme selection"
```

---

## Task 10: Add Override to Systemd + Deploy + Verify

**Files:** None (configuration + deployment)

- [ ] **Step 1: Add tier override to systemd**

```bash
sudo tee -a /etc/systemd/system/kytran-server-manager.service.d/hub.conf > /dev/null << 'EOF'
Environment=KSM_TIER_OVERRIDE=enterprise
EOF
```

- [ ] **Step 2: Restart standalone**

```bash
sudo systemctl daemon-reload
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 3: Verification checklist**

```bash
# 1. Subscription status (should show enterprise from override)
curl -s http://192.168.1.200:8085/dashboard/api/subscription/status | python3 -m json.tool

# 2. All packs should be allowed
# 3. All themes should be available
# 4. Badges should work
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:8085/dashboard/api/compliance/badge/hipaa.svg

# 5. Health endpoint should still work
curl -s http://192.168.1.200:8085/dashboard/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"
```

- [ ] **Step 4: Test free tier (temporarily remove override)**

```bash
# Temporarily test without override
sudo systemctl set-environment KSM_TIER_OVERRIDE=
sudo systemctl restart kytran-server-manager

# Verify free tier gating works:
# - Badge for hipaa.svg should show "UPGRADE TO PRO"
# - Subscription status should show "free"
# - Only CIS Ubuntu pack allowed in scan

# Restore override
sudo systemctl set-environment KSM_TIER_OVERRIDE=enterprise
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 5: Commit any remaining changes + log decision**

```python
mcp__archie__log_decision(
    title="KSM Feature Gating — Subscription Tiers Implemented",
    decision="Free/Pro/Business/Enterprise tiers with feature gating. Internal instance uses KSM_TIER_OVERRIDE=enterprise. Stripe deferred to platform-wide billing project.",
    project_id=193
)
```

---

## Task Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | Config + DB schema (subscriptions table) | 3 min |
| 2 | Subscription service (tier resolution + gating logic) | 5 min |
| 3 | Tier gate decorator (require_tier) | 3 min |
| 4 | Upgrade required template | 5 min |
| 5 | Subscription routes (status + admin) | 3 min |
| 6 | Gate badge + SSO routes | 5 min |
| 7 | Gate compliance packs + remediation | 5 min |
| 8 | Tier-based scan frequency | 3 min |
| 9 | Settings page tier display + theme gating | 5 min |
| 10 | Add override + deploy + verify | 5 min |

**Total: 10 tasks, ~42 minutes**
