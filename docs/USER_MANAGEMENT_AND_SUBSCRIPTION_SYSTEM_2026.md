# User Management & Subscription System - Phase 6.5

**Created:** 2026-01-08
**Updated:** 2026-01-19
**Priority:** HIGH - Required before Phase 7 (Figma Integration)
**Status:** IMPLEMENTED
**Completed By:** Claude Code + A.R.C.H.I.E.

---

## 📋 Executive Summary

This plan establishes comprehensive user management, subscription-based access control, and Google OAuth integration BEFORE implementing Figma integration and other premium features. It ensures:

- ✅ **Subscription-based module access** (Free, Pro, Business, Enterprise)
- ✅ **Google OAuth login** + traditional email/password signup
- ✅ **Dynamic dashboard** that shows modules based on user permissions
- ✅ **Admin panel** for user management and module assignment
- ✅ **Agent/User separation** - Agents are NOT users, but have their own access control
- ✅ **RBAC system** fully integrated with module_registry

---

## 🔍 Current State Analysis

### ✅ **What Already Exists:**

#### **Database Infrastructure (100% Ready):**
```sql
-- Users table with OAuth fields
users (
    id, username, email, password_hash,
    role VARCHAR(50) DEFAULT 'user',              -- Role hierarchy
    is_active BOOLEAN DEFAULT true,
    is_admin BOOLEAN DEFAULT false,
    oauth_provider VARCHAR(50),                    -- 'google', 'github', etc.
    oauth_id VARCHAR(255),                        -- Provider's user ID
    oauth_data JSONB,                             -- Token, refresh_token, etc.
    google_id VARCHAR(255) UNIQUE,                -- Google-specific ID
    subscription_tier VARCHAR(20) DEFAULT 'free', -- 'free', 'pro', 'business', 'enterprise'
    subscription_expires_at TIMESTAMP,
    preferences JSONB DEFAULT '{}'
)

-- Subscription plans (4 plans already seeded!)
subscription_plans (
    id, name, slug, description,
    price_monthly NUMERIC(10,2),
    price_yearly NUMERIC(10,2),
    stripe_price_id_monthly VARCHAR(255),
    stripe_price_id_yearly VARCHAR(255),
    stripe_product_id VARCHAR(255),
    features JSONB,                               -- ["Feature 1", "Feature 2"]
    limits JSONB,                                 -- {"ai_tokens": 10000, "api_calls": 150}
    is_active BOOLEAN DEFAULT true
)
-- Existing Plans:
-- 1. Free ($0/mo): Basic tools, 5 AI requests/day, 10K tokens, 1GB storage
-- 2. Pro ($29/mo): Unlimited AI, priority support, advanced tools, 1M tokens, 50GB
-- 3. Business ($99/mo): Teams, white-label, analytics, 10M tokens, 500GB
-- 4. Enterprise (custom pricing): Everything + SLA, on-premise

-- Subscriptions (linking users to plans)
subscriptions (
    id, user_id, plan_id,
    status VARCHAR(20),                           -- 'active', 'canceled', 'expired'
    current_period_start TIMESTAMP,
    current_period_end TIMESTAMP,
    cancel_at_period_end BOOLEAN,
    stripe_subscription_id VARCHAR(255),
    metadata JSONB
)

-- Permissions (granular tool-level access)
permissions (
    id, user_id,
    tool_name VARCHAR(100),                       -- Module ID from module_registry
    can_access BOOLEAN DEFAULT false,
    can_edit BOOLEAN DEFAULT false,
    can_delete BOOLEAN DEFAULT false,
    can_admin BOOLEAN DEFAULT false,
    granted_at TIMESTAMP,
    granted_by INTEGER                            -- Admin who granted it
)
```

#### **RBAC System (100% Complete - rbac.py):**
```python
# Role hierarchy with numeric levels
Role.PUBLIC = 0          # Not logged in
Role.USER = 10           # Basic authenticated user (FREE tier)
Role.PREMIUM = 20        # Paid subscriber (PRO/BUSINESS/ENTERPRISE)
Role.ADMIN = 90          # Administrator
Role.SUPER_ADMIN = 100   # System owner (you)

# 40+ predefined permissions mapped to roles
# Functions:
- get_user_role(user) -> Role
- has_permission(permission, user) -> bool
- has_role(role, user) -> bool
- can_access_module(module_id, user) -> bool  # ✅ Integrates with module_registry
- get_accessible_modules(user) -> List[str]   # ✅ For dynamic dashboard

# Decorators for route protection:
@require_permission(Permission.ADMIN_ACCESS)
@require_role(Role.PREMIUM)
@require_any_permission(Permission.APP_BUILDER_CREATE, Permission.WEBSITE_BUILDER_CREATE)
```

#### **Module Registry (100% Complete - module_registry.py):**
```python
# Each module has:
- id, name, description, icon, category
- route (URL path)
- blueprint_import (Flask blueprint)
- required_permissions: List[str]              # e.g., ["app_builder:create"]
- minimum_role: str                            # "USER", "PREMIUM", "ADMIN", "SUPER_ADMIN"
- enabled: bool                                # Module on/off switch
- beta, coming_soon flags
- health_check function
- priority (display order)

# Existing modules:
ENABLED:
✅ app_builder (USER, beta) - "app_builder:create"
✅ website_builder (USER, beta) - "website_builder:create", "website_builder:deploy"
✅ code_editor (USER) - "code_editor:write"
✅ archie_chat (USER) - "archie:chat"  # ⚠️ BLUEPRINT NOT REGISTERED!
✅ admin_panel (ADMIN) - "admin:access"

DISABLED (Coming Soon):
❌ social_media (PREMIUM) - "social_media:create", "social_media:schedule"
❌ analytics (USER) - "analytics:view"
❌ figma_integration (PREMIUM) - "figma:import"
❌ settings (USER) - "user:settings"
❌ mining_pool (SUPER_ADMIN) - "admin:mining"
```

