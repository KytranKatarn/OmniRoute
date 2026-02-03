# SaaS Platform Layer Design

**Date**: 2026-02-03
**Status**: Approved
**Version**: 1.0

---

## Overview

Transform A.R.C.H.I.E. from a single-tenant platform into a multi-tenant SaaS platform where ARCHIE operates as an **active AI business partner** within every client organization. The first client is **Kytran Empowerment** (kytranempowerment.com).

### Key Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| ARCHIE's role | Active partner in every org | Not just hosting — ARCHIE has its own seat and acts autonomously |
| Domain routing | Hostinger DNS + existing NPM reverse proxy | DNS-only integration, NPM already owns :80/:443 with auto-SSL |
| Module access | A la carte per org | Tiers can be layered later when client patterns emerge |
| Data isolation | Row-level (default) + Node migration path | `org_id` on shared tables; Bridge Command nodes for full isolation |
| Per-org AI agents | Schema ready, activate later | `ai_config` JSONB column on orgs, build ARCHIE integrations first |
| Email/Calendar scope | Per-user, not per-org | These are personal assistant connections, not business assets |

---

## Architecture

### Model: ARCHIE as Business Partner

Every client organization gets:
- An **ARCHIE seat** (Admin user) that can act autonomously via AI Bridge
- One or more **human users** (e.g., Kytran as owner)
- A la carte **module access** (Store Builder, Website Studio, CRM, etc.)
- **Custom domains** routed through NPM reverse proxy
- **Per-org AI configuration** (personality, tools, knowledge scope — future activation)

### Data Scoping

| Scope | Data | Examples |
|-------|------|----------|
| **Per-org** | Business assets | Stores, products, orders, websites, CRM contacts, invoices |
| **Per-user** | Assistant connections | Email accounts, calendar connections, preferences, sessions |
| **Platform-level** | ARCHIE internals | knowledge_base, improvements, media_hub_services, unified_projects |

### Isolation Model

```
Default: Row-Level Isolation (shared DB, org_id filtering + PostgreSQL RLS)
    |
    | Migration trigger (client needs full isolation)
    v
Node Isolation (Bridge Command remote node, separate DB)
    - Export org data (all rows matching org_id)
    - Provision new ARCHIE node
    - Import data into dedicated database
    - Flip isolation_type: shared -> node, set node_id
    - Future requests proxy through Bridge Command
```

---

## Data Model

### New Tables

#### organizations
```sql
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    owner_user_id INTEGER REFERENCES users(id),
    archie_user_id INTEGER REFERENCES users(id),
    status VARCHAR(50) DEFAULT 'provisioning',  -- provisioning / active / suspended
    settings JSONB DEFAULT '{}',                 -- theme, branding, custom config
    ai_config JSONB DEFAULT '{}',                -- personality, system prompt, enabled tools, knowledge scope
    isolation_type VARCHAR(20) DEFAULT 'shared', -- shared / migrating / node
    node_id VARCHAR(255),                        -- NULL for shared, Bridge Command node ref
    migration_status VARCHAR(50),                -- NULL / exporting / provisioning / importing / verifying / complete
    migrated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### org_users
```sql
CREATE TABLE org_users (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'member',  -- owner / admin / member / archie
    invited_at TIMESTAMP DEFAULT NOW(),
    joined_at TIMESTAMP,
    UNIQUE(org_id, user_id)
);
```

#### org_modules
```sql
CREATE TABLE org_modules (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    module_key VARCHAR(100) NOT NULL,             -- 'store_builder', 'crm', etc.
    enabled BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}',                    -- per-org module settings
    activated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, module_key)
);
```

#### org_domains
```sql
CREATE TABLE org_domains (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL UNIQUE,          -- "dashboard.kytranempowerment.com"
    subdomain VARCHAR(100),                       -- "dashboard"
    root_domain VARCHAR(255),                     -- "kytranempowerment.com"
    target_module VARCHAR(100),                   -- 'dashboard' / 'store_builder' / 'website_studio'
    target_port INTEGER DEFAULT 3000,
    ssl_status VARCHAR(50) DEFAULT 'pending',     -- pending / active / failed
    dns_status VARCHAR(50) DEFAULT 'pending',     -- pending / verified / failed
    dns_provider VARCHAR(50) DEFAULT 'hostinger', -- hostinger / cloudflare / manual
    hostinger_zone_id VARCHAR(255),
    npm_proxy_host_id INTEGER,                    -- NPM proxy host ID for management
    created_at TIMESTAMP DEFAULT NOW(),
    verified_at TIMESTAMP
);
```

#### org_ip_history
```sql
CREATE TABLE org_ip_history (
    id SERIAL PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    detected_at TIMESTAMP DEFAULT NOW()
);
```

### Existing Tables — Add org_id

All `org_id` columns are **nullable** with no default. Existing data stays untouched.

| Table | Module | Migration Note |
|-------|--------|----------------|
| `user_stores` | Store Builder | Each store belongs to an org |
| `store_products` | Store Builder | Inherits org via store (or direct org_id) |
| `store_orders` | Store Builder | Inherits org via store (or direct org_id) |
| `website_builder_projects` | Website Studio | Each site belongs to an org |
| `website_builder_pages` | Website Studio | Inherits org via project |
| `crm_contacts` | CRM | Contacts scoped to org |
| `invoices` | Invoicing | Invoices scoped to org |
| `scheduled_events` | Scheduler | Events scoped to org |

### Tables That Do NOT Get org_id

| Table | Reason |
|-------|--------|
| `users` | Users exist at platform level; `org_users` maps them to orgs |
| `email_accounts` | Per-user assistant connection, not per-org |
| `knowledge_base` | ARCHIE's internal brain |
| `unified_projects` / `unified_tasks` | ARCHIE internal project management |
| `improvement_*` | Platform-level |
| `media_hub_services` | Shared infrastructure (until per-org media access) |

### Row-Level Security

```sql
-- Example RLS policy for user_stores
ALTER TABLE user_stores ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation ON user_stores
    USING (org_id = current_setting('app.current_org_id')::INTEGER OR org_id IS NULL);
