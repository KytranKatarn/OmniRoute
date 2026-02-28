# SaaS Theme System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 8 selectable visual themes for SaaS/Dashboard modules while keeping LCARS locked on admin/AI/dev modules.

**Architecture:** CSS Variable Theme Sheets — each theme is a standalone CSS file (~100-150 lines) overriding `:root` variables via a `body.theme-*` class. Theme resolution: user JSONB metadata → org JSONB settings → `lcars-classic` fallback. Admin modules detected by `ModuleCategory` enum always force LCARS.

**Tech Stack:** Flask (Python), PostgreSQL (JSONB columns), Jinja2 templates, CSS custom properties, vanilla JS

**Design doc:** `docs/plans/2026-02-28-saas-theme-system-design.md`

---

## Task 1: Database — Add Theme Columns via JSONB

**Files:**
- Create: `database/migrations/120_user_theme_preference.sql`

This project uses existing JSONB columns (`users.metadata` and `organizations.settings`) rather than `ALTER TABLE ADD COLUMN`. The migration ensures the JSONB keys exist with defaults.

**Step 1: Write the migration SQL**

Create `database/migrations/120_user_theme_preference.sql`:

```sql
-- Migration 120: User theme preference + org default theme
-- Uses existing JSONB columns (users.metadata, organizations.settings)

-- Set default theme_preference on all users who don't have one
UPDATE users
SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"theme_preference": "lcars-classic"}'::jsonb
WHERE metadata IS NULL OR NOT metadata ? 'theme_preference';

-- Set default_theme on all orgs that don't have one
UPDATE organizations
SET settings = COALESCE(settings, '{}'::jsonb) || '{"default_theme": "lcars-classic"}'::jsonb
WHERE settings IS NULL OR NOT settings ? 'default_theme';
```

**Step 2: Run the migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/120_user_theme_preference.sql
```

If the migration file isn't mounted, copy it in first:
```bash
docker cp database/migrations/120_user_theme_preference.sql archie_database:/tmp/
docker exec -it archie_database psql -U archie -d archie -f /tmp/120_user_theme_preference.sql
```

**Step 3: Verify**

```bash
docker exec -it archie_database psql -U archie -d archie -c "SELECT id, username, metadata->>'theme_preference' as theme FROM users LIMIT 5;"
docker exec -it archie_database psql -U archie -d archie -c "SELECT id, name, settings->>'default_theme' as theme FROM organizations LIMIT 5;"
```

Expected: All users show `lcars-classic` as theme. All orgs show `lcars-classic` as default_theme.

**Step 4: Commit**

```bash
git add database/migrations/120_user_theme_preference.sql
git commit -m "feat(theme): add user theme_preference + org default_theme via JSONB migration"
```

---

## Task 2: Backend — User Class + Theme Context Processor

**Files:**
- Modify: `platform_v2/app.py:156-205` (User class + load_user)
- Modify: `platform_v2/app.py:2202` (new context processor after `inject_module_registry`)

**Step 1: Extend User class to include theme_preference**

In `platform_v2/app.py`, update the `User.__init__` (line ~159) to accept and store `theme_preference`:

```python
class User(UserMixin):
    """User class for Flask-Login with RBAC support"""

    def __init__(
        self,
        id,
        username,
        email,
        role,
        is_admin=False,
        is_super_admin=False,
        subscription_tier=None,
        subscription_expires_at=None,
        theme_preference=None,
    ):
        self.id = id
        self.username = username
        self.email = email
        self.role = role
        self.is_admin = is_admin
        self.is_super_admin = is_super_admin
        self.subscription_tier = subscription_tier or "free"
        self.subscription_expires_at = subscription_expires_at
        self.theme_preference = theme_preference or "lcars-classic"