#### **Dashboard User Management (Partial):**
```python
# Existing routes in /tools/ (now split into standalone modules):
POST /admin/user/create                        # ✅ Create user
POST /admin/user/<id>/update                   # ✅ Update user
POST /admin/user/<id>/password                 # ✅ Reset password
POST /admin/user/<id>/delete                   # ✅ Delete user
GET  /admin/analytics/user-growth              # ✅ User growth analytics

# MISSING:
❌ GET /admin/users (list all users with filtering)
❌ POST /admin/user/<id>/subscription/update   # Change subscription tier
❌ POST /admin/user/<id>/permissions/grant     # Grant specific module permissions
❌ POST /admin/user/<id>/permissions/revoke    # Revoke permissions
❌ GET /admin/user/<id>/permissions            # View user's permissions
❌ UI for user list with subscription tiers
❌ UI for module permission assignment
```

### ❌ **What's Missing:**

1. **Google OAuth Implementation**
   - No OAuth routes registered
   - No Google OAuth library installed (authlib/google-auth)
   - No OAuth callback handling
   - No Google API credentials configured

2. **Dynamic Dashboard**
   - Dashboard is hardcoded HTML (lines 316-456 in dashboard.html)
   - Doesn't check user permissions
   - Shows same tools to all users
   - Doesn't integrate with module_registry or RBAC

3. **Dashboard UI for User Management**
   - No user list view
   - No subscription tier management UI
   - No module permission assignment UI
   - No OAuth user identification

4. **Subscription Enforcement**
   - subscription_tier exists but not checked
   - No automatic permission granting based on tier
   - No subscription expiration handling
   - No upgrade/downgrade workflows

5. **ARCHIE Chat Blueprint**
   - Blueprint exists at tools/archie_core/routes.py:archie_chat_bp
   - **NOT registered in app.py**
   - Module registry says "enabled=True" but it's 404

---

## 🎯 Solution Architecture

### **High-Level Flow:**
```
User Signup/Login
    ↓
┌─────────────────────────────────────┐
│ Authentication                      │
│ ├─ Email/Password (Flask-Login)    │
│ └─ Google OAuth 2.0 (authlib)      │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ User Object Loaded                  │
│ ├─ subscription_tier (from DB)     │
│ ├─ role (from DB or calculated)    │
│ └─ permissions (cached)             │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ RBAC System Determines Access       │
│ ├─ get_user_role() -> Role enum    │
│ ├─ get_user_permissions() -> Set   │
│ └─ can_access_module(id) -> bool   │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Dynamic Dashboard Generation        │
│ ├─ Query module_registry            │
│ ├─ Filter by can_access_module()   │
│ ├─ Group by category               │
│ └─ Render only accessible modules  │
└─────────────────────────────────────┘
    ↓
User sees personalized dashboard
```

### **User Role Determination Logic:**
```python
def get_user_role(user) -> Role:
    """Enhanced role calculation"""
    if not user or not user.is_authenticated:
        return Role.PUBLIC

    # Super Admin (you, the owner)
    if hasattr(user, 'is_super_admin') and user.is_super_admin:
        return Role.SUPER_ADMIN

    # Regular Admin
    if hasattr(user, 'is_admin') and user.is_admin:
        return Role.ADMIN

    # Subscription-based role
    if hasattr(user, 'subscription_tier'):
        tier = user.subscription_tier.lower()

        # Check if subscription is expired
        if hasattr(user, 'subscription_expires_at') and user.subscription_expires_at:
            if user.subscription_expires_at < datetime.now():
                return Role.USER  # Expired premium -> downgrade to FREE

        # Map subscription tier to role
        if tier in ['pro', 'business', 'enterprise']:
            return Role.PREMIUM
        else:  # 'free' or None
            return Role.USER

    return Role.USER
```

---

## 📊 Implementation Plan

### **PHASE 6.5.1: Foundation (Week 1 - Days 1-3)**

#### **Task 1.1: Fix ARCHIE Chat Blueprint** ⚡ **IMMEDIATE**
**Priority:** CRITICAL (blocks dashboard testing)

**Files to Modify:**
- `/mnt/archie_brain/platform_v2/app.py`

**Changes:**
```python
# Around line 802 (after other blueprint imports)
from tools.archie_core.routes import archie_chat_bp

# Around line 812 (after other blueprint registrations)
app.register_blueprint(archie_chat_bp)
```

**Testing:**
- Navigate to `/tools/archie-chat/` - should load without 404
- Send test message to ARCHIE
- Verify conversation history displays

---

#### **Task 1.2: Install Google OAuth Dependencies**
**Priority:** HIGH

**Commands:**
```bash
cd /mnt/archie_brain/platform_v2
pip install authlib==1.3.0
pip install httpx==0.27.0  # Required by authlib
pip freeze > requirements.txt
```

