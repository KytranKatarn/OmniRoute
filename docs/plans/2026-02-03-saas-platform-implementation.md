# SaaS Platform Layer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a multi-tenant SaaS platform layer with organization management, domain routing (Hostinger DNS + NPM reverse proxy), and a la carte module access. First client: Kytran Empowerment.

**Architecture:** New `saas_manager` module in `platform_v2/tools/`. Organizations are the tenant unit. Row-level isolation via `org_id` on shared tables. Domains managed via existing `hostinger_integration.py` + NPM API at `:81`. ARCHIE acts as an active AI partner in each org.

**Tech Stack:** Flask Blueprint, PostgreSQL (raw SQL migrations), Hostinger API (existing client), NPM API (REST, port 81), Jinja2 templates.

**Design Doc:** `docs/plans/2026-02-03-saas-platform-layer-design.md`

---

## Task 1: Database Migration — Core SaaS Tables

**Files:**
- Create: `platform_v2/migrations/030_saas_platform.sql`

**Step 1: Write the migration SQL**

```sql
-- 030_saas_platform.sql
-- SaaS Platform Layer: Organizations, Memberships, Module Access, Domains, IP History

-- Organizations
CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    owner_user_id INTEGER REFERENCES users(id),
    archie_user_id INTEGER REFERENCES users(id),
    status VARCHAR(50) DEFAULT 'provisioning'
        CHECK (status IN ('provisioning', 'active', 'suspended')),
    settings JSONB DEFAULT '{}',
    ai_config JSONB DEFAULT '{}',
    isolation_type VARCHAR(20) DEFAULT 'shared'
        CHECK (isolation_type IN ('shared', 'migrating', 'node')),
    node_id VARCHAR(255),
    migration_status VARCHAR(50)
        CHECK (migration_status IN (NULL, 'exporting', 'provisioning', 'importing', 'verifying', 'complete')),
    migrated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_organizations_status ON organizations(status);
CREATE INDEX IF NOT EXISTS idx_organizations_owner ON organizations(owner_user_id);

DROP TRIGGER IF EXISTS update_organizations_updated_at ON organizations;
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Organization Users (many-to-many)
CREATE TABLE IF NOT EXISTS org_users (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'admin', 'member', 'archie')),
    invited_at TIMESTAMP DEFAULT NOW(),
    joined_at TIMESTAMP,
    UNIQUE(org_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_org_users_org ON org_users(org_id);
CREATE INDEX IF NOT EXISTS idx_org_users_user ON org_users(user_id);

-- Organization Modules (a la carte access)
CREATE TABLE IF NOT EXISTS org_modules (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    module_key VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}',
    activated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, module_key)
);

CREATE INDEX IF NOT EXISTS idx_org_modules_org ON org_modules(org_id);

-- Organization Domains
CREATE TABLE IF NOT EXISTS org_domains (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL UNIQUE,
    subdomain VARCHAR(100),
    root_domain VARCHAR(255),
    target_module VARCHAR(100),
    target_port INTEGER DEFAULT 3000,
    ssl_status VARCHAR(50) DEFAULT 'pending'
        CHECK (ssl_status IN ('pending', 'active', 'failed')),
    dns_status VARCHAR(50) DEFAULT 'pending'
        CHECK (dns_status IN ('pending', 'verified', 'failed')),
    dns_provider VARCHAR(50) DEFAULT 'hostinger'
        CHECK (dns_provider IN ('hostinger', 'cloudflare', 'manual')),
    hostinger_zone_id VARCHAR(255),
    npm_proxy_host_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    verified_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_org_domains_org ON org_domains(org_id);
CREATE INDEX IF NOT EXISTS idx_org_domains_domain ON org_domains(domain);

-- Public IP History
CREATE TABLE IF NOT EXISTS org_ip_history (
    id SERIAL PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    detected_at TIMESTAMP DEFAULT NOW()
);
```

**Step 2: Run the migration**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    with open('/app/migrations/030_saas_platform.sql') as f:
        cur.execute(f.read())
    print('Migration 030 complete')
"
```

**Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt org_*"
docker exec archie_database psql -U archie -d archie -c "\dt organizations"
```

Expected: 5 tables (organizations, org_users, org_modules, org_domains, org_ip_history)

**Step 4: Commit**

```bash
git add platform_v2/migrations/030_saas_platform.sql
git commit -m "feat(saas): add core SaaS platform tables (organizations, domains, modules)"
```

---

## Task 2: Seed Kytran Empowerment as First Organization

**Files:**
- Create: `platform_v2/migrations/031_seed_kytran_empowerment.sql`

**Step 1: Write the seed migration**