```

Application middleware sets `app.current_org_id` on each DB connection based on the logged-in user's active org.

---

## Module: saas_manager

### File Structure

```
platform_v2/tools/saas_manager/
├── __init__.py
├── saas_manager_routes.py      -- Flask blueprint, all API endpoints
├── templates/
│   └── tools/saas_manager/
│       └── saas_manager.html   -- Main UI (org management dashboard)
├── domain_service.py           -- Hostinger DNS API + NPM API integration
├── org_service.py              -- Organization CRUD, module provisioning
├── migration_service.py        -- Shared -> Node migration (scaffold)
└── ip_monitor.py               -- Public IP monitoring + auto-DNS update
```

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/orgs` | List all orgs (admin: all, user: their orgs) |
| POST | `/orgs` | Create new organization |
| GET | `/orgs/<id>` | Org detail (users, modules, domains, status) |
| PUT | `/orgs/<id>` | Update org settings, AI config |
| DELETE | `/orgs/<id>` | Deactivate organization (soft delete) |
| POST | `/orgs/<id>/modules` | Enable/disable modules for org |
| POST | `/orgs/<id>/users` | Add user to org (ties into Account Center) |
| DELETE | `/orgs/<id>/users/<uid>` | Remove user from org |
| GET | `/orgs/<id>/domains` | List org's domains |
| POST | `/orgs/<id>/domains` | Add domain -> Hostinger DNS + NPM setup |
| DELETE | `/orgs/<id>/domains/<did>` | Remove domain, clean up DNS + NPM |
| POST | `/orgs/<id>/domains/<did>/verify` | Check DNS propagation + SSL status |
| GET | `/network/public-ip` | Current public IP + change history |
| POST | `/network/check-ports` | Verify 80/443 forwarded correctly |
| GET | `/dashboard` | SaaS overview: all orgs, domain health, IP status |

### Integration Points

| System | Integration |
|--------|-------------|
| **Account Center** | User creation/role assignment scoped to org |
| **Store Builder** | `org_id` filtering, per-org Printful config |
| **Website Studio** | `org_id` filtering, domain routing |
| **Media Hub** | `org_id` filtering, future subdomain access |
| **Bridge Command** | Node management for migrated orgs |
| **NPM** (Docker API) | Proxy host creation, SSL cert management |
| **Hostinger API** | DNS A/CNAME record management |
| **AI Bridge** | Org-scoped AI context for ARCHIE partner role |

---

## Domain Routing

### Infrastructure