**Create OAuth Config:**
```bash
# Get Google OAuth credentials from:
# https://console.cloud.google.com/apis/credentials

# Add to .env:
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
GOOGLE_REDIRECT_URI=http://192.168.1.200:3000/auth/google/callback
```

---

#### **Task 1.3: Create OAuth Routes**
**Priority:** HIGH

**New File:** `/mnt/archie_brain/platform_v2/oauth_routes.py`

```python
"""
Google OAuth 2.0 Authentication Routes
"""
from flask import Blueprint, redirect, url_for, session, request, flash
from flask_login import login_user, current_user
from authlib.integrations.flask_client import OAuth
from datetime import datetime
import os
import json
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

oauth_bp = Blueprint('oauth', __name__, url_prefix='/auth')

# Initialize OAuth
oauth = OAuth()

def init_oauth(app):
    """Initialize OAuth with Flask app"""
    oauth.init_app(app)

    # Register Google OAuth provider
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

def get_db():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )

@oauth_bp.route('/google/login')
def google_login():
    """Initiate Google OAuth flow"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    redirect_uri = url_for('oauth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@oauth_bp.route('/google/callback')
def google_callback():
    """Handle Google OAuth callback"""
    try:
        # Get authorization token
        token = oauth.google.authorize_access_token()

        # Get user info from Google
        user_info = oauth.google.parse_id_token(token)

        google_id = user_info['sub']
        email = user_info['email']
        name = user_info.get('name', email.split('@')[0])

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if user exists with this google_id
        cur.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
        user = cur.fetchone()

        if not user:
            # Check if email exists (link accounts)
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cur.fetchone()

            if user:
                # Link Google account to existing user
                cur.execute("""
                    UPDATE users
                    SET google_id = %s,
                        oauth_provider = 'google',
                        oauth_id = %s,
                        oauth_data = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (google_id, google_id, json.dumps(token), user['id']))
                conn.commit()
            else:
                # Create new user
                username = name.replace(' ', '_').lower()

                # Ensure unique username
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    username = f"{username}_{google_id[:8]}"

                cur.execute("""
                    INSERT INTO users
                    (username, email, password_hash, google_id, oauth_provider, oauth_id, oauth_data,
                     subscription_tier, role, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    username,
                    email,
                    generate_password_hash(''),  # No password for OAuth users
                    google_id,
                    'google',
                    google_id,
                    json.dumps(token),
                    'free',  # Default to free tier
                    'user',
                    True
                ))

                user_id = cur.fetchone()['id']
                conn.commit()

                # Fetch the newly created user
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()

        # Update last login
        cur.execute("""
            UPDATE users
            SET last_login = %s,
                last_login_ip = %s
            WHERE id = %s
        """, (datetime.now(), request.remote_addr, user['id']))
        conn.commit()

        cur.close()
        conn.close()

        # Log user in with Flask-Login
        from models import User  # Your User model
        user_obj = User.get(user['id'])
        login_user(user_obj, remember=True)

        flash(f'Welcome, {name}! You\'ve successfully logged in with Google.', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f'Google login failed: {str(e)}', 'error')
        return redirect(url_for('login'))
```

**Register in app.py:**
```python
from oauth_routes import oauth_bp, init_oauth

# Register blueprint
app.register_blueprint(oauth_bp)

# Initialize OAuth
init_oauth(app)
```

**Add Google login button to login page:**
```html
<!-- In templates/login.html -->
<div class="oauth-buttons">
    <a href="{{ url_for('oauth.google_login') }}" class="btn btn-google">
        <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google" />
        Continue with Google
    </a>
</div>
```

---

#### **Task 1.4: Enhance User Model with Subscription Methods**
**Priority:** MEDIUM

**File:** `/mnt/archie_brain/platform_v2/models.py` (or wherever User model is)

**Add methods:**
```python
class User(UserMixin):
    # ... existing code ...

    @property
    def is_premium(self):
        """Check if user has an active premium subscription"""
        return self.subscription_tier in ['pro', 'business', 'enterprise']

    @property
    def is_subscription_expired(self):
        """Check if subscription is expired"""
        if not self.subscription_expires_at:
            return False
        return self.subscription_expires_at < datetime.now()

    @property
    def effective_role(self):
        """Get effective role considering subscription status"""
        from rbac import get_user_role
        return get_user_role(self)

    def get_permissions(self):
        """Get all permissions for this user"""
        from rbac import get_user_permissions
        return get_user_permissions(self)

    def can_access_module(self, module_id):
        """Check if user can access a specific module"""
        from rbac import can_access_module
        return can_access_module(module_id, self)

    def get_accessible_modules(self):
        """Get list of module IDs user can access"""
        from rbac import get_accessible_modules
        return get_accessible_modules(self)

    def get_subscription_limits(self):
        """Get subscription plan limits"""
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT limits
            FROM subscription_plans
            WHERE slug = %s
        """, (self.subscription_tier or 'free',))

        result = cur.fetchone()
        cur.close()
        conn.close()

        return result['limits'] if result else {}
```

---

### **PHASE 6.5.2: Dynamic Dashboard (Week 1 - Days 4-5)**

#### **Task 2.1: Create Dynamic Dashboard Generator**
**Priority:** HIGH

**New File:** `/mnt/archie_brain/platform_v2/dashboard_generator.py`