```

**Step 2: Update load_user to extract theme from metadata JSONB**

In `load_user()` (line ~181), extract `theme_preference` from the fetched `metadata` column:

```python
@login_manager.user_loader
def load_user(user_id):
    """Load user by ID with RBAC attributes"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s AND is_active = TRUE", (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()

        if user_data:
            # Extract theme from metadata JSONB
            metadata = user_data.get("metadata") or {}
            theme_pref = metadata.get("theme_preference", "lcars-classic") if isinstance(metadata, dict) else "lcars-classic"

            return User(
                id=user_data["id"],
                username=user_data["username"],
                email=user_data["email"],
                role=user_data["role"],
                is_admin=user_data.get("is_admin", False),
                is_super_admin=user_data.get("is_super_admin", False),
                subscription_tier=user_data.get("subscription_tier", "free"),
                subscription_expires_at=user_data.get("subscription_expires_at"),
                theme_preference=theme_pref,
            )
    except Exception as e:
        print(f"Error loading user: {e}")
    return None
```

**Step 3: Add theme context processor**

After `inject_module_registry()` (line ~2202), add a new context processor that resolves the theme and detects admin modules:

```python
# ============================================================================
# THEME CONTEXT PROCESSOR
# ============================================================================

VALID_THEMES = {
    "lcars-classic", "corporate-blue", "midnight-purple", "warm-minimal",
    "arctic-light", "rose-gold", "forest", "slate-pro"
}

ADMIN_CATEGORIES = {"admin_operations", "ai_command", "development_tools"}


@app.context_processor
def inject_theme_context():
    """
    Inject theme variables into all templates.
    Resolves: user preference → org default → lcars-classic fallback.
    Admin modules always force LCARS.
    """
    theme_name = "lcars-classic"
    is_admin_module = False

    if current_user.is_authenticated:
        # 1. User preference
        user_theme = getattr(current_user, "theme_preference", "lcars-classic")
        if user_theme in VALID_THEMES:
            theme_name = user_theme
        else:
            # 2. Org default (if user has no valid preference)
            try:
                from database import get_db_connection
                with get_db_connection(cursor_factory=RealDictCursor) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT o.settings->>'default_theme' as default_theme
                            FROM organizations o
                            JOIN org_users ou ON ou.org_id = o.id
                            WHERE ou.user_id = %s
                            LIMIT 1
                        """, (current_user.id,))
                        row = cur.fetchone()
                        if row and row["default_theme"] in VALID_THEMES:
                            theme_name = row["default_theme"]
            except Exception:
                pass

        # Detect admin module from request path
        from flask import request
        from module_registry import get_all_modules
        path = request.path
        for mod in get_all_modules():
            if mod.route and path.startswith(mod.route):
                if mod.category and mod.category.value in ADMIN_CATEGORIES:
                    is_admin_module = True
                break

    return {
        "theme_name": theme_name,
        "is_admin_module": is_admin_module,
    }
```

**Step 4: Restart and verify context injection**

```bash
docker compose restart archie_platform
```

Check logs for startup errors:
```bash
docker logs --tail 30 archie_platform
```

Navigate to any page and confirm no errors. The variables are injected but not yet used in templates.

**Step 5: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(theme): User class theme_preference + context processor for theme resolution"
```

---

## Task 3: Template — Conditional Theme CSS Loading in base.html

**Files:**
- Modify: `platform_v2/templates/base.html:27` (after `light-mode.css` import)
- Modify: `platform_v2/templates/base.html:252` (body tag)

**Step 1: Add conditional theme CSS link**

After the `light-mode.css` import (line 27) and before `mobile.css` (line 28), add:

```html
    <!-- SaaS Theme Override (non-LCARS themes on non-admin modules) -->
    {% if theme_name is defined and theme_name != 'lcars-classic' and not is_admin_module %}
    <link rel="stylesheet" href="{{ url_for('static', filename='css/themes/' + theme_name + '.css') }}">
    {% endif %}
```

**Step 2: Add theme class to body tag**

Change the body tag (line 252) from:

```html
<body data-module="{% block module_name %}default{% endblock %}">
```

To:

```html
<body class="{% if theme_name is defined %}theme-{{ theme_name }}{% else %}theme-lcars-classic{% endif %}" data-module="{% block module_name %}default{% endblock %}">
```