```sql
-- 031_seed_kytran_empowerment.sql
-- Seed first organization: Kytran Empowerment

-- Create org (idempotent: skip if slug exists)
INSERT INTO organizations (name, slug, owner_user_id, archie_user_id, status, settings, ai_config)
SELECT
    'Kytran Empowerment',
    'kytran-empowerment',
    (SELECT id FROM users WHERE username = 'Kytran'),
    (SELECT id FROM users WHERE username = 'admin'),
    'active',
    '{"root_domain": "kytranempowerment.com", "branding": {"primary_color": "#1a1a2e"}}'::jsonb,
    '{"personality": "professional", "role": "business_partner"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'kytran-empowerment');

-- Add org memberships
INSERT INTO org_users (org_id, user_id, role, joined_at)
SELECT o.id, u.id, 'owner', NOW()
FROM organizations o, users u
WHERE o.slug = 'kytran-empowerment' AND u.username = 'Kytran'
ON CONFLICT (org_id, user_id) DO NOTHING;

INSERT INTO org_users (org_id, user_id, role, joined_at)
SELECT o.id, u.id, 'archie', NOW()
FROM organizations o, users u
WHERE o.slug = 'kytran-empowerment' AND u.username = 'admin'
ON CONFLICT (org_id, user_id) DO NOTHING;

-- Enable initial modules
INSERT INTO org_modules (org_id, module_key, config)
SELECT o.id, m.key, m.config
FROM organizations o,
(VALUES
    ('store_builder', '{"printful_store": "store.kytranempowerment.com"}'::jsonb),
    ('website_studio', '{"domain": "www.kytranempowerment.com"}'::jsonb),
    ('media_hub', '{"domain": "media.kytranempowerment.com"}'::jsonb),
    ('crm', '{}'::jsonb),
    ('email_manager', '{}'::jsonb),
    ('invoicing', '{}'::jsonb),
    ('scheduler', '{}'::jsonb)
) AS m(key, config)
WHERE o.slug = 'kytran-empowerment'
ON CONFLICT (org_id, module_key) DO NOTHING;

-- Register domains
INSERT INTO org_domains (org_id, domain, subdomain, root_domain, target_module, dns_provider)
SELECT o.id, d.domain, d.sub, d.root, d.target, 'hostinger'
FROM organizations o,
(VALUES
    ('dashboard.kytranempowerment.com', 'dashboard', 'kytranempowerment.com', 'dashboard'),
    ('www.kytranempowerment.com', 'www', 'kytranempowerment.com', 'website_studio'),
    ('store.kytranempowerment.com', 'store', 'kytranempowerment.com', 'store_builder'),
    ('media.kytranempowerment.com', 'media', 'kytranempowerment.com', 'media_hub')
) AS d(domain, sub, root, target)
WHERE o.slug = 'kytran-empowerment'
ON CONFLICT (domain) DO NOTHING;
```

**Step 2: Run and verify**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    with open('/app/migrations/031_seed_kytran_empowerment.sql') as f:
        cur.execute(f.read())
    cur.execute('SELECT name, slug, status FROM organizations')
    print('Orgs:', cur.fetchall())
    cur.execute('SELECT ou.role, u.username FROM org_users ou JOIN users u ON u.id = ou.user_id')
    print('Members:', cur.fetchall())
    cur.execute('SELECT module_key, enabled FROM org_modules')
    print('Modules:', cur.fetchall())
    cur.execute('SELECT domain, target_module, dns_status FROM org_domains')
    print('Domains:', cur.fetchall())
"
```

**Step 3: Commit**

```bash
git add platform_v2/migrations/031_seed_kytran_empowerment.sql
git commit -m "feat(saas): seed Kytran Empowerment as first organization"
```

---

## Task 3: SaaS Manager Module — Skeleton + Registration

**Files:**
- Create: `platform_v2/tools/saas_manager/__init__.py`
- Create: `platform_v2/tools/saas_manager/saas_manager_routes.py`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

**Step 1: Create module directory and __init__.py**

```python
# platform_v2/tools/saas_manager/__init__.py
"""
SaaS Manager Module
===================
Multi-tenant organization management, domain routing, and module provisioning.

API Routes (at /tools/saas-manager/...):
- /orgs GET - List organizations
- /orgs POST - Create organization
- /orgs/<id> GET - Organization details
- /orgs/<id>/modules POST - Enable/disable modules
- /orgs/<id>/domains POST - Add domain
- /network/public-ip GET - Public IP status
- /dashboard GET - SaaS overview dashboard
"""

from .saas_manager_routes import saas_manager_bp
```

**Step 2: Create routes skeleton**

```python
# platform_v2/tools/saas_manager/saas_manager_routes.py
"""
A.R.C.H.I.E. Platform - SaaS Manager Routes
=============================================

Multi-tenant SaaS platform management:
- Organization CRUD
- Module provisioning (a la carte)
- Domain management (Hostinger DNS + NPM reverse proxy)
- Public IP monitoring
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required
from functools import wraps
from database import get_db_cursor

saas_manager_bp = Blueprint(
    "saas_manager", __name__, url_prefix="/tools/saas-manager"
)


def admin_required(f):
    """Require admin access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ──────────────────────────────────────────────────────