```python
"""
Dynamic Dashboard Generator
Generates personalized dashboard based on user's permissions and subscription
"""
from typing import List, Dict
from module_registry import get_enabled_modules, ModuleCategory
from rbac import can_access_module

def get_user_dashboard_data(user) -> Dict:
    """
    Generate dashboard data for a specific user

    Returns:
        {
            'modules_by_category': {
                'creation': [module1, module2],
                'development': [module3],
                ...
            },
            'accessible_count': 15,
            'total_count': 20,
            'user_role': 'PREMIUM',
            'subscription_tier': 'pro',
            'coming_soon_count': 5
        }
    """
    enabled_modules = get_enabled_modules()

    # Filter modules by user access
    accessible = []
    for module in enabled_modules:
        if can_access_module(module.id, user):
            accessible.append(module)

    # Group by category
    modules_by_category = {}
    for module in accessible:
        category = module.category.value
        if category not in modules_by_category:
            modules_by_category[category] = []
        modules_by_category[category].append({
            'id': module.id,
            'name': module.name,
            'description': module.description,
            'icon': module.icon,
            'route': module.route,
            'beta': module.beta,
            'coming_soon': module.coming_soon,
            'priority': module.priority
        })

    # Sort modules within each category by priority
    for category in modules_by_category:
        modules_by_category[category].sort(key=lambda m: m['priority'])

    # Get user role and subscription
    from rbac import get_user_role
    user_role = get_user_role(user)

    return {
        'modules_by_category': modules_by_category,
        'accessible_count': len(accessible),
        'total_count': len(enabled_modules),
        'user_role': user_role.name,
        'subscription_tier': user.subscription_tier if hasattr(user, 'subscription_tier') else 'free',
        'coming_soon_count': len([m for m in enabled_modules if m.coming_soon])
    }

def render_module_card(module: Dict, user) -> str:
    """Render HTML for a single module card"""
    beta_badge = '<span class="badge badge-beta">BETA</span>' if module.get('beta') else ''
    coming_soon_badge = '<span class="badge badge-coming-soon">COMING SOON</span>' if module.get('coming_soon') else ''

    return f"""
    <a href="{module['route']}" class="tool-card">
        <div class="tool-icon">{module['icon']}</div>
        <div class="tool-title">{module['name']}</div>
        <div class="tool-description">
            {module['description']}
            {beta_badge}
            {coming_soon_badge}
        </div>
    </a>
    """
```

**Update dashboard route in app.py:**
```python
from dashboard_generator import get_user_dashboard_data

@app.route('/dashboard')
@login_required
def dashboard():
    """Dynamic dashboard based on user permissions"""
    dashboard_data = get_user_dashboard_data(current_user)

    return render_template(
        'dashboard_dynamic.html',
        dashboard_data=dashboard_data,
        current_user=current_user,
        uptime=get_uptime()
    )
```

---

#### **Task 2.2: Create Dynamic Dashboard Template**
**Priority:** HIGH

**New File:** `/mnt/archie_brain/platform_v2/templates/dashboard_dynamic.html`

