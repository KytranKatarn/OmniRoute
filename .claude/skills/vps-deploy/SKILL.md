---
name: vps-deploy
description: Deploy changed files to any VPS node (outpost-us, future nodes) via scp + docker compose rebuild. Invoke after editing files in /mnt/standalone/ or /mnt/archie_brain/what-the-fact/ for VPS-deployed products. Also triggers on "deploy to VPS", "push to outpost", "update gov-watch on VPS".
---

# VPS Deploy — Multi-Node Deployment Skill

Handles scp + docker compose rebuild for all products running on VPS fleet nodes.
Designed for N nodes.

⚠️ **CORRECTED 2026-09-06 (verified live via SSH during PR #3224's deploy).** This file
previously listed gov-watch/civic-watch/legal-watch/market-watch/WTF as all living on
outpost-us. **All five migrated to Citadel/boston-2 in the 2026-06 window** and have been
there since — outpost-us was downsized to infra-only 2026-08-26 (`.claude/rules/
outpost-vps.md`, `.claude/rules/operational-state.md`'s product table). Confirmed live:
`ssh root@100.64.0.10 "docker ps --format '{{.Names}}'"` returns
`what-the-fact-wtf-{consumer,tech,ingest,ingest-api,postgres}-1` and the equivalent for the
other four products; the outpost-us product dir was emptied the same day (KB #296223).
**Always re-verify with `docker ps` before assuming a node** — this table drifted once
already and cost a mid-deploy detour.

---

## Node Registry

| Node | IP | SSH | SSH Key | Role |
|------|----|-----|---------|------|
| Citadel (boston-2) | 100.64.0.10 (mesh) / 2.25.133.122 (public) | `root@100.64.0.10` | `~/.ssh/id_ed25519` | **Gov/Civic/Legal/Market Watch, WTF (all 5, since 2026-06)** — DR warm-standby base |
| outpost-us | 76.13.107.109 / 100.64.0.2 (mesh) | `kytran@76.13.107.109` or `kytran@100.64.0.2` | `~/.ssh/id_ed25519` | Infra only since 2026-08-26 (Caddy front, SMTP relay, SOCKS egress) — NO product stacks |
| *(future nodes)* | TBD | `kytran@<ip>` | `~/.ssh/id_ed25519` | Add to registry as they join |

**Default node**: Citadel (`root@100.64.0.10`) for the 5 watch products; outpost-us only for
its own infra scripts. Prefer the mesh IP over the public IP for both.

---

## Product Registry (Citadel, `root@100.64.0.10`)

| Product | Source dir (local) | VPS dir | Compose service(s) | Container(s) |
|---------|-------------------|---------|-----------------|-----------|
| **gov-watch** | `/mnt/standalone/kytran-gov-watch/` | `/opt/archie-products/gov-watch/` | `kytran-gov-watch` | `kytran_gov_watch` |
| **civic-watch** | `/mnt/standalone/kytran-civic-watch/` | `/opt/archie-products/civic-watch/` | *(check compose)* | `kytran_watch_api` |
| **legal-watch** | `/mnt/standalone/kytran-legal-watch/` | `/opt/archie-products/legal-watch/` | *(check compose)* | `kytran_legal_api` |
| **market-watch** | `/mnt/standalone/kytran-market-watch/` | `/opt/archie-products/market-watch/` | *(check compose)* | `kytran_market_api` |
| **wtf** | `/mnt/archie_brain/what-the-fact/` (in-tree, NOT `/mnt/standalone/`) | `/opt/archie-products/what-the-fact/` | `wtf-consumer` / `wtf-tech` / `wtf-ingest` | `what-the-fact-wtf-{consumer,tech,ingest,ingest-api,postgres}-1` |

⚠️ **WTF's Postgres user is `wtfuser`, not `wtf`** (`docker exec what-the-fact-wtf-postgres-1
env \| grep POSTGRES` to re-check). WTF has **no `schema_migrations` tracking table** —
migrations are applied by hand: `cat migrations/NNN_*.sql \| ssh root@100.64.0.10 "docker exec -i
what-the-fact-wtf-postgres-1 psql -U wtfuser -d wtf"`, BEFORE rebuilding the containers that
query the new columns. If a migration adds a column the batch worker populates (e.g.
`cluster_metrics.py`), manually trigger that worker once after rebuild — the columns land
NULL/default until its next scheduled cycle otherwise, and a page reads as an honest-but-empty
state (not a bug) until then.

To look up an unknown container/service:
```bash
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 "docker ps --format '{{.Names}}' && ls /opt/archie-products/"
```

---

## Deployment Steps

### Step 1: Identify what changed

Confirm which product and which files were edited. If not told explicitly:
```bash
find /mnt/standalone/<product> -newer /mnt/standalone/<product>/app.py -name "*.py" -o -name "*.html" 2>/dev/null | head -20
```

### Step 2: Copy changed files to VPS

Use the node from the Product Registry above — **Citadel (`root@100.64.0.10`) for the 5 watch
products**, outpost-us only for its own infra scripts.

```bash
# Replace <product>, <vps-dir>, <relative-path>, <host> for each changed file
scp -i ~/.ssh/id_ed25519 \
    /mnt/standalone/<product>/<relative-path> \
    <host>:/opt/archie-products/<vps-dir>/<relative-path>
```

For multiple files, chain scp calls or use rsync (always `--exclude='.env'`):
```bash
# rsync entire product dir (use when many files changed)
rsync -avz --exclude='.env' -e "ssh -i ~/.ssh/id_ed25519" \
    /mnt/standalone/<product>/ \
    <host>:/opt/archie-products/<vps-dir>/
```

### Step 3: Rebuild container

**ALWAYS use `--build` for code changes** — VPS containers use `COPY .` in Dockerfile, not bind mounts. A restart alone will NOT pick up new code.

⚠️ **Apply any new migration to the DB BEFORE this step** if the change adds columns the
running code will query on startup or first request — see the WTF migration note above.

```bash
ssh -i ~/.ssh/id_ed25519 <host> \
    "cd /opt/archie-products/<vps-dir> && docker compose up -d --build --no-deps <compose-service>"
```
(Multi-service products like WTF: list all affected services in one `--build` call, e.g.
`docker compose up -d --build wtf-consumer wtf-tech wtf-ingest` — can take several minutes,
run in background and wait for the notification rather than a foreground 120s timeout.)

**Hot-patch exception** (template/static only, no Python changes):
```bash
# Faster — docker cp + restart (skips full rebuild)
scp -i ~/.ssh/id_ed25519 local-file.html <host>:/opt/archie-products/<vps-dir>/templates/
ssh -i ~/.ssh/id_ed25519 <host> "docker restart <container-name>"
```

### Step 4: Verify container started

```bash
ssh -i ~/.ssh/id_ed25519 <host> \
    "docker logs <container-name> --tail 10 2>&1 | grep -iE 'listening|started|error|traceback'"
```

Expected: `Listening at: http://0.0.0.0:<port>` — the read-only gunicorn socket error is pre-existing (hardened container), ignore it.

### Step 5: Smoke test

Hardened containers often have no `curl` binary inside — test from the HOST, not `docker exec`:
```bash
# From the VPS host (direct port test — bypasses Caddy)
ssh -i ~/.ssh/id_ed25519 <host> \
    "curl -sI http://localhost:<port>/ | head -3"
```

Expected: `HTTP/1.1 200 OK` or `302 FOUND`.

---

## Common Mistakes — DO NOT

- **`docker compose restart <service>`** alone — does NOT pick up code changes. Must use `--build`.
- **`docker compose up -d` without `--no-deps`** — may restart DB container too.
- **Forgetting `--no-deps`** — rebuilds the whole stack including DB. Use `--no-deps` to target only the app.
- **Caddy 404 ≠ app broken** — test via `localhost:<port>` on VPS, not via public domain.

---

## Adding a New Node

When a new outpost/starship joins the cluster:

1. Test SSH: `ssh -i ~/.ssh/id_ed25519 kytran@<new-ip> "echo connected"`
2. If key rejected: add `~/.ssh/id_ed25519.pub` to the node's `~/.ssh/authorized_keys`
3. Add the node to the Node Registry table above
4. Add its products to the Product Registry
5. Update `reference_vps-outpost-us.md` memory file with the new node

---

## Network Note

All VPS containers must join `archie-outpost_archie_net` for Caddy reachability.
Caddy upstream: `reverse_proxy 172.18.0.1:<port>`
If container rebuilt and gets 502: do `docker compose down && docker compose up -d` to refresh iptables NAT (KB #261670).