```
Internet
    |
    v
Telus Gateway (192.168.1.254) -- port forward 80,443 -> 192.168.1.200
    |
    v
Nginx Proxy Manager (docker: nginx-proxy-manager, :80/:443)
    |-- dashboard.kytranempowerment.com -> archie_platform:3000
    |-- www.kytranempowerment.com       -> archie_platform:3000 (website studio)
    |-- store.kytranempowerment.com     -> archie_platform:3000 (store builder)
    |-- media.kytranempowerment.com     -> archie_platform:3000 (media hub, future)
    v
ARCHIE Platform (archie_platform:3000)
    -- Middleware reads Host header -> resolves org + target module
    -- Serves org-scoped content
```

### Domain Add Flow

1. User adds domain in SaaS Manager UI
2. Module calls Hostinger API -> creates DNS A record -> `209.107.102.95` (public IP)
3. Module calls NPM API -> creates proxy host with Let's Encrypt SSL
4. DNS verification loop polls until propagation confirmed
5. SSL auto-provisioned once DNS resolves
6. `dns_status` and `ssl_status` update in `org_domains`

### Public IP Monitoring

- Periodic check via `api.ipify.org` (every 15 minutes)
- On change: log to `org_ip_history`, auto-update all Hostinger DNS records
- Alert via platform notifications

---

## Network Details

| Resource | Value |
|----------|-------|
| Server LAN IP | 192.168.1.200 |
| Current Public IP | 209.107.102.95 |
| Gateway | 192.168.1.254 (Telus business fibre, Vodafone-branded) |
| Required Port Forwards | 80 -> 192.168.1.200:80, 443 -> 192.168.1.200:443 |
| NPM Admin | http://192.168.1.200:81 |
| DNS Provider | Hostinger (API-managed) |

**Gateway Note**: Telus-provided gateway has web UI only, no programmable API. Port forwards must be configured manually. Future upgrade to pfSense/OPNsense will enable API-managed gateway via `gateway_service.py`.

---

## Kytran Empowerment — First Client

| Property | Value |
|----------|-------|
| Organization | Kytran Empowerment |
| Root Domain | kytranempowerment.com |
| Owner User | Kytran (human) |
| ARCHIE User | Admin (AI partner) |
| Isolation | shared (row-level) |

### Domains

| Subdomain | Target Module | Purpose |
|-----------|---------------|---------|
| dashboard.kytranempowerment.com | Platform Dashboard | ARCHIE management interface |
| www.kytranempowerment.com | Website Studio | Company website |
| store.kytranempowerment.com | Store Builder | Printful storefront |
| media.kytranempowerment.com | Media Hub | Media access (future) |

### Enabled Modules

- Dashboard (Platform access)
- Store Builder (Printful integration: store.kytranempowerment.com)
- Website Studio (www.kytranempowerment.com)
- Media Hub (future: media.kytranempowerment.com)
- CRM, Email Manager, Invoicing, Scheduler (as needed)

---

## Implementation Phases

### Phase 1 — Foundation
- Create all new database tables (organizations, org_users, org_modules, org_domains, org_ip_history)
- Build `saas_manager` module skeleton (routes, templates, services)
- Register in `module_registry.py` + `rbac.py`
- Create "Kytran Empowerment" as first org with Admin + Kytran users
- Public IP monitor service

### Phase 2 — Domain Management
- Hostinger DNS API integration (`domain_service.py`)
- NPM API integration (auto-create proxy hosts + SSL)
- Domain verification flow (DNS propagation check)
- Wire up `dashboard.kytranempowerment.com` as first live domain

### Phase 3 — Org Scoping
- Add `org_id` to per-org tables (stores, websites, CRM, invoices)
- Middleware to set org context from logged-in user's active org
- Update Store Builder, Website Studio, CRM queries to filter by `org_id`
- Assign existing Kytran Empowerment data to the new org
- PostgreSQL RLS policies

### Phase 4 — Dashboard UI
- SaaS Manager dashboard (org cards, domain health, IP status)
- "New Organization" wizard
- Module assignment interface
- Per-org AI config panel (scaffold for per-org ARCHIE personalities)

### Phase 5 — Future (Documented, Not Built Yet)
- Migration service: shared -> node (via Bridge Command)
- Per-org AI agent personalities (Option B full activation)
- Gateway API integration (when router upgraded to pfSense/OPNsense)
- Tier/package system (when client patterns emerge from real usage)
- Per-org knowledge bases (scoped AI memory)