@saas_manager_bp.route("/")
@admin_required
def dashboard():
    """SaaS Manager main page."""
    return render_template("tools/saas_manager.html")


# ── Organizations ──────────────────────────────────────────────────

@saas_manager_bp.route("/orgs", methods=["GET"])
@admin_required
def list_orgs():
    """List all organizations."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT o.*,
                   COUNT(DISTINCT ou.user_id) AS user_count,
                   COUNT(DISTINCT om.id) FILTER (WHERE om.enabled) AS module_count,
                   COUNT(DISTINCT od.id) AS domain_count
            FROM organizations o
            LEFT JOIN org_users ou ON ou.org_id = o.id
            LEFT JOIN org_modules om ON om.org_id = o.id
            LEFT JOIN org_domains od ON od.org_id = o.id
            GROUP BY o.id
            ORDER BY o.created_at DESC
        """)
        orgs = cur.fetchall()
    return jsonify({"success": True, "orgs": orgs})


@saas_manager_bp.route("/orgs", methods=["POST"])
@admin_required
def create_org():
    """Create a new organization."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "error": "Organization name required"}), 400

    slug = name.lower().replace(" ", "-").replace("_", "-")

    with get_db_cursor() as (conn, cur):
        # Check slug uniqueness
        cur.execute("SELECT id FROM organizations WHERE slug = %s", (slug,))
        if cur.fetchone():
            return jsonify({"success": False, "error": f"Organization '{slug}' already exists"}), 409

        cur.execute("""
            INSERT INTO organizations (name, slug, owner_user_id, archie_user_id, status, settings, ai_config)
            VALUES (%s, %s, %s,
                    (SELECT id FROM users WHERE username = 'admin'),
                    'active', %s, %s)
            RETURNING id, name, slug
        """, (
            name, slug,
            data.get("owner_user_id"),
            json.dumps(data.get("settings", {})),
            json.dumps(data.get("ai_config", {})),
        ))
        org = cur.fetchone()

        # Auto-add ARCHIE seat
        cur.execute("""
            INSERT INTO org_users (org_id, user_id, role, joined_at)
            SELECT %s, id, 'archie', NOW() FROM users WHERE username = 'admin'
            ON CONFLICT DO NOTHING
        """, (org["id"],))

        # Add owner if specified
        if data.get("owner_user_id"):
            cur.execute("""
                INSERT INTO org_users (org_id, user_id, role, joined_at)
                VALUES (%s, %s, 'owner', NOW())
                ON CONFLICT DO NOTHING
            """, (org["id"], data["owner_user_id"]))

    return jsonify({"success": True, "org": org}), 201


@saas_manager_bp.route("/orgs/<int:org_id>", methods=["GET"])
@admin_required
def get_org(org_id):
    """Get organization details with users, modules, domains."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM organizations WHERE id = %s", (org_id,))
        org = cur.fetchone()
        if not org:
            return jsonify({"success": False, "error": "Not found"}), 404

        cur.execute("""
            SELECT ou.*, u.username, u.email
            FROM org_users ou JOIN users u ON u.id = ou.user_id
            WHERE ou.org_id = %s
        """, (org_id,))
        users = cur.fetchall()

        cur.execute("SELECT * FROM org_modules WHERE org_id = %s ORDER BY module_key", (org_id,))
        modules = cur.fetchall()

        cur.execute("SELECT * FROM org_domains WHERE org_id = %s ORDER BY domain", (org_id,))
        domains = cur.fetchall()

    return jsonify({"success": True, "org": org, "users": users, "modules": modules, "domains": domains})


@saas_manager_bp.route("/orgs/<int:org_id>", methods=["PUT"])
@admin_required
def update_org(org_id):
    """Update organization settings."""
    data = request.get_json() or {}
    with get_db_cursor() as (conn, cur):
        fields = []
        values = []
        for key in ("name", "status", "settings", "ai_config"):
            if key in data:
                fields.append(f"{key} = %s")
                val = data[key]
                if key in ("settings", "ai_config"):
                    import json
                    val = json.dumps(val)
                values.append(val)

        if not fields:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        values.append(org_id)
        cur.execute(
            f"UPDATE organizations SET {', '.join(fields)} WHERE id = %s RETURNING *",
            values,
        )
        org = cur.fetchone()
        if not org:
            return jsonify({"success": False, "error": "Not found"}), 404

    return jsonify({"success": True, "org": org})


# ── Module Management ──────────────────────────────────────────────