**Step 3: Restart and verify**

```bash
docker compose restart archie_platform
```

View page source on any page — confirm:
- `<body class="theme-lcars-classic" ...>` appears
- No theme CSS `<link>` loaded (since default is lcars-classic)

**Step 4: Commit**

```bash
git add platform_v2/templates/base.html
git commit -m "feat(theme): conditional theme CSS loading + body class in base.html"
```

---

## Task 4: CSS — Create Corporate Blue Theme

**Files:**
- Create: `platform_v2/static/css/themes/corporate-blue.css`

This is the reference theme. All other themes follow the same pattern.

**Step 1: Create the themes directory**

```bash
mkdir -p platform_v2/static/css/themes
```

**Step 2: Write corporate-blue.css**

Create `platform_v2/static/css/themes/corporate-blue.css`:

```css
/*
 * Corporate Blue Theme — Clean, professional aesthetic
 * Overrides LCARS sci-fi variables with business-friendly design
 */

body.theme-corporate-blue {
    /* === BACKGROUNDS === */
    --archie-bg-void: #020617;
    --archie-bg-primary: #0f172a;
    --archie-bg-secondary: #1e293b;
    --archie-bg-tertiary: #334155;
    --archie-bg-elevated: #1e293b;
    --archie-bg-hover: #334155;

    /* === TEXT === */
    --archie-text-primary: #e2e8f0;
    --archie-text-secondary: #94a3b8;
    --archie-text-tertiary: #64748b;
    --archie-text-muted: #475569;

    /* === PRIMARY ACCENT (blue) === */
    --archie-accent: #3b82f6;
    --archie-green: #3b82f6;
    --archie-green-dim: #2563eb;
    --archie-green-bright: #60a5fa;
    --archie-green-alpha-10: rgba(59, 130, 246, 0.1);
    --archie-green-alpha-20: rgba(59, 130, 246, 0.2);
    --archie-green-alpha-30: rgba(59, 130, 246, 0.3);

    /* === SECONDARY (cyan → blue-lighter) === */
    --archie-cyan: #60a5fa;
    --archie-cyan-dim: #3b82f6;
    --archie-cyan-bright: #93c5fd;
    --archie-cyan-alpha-10: rgba(96, 165, 250, 0.1);
    --archie-cyan-alpha-20: rgba(96, 165, 250, 0.2);
    --archie-cyan-alpha-30: rgba(96, 165, 250, 0.3);

    /* === ORANGE → Amber accent === */
    --archie-orange: #f59e0b;
    --archie-orange-dim: #d97706;
    --archie-orange-bright: #fbbf24;
    --archie-orange-alpha-10: rgba(245, 158, 11, 0.1);
    --archie-orange-alpha-20: rgba(245, 158, 11, 0.2);

    /* === STATUS COLORS (keep standard) === */
    --archie-success: #22c55e;
    --archie-warning: #f59e0b;
    --archie-danger: #ef4444;
    --archie-info: #3b82f6;

    /* === BORDERS === */
    --archie-border-default: rgba(59, 130, 246, 0.2);
    --archie-border-muted: rgba(59, 130, 246, 0.1);
    --archie-border-subtle: rgba(59, 130, 246, 0.06);
    --archie-border-emphasis: rgba(59, 130, 246, 0.4);

    /* === GLOWS (subtle professional) === */
    --archie-glow-green-sm: 0 0 6px rgba(59, 130, 246, 0.2);
    --archie-glow-green-md: 0 0 12px rgba(59, 130, 246, 0.25);
    --archie-glow-green-lg: 0 0 20px rgba(59, 130, 246, 0.3);
    --archie-glow-cyan-sm: 0 0 6px rgba(96, 165, 250, 0.2);
    --archie-glow-cyan-md: 0 0 12px rgba(96, 165, 250, 0.25);
    --archie-text-glow-green: 0 0 6px rgba(59, 130, 246, 0.3);
    --archie-text-glow-cyan: 0 0 6px rgba(96, 165, 250, 0.3);

    /* === SHADOWS (clean) === */
    --archie-shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.2);
    --archie-shadow-md: 0 4px 12px rgba(0, 0, 0, 0.25);
    --archie-shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.3);

    /* === STRUCTURAL === */
    --archie-radius-sm: 6px;
    --archie-radius-md: 8px;
    --archie-radius-lg: 12px;
    --archie-radius-xl: 16px;

    /* === FONTS (Inter for professional look) === */
    --archie-font-heading: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --archie-font-display: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Load Inter font */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Disable LCARS-specific decorative elements */
body.theme-corporate-blue .scanlines,
body.theme-corporate-blue .lcars-scanline {
    display: none !important;
}
```

