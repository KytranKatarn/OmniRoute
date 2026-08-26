# Outpost VPS Rules (Global Fleet)

All VPS fleet nodes follow this pattern. Hard-won from outpost-us setup.
**Authoritative alongside `fleet.md` — both apply.**

---

## Global Outpost Map

Names below are the 2026-06-04 canonical set (display `node_name` / mesh `given_name`). Full roster + ship-class + audit: `fleet.md` + KB #270521.

| Display name | mesh given_name | Public IP | Mesh IP | Region | DB ID | Status |
|------|------|-----------|---------|--------|-------|--------|
| Outpost - United States | outpost-us | 76.13.107.109 | 100.64.0.2 | us-east (Ashburn VA) | 93 | Online (CPU outpost; SSH `kytran@`) |
| Outpost - Singapore | outpost-singapore | 156.67.217.86 | 100.64.0.5 | asia-east (Singapore) | 125 | Online |
| Outpost - Lithuania | outpost-lithuania | 72.62.112.210 | 100.64.0.7 | eu-west (Vilnius, LT) | 126 | Online |
| Outpost - United Kingdom | outpost-uk | 2.24.130.153 | 100.64.0.8 | eu-west (Manchester, UK) | 127 | Online |
| Citadel - United States | citadel-us | 2.25.133.122 | 100.64.0.10 | us-east (Boston) | 128 | Online — **DR warm-standby base** (boston-2): watch products + DR replica. SSH `root@` |
| Beacon | beacon | 2.25.170.252 | 100.64.0.11 | us-east (Boston) | 129 | Online — **front-door ingress** (Caddy; no Ollama/agents) |

**Update this table when each node enrolls (mesh IP + DB ID).** Renames are display-only (`node_name` + headscale `given_name`); `node_id` is unchanged.

---

## Outpost Hardware Baseline (outpost-us)

| Item | Value |
|------|-------|
| CPU | AMD EPYC 9354P |
| RAM | 7.8 GB |
| GPU | None — CPU inference only |
| OS | Ubuntu 22.04.5 LTS |
| SSH user | `kytran` (passwordless sudo — **NOT limited to docker**, see note) |
| Root login | Disabled |
| Auth | SSH key `~/.ssh/id_ed25519` |

---