```html
{% extends "base.html" %}

{% block title %}A.R.C.H.I.E. Dashboard{% endblock %}

{% block styles %}
/* Copy all styles from existing dashboard.html (lines 6-270) */
/* Add new styles for badges */
.badge {
    display: inline-block;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    margin-left: 10px;
    letter-spacing: 1px;
}

.badge-beta {
    background: rgba(255, 193, 7, 0.3);
    color: #FFC107;
    border: 1px solid #FFC107;
}

.badge-coming-soon {
    background: rgba(33, 150, 243, 0.3);
    color: #2196F3;
    border: 1px solid #2196F3;
}

.badge-locked {
    background: rgba(244, 67, 54, 0.3);
    color: #F44336;
    border: 1px solid #F44336;
}

.upgrade-cta {
    border: 2px dashed #00FF00;
    padding: 30px;
    text-align: center;
    margin: 20px;
    background: rgba(0, 255, 0, 0.05);
}

.category-section {
    margin-bottom: 40px;
}

.category-title {
    font-size: 1.5rem;
    letter-spacing: 5px;
    margin: 30px 20px 20px 20px;
    padding-bottom: 10px;
    border-bottom: 2px solid #00FF00;
    text-transform: uppercase;
}
{% endblock %}

{% block content %}
<!-- Sandbox Mode Banner -->
{% include 'sandbox_banner.html' %}

<!-- Scanline Effect -->
<div class="scanline"></div>

<!-- User Header -->
<div class="user-header">
    <div class="user-info-left">
        <div class="user-welcome">
            > LOGGED IN AS: <span class="user-name">{{ current_user.username|upper }}</span>
        </div>
        <div class="user-role">
            ROLE: {{ dashboard_data.user_role }}
            {% if dashboard_data.subscription_tier != 'free' %}
            | SUBSCRIPTION: {{ dashboard_data.subscription_tier|upper }}
            {% endif %}
        </div>
    </div>
    <div>
        <a href="{{ url_for('logout') }}" class="logout-btn">[ LOGOUT ]</a>
    </div>
</div>

<!-- Matrix Header -->
<div class="matrix-header">
    <h1>A.R.C.H.I.E.</h1>
    <div class="subtitle">AI RESEARCH COMMAND HUB & INTELLIGENT ENGINE</div>
    <div class="subtitle" style="margin-top: 10px; font-size: 0.8rem;">
        {{ dashboard_data.accessible_count }} of {{ dashboard_data.total_count }} modules available to you
    </div>
</div>

<!-- Navigation Tabs -->
<div class="nav-tabs">
    <a href="{{ url_for('dashboard') }}" class="nav-tab active">🏠 ARCHIE LOCAL</a>
    <a href="#" class="nav-tab">💻 DEEPSEEK</a>
    {% if current_user.is_admin %}
    <a href="{{ url_for('admin.index') }}" class="nav-tab">🔧 ADMIN</a>
    {% endif %}
    <a href="#" class="nav-tab">📊 PSQL</a>
    <a href="#" class="nav-tab">☁️ CLAUDE</a>
    <a href="#" class="nav-tab">⚙️ OPT-A</a>
</div>

<!-- Modules by Category -->
{% for category, modules in dashboard_data.modules_by_category.items() %}
<div class="category-section">
    <div class="category-title">{{ category|upper }}</div>

    <div class="tool-grid">
        {% for module in modules %}
        <a href="{{ module.route }}" class="tool-card">
            <div class="tool-icon">{{ module.icon }}</div>
            <div class="tool-title">
                {{ module.name }}
                {% if module.beta %}
                <span class="badge badge-beta">BETA</span>
                {% endif %}
                {% if module.coming_soon %}
                <span class="badge badge-coming-soon">COMING SOON</span>
                {% endif %}
            </div>
            <div class="tool-description">
                {{ module.description }}
            </div>
        </a>
        {% endfor %}
    </div>
</div>
{% endfor %}

<!-- Upgrade CTA (if free tier) -->
{% if dashboard_data.subscription_tier == 'free' %}
<div class="upgrade-cta">
    <h2>🚀 UNLOCK MORE MODULES</h2>
    <p>Upgrade to PRO or BUSINESS to access advanced tools like Social Media Automation, Figma Integration, and more!</p>
    <a href="/pricing" class="btn btn-primary">VIEW PRICING</a>
</div>
{% endif %}

<!-- Status Bar -->
<div class="status-bar">
    <div class="status-left">
        <div>SYSTEM TIME: <span class="blink">●</span> <span id="clock"></span></div>
        <div>AI STATUS: <span style="color: #00FF00;">● ON</span></div>
        <div>SERVER UPTIME: <span id="uptime">{{ uptime }}</span></div>
    </div>
    <div class="status-right">
        <a href="{{ url_for('dashboard') }}" class="status-btn">📊 DASHBOARD</a>
        <a href="http://192.168.1.200:8080" target="_blank" class="status-btn">🚪 CODE SERVER</a>
    </div>
</div>

<script>
// Clock
function updateClock() {
    const now = new Date();
    const time = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('clock').textContent = time;
}
setInterval(updateClock, 1000);
updateClock();

// Server uptime
function updateServerUptime() {
    fetch('/health')
        .then(r => r.json())
        .then(data => {
            if (data.uptime) {
                document.getElementById('uptime').textContent = data.uptime;
            }
        })
        .catch(e => console.log('Uptime fetch failed'));
}
updateServerUptime();
setInterval(updateServerUptime, 30000);
</script>
{% endblock %}
```

---

### **PHASE 6.5.3: Dashboard User Management (Week 2 - Days 1-3)**

#### **Task 3.1: Create Admin User Management UI**
**Priority:** HIGH

**Update:** `/mnt/archie_brain/platform_v2/templates/ (now modular templates)`

**Add new section in left sidebar:**
```html
<!-- In the left sidebar menu -->
<div class="admin-section">
    <div class="section-title">SYSTEM</div>
    <a href="#users" onclick="showSection('users'); return false;">
        <i class="icon">👥</i> USERS
    </a>
    <a href="#subscriptions" onclick="showSection('subscriptions'); return false;">
        <i class="icon">💳</i> SUBSCRIPTIONS
    </a>
    <a href="#permissions" onclick="showSection('permissions'); return false;">
        <i class="icon">🔐</i> PERMISSIONS
    </a>
    <a href="#modules" onclick="showSection('modules'); return false;">
        <i class="icon">🧩</i> MODULES
    </a>
</div>
```