@saas_manager_bp.route("/orgs/<int:org_id>/modules", methods=["POST"])
@admin_required
def manage_org_modules(org_id):
    """Enable or disable modules for an organization."""
    data = request.get_json() or {}
    module_key = data.get("module_key", "").strip()
    enabled = data.get("enabled", True)

    if not module_key:
        return jsonify({"success": False, "error": "module_key required"}), 400

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            INSERT INTO org_modules (org_id, module_key, enabled, config)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (org_id, module_key)
            DO UPDATE SET enabled = EXCLUDED.enabled, config = COALESCE(NULLIF(EXCLUDED.config::text, '{}')::jsonb, org_modules.config)
            RETURNING *
        """, (org_id, module_key, enabled, json.dumps(data.get("config", {}))))
        mod = cur.fetchone()

    return jsonify({"success": True, "module": mod})


# ── User Management ────────────────────────────────────────────────

@saas_manager_bp.route("/orgs/<int:org_id>/users", methods=["POST"])
@admin_required
def add_org_user(org_id):
    """Add a user to an organization."""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    role = data.get("role", "member")

    if not user_id:
        return jsonify({"success": False, "error": "user_id required"}), 400

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            INSERT INTO org_users (org_id, user_id, role, joined_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
            RETURNING *
        """, (org_id, user_id, role))
        membership = cur.fetchone()

    return jsonify({"success": True, "membership": membership})


@saas_manager_bp.route("/orgs/<int:org_id>/users/<int:user_id>", methods=["DELETE"])
@admin_required
def remove_org_user(org_id, user_id):
    """Remove a user from an organization."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "DELETE FROM org_users WHERE org_id = %s AND user_id = %s RETURNING id",
            (org_id, user_id),
        )
        deleted = cur.fetchone()

    if not deleted:
        return jsonify({"success": False, "error": "Membership not found"}), 404
    return jsonify({"success": True})


# ── Domain Management ──────────────────────────────────────────────

@saas_manager_bp.route("/orgs/<int:org_id>/domains", methods=["GET"])
@admin_required
def list_org_domains(org_id):
    """List domains for an organization."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM org_domains WHERE org_id = %s ORDER BY domain", (org_id,))
        domains = cur.fetchall()
    return jsonify({"success": True, "domains": domains})


@saas_manager_bp.route("/orgs/<int:org_id>/domains", methods=["POST"])
@admin_required
def add_org_domain(org_id):
    """Add a domain to an organization. Triggers DNS + NPM setup."""
    data = request.get_json() or {}
    domain = data.get("domain", "").strip().lower()
    target_module = data.get("target_module", "dashboard")

    if not domain:
        return jsonify({"success": False, "error": "domain required"}), 400

    # Parse subdomain and root
    parts = domain.split(".", 1)
    subdomain = parts[0] if len(parts) > 1 else None
    root_domain = parts[1] if len(parts) > 1 else domain

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            INSERT INTO org_domains (org_id, domain, subdomain, root_domain, target_module, dns_provider)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (org_id, domain, subdomain, root_domain, target_module, data.get("dns_provider", "hostinger")))
        dom = cur.fetchone()

    # Trigger async DNS + NPM setup (Phase 2)
    # from tools.saas_manager.domain_service import setup_domain_async
    # setup_domain_async(dom["id"])

    return jsonify({"success": True, "domain": dom}), 201