> ⚠️ **`kytran`'s passwordless sudo is BROADER than docker** (measured 2026-08-26). This table said
> "passwordless sudo for docker" until then; in fact `sudo -n true` succeeds and `sudo rm -rf` works.
> It came up decommissioning the stale product tree: `static/img/*` logo files are **root-owned**, so
> a plain `rm -rf` as `kytran` **partially failed** — 5 of 8 dirs removed, 3 refused. Read the `rm`
> output; the command's exit status alone reads as success.
>
> **Product deployments were REMOVED from outpost-us on 2026-08-26** (`/opt/archie-products`
> 98 MB → 4 K). The node is now genuinely infra-only, matching `operational-state.md`. Before
> deleting any VPS product dir, run `git status` in it first — four of the eight were git checkouts
> with dirty trees holding files that existed in no commit (KB #296223).

## Outpost Tier Capabilities

| Capability | Value |
|------------|-------|
| Inference | CPU only — max model 4 GB |
| Models | `qwen2.5:1.5b`, `llama3.2:3b`, `nomic-embed-text` |
| Docker | Full compose stack |
| GPU | None |
| Role | Regional egress, CPU agents, product hosting |

**Max model size 4 GB** — never load 7B on outpost, it swaps to disk and kills latency.

---

## Enrollment Flow (T2930 — use the Fleet tab)

The **correct path** for a new outpost is the Add Node modal in Fleet tab (fixed T2930):

1. Go to `http://192.168.1.200:3000/tools/department-hq` → Fleet tab → **Add Node**
2. Fill in: Node Name (`outpost-asia`), Mesh IP (optional, auto-discovered), Deployment Mode = **Outpost**
3. Click **Generate Setup Command** → copy the one-liner
4. SSH into new VPS, paste the one-liner
5. The generated script: installs Docker, joins Headscale, auto-discovers mesh IP,
   POSTs it back to hub, writes `/opt/archie-node/.env`, starts the agent stack

**Do NOT use raw docker commands to bootstrap — use the generated script.**
The generated script handles Headscale pre-auth key generation, mesh registration,
and env wiring in one pass.

---

## Pre-Enrollment Checklist (before pasting the setup script)

```bash
# 1. SSH into new VPS:
ssh -i ~/.ssh/id_ed25519 kytran@<PUBLIC_IP>

# 2. Confirm Ubuntu 22.04:
lsb_release -a

# 3. Open required ports in Hostinger panel + UFW:
#    22 (SSH), 80 (HTTP/Caddy), 443 (HTTPS/Caddy), 11434 (Ollama — mesh-only)
sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443
sudo ufw allow from 172.0.0.0/8 to any port 11434   # Docker bridge → Ollama (KB #265604)
sudo ufw allow from 100.64.0.0/10 to any port 11434  # Headscale mesh peers → Ollama
sudo ufw enable

# 4. Create product dir:
sudo mkdir -p /opt/archie-products
sudo chown kytran:kytran /opt/archie-products
```

---

## BRIDGE_URL Invariant

Every `.env` on every outpost:
```
BRIDGE_URL=http://100.64.0.4:3000
```

**Never**:
- `https://platform.kytranempowerment.com` — CDN 60s timeout, bypasses queue
- `http://192.168.1.200:3000` — hub LAN IP, unreachable from VPS
- `http://localhost:3000` — loopback, wrong

---

## Product Deploy Pattern (image-baked, no git on VPS)

```bash
# Sync from hub (NEVER overwrite .env):
rsync -avz --exclude='.env' --exclude='__pycache__' \
  -e "ssh -i ~/.ssh/id_ed25519" \
  /mnt/standalone/<product>/ \
  kytran@<PUBLIC_IP>:/opt/archie-products/<product>/

# Rebuild — NEVER use restart for code changes (Dockerfile is COPY .):
ssh -i ~/.ssh/id_ed25519 kytran@<PUBLIC_IP> \
  "cd /opt/archie-products/<product> && docker compose up -d --build"
```

Use `/vps-deploy <product>` skill for guided flow.

---

## Caddy Pattern (auto Let's Encrypt)

Caddy handles all SSL automatically. Runs on 80/443.
Caddyfile at `/opt/archie-outpost/Caddyfile`:

```
<subdomain>.kytranempowerment.com {
    reverse_proxy localhost:<PORT>
}
```

- Products route to LOCAL containers — only `api.kytranempowerment.com` proxies to hub
- Caddy provisions Let's Encrypt certs on first request
- Install: `sudo apt install caddy` (add Caddy apt repo first)

---

## Container Network Rule (MANDATORY — KB #261670)

Every product container must join the shared Caddy-reachable network:
```yaml
networks:
  default:
  archie_net:
    external: true
    name: archie-outpost_archie_net   # prefix matches outpost name
```

Create the network before first `compose up`:
```bash
docker network create archie-outpost_archie_net
```

Without this Caddy cannot reach the container → 502.

---

## Fleet Registration (after enrollment, feeds the ARMADA world map)

```sql
UPDATE remote_nodes SET
  extra_capabilities = extra_capabilities || '{
    "region": "us-east",
    "geo_lat": 38.89,
    "geo_lon": -77.47,
    "location_city": "Ashburn",
    "location_country": "United States",
    "provider": "Hostinger KVM2"
  }'::jsonb
WHERE node_name = 'outpost-us';
```

Region codes: `us-east`, `eu-west`, `asia-east`, `local` (LAN Starships)

**Hostinger DC geo coordinates:**

| DC | City | Lat | Lon |
|----|------|-----|-----|
| US East | Ashburn, VA | 38.89 | -77.47 |
| EU | Amsterdam / Vilnius | 52.37 / 54.69 | 4.90 / 25.28 |
| Asia | Singapore | 1.35 | 103.82 |

---

## Known Gotchas (outpost-us learnings)

| Problem | Fix |
|---------|-----|
| VPS path wrong: `kytran-<product>/` | Correct path is always `<product>/` — verify with `docker inspect` |
| `docker cp` fails (read_only containers) | rsync + `docker compose up -d --build` always |
| BRIDGE_URL wrong | Must be `http://100.64.0.4:3000` — mesh IP only |
| UFW blocks Docker → agent port | `ufw allow from 172.0.0.0/8 to any port 11434` |
| Tailscale drops mesh IP after reboot | Use reusable pre-auth key; add `--accept-routes` flag |
| 502 after container rebuild | `docker compose down && docker compose up -d` — flushes iptables NAT |
| DNS propagation delay | Test with `dig <subdomain>` before blaming Caddy cert errors |
| Containers can't reach external hostnames | Add `dns: [192.168.1.200, 1.1.1.1]` to each service in compose (KB standalone-extraction.md #10) |
| .env overwritten on rsync | Always `--exclude='.env'` — VPS .env is gitignored and has secrets |
| Headscale pre-auth key expired | Generate new: `docker exec archie_headscale headscale preauthkeys create --user archie-fleet --expiration 24h --reusable` |

---

## SSH Key Distribution

Hub's public key must be in `authorized_keys` on every outpost:
```bash
# From hub — add to new VPS (requires initial password auth once):
ssh-copy-id -i ~/.ssh/id_ed25519 kytran@<NEW_VPS_IP>
# Or paste ~/.ssh/id_ed25519.pub into Hostinger panel during provisioning
```

---

## Models Allowed on Outpost

CPU-only, 4 GB RAM ceiling:
- `qwen2.5:1.5b` — primary agent model
- `llama3.2:3b` — secondary / fallback
- `nomic-embed-text` — embeddings

Never assign to outpost:
- `qwen2.5:7b` — requires 6+ GB, swaps badly on 8 GB VPS
- `mistral:7b` / `gemma3:12b` / `dolphin3:latest` — hub/Starship only