**Add section HTML:**
```html
<!-- Users Section -->
<div id="users-section" class="content-section" style="display: none;">
    <div class="section-header">
        <h2>👥 USER MANAGEMENT</h2>
        <button class="btn btn-primary" onclick="openCreateUserModal()">+ NEW USER</button>
    </div>

    <!-- User filters -->
    <div class="filters">
        <input type="text" id="user-search" placeholder="Search users..." onkeyup="filterUsers()" />
        <select id="role-filter" onchange="filterUsers()">
            <option value="">All Roles</option>
            <option value="user">USER</option>
            <option value="premium">PREMIUM</option>
            <option value="admin">ADMIN</option>
        </select>
        <select id="subscription-filter" onchange="filterUsers()">
            <option value="">All Subscriptions</option>
            <option value="free">FREE</option>
            <option value="pro">PRO</option>
            <option value="business">BUSINESS</option>
            <option value="enterprise">ENTERPRISE</option>
        </select>
        <select id="status-filter" onchange="filterUsers()">
            <option value="">All Status</option>
            <option value="active">ACTIVE</option>
            <option value="inactive">INACTIVE</option>
        </select>
    </div>

    <!-- User table -->
    <table class="data-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>Username</th>
                <th>Email</th>
                <th>Role</th>
                <th>Subscription</th>
                <th>OAuth</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last Login</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="users-table-body">
            <!-- Populated via JavaScript -->
        </tbody>
    </table>
</div>

<!-- Subscriptions Section -->
<div id="subscriptions-section" class="content-section" style="display: none;">
    <div class="section-header">
        <h2>💳 SUBSCRIPTION MANAGEMENT</h2>
    </div>

    <!-- Subscription plans overview -->
    <div class="subscription-plans-grid">
        <!-- Populated via JavaScript -->
    </div>

    <!-- Active subscriptions table -->
    <h3>Active Subscriptions</h3>
    <table class="data-table">
        <thead>
            <tr>
                <th>User</th>
                <th>Plan</th>
                <th>Status</th>
                <th>Started</th>
                <th>Expires</th>
                <th>Stripe ID</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="subscriptions-table-body">
            <!-- Populated via JavaScript -->
        </tbody>
    </table>
</div>

<!-- Permissions Section -->
<div id="permissions-section" class="content-section" style="display: none;">
    <div class="section-header">
        <h2>🔐 MODULE PERMISSIONS</h2>
    </div>

    <!-- User selector -->
    <div class="permission-manager">
        <div class="user-selector">
            <label>Select User:</label>
            <select id="permission-user-select" onchange="loadUserPermissions()">
                <option value="">-- Select User --</option>
                <!-- Populated via JavaScript -->
            </select>
        </div>

        <!-- Permission matrix -->
        <div id="permission-matrix" style="display: none;">
            <table class="permission-table">
                <thead>
                    <tr>
                        <th>Module</th>
                        <th>Access</th>
                        <th>Edit</th>
                        <th>Delete</th>
                        <th>Admin</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="permission-matrix-body">
                    <!-- Populated via JavaScript -->
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- Modules Section -->
<div id="modules-section" class="content-section" style="display: none;">
    <div class="section-header">
        <h2>🧩 MODULE REGISTRY</h2>
        <button class="btn btn-primary" onclick="syncModuleRegistry()">🔄 SYNC REGISTRY</button>
    </div>

    <table class="data-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Category</th>
                <th>Min Role</th>
                <th>Enabled</th>
                <th>Beta</th>
                <th>Health</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="modules-table-body">
            <!-- Populated via JavaScript -->
        </tbody>
    </table>
</div>
```

---

#### **Task 3.2: Create Admin User Management API Endpoints**
**Priority:** HIGH

**File:** `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)`