@saas_manager_bp.route("/orgs/<int:org_id>/domains/<int:domain_id>", methods=["DELETE"])
@admin_required
def remove_org_domain(org_id, domain_id):
    """Remove a domain. Cleans up DNS + NPM."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "DELETE FROM org_domains WHERE id = %s AND org_id = %s RETURNING domain",
            (domain_id, org_id),
        )
        deleted = cur.fetchone()

    if not deleted:
        return jsonify({"success": False, "error": "Domain not found"}), 404

    # Trigger async DNS + NPM cleanup (Phase 2)
    # from tools.saas_manager.domain_service import cleanup_domain_async
    # cleanup_domain_async(deleted["domain"])

    return jsonify({"success": True, "removed": deleted["domain"]})


@saas_manager_bp.route("/orgs/<int:org_id>/domains/<int:domain_id>/verify", methods=["POST"])
@admin_required
def verify_domain(org_id, domain_id):
    """Check DNS propagation and SSL status for a domain."""
    import socket

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM org_domains WHERE id = %s AND org_id = %s", (domain_id, org_id))
        dom = cur.fetchone()
        if not dom:
            return jsonify({"success": False, "error": "Domain not found"}), 404

        # DNS check
        dns_ok = False
        resolved_ip = None
        try:
            resolved_ip = socket.gethostbyname(dom["domain"])
            # Check against our public IP
            import urllib.request
            public_ip = urllib.request.urlopen("https://api.ipify.org").read().decode()
            dns_ok = resolved_ip == public_ip
        except Exception:
            pass

        new_dns_status = "verified" if dns_ok else "failed"
        cur.execute(
            "UPDATE org_domains SET dns_status = %s, verified_at = NOW() WHERE id = %s",
            (new_dns_status, domain_id),
        )

    return jsonify({
        "success": True,
        "domain": dom["domain"],
        "dns_status": new_dns_status,
        "resolved_ip": resolved_ip,
        "dns_ok": dns_ok,
    })


# ── Network / IP Monitoring ───────────────────────────────────────

@saas_manager_bp.route("/network/public-ip", methods=["GET"])
@admin_required
def get_public_ip():
    """Get current public IP and change history."""
    import urllib.request

    try:
        current_ip = urllib.request.urlopen("https://api.ipify.org").read().decode()
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not detect public IP: {e}"}), 500

    with get_db_cursor() as (conn, cur):
        # Log if changed
        cur.execute("SELECT ip_address FROM org_ip_history ORDER BY detected_at DESC LIMIT 1")
        last = cur.fetchone()
        ip_changed = last is None or last["ip_address"] != current_ip

        if ip_changed:
            cur.execute("INSERT INTO org_ip_history (ip_address) VALUES (%s)", (current_ip,))

        # History
        cur.execute("SELECT * FROM org_ip_history ORDER BY detected_at DESC LIMIT 20")
        history = cur.fetchall()

    return jsonify({
        "success": True,
        "current_ip": current_ip,
        "changed": ip_changed,
        "history": history,
    })


@saas_manager_bp.route("/network/check-ports", methods=["POST"])
@admin_required
def check_ports():
    """Verify ports 80/443 are accessible from outside."""
    import urllib.request

    results = {}
    for port in [80, 443]:
        try:
            public_ip = urllib.request.urlopen("https://api.ipify.org").read().decode()
            proto = "https" if port == 443 else "http"
            url = f"{proto}://{public_ip}:{port}/"
            req = urllib.request.Request(url, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=5)
            results[port] = {"open": True, "status": resp.status}
        except Exception as e:
            results[port] = {"open": False, "error": str(e)}

    return jsonify({"success": True, "ports": results})


# ── Available Modules List ─────────────────────────────────────────

@saas_manager_bp.route("/available-modules", methods=["GET"])
@admin_required
def available_modules():
    """List all modules available for assignment to organizations."""
    from module_registry import get_enabled_modules
    modules = []
    for m in get_enabled_modules():
        modules.append({
            "key": m.id,
            "name": m.name,
            "description": m.description,
            "category": m.category.value if m.category else None,
            "icon": m.icon,
        })
    return jsonify({"success": True, "modules": modules})


import json  # noqa: E402 (used in multiple routes above)
```

**Step 3: Register in module_registry.py**

Add to the `SAAS_SERVICES` category section:

```python
ModuleDefinition(
    id="saas_manager",
    name="SaaS Manager",
    description="Multi-tenant platform management<br>Organizations • Domains • Modules",
    icon="building-2",
    category=ModuleCategory.ADMIN_OPERATIONS,
    route="/tools/saas-manager",
    blueprint_import="tools.saas_manager.saas_manager_routes:saas_manager_bp",
    required_permissions=["admin:saas"],
    minimum_role="ADMIN",
    enabled=True,
    health_check=lambda: default_health_check("saas_manager"),
    priority=0,
    tags=["saas", "organizations", "domains", "multi-tenant", "admin-operations"],
    version="1.0",
),
```

**Step 4: Register permission in rbac.py**

Add `ADMIN_SAAS = "admin:saas"` to the Permission enum and add it to the ADMIN role set.

**Step 5: Verify module loads**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | grep -i saas
```

Expected: `Loaded module: SaaS Manager (/tools/saas-manager)`

**Step 6: Test API endpoints**

```bash
# Login and test
docker exec archie_platform python3 -c "
import requests
s = requests.Session()
# Test list orgs
from tools.saas_manager.saas_manager_routes import saas_manager_bp
print('Blueprint registered:', saas_manager_bp.name)
"

# Test via curl after login
curl -s -b /tmp/cookies.txt http://192.168.1.200:3000/tools/saas-manager/orgs | python3 -m json.tool
```

**Step 7: Commit**

```bash
git add platform_v2/tools/saas_manager/ platform_v2/module_registry.py platform_v2/rbac.py
git commit -m "feat(saas): add SaaS Manager module with org/domain/module CRUD endpoints"
```

---

## Task 4: SaaS Manager Dashboard UI

**Files:**
- Create: `platform_v2/templates/tools/saas_manager.html`

**Step 1: Create the dashboard template**

Build a single-page dashboard following the existing ARCHIE module UI patterns (admin_backups.html style):
- Organization cards grid showing: name, status, user count, module count, domain count
- Click org card to expand details panel (users, modules, domains)
- "New Organization" button → modal wizard
- Domain management with DNS/SSL status badges (pending=yellow, verified=green, failed=red)
- Network panel: current public IP, port check, IP change history
- Module assignment: checkbox list of available modules per org

The template should extend `base.html` and use the ARCHIE design system (dark theme, Lucide icons, status badges).

**Step 2: Verify the page loads**

```bash
curl -s -b /tmp/cookies.txt http://192.168.1.200:3000/tools/saas-manager/ -o /dev/null -w "%{http_code}"
```

Expected: `200`

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/saas_manager.html
git commit -m "feat(saas): add SaaS Manager dashboard UI"
```

---

## Task 5: Domain Service — Hostinger DNS + NPM Integration

**Files:**
- Create: `platform_v2/tools/saas_manager/domain_service.py`
- Modify: `platform_v2/tools/saas_manager/saas_manager_routes.py` (uncomment domain_service calls)

**Step 1: Create the domain service**

```python
# platform_v2/tools/saas_manager/domain_service.py
"""
Domain Service — Hostinger DNS + NPM Reverse Proxy
===================================================