**Step 3: Test by manually setting theme in DB**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"corporate-blue\"') WHERE username = 'admin';"
docker compose restart archie_platform
```

Navigate to a SaaS module (e.g., CRM). Verify blue accent colors appear. Navigate to an admin module (e.g., System Operations). Verify LCARS green stays.

**Step 4: Reset admin user theme back to lcars-classic**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"lcars-classic\"') WHERE username = 'admin';"
```

**Step 5: Commit**

```bash
git add platform_v2/static/css/themes/corporate-blue.css
git commit -m "feat(theme): corporate-blue theme CSS — professional blue accent"
```

---

## Task 5: CSS — Create Remaining 6 Themes

**Files:**
- Create: `platform_v2/static/css/themes/midnight-purple.css`
- Create: `platform_v2/static/css/themes/warm-minimal.css`
- Create: `platform_v2/static/css/themes/arctic-light.css`
- Create: `platform_v2/static/css/themes/rose-gold.css`
- Create: `platform_v2/static/css/themes/forest.css`
- Create: `platform_v2/static/css/themes/slate-pro.css`

All follow the exact same pattern as `corporate-blue.css` — override the same CSS variable set, only changing color values. Each theme body class selector matches its filename (e.g., `body.theme-midnight-purple`).

**Theme color specs:**

| Theme | Accent | Secondary | BG Primary | BG Secondary |
|-------|--------|-----------|------------|--------------|
| midnight-purple | `#8b5cf6` | `#a78bfa` | `#0f0a1a` | `#1a1130` |
| warm-minimal | `#f59e0b` | `#fbbf24` | `#1a1408` | `#2d2410` |
| arctic-light | `#06b6d4` | `#22d3ee` | `#0a1929` | `#132f4c` |
| rose-gold | `#f43f5e` | `#fb7185` | `#1a0a10` | `#2d1420` |
| forest | `#22c55e` | `#4ade80` | `#0a1a0e` | `#142d18` |
| slate-pro | `#64748b` | `#94a3b8` | `#0f1218` | `#1e2430` |

**Step 1: Create all 6 theme files**

Each file follows `corporate-blue.css` structure exactly, replacing:
- `body.theme-corporate-blue` → `body.theme-<id>`
- All color values per the table above
- Same variable set, same structure, same @import for Inter font
- Same scanline disable rule

**Step 2: Verify each theme manually** (optional, can be done later via UI)

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"midnight-purple\"') WHERE username = 'admin';"
docker compose restart archie_platform
```

Visit a SaaS module, check purple accent. Repeat for each theme or skip until the UI selector is built.

**Step 3: Reset to LCARS**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"lcars-classic\"') WHERE username = 'admin';"
```

**Step 4: Commit**

```bash
git add platform_v2/static/css/themes/
git commit -m "feat(theme): 6 additional theme CSS files — midnight-purple, warm-minimal, arctic-light, rose-gold, forest, slate-pro"
```

---

## Task 6: API — Theme GET/PUT Endpoints

**Files:**
- Modify: `platform_v2/tools/user_profile/routes.py` (add 2 new routes)

**Step 1: Add GET /api/user/theme endpoint**

In `platform_v2/tools/user_profile/routes.py`, after the `change_password` route (line ~119), add:

```python
VALID_THEMES = [
    "lcars-classic", "corporate-blue", "midnight-purple", "warm-minimal",
    "arctic-light", "rose-gold", "forest", "slate-pro"
]


@user_profile_bp.route("/api/user/theme")
@login_required
def get_user_theme():
    """Get the resolved theme for current user"""
    theme = getattr(current_user, "theme_preference", "lcars-classic")
    return jsonify({"success": True, "theme": theme, "available_themes": VALID_THEMES})


@user_profile_bp.route("/api/user/theme", methods=["PUT"])
@login_required
def set_user_theme():
    """Set user's theme preference"""
    data = request.get_json()
    if not data or "theme" not in data:
        return jsonify({"success": False, "error": "Missing 'theme' field"}), 400

    theme = data["theme"]
    if theme not in VALID_THEMES:
        return jsonify({"success": False, "error": f"Invalid theme: {theme}"}), 400

    with get_db_connection(cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET metadata = jsonb_set(
                       COALESCE(metadata, '{}'::jsonb),
                       '{theme_preference}',
                       %s::jsonb
                   )
                   WHERE id = %s""",
                (f'"{theme}"', current_user.id),
            )
            conn.commit()

    # Update in-memory user object
    current_user.theme_preference = theme

    return jsonify({"success": True, "theme": theme})
```

**Step 2: Test the API**

```bash
# GET current theme
curl -s -b /tmp/cookies.txt http://192.168.1.200:3000/tools/my-profile/api/user/theme | python3 -m json.tool

# SET corporate-blue
curl -s -b /tmp/cookies.txt -X PUT -H "Content-Type: application/json" \
  -d '{"theme": "corporate-blue"}' \
  http://192.168.1.200:3000/tools/my-profile/api/user/theme | python3 -m json.tool

# Verify it took effect
curl -s -b /tmp/cookies.txt http://192.168.1.200:3000/tools/my-profile/api/user/theme | python3 -m json.tool

# Reset to LCARS
curl -s -b /tmp/cookies.txt -X PUT -H "Content-Type: application/json" \
  -d '{"theme": "lcars-classic"}' \
  http://192.168.1.200:3000/tools/my-profile/api/user/theme | python3 -m json.tool
```

Expected: GET returns `{"success": true, "theme": "lcars-classic", "available_themes": [...]}`. PUT returns `{"success": true, "theme": "corporate-blue"}`.

**Step 3: Commit**

```bash
git add platform_v2/tools/user_profile/routes.py
git commit -m "feat(theme): GET/PUT /api/user/theme endpoints for theme preference"
```

---

## Task 7: UI — Theme Selector in My Profile

**Files:**
- Modify: `platform_v2/templates/tools/user_profile.html` (add Appearance section)

**Step 1: Add the Appearance section**

After the existing profile content (password change section), add a new "APPEARANCE" section with a grid of 8 theme preview cards. Each card shows:
- 3-4 colored bars (accent, bg, text preview)
- Theme name label
- Checkmark on active theme
- Click handler that calls `PUT /api/user/theme` and reloads the page

HTML structure:

```html
<!-- Appearance Section -->
<div class="profile-section" style="margin-top: 24px;">
    <div class="lcars-section-label" style="...">APPEARANCE</div>
    <div class="theme-grid" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px;">
        <!-- Repeat for each theme -->
        <div class="theme-card" data-theme="lcars-classic" onclick="selectTheme('lcars-classic')" style="...">
            <div class="theme-swatches" style="display: flex; gap: 3px; height: 32px; border-radius: 4px; overflow: hidden;">
                <div style="flex: 3; background: #010409;"></div>
                <div style="flex: 1; background: #00ff41;"></div>
                <div style="flex: 1; background: #00ffff;"></div>
                <div style="flex: 1; background: #ffaa00;"></div>
            </div>
            <div class="theme-name" style="...">LCARS Classic</div>
            <div class="theme-check" style="display: none;">&#10003;</div>
        </div>
        <!-- ... 7 more cards ... -->
    </div>
</div>
```

JS:

```javascript
async function selectTheme(themeId) {
    try {
        const resp = await fetch('/tools/my-profile/api/user/theme', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: themeId })
        });
        const data = await resp.json();
        if (data.success) {
            // Reload to apply new theme via server-side rendering
            window.location.reload();
        }
    } catch (e) {
        console.error('Failed to set theme:', e);
    }
}

// Highlight active theme on load
document.addEventListener('DOMContentLoaded', async function() {
    try {
        const resp = await fetch('/tools/my-profile/api/user/theme');
        const data = await resp.json();
        if (data.success) {
            document.querySelectorAll('.theme-card').forEach(card => {
                const check = card.querySelector('.theme-check');
                if (card.dataset.theme === data.theme) {
                    card.style.borderColor = 'var(--archie-accent, #3b82f6)';
                    if (check) check.style.display = 'block';
                }
            });
        }
    } catch (e) {}
});
```

Theme card color specs for swatches:

| Theme | Bar 1 (BG) | Bar 2 (Accent) | Bar 3 (Secondary) | Bar 4 (Tertiary) |
|-------|-----------|----------------|-------------------|-----------------|
| lcars-classic | `#010409` | `#00ff41` | `#00ffff` | `#ffaa00` |
| corporate-blue | `#0f172a` | `#3b82f6` | `#60a5fa` | `#f59e0b` |
| midnight-purple | `#0f0a1a` | `#8b5cf6` | `#a78bfa` | `#f59e0b` |
| warm-minimal | `#1a1408` | `#f59e0b` | `#fbbf24` | `#78716c` |
| arctic-light | `#0a1929` | `#06b6d4` | `#22d3ee` | `#f59e0b` |
| rose-gold | `#1a0a10` | `#f43f5e` | `#fb7185` | `#f59e0b` |
| forest | `#0a1a0e` | `#22c55e` | `#4ade80` | `#f59e0b` |
| slate-pro | `#0f1218` | `#64748b` | `#94a3b8` | `#f59e0b` |

**Step 2: Responsive — 2 columns at <768px, 1 column at <480px**

Add CSS:
```css
@media (max-width: 768px) {
    .theme-grid { grid-template-columns: repeat(2, 1fr) !important; }
}
@media (max-width: 480px) {
    .theme-grid { grid-template-columns: 1fr !important; }
}
```

**Step 3: Test**

Navigate to My Profile. Verify:
- 8 theme cards in a 4x2 grid
- Current theme (lcars-classic) has a checkmark
- Click "Corporate Blue" → page reloads with blue accent on SaaS modules
- Click "LCARS Classic" → back to green sci-fi

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/user_profile.html
git commit -m "feat(theme): theme selector grid in My Profile — 8 themes with instant preview"
```

---

## Task 8: UI — Org Default Theme in Account Center

**Files:**
- Modify: `platform_v2/templates/tools/account_center.html` (Organization tab)

**Step 1: Locate the Organization tab content**

Find the Organization section/tab in Account Center. Add a "Default Theme" dropdown at the bottom of the org settings area.

HTML:
```html
<div class="org-theme-setting" style="margin-top: 20px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.06);">
    <label style="...">DEFAULT THEME</label>
    <p style="...">Fallback theme for org members who haven't chosen their own.</p>
    <select id="orgDefaultTheme" class="form-select" style="..." onchange="setOrgTheme(this.value)">
        <option value="lcars-classic">LCARS Classic</option>
        <option value="corporate-blue">Corporate Blue</option>
        <option value="midnight-purple">Midnight Purple</option>
        <option value="warm-minimal">Warm Minimal</option>
        <option value="arctic-light">Arctic Light</option>
        <option value="rose-gold">Rose Gold</option>
        <option value="forest">Forest</option>
        <option value="slate-pro">Slate Pro</option>
    </select>
</div>
```

**Step 2: Add API route for org theme** (if needed)

This may need a new endpoint in the account_center routes:

```python
@account_center_bp.route("/api/org/<int:org_id>/theme", methods=["PUT"])
@login_required
def set_org_theme(org_id):
    """Set organization default theme (org admin only)"""
    # Verify user is org admin
    # Update organizations.settings JSONB with default_theme
    ...