**Add these endpoints:**
```python
# ============================================================================
# USER MANAGEMENT (Enhanced)
# ============================================================================

@admin_bp.route('/users', methods=['GET'])
@login_required
def list_users():
    """List all users with filtering"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    # Get filters from query params
    search = request.args.get('search', '').lower()
    role_filter = request.args.get('role', '')
    subscription_filter = request.args.get('subscription', '')
    status_filter = request.args.get('status', '')

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            u.id, u.username, u.email, u.role, u.subscription_tier,
            u.is_active, u.is_admin, u.created_at, u.last_login,
            u.oauth_provider, u.google_id, u.subscription_expires_at,
            COUNT(DISTINCT ac.id) as conversation_count,
            COUNT(DISTINCT abp.id) as project_count
        FROM users u
        LEFT JOIN ai_conversations ac ON u.id = ac.user_id
        LEFT JOIN app_builder_projects abp ON u.id = abp.user_id
        WHERE 1=1
    """

    params = []

    # Apply filters
    if search:
        query += " AND (LOWER(u.username) LIKE %s OR LOWER(u.email) LIKE %s)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param])

    if role_filter:
        query += " AND u.role = %s"
        params.append(role_filter)

    if subscription_filter:
        query += " AND u.subscription_tier = %s"
        params.append(subscription_filter)

    if status_filter == 'active':
        query += " AND u.is_active = TRUE"
    elif status_filter == 'inactive':
        query += " AND u.is_active = FALSE"

    query += " GROUP BY u.id ORDER BY u.created_at DESC"

    cur.execute(query, params)
    users = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'users': [dict(u) for u in users],
        'total_count': len(users)
    })

@admin_bp.route('/user/<int:user_id>/subscription/update', methods=['POST'])
@login_required
def update_user_subscription(user_id):
    """Update user's subscription tier"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    new_tier = data.get('subscription_tier')  # 'free', 'pro', 'business', 'enterprise'
    expires_at = data.get('expires_at')  # ISO timestamp or None

    if new_tier not in ['free', 'pro', 'business', 'enterprise']:
        return jsonify({'error': 'Invalid subscription tier'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET subscription_tier = %s,
            subscription_expires_at = %s,
            updated_at = NOW()
        WHERE id = %s
    """, (new_tier, expires_at, user_id))

    conn.commit()
    cur.close()
    conn.close()

    # Log the change
    from tools.audit_logger import log_action
    log_action(
        user_id=current_user.id,
        action='UPDATE_USER_SUBSCRIPTION',
        details=f'Changed user {user_id} subscription to {new_tier}',
        target_id=user_id
    )

    return jsonify({'success': True, 'message': 'Subscription updated'})

@admin_bp.route('/user/<int:user_id>/permissions', methods=['GET'])
@login_required
def get_user_permissions(user_id):
    """Get all permissions for a user"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get explicit permissions from permissions table
    cur.execute("""
        SELECT * FROM permissions
        WHERE user_id = %s
        ORDER BY tool_name
    """, (user_id,))

    explicit_permissions = cur.fetchall()

    # Get user info for role-based permissions
    cur.execute("SELECT role, subscription_tier FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()

    cur.close()
    conn.close()

    # Calculate effective permissions from RBAC
    from rbac import get_user_role, get_user_permissions
    from models import User

    user_obj = User.get(user_id)
    role = get_user_role(user_obj)
    role_permissions = get_user_permissions(user_obj)

    return jsonify({
        'success': True,
        'user_id': user_id,
        'role': user['role'],
        'subscription_tier': user['subscription_tier'],
        'effective_role': role.name,
        'explicit_permissions': [dict(p) for p in explicit_permissions],
        'role_permissions': [p.value for p in role_permissions]
    })

@admin_bp.route('/user/<int:user_id>/permissions/grant', methods=['POST'])
@login_required
def grant_user_permission(user_id):
    """Grant a specific module permission to a user"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    tool_name = data.get('tool_name')  # Module ID
    can_access = data.get('can_access', True)
    can_edit = data.get('can_edit', False)
    can_delete = data.get('can_delete', False)
    can_admin = data.get('can_admin', False)

    conn = get_db()
    cur = conn.cursor()

    # Check if permission already exists
    cur.execute("""
        SELECT id FROM permissions
        WHERE user_id = %s AND tool_name = %s
    """, (user_id, tool_name))

    existing = cur.fetchone()

    if existing:
        # Update existing permission
        cur.execute("""
            UPDATE permissions
            SET can_access = %s, can_edit = %s, can_delete = %s, can_admin = %s,
                granted_by = %s, granted_at = NOW()
            WHERE id = %s
        """, (can_access, can_edit, can_delete, can_admin, current_user.id, existing[0]))
    else:
        # Create new permission
        cur.execute("""
            INSERT INTO permissions
            (user_id, tool_name, can_access, can_edit, can_delete, can_admin, granted_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, tool_name, can_access, can_edit, can_delete, can_admin, current_user.id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Permission granted'})

@admin_bp.route('/user/<int:user_id>/permissions/revoke', methods=['POST'])
@login_required
def revoke_user_permission(user_id):
    """Revoke a specific module permission from a user"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    tool_name = data.get('tool_name')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM permissions
        WHERE user_id = %s AND tool_name = %s
    """, (user_id, tool_name))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Permission revoked'})

# ============================================================================
# MODULE REGISTRY MANAGEMENT
# ============================================================================

@admin_bp.route('/modules', methods=['GET'])
@login_required
def list_modules():
    """List all modules from module_registry"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from module_registry import get_all_modules, check_all_modules_health

    modules = get_all_modules()
    health_results = check_all_modules_health()

    module_list = []
    for module in modules:
        module_list.append({
            'id': module.id,
            'name': module.name,
            'description': module.description,
            'icon': module.icon,
            'category': module.category.value,
            'route': module.route,
            'minimum_role': module.minimum_role,
            'required_permissions': module.required_permissions,
            'enabled': module.enabled,
            'beta': module.beta,
            'coming_soon': module.coming_soon,
            'priority': module.priority,
            'tags': module.tags,
            'health': health_results.get(module.id, {'healthy': False, 'status': 'unknown'})
        })

    return jsonify({
        'success': True,
        'modules': module_list,
        'total_count': len(module_list)
    })

@admin_bp.route('/module/<module_id>/toggle', methods=['POST'])
@login_required
def toggle_module(module_id):
    """Enable/disable a module (requires code change to persist)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    # Note: This would require dynamic module registry updates
    # For now, return warning
    return jsonify({
        'success': False,
        'message': 'Module enable/disable requires code deployment',
        'info': 'Edit module_registry.py and change enabled=True/False'
    })
```

---

### **PHASE 6.5.4: Testing & Documentation (Week 2 - Days 4-5)**

#### **Task 4.1: Testing Checklist**

**User Registration & Login:**
- [ ] Create user with email/password
- [ ] Login with email/password
- [ ] Login with Google OAuth
- [ ] Existing user can link Google account
- [ ] Password reset works
- [ ] Session persistence

**Subscription & Permissions:**
- [ ] Free user sees only FREE tier modules
- [ ] Pro user sees PRO tier modules
- [ ] Admin sees all modules including dashboard
- [ ] Subscription expiration downgrades access
- [ ] Manual permission grant/revoke works
- [ ] RBAC decorators protect routes correctly

**Dynamic Dashboard:**
- [ ] Dashboard shows only accessible modules
- [ ] Modules grouped by category
- [ ] Beta/Coming Soon badges display
- [ ] Upgrade CTA shows for free users
- [ ] Module cards link correctly
- [ ] Health checks display

**Dashboard:**
- [ ] User list displays all users
- [ ] Filters work (search, role, subscription, status)
- [ ] Create new user
- [ ] Update user subscription tier
- [ ] Grant module permissions
- [ ] Revoke permissions
- [ ] View user's effective permissions
- [ ] Module registry displays
- [ ] Module health checks run

**OAuth Security:**
- [ ] OAuth state parameter prevents CSRF
- [ ] Tokens stored securely
- [ ] No sensitive data in URL
- [ ] HTTPS enforced (production)

---

#### **Task 4.2: Documentation**

