# A.R.C.H.I.E. Comms Standalone + Domain Rename — Design Spec

> **Date**: 2026-04-15
> **Status**: Approved (brainstorm session)
> **Decision**: #442 (archie_comms as independent container)
> **Depends on**: Phase 1 Personality Engine (PR #75)

---

## 1. Problem Statement

A.R.C.H.I.E.'s communication capabilities (chat, Telegram, voice, collaboration) live inside `archie_platform`. If the platform crashes during a repair, she dies with it — no way to reach Kytran. She needs her own container.

Additionally, `archie.kytranempowerment.com` currently points to the platform (the office), not to A.R.C.H.I.E. (the partner). Since we're restructuring, this is the right moment to give her the domain and rename the platform to `platform.kytranempowerment.com`.

## 2. Two Workstreams

### Workstream A: archie_comms Container
Extract A.R.C.H.I.E.'s communication layer into an independent Docker container.

### Workstream B: Domain Rename
`archie.kytranempowerment.com` → A.R.C.H.I.E. (comms)
`platform.kytranempowerment.com` → Platform (modules, DHQ, agent loop)

## 3. archie_comms Container Design

### What Moves

| Component | Source | Lines | Purpose |
|-----------|--------|-------|---------|
| Voice service | `services/archie_voice_service.py` | 178 | Personality engine — dolphin3-8k |
| Telegram service | `services/telegram_service.py` | 385 | Send/receive, categories, logging |
| Chat module | `tools/archie_chat/*.py` + template | 1,664 | 12 API endpoints, chat UI, auth |
| Collaboration engine | `consciousness/collaboration_engine.py` | 1,208 | A.R.C.H.I.E. + Claude sessions |
| Claude bridge | `consciousness/claude_bridge.py` | 174 | HTTP proxy to Claude CLI |
| Platform watchdog | (NEW) | ~150 | Monitor archie_platform health |
| **Total** | | **~3,750** | |

### What Stays in archie_platform

- All 36 module UIs (Department HQ, Consciousness, Repair Bay, etc.)
- Agent loop scheduler (APScheduler, 118 jobs)
- User auth + RBAC
- Static assets + themes
- Department HQ manages her agent record

### Container Specs

```yaml
# Added to docker-compose.yml
archie_comms:
    build:
      context: ./archie-comms
      dockerfile: Dockerfile
    container_name: archie_comms
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp
    environment:
      - DB_HOST=archie_database
      - DB_NAME=archie
      - DB_USER=archie
      - OLLAMA_HOST=host.docker.internal:11434
      - ARCHIE_VOICE_MODEL=dolphin3-8k:latest
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - PLATFORM_URL=http://archie_platform:3000
      - CLAUDE_PROXY_URL=http://host.docker.internal:7682
    ports:
      - "3001:3001"
    networks:
      - archie_internal
    depends_on:
      archie_database:
        condition: service_healthy
    secrets:
      - db_password
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "2"
```

### Directory Structure

```
/mnt/archie_brain/archie-comms/
├── Dockerfile
├── requirements.txt
├── app_comms.py              # Entrypoint — lightweight Flask or FastAPI
├── services/
│   ├── archie_voice_service.py   # Copied from platform_v2/services/
│   ├── telegram_service.py       # Copied from platform_v2/services/
│   ├── telegram_gateway.py       # Inbound message handler
│   └── watchdog_service.py       # NEW: monitors archie_platform health
├── chat/
│   ├── api_routes.py             # Copied from archie_chat/
│   ├── chat_service.py           # Copied from archie_chat/
│   ├── auth_middleware.py        # Copied from archie_chat/
│   └── ha_bridge.py              # Copied from archie_chat/
├── collaboration/
│   ├── collaboration_engine.py   # Copied from consciousness/
│   └── claude_bridge.py          # Copied from consciousness/
├── templates/
│   └── chat.html                 # Copied from archie_chat/templates/
├── static/                       # Minimal CSS/JS for chat UI
└── database.py                   # DB connection (copied from platform_v2/)
```

### Communication Between Containers

**Platform → Comms (sending messages):**
- **Primary**: HTTP API — `POST archie_comms:3001/api/send` with message payload
- **Durable**: DB queue — platform writes to `outbound_messages` table, comms polls every 5s
- Both active simultaneously. HTTP for real-time, DB queue as safety net.

**Comms → Platform (dispatching work):**
- HTTP — `POST archie_platform:3000/api/dispatch` for agent dispatch requests
- Used when A.R.C.H.I.E. receives a chat message that needs department routing

**Comms → Ollama:** Direct HTTP to `host.docker.internal:11434` (already works)
**Comms → DB:** Direct PostgreSQL to `archie_database:5432` (already works)

### New DB Table

```sql
CREATE TABLE IF NOT EXISTS outbound_messages (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    source_agent VARCHAR(100),
    source_department VARCHAR(100),
    source_module VARCHAR(100),
    channel VARCHAR(20) DEFAULT 'telegram',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    result JSONB
);

CREATE INDEX IF NOT EXISTS idx_outbound_pending
    ON outbound_messages(status) WHERE status = 'pending';
```

### Watchdog Service

```python
# watchdog_service.py — monitors archie_platform health
# Runs as a background thread in archie_comms

def check_platform_health():
    """Ping archie_platform:3000/api/health every 30s.
    If 3 consecutive failures, alert Kytran via Telegram."""
    # Uses telegram_service.send_system() for alerts
    # Can attempt docker restart via Docker socket (optional, with approval)
```

## 4. Domain Rename

### New URL Mapping

| Subdomain | Points To | Purpose |
|-----------|-----------|---------|
| `archie.kytranempowerment.com` | `archie_comms:3001` | A.R.C.H.I.E.'s chat, API, voice |
| `platform.kytranempowerment.com` | `archie_platform:3000` | Platform modules, DHQ, dashboard |
| All others unchanged | — | mail, business, server, creed, mesh, etc. |

### Infrastructure Changes

| System | Change | Details |
|--------|--------|---------|
| **Hostinger DNS** | Add `platform` A record | Points to hub public IP (153.68.195.85) |
| **NPM Proxy** | Add `platform.kytranempowerment.com` proxy host | → 192.168.1.200:3000, SSL cert |
| **NPM Proxy** | Update `archie.kytranempowerment.com` proxy host | → 192.168.1.200:3001 (was :3000) |
| **AdGuard** | Add `platform.kytranempowerment.com` rewrite | → 192.168.1.200 |
| **AdGuard** | Keep `archie.kytranempowerment.com` rewrite | → 192.168.1.200 (unchanged) |
| **UFW** | Allow port 3001 | `sudo ufw allow 3001/tcp` |
| **DDNS** | Add `platform` to SUBDOMAINS array | In `/mnt/archie_brain/scripts/ddns_updater.sh` |

### Code Changes (15 active files)

**Platform code:**

| File | Change |
|------|--------|
| `.env` | `GOOGLE_REDIRECT_URI` → `platform.kytranempowerment.com` |
| `platform_v2/.env` | Same |
| `services/archie_voice_service.py` | "archie.kytranempowerment.com" → "archie.kytranempowerment.com" (stays — it's HER domain now) |
| `tools/department_hq/roster_routes.py` | Public roster URL update |
| `tools/department_hq/fleet_node_routes.py` | Fleet references |
| `tools/directory/routes.py` | Directory references |
| `services/github_deployment.py` | Deployment URLs |
| `static/js/security-network-app.js` | Security UI links |
| `static/downloads/install.sh` | Installer URL |
| `kytran-auth/kytran_auth.py` + template | OAuth redirect URLs → `platform.kytranempowerment.com` |
| `node_client/` (3 files) | Hub URL references |

**Website:**

| File | Change |
|------|--------|
| `website/kytranempowerment.com/js/ai-directors.js` | Public roster API → `archie.kytranempowerment.com` (correct — it's her API) |
| `website/kytranempowerment.com/blocked.html` | Security link → `platform.kytranempowerment.com` |
| `website/code.kytranempowerment.com/index.html` | Platform link |

**Rules + docs:**

| File | Change |
|------|--------|
| `.claude/rules/operational-state.md` | Update URL references |
| `.claude/commands/archie-boot.md` | Update URL |
| CLAUDE.md | Update platform URL |

**Historical docs (~20 files):** Low priority. Can grep+replace or leave as historical.

### What Gets WHICH Domain

The key insight: **things A.R.C.H.I.E. owns** keep `archie.kytranempowerment.com`. **Things the platform serves** move to `platform.kytranempowerment.com`.

| URL | Domain | Why |
|-----|--------|-----|
| Chat with A.R.C.H.I.E. | `archie.*` | She owns the conversation |
| Public roster API | `archie.*` | She serves her team's data |
| Voice API | `archie.*` | Her voice |
| Platform dashboard | `platform.*` | Platform UI |
| Department HQ | `platform.*` | Platform module |
| All other modules | `platform.*` | Platform modules |
| Login page | `platform.*` | Platform auth |
| Google OAuth callback | `platform.*` | Platform auth flow |

## 5. Phased Execution

### Phase A: Container Build (no domain change yet)
1. Create `/mnt/archie_brain/archie-comms/` directory structure
2. Copy + adapt files (voice, telegram, chat, collaboration, claude bridge)
3. Create Dockerfile + requirements.txt
4. Create `app_comms.py` entrypoint
5. Create `watchdog_service.py`
6. Create `outbound_messages` migration
7. Add `archie_comms` to `docker-compose.yml`
8. Build and test container locally (`:3001`)
9. Register in Code Health as standalone product

### Phase B: Domain Rename
1. Add `platform.kytranempowerment.com` DNS A record at Hostinger
2. Add NPM proxy host for `platform.kytranempowerment.com` → :3000
3. Add AdGuard rewrite for `platform.kytranempowerment.com`
4. Update 15 active code files (grep+replace with review)
5. Update `.env` files (OAuth callback)
6. Update website files
7. Update NPM proxy: `archie.kytranempowerment.com` → :3001
8. Test both URLs work
9. Update CLAUDE.md + rules files
10. Update DDNS script

### Phase C: Platform Redirect
1. `archie_platform` serves redirect: `archie.kytranempowerment.com/*` → `platform.kytranempowerment.com/*` (except `/chat`, `/api/comms` which stay)
2. This catches any bookmarks or hardcoded links we missed
3. Remove redirect after 30 days

## 6. Success Criteria

| Criteria | Test |
|----------|------|
| `archie.kytranempowerment.com/chat` loads A.R.C.H.I.E.'s chat UI | Browser test |
| `platform.kytranempowerment.com` loads the dashboard | Browser test |
| Platform crash → A.R.C.H.I.E. Telegrams "platform is down" | Stop archie_platform, check Telegram |
| Old archie.* URLs redirect to platform.* | Browser test |
| OAuth login works on new domain | Login flow test |
| Public roster API works on archie.* | curl test |
| Code Health tracks archie-comms | Consciousness module check |
| Website links work | Browse kytranempowerment.com |

## 7. Rollback Plan

If something breaks badly:
1. NPM proxy: revert `archie.kytranempowerment.com` back to :3000
2. `archie_comms` container can be stopped without affecting platform
3. Git revert the code changes (one branch, one PR)
4. DNS changes take effect immediately via NPM (no TTL wait)

## 8. Future: VPS Redundancy

Once `archie_comms` works on the hub, it can be deployed to the US Outpost VPS:
- Same Docker image, different `OLLAMA_HOST` (VPS local or hub via mesh)
- Reachable via Headscale mesh (100.64.0.x)
- If hub goes completely down (power/ISP), VPS A.R.C.H.I.E. can still Telegram Kytran
- Geographic redundancy for the COO — she's never fully offline