Automates:
1. DNS record creation via Hostinger API
2. Proxy host creation via Nginx Proxy Manager API
3. SSL certificate provisioning (Let's Encrypt via NPM)
4. DNS propagation verification
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

NPM_API_URL = os.environ.get("NPM_API_URL", "http://192.168.1.200:81/api")
NPM_EMAIL = os.environ.get("NPM_ADMIN_EMAIL", "")
NPM_PASSWORD = os.environ.get("NPM_ADMIN_PASSWORD", "")


class NPMClient:
    """Nginx Proxy Manager API client."""

    def __init__(self):
        self.base_url = NPM_API_URL
        self.token = None

    def _auth(self):
        """Authenticate and get JWT token."""
        if self.token:
            return
        resp = requests.post(f"{self.base_url}/tokens", json={
            "identity": NPM_EMAIL,
            "secret": NPM_PASSWORD,
        })
        resp.raise_for_status()
        self.token = resp.json()["token"]

    def _headers(self):
        self._auth()
        return {"Authorization": f"Bearer {self.token}"}

    def create_proxy_host(self, domain: str, forward_host: str, forward_port: int, ssl: bool = True) -> dict:
        """Create a proxy host in NPM."""
        payload = {
            "domain_names": [domain],
            "forward_scheme": "http",
            "forward_host": forward_host,
            "forward_port": forward_port,
            "block_exploits": True,
            "allow_websocket_upgrade": True,
            "access_list_id": 0,
            "certificate_id": 0,
            "ssl_forced": False,
            "meta": {"letsencrypt_agree": True},
            "advanced_config": "",
            "locations": [],
            "http2_support": True,
            "hsts_enabled": False,
            "hsts_subdomains": False,
        }

        resp = requests.post(f"{self.base_url}/nginx/proxy-hosts", json=payload, headers=self._headers())
        resp.raise_for_status()
        host = resp.json()

        # Request SSL certificate if desired
        if ssl:
            try:
                self.request_ssl(host["id"], domain)
            except Exception as e:
                logger.warning(f"SSL request failed for {domain}: {e}")

        return host

    def request_ssl(self, proxy_host_id: int, domain: str) -> dict:
        """Request Let's Encrypt SSL for a proxy host."""
        # Create certificate
        cert_resp = requests.post(f"{self.base_url}/nginx/certificates", json={
            "domain_names": [domain],
            "meta": {
                "letsencrypt_email": NPM_EMAIL,
                "letsencrypt_agree": True,
                "dns_challenge": False,
            },
            "provider": "letsencrypt",
        }, headers=self._headers())
        cert_resp.raise_for_status()
        cert = cert_resp.json()

        # Assign to proxy host
        requests.put(f"{self.base_url}/nginx/proxy-hosts/{proxy_host_id}", json={
            "certificate_id": cert["id"],
            "ssl_forced": True,
            "http2_support": True,
        }, headers=self._headers())

        return cert

    def delete_proxy_host(self, proxy_host_id: int):
        """Delete a proxy host from NPM."""
        resp = requests.delete(
            f"{self.base_url}/nginx/proxy-hosts/{proxy_host_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()

    def list_proxy_hosts(self) -> list:
        """List all proxy hosts."""
        resp = requests.get(f"{self.base_url}/nginx/proxy-hosts", headers=self._headers())
        resp.raise_for_status()
        return resp.json()


def setup_domain(domain_row: dict, public_ip: str) -> dict:
    """
    Full domain setup: Hostinger DNS + NPM proxy host.

    Args:
        domain_row: Row from org_domains table
        public_ip: Server's current public IP

    Returns:
        dict with status of each step
    """
    from hostinger_integration import get_hostinger_api

    result = {"dns": None, "proxy": None, "ssl": None}
    domain = domain_row["domain"]
    subdomain = domain_row["subdomain"]
    root_domain = domain_row["root_domain"]

    # Step 1: Hostinger DNS
    try:
        api = get_hostinger_api()
        dns_result = api.add_dns_record(
            domain=root_domain,
            record_type="A",
            name=subdomain or "@",
            content=public_ip,
            ttl=3600,
        )
        result["dns"] = {"success": True, "record": dns_result}
    except Exception as e:
        result["dns"] = {"success": False, "error": str(e)}

    # Step 2: NPM proxy host
    try:
        npm = NPMClient()
        host = npm.create_proxy_host(
            domain=domain,
            forward_host="archie_platform",
            forward_port=domain_row.get("target_port", 3000),
            ssl=True,
        )
        result["proxy"] = {"success": True, "proxy_host_id": host["id"]}
        result["ssl"] = {"success": True}
    except Exception as e:
        result["proxy"] = {"success": False, "error": str(e)}

    return result


def cleanup_domain(domain: str, npm_proxy_host_id: int = None):
    """Remove DNS record and NPM proxy host for a domain."""
    from hostinger_integration import get_hostinger_api

    # Remove from NPM
    if npm_proxy_host_id:
        try:
            npm = NPMClient()
            npm.delete_proxy_host(npm_proxy_host_id)
        except Exception as e:
            logger.warning(f"Failed to remove NPM proxy host {npm_proxy_host_id}: {e}")

    # DNS removal would need record_id tracking — log for manual cleanup
    logger.info(f"Domain {domain} removed. Check Hostinger DNS manually if needed.")
```

**Step 2: Wire domain_service into routes**

Uncomment the `setup_domain_async` and `cleanup_domain_async` calls in the domain add/remove routes, replacing with synchronous calls for now:

```python
# In add_org_domain, after the INSERT:
from tools.saas_manager.domain_service import setup_domain
import urllib.request
public_ip = urllib.request.urlopen("https://api.ipify.org").read().decode()
setup_result = setup_domain(dom, public_ip)

# Update statuses based on result
dns_status = "verified" if setup_result["dns"] and setup_result["dns"]["success"] else "pending"
ssl_status = "active" if setup_result["ssl"] and setup_result["ssl"]["success"] else "pending"
npm_id = setup_result["proxy"]["proxy_host_id"] if setup_result["proxy"] and setup_result["proxy"]["success"] else None

with get_db_cursor() as (conn, cur):
    cur.execute("""
        UPDATE org_domains SET dns_status = %s, ssl_status = %s, npm_proxy_host_id = %s
        WHERE id = %s
    """, (dns_status, ssl_status, npm_id, dom["id"]))
```

**Step 3: Add NPM env vars to docker-compose.yml**

```yaml
# Under archie_platform environment:
- NPM_API_URL=http://192.168.1.200:81/api
- NPM_ADMIN_EMAIL=${NPM_ADMIN_EMAIL}
- NPM_ADMIN_PASSWORD=${NPM_ADMIN_PASSWORD}
```

**Step 4: Test domain service**

```bash
docker exec archie_platform python3 -c "
from tools.saas_manager.domain_service import NPMClient
npm = NPMClient()
hosts = npm.list_proxy_hosts()
print(f'NPM has {len(hosts)} proxy hosts')
for h in hosts:
    print(f'  {h[\"domain_names\"]} -> {h[\"forward_host\"]}:{h[\"forward_port\"]}')
"
```

**Step 5: Commit**

```bash
git add platform_v2/tools/saas_manager/domain_service.py docker-compose.yml platform_v2/tools/saas_manager/saas_manager_routes.py
git commit -m "feat(saas): add domain service with Hostinger DNS + NPM proxy integration"
```

---

## Task 6: Public IP Monitor Service

**Files:**
- Create: `platform_v2/tools/saas_manager/ip_monitor.py`

**Step 1: Create IP monitor**

```python
# platform_v2/tools/saas_manager/ip_monitor.py
"""
Public IP Monitor
=================

Periodically checks the server's public IP address.
On change: logs to org_ip_history, updates all Hostinger DNS records.
"""

import logging
import urllib.request
from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_public_ip() -> str:
    """Detect current public IP."""
    for url in ["https://api.ipify.org", "https://ifconfig.me", "https://icanhazip.com"]:
        try:
            return urllib.request.urlopen(url, timeout=5).read().decode().strip()
        except Exception:
            continue
    raise RuntimeError("Could not detect public IP from any provider")


def check_and_update_ip() -> dict:
    """
    Check public IP. If changed, log and update DNS records.

    Returns:
        dict with current_ip, changed, updated_domains
    """
    current_ip = get_public_ip()

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT ip_address FROM org_ip_history ORDER BY detected_at DESC LIMIT 1")
        last = cur.fetchone()
        old_ip = last["ip_address"] if last else None
        changed = old_ip != current_ip

        if changed:
            cur.execute("INSERT INTO org_ip_history (ip_address) VALUES (%s)", (current_ip,))
            logger.info(f"Public IP changed: {old_ip} -> {current_ip}")

    updated_domains = []
    if changed and old_ip:
        updated_domains = _update_dns_records(current_ip)

    return {"current_ip": current_ip, "changed": changed, "old_ip": old_ip, "updated_domains": updated_domains}


def _update_dns_records(new_ip: str) -> list:
    """Update all Hostinger DNS A records to point to new IP."""
    from hostinger_integration import get_hostinger_api

    updated = []
    api = get_hostinger_api()

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("""
            SELECT DISTINCT root_domain FROM org_domains
            WHERE dns_provider = 'hostinger' AND dns_status = 'verified'
        """)
        root_domains = [r["root_domain"] for r in cur.fetchall()]

    for root in root_domains:
        try:
            records = api.get_dns_records(root)
            if records.get("success"):
                for rec in records.get("data", []):
                    if rec.get("type") == "A":
                        api.update_dns_record(
                            domain=root,
                            record_id=rec["id"],
                            record_type="A",
                            name=rec["name"],
                            content=new_ip,
                            ttl=rec.get("ttl", 3600),
                        )
                        updated.append(f"{rec['name']}.{root}")
        except Exception as e:
            logger.error(f"Failed to update DNS for {root}: {e}")

    return updated
```

**Step 2: Test IP monitor**

```bash
docker exec archie_platform python3 -c "
from tools.saas_manager.ip_monitor import check_and_update_ip
result = check_and_update_ip()
print(result)
"
```

**Step 3: Commit**

```bash
git add platform_v2/tools/saas_manager/ip_monitor.py
git commit -m "feat(saas): add public IP monitor with auto-DNS update"
```

---

## Task 7: Add org_id to Existing Per-Org Tables

**Files:**
- Create: `platform_v2/migrations/032_add_org_id_to_business_tables.sql`

**Step 1: Write the migration**

```sql
-- 032_add_org_id_to_business_tables.sql
-- Add org_id to per-organization business tables

-- user_stores
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'user_stores' AND column_name = 'org_id') THEN
        ALTER TABLE user_stores ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_user_stores_org ON user_stores(org_id);
        RAISE NOTICE 'Added org_id to user_stores';
    END IF;
END $$;

-- store_products
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'store_products' AND column_name = 'org_id') THEN
        ALTER TABLE store_products ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_store_products_org ON store_products(org_id);
        RAISE NOTICE 'Added org_id to store_products';
    END IF;
