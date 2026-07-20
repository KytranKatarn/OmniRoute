# A.R.C.H.I.E. Comms

Independent communication layer for the A.R.C.H.I.E. platform. Runs as the
`archie_comms` container on **:3002**, served at `archie.kytranempowerment.com`.

It is deliberately a **separate process from `archie_platform`** — if the platform is
down, this is the surface that can still reach you and still tell you the platform is
down. The watchdog below only means something because it does not share a process with
the thing it watches.

## What it does

| Capability | Detail |
|---|---|
| **Chat UI + API** | Conversation CRUD, history, attachments, escalation (`/api/chat/*`) |
| **Telegram bridge** | Send/receive in A.R.C.H.I.E.'s voice — the single outbound voice, no agent DMs the owner directly |
| **Platform watchdog** | Polls `${PLATFORM_URL}/api/health` and alerts when the platform stops answering (`services/watchdog_service.py`) |
| **Outbound queue** | Processes queued messages so a transient outage delays delivery instead of dropping it |
| **Approvals** | Serves the pending queue and the approve/deny verbs (`/api/approvals/*`) — the human gate for Tier-2 actions |
| **Unified alerts** | `/api/alerts/unified` with read/mark-all-read |
| **Collaboration engine** | Claude bridge (`collaboration/`) |

## Running it

This product has **no `docker-compose.yml` of its own** — that is intentional. It is a
service of the root stack, built from the repo root:

```yaml
# /mnt/archie_brain/docker-compose.yml
archie_comms:
  build:
    context: ./archie-comms
    dockerfile: Dockerfile
  container_name: archie_comms
  ports: ["3002:3002"]
```

```bash
cd /mnt/archie_brain
docker compose up -d --build archie_comms      # code changes need --build
docker compose restart archie_comms            # config/env only
docker logs -f archie_comms
```

A private compose file here would duplicate and conflict with the root definition.

## Health

```
GET /api/health        -> app_comms.py:261
```

Used by the platform's own monitoring. Keep it dependency-free and cheap: it must be
able to answer while the rest of the system is unhealthy, which is the entire point of
running this service separately.

## Layout

```
app_comms.py        Flask entrypoint, health, HMAC-verified internal routes
chat/               chat UI + conversation API
collaboration/      Claude bridge
services/           watchdog, outbound queue, Telegram
templates/ static/  self-contained UI assets
migrations/         schema for this service
tests/
```

## Stack

Flask 3.1 · flask-login · psycopg2 · `python-telegram-bot` 21 · websocket-client
(`requirements.txt`)

## Conventions that apply here

- **All LLM inference goes through the DHQ dispatcher** (ADR-013) — never call Ollama
  directly from this service.
- **Mesh IPs, never public hostnames**, for anything cluster-internal: the Hostinger
  CDN caps at 60s and hides traffic from `task_execution_log`.
- **A.R.C.H.I.E. is the single outbound voice.** Individual agents do not message the
  owner; they route through here.