**Create:** `/mnt/archie_brain/docs/USER_SUBSCRIPTION_GUIDE.md`

```markdown
# User Management & Subscription System Guide

## For Users

### Creating an Account
1. **Email/Password**: Click "Sign Up" on login page
2. **Google OAuth**: Click "Continue with Google"

### Subscription Tiers
- **FREE**: Basic access, 5 AI requests/day
- **PRO ($29/mo)**: Unlimited AI, advanced tools
- **BUSINESS ($99/mo)**: Teams, analytics, white-label
- **ENTERPRISE**: Custom pricing, on-premise options

### Upgrading Your Subscription
1. Go to Dashboard
2. Click "UPGRADE" button
3. Select plan
4. Complete payment via Stripe

## For Admins

### Managing Users
Navigate to Dashboard > System > Users

**Creating Users:**
- Click "+ NEW USER"
- Enter username, email, password
- Select subscription tier and role
- Click "Create"

**Updating Subscriptions:**
- Find user in list
- Click "Edit"
- Change subscription tier
- Set expiration date
- Save

**Granting Module Permissions:**
1. Go to Dashboard > System > Permissions
2. Select user from dropdown
3. Check boxes for module access
4. Click "Grant Permission"

### Understanding Roles
- **PUBLIC**: Not logged in, view directory only
- **USER**: Basic authenticated (FREE tier)
- **PREMIUM**: Paid subscribers (PRO/BUSINESS/ENTERPRISE)
- **ADMIN**: Platform administrators
- **SUPER_ADMIN**: System owner (you)

### Module Access Control
Each module requires:
1. **Minimum Role**: USER, PREMIUM, ADMIN, or SUPER_ADMIN
2. **Specific Permissions**: e.g., "app_builder:create"

Users must meet BOTH criteria to access a module.
```

---

## 📊 Success Criteria

### **Phase 6.5.1 Complete When:**
- ✅ ARCHIE Chat blueprint registered and accessible
- ✅ Google OAuth library installed
- ✅ OAuth routes created and tested
- ✅ User model has subscription methods
- ✅ Can login with Google successfully

### **Phase 6.5.2 Complete When:**
- ✅ Dynamic dashboard generates from module_registry
- ✅ Dashboard shows different modules for FREE vs PRO users
- ✅ Modules grouped by category
- ✅ Beta/Coming Soon badges display correctly
- ✅ RBAC integration works (can_access_module checks)

### **Phase 6.5.3 Complete When:**
- ✅ Admin panel has Users/Subscriptions/Permissions/Modules sections
- ✅ Can list all users with filtering
- ✅ Can update user subscription tier
- ✅ Can grant/revoke module permissions
- ✅ Can view user's effective permissions
- ✅ Module registry health checks display

### **Phase 6.5.4 Complete When:**
- ✅ All testing checklist items pass
- ✅ Documentation created and reviewed
- ✅ No regressions in existing functionality

---

## 🚀 Post-Implementation: Phase 7 Ready

Once Phase 6.5 is complete, you'll be ready for Phase 7 (Figma Integration) because:

1. ✅ **Subscription system** enforces PREMIUM access for Figma module
2. ✅ **RBAC** checks `figma:import` permission
3. ✅ **Dynamic dashboard** automatically shows Figma when enabled for PREMIUM users
4. ✅ **Admin panel** allows granting Figma access to specific users
5. ✅ **OAuth infrastructure** ready for Figma OAuth if needed

---

## 📁 Files Summary

### **New Files to Create:**
1. `/mnt/archie_brain/platform_v2/oauth_routes.py` (500 lines)
2. `/mnt/archie_brain/platform_v2/dashboard_generator.py` (150 lines)
3. `/mnt/archie_brain/platform_v2/templates/dashboard_dynamic.html` (400 lines)
4. `/mnt/archie_brain/docs/USER_SUBSCRIPTION_GUIDE.md` (200 lines)

### **Files to Modify:**
1. `/mnt/archie_brain/platform_v2/app.py` (add OAuth + dashboard route)
2. `/mnt/archie_brain/platform_v2/models.py` (add User methods)
3. `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)` (add user management endpoints)
4. `/mnt/archie_brain/platform_v2/templates/ (now modular templates)` (add System sections)
5. `/mnt/archie_brain/platform_v2/templates/login.html` (add Google login button)
6. `/mnt/archie_brain/platform_v2/requirements.txt` (add authlib, httpx)
7. `/mnt/archie_brain/.env` (add Google OAuth credentials)

### **Database Changes:**
**None required** - All tables already exist!

---

## 🎯 Timeline Estimate

**Week 1:**
- Days 1-3: OAuth + ARCHIE Chat fix (Task 1.1-1.4)
- Days 4-5: Dynamic Dashboard (Task 2.1-2.2)

**Week 2:**
- Days 1-3: Dashboard UI + API (Task 3.1-3.2)
- Days 4-5: Testing + Documentation (Task 4.1-4.2)

**Total: 10 working days (2 weeks)**

---

**STATUS:** ✅ PLAN COMPLETE - Ready for User Approval
**Next Step:** Implement Phase 6.5.1 Task 1.1 (Fix ARCHIE Chat Blueprint)
**Blockers:** None - all dependencies already exist
**Priority:** HIGH - Must complete before Phase 7 (Figma)

🎯 **This plan ensures proper multi-user access control before adding premium features.**
