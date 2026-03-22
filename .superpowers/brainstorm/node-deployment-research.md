# Remote Node Deployment Patterns — Research Synthesis

**Date**: 2026-03-21 | **Goal**: Find the best pattern for ARCHIE single-command node deployment

---

## Platform Comparison Matrix

| Platform | Install Command Pattern | Auth Model | Networking | Updates | Complexity |
|----------|----------------------|------------|------------|---------|------------|
| **K3s** | `curl \| K3S_URL=... K3S_TOKEN=... sh -` | Pre-shared token (file on server) | Direct IP, port 6443 | Re-run install script | **Simplest** |
| **Tailscale** | `curl \| sh` then `tailscale up --auth-key=tskey-xxx` | Auth key (one-off or reusable) | WireGuard VPN mesh | Auto-update daemon | Simple |
| **Coolify** | Hub SSHes into node (no agent install) | SSH key (ED25519) | SSH multiplexing | Hub pushes via SSH | Medium |
| **Portainer** | `docker run portainer/agent` | AGENT_SECRET env var | Port 9001 (agent) or outbound-only (Edge) | Pull new image | Medium |
| **CapRover** | Hub SSHes into node, runs `docker swarm join --token` | Docker Swarm token + SSH key | Docker Swarm overlay | Swarm service updates | Medium |
| **Dokku** | `git push dokku main` | SSH key for git push | SSH | Git push triggers rebuild | N/A (app deploy, not node) |

---

## Detailed Analysis

### 1. K3s — The Gold Standard for "Single Command Join"

**Install/Join command:**
```bash
# On new node:
curl -sfL https://get.k3s.io | K3S_URL=https://hub-ip:6443 K3S_TOKEN=mynodetoken sh -
```

**How it works:**
- Same script for server and agent — behavior determined by presence of `K3S_URL`
- Token is a pre-shared secret stored at `/var/lib/rancher/k3s/server/node-token` on server
- Script auto-detects OS, installs binary, creates systemd service, joins cluster
- Auto-restarts on crash or reboot

**Auth:** Pre-shared token. No interactive login. Token generated once on server, reused for all nodes.

**Updates:** Re-run the install script with `INSTALL_K3S_CHANNEL=latest` or use system-upgrade-controller.

**Networking:** Direct IP:port. Nodes must reach server on port 6443.

**Why it's great:** One line. No prerequisites. Handles everything. Idempotent.

---

### 2. Tailscale — Best "Join a Network" Pattern

**Install command:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --auth-key=tskey-auth-xxxx
```

**How it works:**
- Auth keys are pre-generated in the admin console (one-off or reusable)
- One-off keys auto-revoke after single use
- Node joins WireGuard mesh VPN, gets stable IP (100.x.x.x)
- No port forwarding needed — all traffic encrypted point-to-point

**Auth:** Auth keys bypass interactive browser login. Can be ephemeral (auto-expire) or reusable.

**Updates:** Built-in auto-updater daemon.

**Why it's great:** Solves networking AND authentication in one step. No firewall rules needed.

---

### 3. Coolify — Best "Hub Controls Everything" Pattern

**How it works (NO agent on node):**
1. User adds server IP + SSH key in Coolify UI
2. Hub SSHes into node and runs validation: OS detection, Docker install, prerequisites
3. Hub deploys a `coolify-sentinel` monitoring container on the node
4. ALL subsequent management is via SSH from hub to node
5. Sentinel pushes metrics back to hub via HTTP (`/api/v1/sentinel/push`)

**Provisioning pipeline (9 steps):**
1. Server type selection (localhost / remote SSH / cloud provider)
2. SSH key selection or ED25519 generation
3. Connection validation with retry logic
4. OS detection (Debian, RHEL, SUSE, Arch)
5. Prerequisites install (curl, wget, git, jq) — max 3 retries
6. Docker Engine install (OS-specific)
7. Docker version validation against minimums
8. Reverse proxy setup (Traefik or Caddy)
9. Ongoing health checks via ServerManagerJob

**Auth:** SSH key (generated or user-provided, encrypted in DB). Sentinel uses per-server token for metrics push.

**Updates:** Hub pushes commands via SSH. Sentinel container updated by hub re-deploying it.

**Networking:** SSH multiplexing with persistent connections. Sentinel metrics pushed outbound over HTTP.

**Why it's great:** Node needs zero pre-configuration. Hub does all the work. Comprehensive validation.

---

### 4. Portainer — Best Agent Container Pattern

**Standard Agent (node accessible from hub):**
```bash
docker run -d -p 9001:9001 --name portainer_agent --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/docker/volumes:/var/lib/docker/volumes \
  portainer/agent:latest