END $$;

-- store_orders
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'store_orders' AND column_name = 'org_id') THEN
        ALTER TABLE store_orders ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_store_orders_org ON store_orders(org_id);
        RAISE NOTICE 'Added org_id to store_orders';
    END IF;
END $$;

-- website_builder_projects
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'website_builder_projects' AND column_name = 'org_id') THEN
        ALTER TABLE website_builder_projects ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_website_projects_org ON website_builder_projects(org_id);
        RAISE NOTICE 'Added org_id to website_builder_projects';
    END IF;
END $$;

-- Assign existing data to Kytran Empowerment
DO $$
DECLARE
    ke_org_id INTEGER;
BEGIN
    SELECT id INTO ke_org_id FROM organizations WHERE slug = 'kytran-empowerment';
    IF ke_org_id IS NOT NULL THEN
        UPDATE user_stores SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE store_products SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE store_orders SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE website_builder_projects SET org_id = ke_org_id WHERE org_id IS NULL;
        RAISE NOTICE 'Assigned existing data to Kytran Empowerment (org_id=%)', ke_org_id;
    END IF;
END $$;
```

**Step 2: Run and verify**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    with open('/app/migrations/032_add_org_id_to_business_tables.sql') as f:
        cur.execute(f.read())
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name = 'user_stores' AND column_name = 'org_id'\")
    print('user_stores has org_id:', cur.fetchone() is not None)
\"
```

**Step 3: Commit**

```bash
git add platform_v2/migrations/032_add_org_id_to_business_tables.sql
git commit -m "feat(saas): add org_id to business tables and assign to Kytran Empowerment"
```

---

## Task Summary

| Task | Description | Dependencies |
|------|-------------|--------------|
| 1 | Database migration — core SaaS tables | None |
| 2 | Seed Kytran Empowerment org | Task 1 |
| 3 | SaaS Manager module skeleton + registration | Task 1 |
| 4 | Dashboard UI | Task 3 |
| 5 | Domain service (Hostinger + NPM) | Task 3 |
| 6 | IP monitor service | Task 1 |
| 7 | Add org_id to existing tables | Task 2 |

**Execution order:** 1 → 2 → 3 → (4, 5, 6 in parallel) → 7
