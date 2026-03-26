# Kytran Business Suite — Design Specification

**Date:** 2026-03-26
**Status:** Approved
**Project:** #196 — Unified Business Suite
**Product Name:** Kytran Business Suite
**Repo:** KytranKatarn/kytran-business-suite
**Subdomain:** business.kytranempowerment.com
**Docker Image:** ghcr.io/kytrankatarn/kytran-business-suite

---

## 1. Product Vision

A modular business operations platform where customers pick the modules they need. AI agents (powered by C.O.M.M.E.R.C.E. via A.R.C.H.I.E. Bridge dispatch) handle automations between modules as a premium tier feature.

**Target market:** Kytran Empowerment and clients first (tenant #1 at Enterprise tier), then self-serve SaaS for small-to-mid businesses.

**Differentiator:** Modular marketplace + AI agent orchestration. No other small business SaaS has native AI agents coordinating between business modules.

**Competitors:** Odoo (modular, open-source), Zoho One (45+ apps), HubSpot (marketing-led). We combine Odoo's modularity with AI-native automation.

---

## 2. Architecture

### 2.1 Pattern: Modular Monolith with Plugin Architecture

Single Flask application with a plugin system. Each business module is a self-contained plugin with a manifest declaring its identity, dependencies, events, and permissions. A plugin loader discovers and registers plugins at startup.

This gives operational simplicity (one Docker container, one DB) with architectural cleanliness for module isolation, per-tenant enablement, and future marketplace expansion.

### 2.2 Four Layers

1. **Core Layer** (always loaded) — app factory, tenant middleware, plugin loader, event bus, mail client, auth, Stripe billing, RBAC, marketplace UI, Bridge client
2. **Integrations Layer** (core connectors) — Google Workspace, Microsoft 365, Stalwart Mail, generic SMTP, Printful, Social OAuth
3. **Plugin Layer** (per-tenant) — all business modules, enabled/disabled per tenant based on tier + add-on purchases
4. **Event Bus** — pub/sub between plugins. Modules emit events (e.g., `contact.created`, `order.placed`), other modules and the automations engine consume them.

### 2.3 Multi-Tenancy: Schema-Per-Tenant

Each tenant gets their own PostgreSQL schema in the same database.

**`public` schema (shared):**
- `tenants` — id, name, slug, stripe_customer_id, tier (free/business/enterprise), created_at, settings (JSONB)
- `tenant_modules` — tenant_id, module_slug, enabled, source (tier_included/addon_purchase), activated_at
- `module_catalog` — slug, name, description, version, category, tier_required, price_monthly, icon, dependencies (JSONB)
- `tenant_users` — user_id, tenant_id, role (owner/admin/member/viewer)
- `users` — id, email, name, password_hash, google_id, created_at
- `stripe_config` — webhook_secret, product_ids (JSONB), price_ids (JSONB)
- `event_log` — tenant_id, event_type, payload (JSONB), source_plugin, created_at

**Per-tenant schema (`tenant_{id}`):**
- Plugin-specific tables created by each plugin's migrations
- e.g., `crm_customers`, `invoices`, `store_products`, `workflow_queue`
- No `tenant_id` column needed — schema isolation handles it

**Request flow:**
1. Identify tenant from subdomain or session
2. Set PostgreSQL `search_path` to `tenant_{id}, public`
3. Check `tenant_modules` — is the requested plugin enabled for this tenant?
4. If yes, route to plugin. If no, 403 with marketplace upsell.

**Why schema isolation:**
- Security: query bugs can't leak data between tenants
- Backups: backup/restore individual tenants
- Performance: indexes are per-tenant
- Deletion: `DROP SCHEMA tenant_{id} CASCADE` for clean removal
- Migration: run DB migrations per-tenant for module-specific tables

### 2.4 Deployment Modes

| Mode | DB | AI Agents | Use Case |
|------|-----|-----------|----------|
| **Hub-hosted** | ARCHIE's PostgreSQL (`archie_database`) | Direct Bridge access | Kytran Empowerment + clients |
| **Node-hosted** | Local PostgreSQL on client node | Via mesh to Hub Bridge | Privacy-conscious clients |
| **Self-hosted** | Own PostgreSQL | Cloud API or none | Independent users (GitHub download) |

For tenant #1 (Kytran Empowerment): no separate DB container. Suite points at `archie_database` and creates a `tenant_kytran` schema. This makes the suite part of A.R.C.H.I.E.'s consciousness.

Config switches via env vars:
- `KBS_DB_HOST=archie_database` (hub) vs `kbs-postgres` (standalone)
- `KBS_BRIDGE_URL=http://192.168.1.200:3000/api/bridge` (hub) vs empty (no AI)

---

## 3. Plugin System

### 3.1 Plugin Structure

```
plugins/kbs-crm/
  manifest.json          # Identity, dependencies, events, permissions
  __init__.py            # Blueprint registration
  routes.py              # HTTP endpoints
  models.py              # DB models or raw SQL helpers
  migrations/            # Module-specific DB tables
    001_initial.sql
  templates/             # Jinja2 templates
    crm.html
  static/                # CSS/JS
    css/crm.css
    js/crm.js
  tests/                 # Plugin tests
```

### 3.2 manifest.json Schema

```json
{
  "slug": "crm",
  "name": "CRM & Contacts",
  "version": "1.0.0",
  "description": "Customer relationship management",
  "category": "core|commerce|marketing|communications|operations|legal_finance|industry",
  "tier_required": "free|business|enterprise",
  "price_monthly": null,
  "icon": "users",
  "dependencies": [],
  "emits": ["contact.created", "contact.updated", "contact.deleted"],
  "consumes": ["order.created", "invoice.paid", "appointment.completed"],
  "permissions": ["crm.read", "crm.write", "crm.export", "crm.admin"],
  "nav": {
    "label": "CRM",
    "icon": "users",
    "order": 10
  }
}
```

### 3.3 Plugin Loader

At app startup:
1. Scan `plugins/` for `manifest.json` files
2. Validate manifests (dependencies exist, no circular deps)
3. Register Flask Blueprints in dependency order
4. Register event listeners from `consumes` declarations
5. Build navigation menu (filtered per-tenant by enabled modules)

### 3.4 Event Bus

In-process pub/sub. No external message broker needed at this scale.

```python
# Emitting (in CRM plugin):
event_bus.emit("contact.created", {"contact_id": 123, "name": "Jane Smith"})

# Consuming (in Invoicing plugin):
@event_bus.on("contact.created")
def sync_billing_contact(data): ...

# Consuming (in Automations engine):
@event_bus.on("contact.created")
def check_automation_triggers(data): ...
```

**Rules:**
- Events include `tenant_id` automatically from request context
- Bus only routes events to plugins enabled for that tenant
- Sync delivery for critical flows (same request)
- Async delivery via Redis queue for non-critical flows (email, notifications)
- All events logged to `public.event_log` for debugging and automation history

---

## 4. Module Catalog

### 4.1 Complete Module Map

| Module | Category | Tier | Source | Phase |
|--------|----------|------|--------|-------|
| CRM & Contacts | Core | Free | Migrate from ARCHIE (52 routes) | 1 |
| Invoicing & Billing | Core | Free | Migrate from ARCHIE (20 routes) | 1 |
| Store / E-Commerce | Commerce | Free | Migrate from ARCHIE (27 routes) | 1 |
| Automations Engine | Operations | Free (engine) / Enterprise (UI) | Migrate from ARCHIE (15 routes) | 1 (engine), 3 (UI) |
| Appointments | Operations | Business | New build | 1 |
| Content Studio | Marketing | Business | Migrate from ARCHIE (17 routes) | 2 |
| Social Media | Marketing | Business | Migrate from ARCHIE (48 routes) | 2 |
| Website Builder | Marketing | Business | Migrate from ARCHIE (59 routes) | 2 |
| Marketing Dashboard | Marketing | Business | New (consolidate CRM + Social analytics) | 2 |
| Call Center | Communications | Enterprise | Migrate from ARCHIE (22 routes) | 3 |
| Help Desk | Communications | Business | New build | 3 |
| Automations UI | Operations | Enterprise | New build (visual workflow builder) | 3 |
| Contracts & Legal | Legal & Finance | Enterprise | New build | 4 |
| Accounting | Legal & Finance | Business | New build + QuickBooks/Xero integration | 4 |
| Industry Add-ons | Industry | Varies | New builds (limo dispatch, salon, etc.) | 4+ |

### 4.2 Event Topology (Phase 1 modules)

```
CRM emits:        contact.created, contact.updated, contact.deleted,
                  segment.member_added, interaction.logged
CRM consumes:     order.created, invoice.paid, appointment.completed

Invoicing emits:  invoice.created, invoice.sent, invoice.paid,
                  invoice.overdue, payment.received
Invoicing consumes: contact.created, order.created

Store emits:      order.created, order.shipped, order.completed,
                  product.created, product.updated
Store consumes:   contact.created, invoice.paid

Automations:      consumes ALL events, checks tenant workflows,
                  emits: automation.triggered, automation.completed
```

---

## 5. Pricing & Gating

### 5.1 Tier Structure

| Tier | Included Modules | AI Features | Price |
|------|-----------------|-------------|-------|
| **Free** | CRM, Invoicing, Store, Automations engine (event-driven only) | None | $0 |
| **Business** | All Free + Appointments, Content Studio, Social Media, Website Builder, Marketing Dashboard, Help Desk, Accounting | Basic AI (content templates, writing suggestions, email subject lines — single-shot API calls, no agent orchestration) | TBD |
| **Enterprise** | All Business + Call Center, Automations UI (visual workflow builder), Contracts & Legal | Full AI agent orchestration via C.O.M.M.E.R.C.E. | TBD |

Industry add-on modules are priced separately (a la carte) on top of any tier.

### 5.2 Module Activation Flow

**Tier-included module:**
User clicks "Enable" → `tenant_modules` row created with `source=tier_included` → plugin activated immediately.

**Add-on module:**
User clicks "Enable" → Stripe Checkout session → payment confirmed via webhook → `tenant_modules` row created with `source=addon_purchase` → plugin activated.

**Tier upgrade:**
User clicks "Upgrade" → Stripe Billing Portal → subscription updated via webhook → all new-tier modules unlocked in `tenant_modules`.

### 5.3 CRM Integration (dogfooding)

The suite manages its own subscribers through its own modules:
- Signup → CRM contact auto-created + Stripe customer created
- Module purchase → CRM interaction logged + Invoice auto-generated
- Churn → CRM interaction logged + Automations engine fires retention workflow

---

## 6. AI Agent Integration

### 6.1 Agent-to-Module Mapping

| Module Category | AI Director | Department |
|----------------|-------------|------------|
| Core (CRM) | R.E.S.O.L.V.E. | Customer Success & Support |
| Core (Invoicing) | L.E.D.G.E.R. | Finance & Accounting |
| Commerce (Store/Shipping) | C.A.R.G.O. | Logistics & Supply Chain |
| Marketing (Content/Social/Website) | S.I.G.N.A.L. | Marketing & Communications |
| Marketing (Content Studio) | M.U.S.E. | Creative & Design |
| Communications (Call Center/Help Desk) | R.E.S.O.L.V.E. | Customer Success & Support |
| Operations (Automations) | B.A.S.E. | Operations & Infrastructure |
| Legal & Finance (Contracts) | G.A.V.E.L. | Legal & Regulatory |
| Suite-wide orchestration | C.O.M.M.E.R.C.E. | New — suite orchestrator |

### 6.2 C.O.M.M.E.R.C.E. Agent

The suite's orchestrator agent. Does not replace department directors — coordinates them.

Example: "Send an invoice to my last 10 overdue customers"
→ C.O.M.M.E.R.C.E. breaks down:
  → R.E.S.O.L.V.E. pulls overdue contacts from CRM
  → L.E.D.G.E.R. generates invoices
  → S.I.G.N.A.L. sends emails via mail client

### 6.3 Architecture

AI agents live outside the suite. Enterprise tenants call A.R.C.H.I.E.'s Bridge via API:

```
Suite → bridge_client.py → KBS_BRIDGE_URL → A.R.C.H.I.E. Bridge → Agent dispatch → Response
```

- Free tier: no AI
- Business tier: basic AI (templates, content suggestions via simple API calls)
- Enterprise tier: full C.O.M.M.E.R.C.E. orchestration

---

## 7. Email Infrastructure

### 7.1 Unified Mail Client

`core/mail_client.py` abstracts over multiple providers. Configured per-tenant:

| Provider | Config | Use Case |
|----------|--------|----------|
| Stalwart | SMTP to `mail.kytranempowerment.com` | Kytran-hosted tenants |
| Google Workspace | OAuth + Gmail API | Tenants using Google |
| Microsoft 365 | OAuth + Graph API | Tenants using Outlook |
| Generic SMTP | Host/port/credentials | Self-hosted, SendGrid, Mailgun |

### 7.2 Tenant #1 (Kytran Empowerment)

- Primary: Stalwart (`mail.kytranempowerment.com`)
- Google Workspace connected for testing (Kytran Gmail account)
- Both available — suite can route based on purpose (transactional via Stalwart, marketing via Gmail)

---

## 8. Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend | Flask (Python) | Matches A.R.C.H.I.E., code migrates directly |
| Database | PostgreSQL 16 (schema-per-tenant) | Already running as `archie_database` |
| Cache/Queue | Redis | Sessions, async event queue, rate limiting |
| Background Worker | APScheduler or Celery (Redis broker) | Async events, email queue, scheduled automations |
| Frontend | Jinja2 + LCARS theme + vanilla JS | Matches platform, no framework overhead |
| Auth | Flask-Login + Google OAuth + SSO stub | Proven pattern |
| Payments | Stripe (Checkout + Billing Portal + Webhooks) | Project #195 foundation |
| Email | Stalwart / Google / M365 / SMTP | Configurable per tenant |
| AI | A.R.C.H.I.E. Bridge API | Enterprise tier only |
| Containers | Docker Compose | Matches platform conventions |

---

## 9. Repo Structure

```
kytran-business-suite/
├── docker-compose.yml          # App + Redis + Worker (+ optional Postgres)
├── Dockerfile
├── .env.example
├── README.md
├── core/
│   ├── app.py                  # Flask app factory
│   ├── config.py               # Env-based config
│   ├── tenant.py               # Tenant middleware (schema switching)
│   ├── auth.py                 # Local + Google OAuth + SSO
│   ├── rbac.py                 # Role-based access
│   ├── plugin_loader.py        # Discover + register plugins
│   ├── event_bus.py            # Pub/sub between plugins
│   ├── mail_client.py          # Unified email
│   ├── stripe_billing.py       # Checkout, webhooks, tier management
│   ├── marketplace.py          # Module catalog + enable/disable UI
│   ├── bridge_client.py        # AI agent API calls
│   └── database.py             # DB connection + schema manager
├── integrations/
│   ├── google_workspace.py
│   ├── microsoft365.py
│   ├── printful.py
│   └── social_oauth.py
├── plugins/
│   ├── kbs-crm/
│   ├── kbs-invoicing/
│   ├── kbs-store/
│   ├── kbs-automations/
│   ├── kbs-appointments/
│   └── ...
├── shared/
│   ├── theme/                  # LCARS CSS/JS (self-contained)
│   └── templates/              # base.html, dashboard.html, marketplace.html
├── migrations/                 # Core schema migrations
├── scripts/
│   ├── seed_tenant.py          # Create tenant #1
│   ├── migrate.py              # Run migrations
│   └── create_plugin.py        # Scaffold new plugin
└── tests/
```

---

## 10. Docker Stack

```yaml
# docker-compose.yml
services:
  kytran-business-suite:
    build: .
    ports: ["8090:8090"]
    env_file: .env
    depends_on: [kbs-redis]
    # For hub-hosted: network connects to archie_database
    # For standalone: depends_on includes kbs-postgres

  kbs-redis:
    image: redis:7-alpine
    volumes: ["redis-data:/data"]

  kbs-worker:
    build: .
    command: python -m core.worker
    env_file: .env
    depends_on: [kbs-redis]

  # Optional — only for standalone deployment
  # kbs-postgres:
  #   image: postgres:16-alpine
  #   volumes: ["pg-data:/var/lib/postgresql/data"]
```

For tenant #1 (hub-hosted), the suite joins ARCHIE's Docker network and connects to `archie_database` directly.

---

## 11. Phasing

### Phase 1 — Foundation + Core Business Ops
**Deliverable:** Working suite at business.kytranempowerment.com with CRM + Invoicing + Store + Automations engine + Appointments. Tenant #1 (Kytran Empowerment) at Enterprise tier.

| Step | What | Source |
|------|------|--------|
| 1.1 | Scaffold repo, Docker stack, core layer | New |
| 1.2 | Auth (local + Google OAuth + SSO stub) | New + Google Work Suite code |
| 1.3 | CRM plugin — migrate, adapt to plugin structure | `platform_v2/tools/crm/` |
| 1.4 | Invoicing plugin — migrate, wire to CRM contacts | `platform_v2/tools/invoicing/` |
| 1.5 | Store plugin — migrate, wire orders to invoicing + CRM | `platform_v2/tools/store_builder/` |
| 1.6 | Automations engine — event bus consumers, workflow runner (no UI) | `platform_v2/tools/automations/` |
| 1.7 | Stripe billing — tier management, module activation, webhooks | Project #195 |
| 1.8 | Mail client — Stalwart + Google Workspace + generic SMTP | New + `tools/google_work_suite/` |
| 1.9 | Marketplace UI — module catalog, enable/disable, tier upsell | New |
| 1.10 | LCARS theme — self-contained, responsive | Extract from platform |
| 1.11 | Appointments plugin | New |
| 1.12 | Tenant #1 seed — Kytran Empowerment, Enterprise, Gmail connected | Config |

### Phase 2 — Marketing & Content
Content Studio, Social Media, Website Builder, Marketing Dashboard.

### Phase 3 — Communications & Services
Call Center, Help Desk, Automations UI (visual workflow builder), C.O.M.M.E.R.C.E. agent.

### Phase 4 — Finance, Legal & Industry
Contracts & Legal, Accounting (with QuickBooks/Xero integration), industry module framework, first vertical add-on.

### Migration Strategy (per module)

1. Copy routes/templates/static into plugin structure
2. Add manifest.json (events, dependencies, permissions)
3. Convert DB queries from global tables to tenant schema tables
4. Remove tenant_id column filtering (schema isolation handles it)
5. Replace direct Ollama calls with Bridge API (Enterprise only)
6. Replace ARCHIE-specific imports with suite core imports
7. Test in isolation with tenant #1
8. Replace ARCHIE module with redirect link to standalone

---

## 12. Node Architecture Considerations

The suite must support node-hosted deployment for data privacy. Design constraints for Phase 1:

- DB connection must be configurable via env vars (hub DB vs local DB)
- Bridge URL must be configurable (direct vs mesh vs empty)
- No hard dependencies on ARCHIE-specific infrastructure
- Docker Compose works both standalone and as part of a larger stack

Full node integration (OTA push, mesh sync, agent runner on nodes) is a separate brainstorm and spec after Phase 1 ships.

---

## 13. Design Constraints

- Follow standalone extraction playbook (`.claude/rules/standalone-extraction.md`)
- Register in Code Health scanner after Phase 1
- Compliance scanning via S.H.I.E.L.D. (Tier 2)
- LCARS theme is the brand differentiator — self-contained, no ARCHIE imports
- All Docker containers: read_only rootfs, resource limits, pinned image tags
- No secrets in code or env — Docker secrets or `.env` (never committed)
- Black formatting enforced
- Per-user data isolation via schema — no row-level tenant_id filtering