```

**Edge Agent (node behind firewall — RECOMMENDED):**
- Generated `docker run` command from Portainer UI includes embedded join token
- Agent makes outbound-only connections (polls hub every 5s for pending jobs)
- Uses TLS tunnel on port 8000 for secure bidirectional comms
- No inbound ports needed on node

**Auth:** `AGENT_SECRET` env var (shared secret) or Edge join token (generated per-environment).

**Updates:** Pull new agent image, recreate container.

**Networking:**
- Standard: Hub connects to agent on port 9001
- Edge: Agent polls hub outbound (ports 9443 + 8000 on hub). **No inbound ports on node.**

**Why it's great:** Edge Agent model is firewall-friendly. Outbound-only polling. Docker-native.

---

### 5. CapRover — Docker Swarm Under the Hood

**Join via UI:**
1. Enter hub IP, new node IP, SSH private key, node type (worker)
2. CapRover SSHes to node and runs `docker swarm join --token SWMTKN-xxx hub-ip:2377`

**Join via CLI:**
```bash
# On hub: get the token
docker swarm join-token worker
# On node: join
docker swarm join --token SWMTKN-1-xxx HUB_IP:2377
```

**Auth:** Docker Swarm token (auto-generated) + SSH key for initial setup.

**Updates:** Docker Swarm service updates propagate to all nodes.

**Networking:** Docker Swarm overlay network. Requires ports 2377, 7946, 4789.

**Why it's great:** Proven clustering with Docker Swarm. Built-in load balancing.

---

### 6. Dokku — Not Relevant for Node Management

Dokku is a single-server PaaS. Deployment is `git push` based. No multi-node clustering.
Included for completeness — its pattern (git remote + push) is elegant but not applicable to our fleet model.

---

## Recommended Pattern for ARCHIE

### Hybrid: K3s-style command + Coolify-style provisioning + Portainer Edge-style heartbeat

**The ideal ARCHIE node installer command:**
```bash
curl -fsSL https://archie.hub-ip/install.sh | HUB_URL=https://hub-ip:3000 NODE_TOKEN=xxx sh -
```

**What the script should do (in order):**
1. **Validate environment** — check OS, architecture, disk space, GPU presence
2. **Install Docker** if not present (copy Coolify's OS-detection + install logic)
3. **Pull containers** — `docker compose pull` for Ollama + ComfyUI + archie-node-agent
4. **Configure** — write `.env` with HUB_URL, NODE_TOKEN, detected hardware (GPU model, VRAM, RAM)
5. **Start services** — `docker compose up -d` using `docker-compose.node.yml`
6. **Register with hub** — POST to `HUB_URL/api/fleet/register` with token + hardware info
7. **Start heartbeat** — node agent polls hub or pushes heartbeat every 30s

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Auth model** | Pre-shared token (K3s pattern) | Simple, no interactive login, token generated in Starbase UI |
| **Communication direction** | Node pushes to hub (Coolify Sentinel pattern) | Firewall-friendly, no inbound ports needed on node |
| **Agent model** | Lightweight container (Portainer pattern) | Docker-native, easy to update, self-contained |
| **Install delivery** | `curl \| sh` with env vars (K3s pattern) | Universal, one command, idempotent |
| **Updates** | Hub signals node agent, agent pulls new compose (current OTA pattern) | Already built, proven |
| **Hardware detection** | In install script (Coolify validation pattern) | GPU/RAM/CPU detected before registration |

### Token Flow
1. Admin clicks "Add Node" in Starbase UI
2. Hub generates a one-time token, stores in `remote_nodes` table (status: pending)
3. Hub displays: `curl -fsSL https://hub-ip:3000/api/fleet/install.sh | HUB_URL=... NODE_TOKEN=xxx sh -`
4. User runs command on new machine
5. Script installs Docker, pulls images, starts services
6. Node agent POSTs registration to hub with hardware info
7. Hub validates token, marks node as "online", assigns agents

### What to Copy from Each Platform

| From | Copy This |
|------|-----------|
| **K3s** | `curl \| ENV=val sh -` pattern, idempotent script, same script for install + rejoin |
| **Coolify** | OS detection, Docker install logic, multi-step validation with retries, Sentinel push model |
| **Portainer Edge** | Outbound-only polling, TLS tunnel for reverse access, join token concept |
| **Tailscale** | One-off auth keys that auto-revoke, ephemeral node concept |
| **CapRover** | Docker Swarm overlay if we ever need multi-node networking |

### What NOT to Copy

- **Coolify's SSH-from-hub model** — requires SSH access to every node, doesn't scale for untrusted networks
- **CapRover's Docker Swarm dependency** — overkill for our GPU dispatch use case
- **Dokku's git-push model** — wrong paradigm entirely
- **Portainer's legacy agent** — requires inbound port 9001 (Edge Agent is better)

---

## Sources

- [Coolify Installation Docs](https://coolify.io/docs/get-started/installation)
- [Coolify Server Management (DeepWiki)](https://deepwiki.com/coollabsio/coolify/3-server-management)
- [Coolify Server Provisioning (DeepWiki)](https://deepwiki.com/coollabsio/coolify/3.2-server-provisioning-and-validation)
- [Coolify Sentinel Monitoring (DeepWiki)](https://deepwiki.com/coollabsio/coolify/3.5-server-monitoring-(sentinel-and-metrics))
- [CapRover Cluster Docs](https://caprover.com/docs/app-scaling-and-cluster.html)
- [K3s Quick-Start Guide](https://docs.k3s.io/quick-start)
- [Portainer Agent Install Docs](https://docs.portainer.io/admin/environments/add/docker/agent)
- [Portainer Edge Agent Docs](https://docs.portainer.io/admin/environments/add/docker/edge)
- [Tailscale Auth Keys](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale Quickstart](https://tailscale.com/docs/how-to/quickstart)
- [Dokku Application Deployment](https://dokku.com/docs/deployment/application-deployment/)
- [Docker Swarm Join](https://docs.docker.com/engine/swarm/join-nodes/)
