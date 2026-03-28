# Unified Kytran Auth — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** 4 phases — device registration (now), Kytran accounts, Stripe billing, cross-product wiring

---

## Decisions Made

| Decision | Choice |
|----------|--------|
| Auth scope | CLI + nodes + all standalone products |
| Auth method | Device registration + API key with admin approval |
| Approval location | Department HQ (Starbase being retired) |
| Account system | Unified Kytran Account across all products |
| Subscription | Stripe-backed tiers (Free/Pro/Team/Enterprise) |
| SSO | OAuth2 "Sign in with Kytran" for standalone products |
| CLI auth | Browser-based OAuth flow (like claude auth) |

---

## Phase 1: Device Registration + API Keys

### DB table: registered_devices

```sql
CREATE TABLE registered_devices (
    id SERIAL PRIMARY KEY,
    device_name VARCHAR(100) NOT NULL,
    device_type VARCHAR(20) NOT NULL,
    hostname VARCHAR(200),
    hardware_info JSONB DEFAULT '{}',
    purpose TEXT DEFAULT '',
    api_key_hash VARCHAR(200),
    status VARCHAR(20) DEFAULT 'pending',
    user_id INTEGER REFERENCES users(id),
    registered_at TIMESTAMP DEFAULT NOW(),
    approved_at TIMESTAMP,
    approved_by INTEGER REFERENCES users(id),
    last_seen TIMESTAMP,
    request_count INTEGER DEFAULT 0,
    CONSTRAINT chk_device_type CHECK (device_type IN ('cli', 'node', 'kso', 'kbs', 'standalone')),
    CONSTRAINT chk_device_status CHECK (status IN ('pending', 'approved', 'denied', 'revoked'))
);
```

### API key format
`archie_` + 32 random hex chars = 38 chars total. Stored as bcrypt hash.

### Endpoints

```
POST /api/auth/register     → register new device (returns pending status)
POST /api/auth/approve/{id} → admin approves, generates + returns API key (one-time)
POST /api/auth/deny/{id}    → admin denies registration
POST /api/auth/revoke/{id}  → revoke an approved device
GET  /api/auth/devices      → list all registered devices (admin)
POST /api/auth/validate     → validate an API key (for standalone products to check)
```

### Auth middleware
Every /api/* request checks Authorization header. Public endpoints (/creed, /api/auth/register) are exempt.

### Department HQ integration
Operations tab gets a "Devices" section showing pending/approved/revoked devices with approve/deny/revoke buttons.

### CLI integration
`archie auth register` → sends device info → gets back "pending, await approval"
`archie auth status` → checks if approved, retrieves key
Stores key in `~/.archie/credentials`

---

## Phase 2: Kytran Account + OAuth2 (future)

- Account Center users table enhanced with roles, subscription_tier
- OAuth2 provider (/auth/authorize, /auth/token, /auth/callback)
- "Sign in with Kytran" button for KSO, KBS, future products
- registered_devices linked to user_id
- CLI does browser OAuth flow: archie auth login → opens browser → approves → CLI gets key

---

## Phase 3: Stripe Integration (future)

- Auto-create Stripe customer on signup
- Subscription tiers: Free ($0), Pro ($29), Team ($99), Enterprise (custom)
- Feature gating: skills, dispatch limits, node count, A/B testing
- Billing portal in Account Center
- CLI checks tier before executing gated skills

---

## Phase 4: Cross-Product Wiring (future)

- Business Suite CRM accounts = Kytran accounts
- KSO admin auth = Kytran admin accounts
- Node registration linked to team subscriptions
- Shared session/token across all products on *.kytranempowerment.com

---

## Starbase Retirement (follow-up)

Absorb remaining Starbase functionality:
- Node connect/disconnect → System Operations or Department HQ Operations
- Model distribution → Agent Academy Models tab
- Mesh sync → System Operations
- Deprecate Starbase module