```

Or reuse an existing org settings PUT endpoint if one exists.

**Step 3: Load current org theme on tab init**

Fetch org settings and set the dropdown's selected value.

**Step 4: Test**

Navigate to Account Center → Organization tab. Change dropdown to "Corporate Blue". Verify it saves. Log in as a different org user with no personal theme preference — they should see Corporate Blue.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/account_center.html
# If routes were modified:
git add platform_v2/tools/account_center/routes.py
git commit -m "feat(theme): org default theme dropdown in Account Center"
```

---

## Task 9: Integration Testing & Polish

**Files:**
- No new files — verification and edge-case fixes

**Step 1: Test theme resolution chain**

1. Set user theme to `lcars-classic`, org to `corporate-blue`
   - SaaS modules → should show LCARS (user pref wins)
2. Remove user theme (set to empty/null)
   - SaaS modules → should show Corporate Blue (org fallback)
3. Remove org theme too
   - SaaS modules → should show LCARS (ultimate fallback)

```bash
# Set org default to corporate-blue
docker exec -it archie_database psql -U archie -d archie -c "UPDATE organizations SET settings = jsonb_set(COALESCE(settings, '{}'), '{default_theme}', '\"corporate-blue\"') WHERE id = 1;"

# Remove user preference to test fallback
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = metadata - 'theme_preference' WHERE username = 'admin';"

docker compose restart archie_platform
```

Visit CRM → should show Corporate Blue. Visit System Operations → should show LCARS.

**Step 2: Test admin module lockout**

Navigate to each admin category module while user has a non-LCARS theme set:
- Account Center → should show LCARS (admin_operations)
- System Operations → LCARS
- Backup Manager → LCARS
- Security & Network → LCARS
- Bridge Command → LCARS (ai_command)
- Consciousness → LCARS (ai_command)
- Dev HQ → LCARS (development_tools)

**Step 3: Test light/dark mode interaction**

With Corporate Blue theme active, toggle light/dark mode. Verify `light-mode.css` still layers on top correctly (it should — CSS specificity of `body.light-mode` is independent of `body.theme-corporate-blue`).

**Step 4: Test dashboard with theme**

Dashboard is in "themed" scope per design. Navigate to Dashboard with Corporate Blue active. Verify LCARS frames are unaffected (frame CSS uses its own `--frame-color` inline variables).

**Step 5: Fix any edge cases discovered during testing**

Common issues to watch for:
- LCARS frames using `--frame-color` directly → should be unaffected (set per-module inline)
- Hardcoded hex colors in individual templates → need `var()` wrappers (fix as found)
- `light-mode.css` overriding theme colors → check specificity

**Step 6: Reset test data and commit any fixes**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"lcars-classic\"') WHERE username = 'admin';"
```

```bash
git add -A
git commit -m "fix(theme): edge-case fixes from integration testing"
```

---

## Summary — Commit Sequence

| # | Commit | Files |
|---|--------|-------|
| 1 | DB migration — JSONB theme keys | `database/migrations/120_user_theme_preference.sql` |
| 2 | User class + context processor | `platform_v2/app.py` |
| 3 | base.html conditional loading | `platform_v2/templates/base.html` |
| 4 | Corporate Blue theme CSS | `platform_v2/static/css/themes/corporate-blue.css` |
| 5 | 6 remaining theme CSS files | `platform_v2/static/css/themes/*.css` |
| 6 | API endpoints GET/PUT | `platform_v2/tools/user_profile/routes.py` |
| 7 | My Profile theme selector UI | `platform_v2/templates/tools/user_profile.html` |
| 8 | Account Center org default | `platform_v2/templates/tools/account_center.html` |
| 9 | Integration testing fixes | Various |

**Total new files:** 8 (1 migration + 7 CSS themes)
**Modified files:** 4 (`app.py`, `base.html`, `user_profile.html`, `account_center.html`) + routes
