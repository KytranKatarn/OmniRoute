---
name: vps-deploy
description: Deploy changed files to any VPS node (outpost-us, future nodes) via scp + docker compose rebuild. Invoke after editing files in /mnt/standalone/ or /mnt/archie_brain/what-the-fact/ for VPS-deployed products. Also triggers on "deploy to VPS", "push to outpost", "update gov-watch on VPS".
---

# VPS Deploy — Multi-Node Deployment Skill

Handles scp + docker compose rebuild for all products running on VPS fleet nodes.
Currently: outpost-us (76.13.107.109). Designed for N nodes.

---

## Node Registry

| Node | IP | SSH | SSH Key | Role |
|------|----|-----|---------|------|
| outpost-us | 76.13.107.109 | `kytran@76.13.107.109` | `~/.ssh/id_ed25519` | Primary outpost — Gov/Civic/Legal/Market Watch, WTF |
| *(future nodes)* | TBD | `kytran@<ip>` | `~/.ssh/id_ed25519` | Add to registry as they join |

**Default node**: outpost-us unless args specify otherwise.

---

## Product Registry (outpost-us)

| Product | Source dir (local) | VPS dir | Compose service | Container |
|---------|-------------------|---------|-----------------|-----------|
| **gov-watch** | `/mnt/standalone/kytran-gov-watch/` | `/opt/archie-products/gov-watch/` | `kytran-gov-watch` | `kytran_gov_watch` |
| **civic-watch** | `/mnt/standalone/kytran-civic-watch/` | `/opt/archie-products/civic-watch/` | *(check compose)* | *(check compose)* |
| **legal-watch** | `/mnt/standalone/kytran-legal-watch/` | `/opt/archie-products/legal-watch/` | *(check compose)* | *(check compose)* |
| **market-watch** | `/mnt/standalone/kytran-market-watch/` | `/opt/archie-products/market-watch/` | *(check compose)* | *(check compose)* |
| **wtf** | `/mnt/archie_brain/what-the-fact/` | `/opt/archie-products/what-the-fact/` | `wtf-consumer` / `wtf-tech` / `wtf-ingest` | *(check)* |

To look up an unknown container/service:
```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker ps --format '{{.Names}}' && ls /opt/archie-products/"
```

---

## Deployment Steps

### Step 1: Identify what changed

Confirm which product and which files were edited. If not told explicitly:
```bash
find /mnt/standalone/<product> -newer /mnt/standalone/<product>/app.py -name "*.py" -o -name "*.html" 2>/dev/null | head -20
```

### Step 2: Copy changed files to VPS

```bash
# Replace <product>, <vps-dir>, <relative-path> for each changed file
scp -i ~/.ssh/id_ed25519 \
    /mnt/standalone/<product>/<relative-path> \
    kytran@76.13.107.109:/opt/archie-products/<vps-dir>/<relative-path>
```

For multiple files, chain scp calls or use rsync:
```bash
# rsync entire product dir (use when many files changed)
rsync -avz -e "ssh -i ~/.ssh/id_ed25519" \
    /mnt/standalone/<product>/ \
    kytran@76.13.107.109:/opt/archie-products/<vps-dir>/
```

### Step 3: Rebuild container

**ALWAYS use `--build` for code changes** — VPS containers use `COPY .` in Dockerfile, not bind mounts. A restart alone will NOT pick up new code.

```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "cd /opt/archie-products/<vps-dir> && docker compose up -d --build --no-deps <compose-service>"
```

**Hot-patch exception** (template/static only, no Python changes):
```bash
# Faster — docker cp + restart (skips full rebuild)
scp -i ~/.ssh/id_ed25519 local-file.html kytran@76.13.107.109:/opt/archie-products/<vps-dir>/templates/
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker restart <container-name>"
```

### Step 4: Verify container started

```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "docker logs <container-name> --tail 10 2>&1 | grep -iE 'listening|started|error|traceback'"
```

Expected: `Listening at: http://0.0.0.0:<port>` — the read-only gunicorn socket error is pre-existing (hardened container), ignore it.

### Step 5: Smoke test

```bash
# From VPS (direct port test — bypasses Caddy/NPM)
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
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
