# Network Security & Remote Inference Research
## Exposing Ollama + ComfyUI Across Networks — Architecture Decision Support
### Date: 2026-03-21 | Depth: Exhaustive

---

## 1. VPN/Tunnel Solutions

### Tailscale (RECOMMENDED for LAN+WAN private fleet)
- **Works**: Yes, production-ready, WireGuard-based mesh VPN
- **Setup**: ~10 min per node. `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up`
- **Auth**: ACLs per device/user, MagicDNS, no API-key-per-request (network-level auth)
- **LAN+WAN**: Yes. Peer-to-peer when possible, DERP relay when NAT fails. Adds 5-15ms
- **Tailscale Funnel**: Exposes services publicly with HTTPS + valid certs. Double opt-in (admin console + device). Good for API endpoints
- **Gotchas**: Free tier = 100 devices, 3 users. Control plane is SaaS (not self-hostable without Headscale). Funnel has bandwidth limits
- **Best for**: Private fleet dispatch (hub to nodes). Each node installs Tailscale, joins tailnet, done. No port forwarding needed

### WireGuard (Raw)
- **Works**: Yes, kernel-level, fastest option (1-3ms overhead)
- **Setup**: Medium — manual key exchange, config files per peer, firewall rules
- **Auth**: Cryptographic key pairs only. No user/token auth
- **LAN+WAN**: LAN trivial, WAN needs port forwarding or a public relay
- **Gotchas**: No auto NAT traversal, no service discovery. You manage everything
- **Best for**: Permanent site-to-site links where you control both firewalls

### Cloudflare Tunnel (RECOMMENDED for public-facing endpoints)
- **Works**: Yes, production-grade
- **Setup**: Easy. `cloudflared tunnel create <name>` + config YAML
- **Auth**: Cloudflare Access adds SSO/OAuth/one-time-pin in front of any tunnel. Can add service tokens for API-to-API auth
- **LAN+WAN**: WAN only (outbound-only from your server, no inbound ports)
- **Gotchas**: MITM by design — Cloudflare decrypts traffic at their edge. Free tier generous. Latency depends on nearest PoP
- **Best for**: Exposing Ollama/ComfyUI to Hostinger VMs or public clients. Service tokens = API key equivalent

### ngrok
- **Works**: Yes, mature product
- **Setup**: Very easy. `ngrok http 11434` for instant tunnel
- **Auth**: Built-in OAuth, OIDC, mutual TLS, IP restrictions via Traffic Policy. API gateway features
- **LAN+WAN**: WAN only
- **Gotchas**: Free tier = random URLs that change. Paid ($8/mo) for custom domains + persistent endpoints. Bandwidth metered
- **Best for**: Quick testing. Too expensive for production fleet traffic

### bore (self-hosted)
- **Works**: Yes, minimal Rust binary
- **Setup**: Very easy. `bore local 11434 --to bore.pub` or self-host server
- **Auth**: Shared secret only. No per-request token auth
- **LAN+WAN**: WAN via relay server
- **Gotchas**: TCP only, no TLS termination, no auth middleware. Very barebones
- **Best for**: Quick ephemeral tunnels. Not for production

### rathole (self-hosted)
- **Works**: Yes, Rust-based, frp alternative with better performance
- **Setup**: Config file similar to frp. Self-host required
- **Auth**: Token per service binding. TLS support
- **LAN+WAN**: WAN via relay server
- **Gotchas**: Low-level, no dashboard. Good perf, tiny footprint
- **Best for**: Self-hosted tunneling where you want minimal resource usage

### ZeroTier
- **Works**: Yes, Layer 2 virtual network
- **Setup**: Easy install, controller is self-hostable (unlike Tailscale)
- **Auth**: Network-level. Device must be authorized to join network
- **LAN+WAN**: Yes, similar to Tailscale but L2 (Ethernet-level)
- **Gotchas**: Own protocol (not WireGuard). Free tier = 25 devices. Slightly more complex than Tailscale
- **Best for**: When you need full self-hosted control plane or L2 features (multicast, bridging)

---

## 2. Ollama-Specific Networking

### Ollama Built-in Auth
- **ollama.com API**: Has API key support (`OLLAMA_API_KEY` env var, Bearer token in header). Keys don't expire, revocable from settings
- **Local Ollama server**: **NO BUILT-IN AUTH**. Anyone who can reach port 11434 can use your GPU. This is the #1 problem to solve
- **OLLAMA_ORIGINS**: Controls CORS only, not authentication
- **Status**: Issue #8536 and #1053 request API key auth. Still open as of 2026. Ollama team recommends reverse proxy

### Caddy + Bearer Token (RECOMMENDED — simplest auth proxy)
- **Repo**: github.com/bartolli/ollama-bearer-auth-caddy (28 stars, active)
- **How**: Caddyfile checks `Authorization: Bearer <key>` header, proxies to localhost:11434
- **Setup**: Docker Compose with Caddy + Ollama. Edit `valid_keys.conf` with your tokens
- **Gotchas**: Simple but effective. Supports multiple API keys. Auto-HTTPS with Caddy
- **Config pattern**:
  ```
  :11435 {
    @authorized {
      header Authorization "Bearer {env.OLLAMA_API_KEY}"
    }
    handle @authorized {
      reverse_proxy localhost:11434
    }
    respond 401
  }
  ```

### Nginx + Bearer Token
- **How**: Lua script in Nginx reads API keys from file, validates Bearer header
- **Repo**: github.com/kesor/ollama-proxy (Nginx + Cloudflare Tunnel combo)
- **Gotchas**: More config than Caddy, but more flexibility. Rate limiting built-in

### LiteLLM Proxy (RECOMMENDED — feature-rich API gateway)
- **Works**: Yes, actively maintained, 25k+ GitHub stars
- **Setup**: `pip install litellm[proxy]` or Docker. Config YAML maps models to Ollama backends
- **Auth**: Virtual API keys with master key (`sk-` prefix). Per-key model access, spend tracking, rate limits
- **Features**: OpenAI-compatible API, load balancing across multiple Ollama instances, key management UI, usage analytics
- **Config**:
  ```yaml
  model_list:
    - model_name: qwen2.5
      litellm_params:
        model: ollama/qwen2.5:7b
        api_base: http://192.168.1.200:11434
    - model_name: qwen2.5
      litellm_params:
        model: ollama/qwen2.5:7b
        api_base: http://node-246:11434
  general_settings:
    master_key: sk-archie-master-key-here
    database_url: "postgresql://archie:pass@192.168.1.200:5432/archie"
  ```
- **Gotchas**: Requires PostgreSQL for key management. Adds ~10ms latency. Python-based (heavier than Caddy)
- **Best for**: Multi-node fleet with per-key access control and usage tracking

### ollama-proxy (Nginx-based)
- **Repo**: github.com/kesor/ollama-proxy
- **How**: Nginx container validates auth, proxies to Ollama, exposed via Cloudflare Tunnel
- **Best for**: Quick Docker-based auth proxy with Cloudflare integration

---

## 3. ComfyUI Networking

### ComfyUI Built-in Auth
- **NONE**. Issue #10653 requests built-in auth. No password protection whatsoever. ComfyUI trusts all connections

### ComfyUI Docker Authentication (JWT-based)
- **Repo**: github.com/Fab1can/comfyui-docker-authentication
- **How**: Docker Compose with Nginx reverse proxy + Node.js auth server. JWT tokens via OTP login
- **Setup**:
  1. Clone repo, set `JWT_SECRET` in `.env`
  2. `docker compose up -d`
  3. Get OTP from logs: `docker compose logs auth-server`
  4. Login: `curl "http://localhost:8188/auth/login?otp=<OTP>"`
  5. JWT cookie set, all subsequent requests authenticated
- **Gotchas**: OTP rotates. JWT stored as HTTP-only cookie. Works for browser UI access

### Caddy/Nginx Basic Auth + Reverse Proxy
- **Pattern**: Same as Ollama — put Caddy or Nginx in front of port 8188
- **For API-only access**: Bearer token validation (same Caddyfile pattern as Ollama, just different upstream port)
- **For browser access**: HTTP Basic Auth or OAuth proxy (oauth2-proxy)

### Cloudflare Tunnel + Access
- **Best approach for remote ComfyUI**: Cloudflare Tunnel exposes 8188, Cloudflare Access adds one-time-pin or OAuth gate
- **No client install needed**: Users authenticate via browser, Cloudflare proxies to your ComfyUI
- **For API dispatch**: Use Cloudflare Service Tokens (machine-to-machine auth)

---

## 4. Mesh/Cluster Solutions

### Docker Swarm
- **Works**: Yes, built into Docker Engine
- **Setup**: `docker swarm init` on manager, `docker swarm join` on workers. 5 minutes
- **Best for**: Simple container orchestration across 2-5 nodes
- **Gotchas**: Effectively maintenance-mode (Docker invested in Kubernetes). Limited auto-scaling. Overlay networking can be slow
- **Verdict**: Simplest option but aging. Fine for stable workloads

### K3s (Lightweight Kubernetes)
- **Works**: Yes, CNCF certified Kubernetes in a 40MB binary
- **Setup**: `curl -sfL https://get.k3s.io | sh -` on server, token-join workers. ~15 min
- **Resources**: 512MB RAM baseline, single binary
- **Best for**: When you want Kubernetes ecosystem (Helm charts, operators) on small hardware
- **Gotchas**: Still Kubernetes complexity. Overkill for 2-3 nodes running Ollama
- **Verdict**: Good if you plan to scale beyond 5 nodes or want k8s ecosystem

### HashiCorp Nomad
- **Works**: Yes, mature orchestrator
- **Setup**: Single binary, HCL job files. ~20 min for basic cluster
- **Best for**: Mixed workloads (containers + non-container). Better CPU/memory efficiency than K3s
- **Gotchas**: Smaller ecosystem than k8s. HashiCorp licensing changes (BSL)
- **Verdict**: Good middle ground — simpler than k8s, more features than Swarm

### Hive (Ollama-Specific Distributed Inference) — NEW, INTERESTING
- **Repo**: github.com/VakeDomen/HiveCore + github.com/VakeDomen/HiveNode
- **Published**: 2025 academic paper (ScienceDirect)
- **Architecture**: HiveCore (Java, central proxy) + HiveNode (Rust, worker agents)
- **Auth**: Admin/Client API keys stored in SQLite. Bearer token on all requests
- **How it works**:
  1. HiveCore runs on hub (ports 6666 client, 7777 nodes, 6668 management)
  2. HiveNode runs on each GPU node, connects OUTBOUND to HiveCore (no port forwarding!)
  3. HiveNode advertises available models
  4. Client sends inference to HiveCore, which queues and routes to available node
- **Config**:
  ```ini
  [Server]
  USER_AUTHENTICATION = true
  PROXY_PORT = 6666
  NODE_CONNECTION_PORT = 7777
  MANAGEMENT_CONNECTION_PORT = 6668
  ```
- **Gotchas**: Young project (17 stars). Java dependency for core. Academic origin
- **Verdict**: Architecturally excellent for ARCHIE's use case. Outbound-only connections from nodes = no firewall config. Built-in auth. But immature

### OLOL (Ollama Load Balancer)
- **Repo**: github.com/K2/olol
- **How**: Python gRPC-based load balancer across multiple Ollama instances
- **Features**: Transparent scaling, fault tolerance, sync+async support
- **Gotchas**: Small project (26 stars), gRPC adds complexity vs REST
- **Verdict**: Interesting for pure load balancing but less mature than LiteLLM

### exo (Distributed Inference)
- **What**: Peer-to-peer distributed inference across heterogeneous devices
- **Best for**: Splitting large models across multiple GPUs (tensor parallelism)
- **Gotchas**: Different use case — model sharding, not request routing
- **Verdict**: Not relevant for ARCHIE (you route requests, not shard models)

---

## 5. Branded Installer Patterns

### curl | bash (MOST COMMON)
- **Used by**: Coolify, K3s, Tailscale, Docker, Homebrew
- **Coolify**: `curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash`
- **K3s**: `curl -sfL https://get.k3s.io | sh -`
- **Pattern**: Download shell script, detect OS/arch, install dependencies, configure services
- **Pros**: Universal, no package manager dependency, works on any Linux
- **Cons**: Security concerns (pipe to bash), hard to version/update
- **Best practice**: Host script on your CDN, pin versions, verify checksums

### Docker-Based Installer (RECOMMENDED for ARCHIE)
- **Used by**: Coolify, Portainer, CapRover
- **Pattern**:
  1. Install script checks for Docker, installs if missing
  2. Pulls docker-compose.yml from your registry
  3. `docker compose up -d` starts everything
  4. First-run setup via API or web UI
- **Coolify approach**: Single script installs Docker CE + pulls Coolify containers. Environment variables customize install
- **CapRover approach**: `docker run caprover/caprover` bootstraps entire PaaS
- **Pros**: Reproducible, isolated, easy updates (just pull new images)
- **Cons**: Requires Docker (but you already mandate it)

### .deb/.rpm Packages
- **Used by**: Tailscale, Ollama, traditional software
- **Pattern**: APT/YUM repo + `apt install archie-node`
- **Pros**: System-managed updates, proper service management (systemd)
- **Cons**: Package maintenance overhead, distro-specific

### Snap
- **Used by**: Some projects, declining in popularity
- **Verdict**: Skip — Docker-based is better for your use case

---

## 6. Recommendation for ARCHIE (Hub 192.168.1.200 → Nodes)

### Simplest Production-Ready Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        HUB (192.168.1.200)                  │
│                                                             │
│  ┌──────────┐    ┌───────────┐    ┌──────────────────────┐  │
│  │ ARCHIE   │───>│ Caddy     │───>│ Ollama :11434        │  │
│  │ Platform │    │ Auth Proxy│    │ ComfyUI :8188        │  │
│  │ :3000    │    │ :11435    │    └──────────────────────┘  │
│  └──────────┘    └───────────┘                              │
│       │                                                     │
│       │         ┌────────────────┐                          │
│       └────────>│ Tailscale      │ (mesh VPN)               │
│                 │ tailnet        │                           │
│                 └───────┬────────┘                           │
└─────────────────────────┼───────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
     ┌────────▼──┐ ┌──────▼───┐ ┌────▼────────┐
     │ Node .246 │ │ Node N   │ │ Hostinger   │
     │ (LAN)     │ │ (LAN)    │ │ VM (WAN)    │
     │           │ │          │ │             │
     │ Caddy     │ │ Caddy    │ │ Caddy       │
     │ :11435    │ │ :11435   │ │ :11435      │
     │ Ollama    │ │ Ollama   │ │ Ollama      │
     │ :11434    │ │ :11434   │ │ :11434      │
     │ ComfyUI   │ │          │ │             │
     │ :8188     │ │          │ │             │
     └───────────┘ └──────────┘ └─────────────┘
```

### Layer 1: Network — Tailscale (5 min setup per node)
- Install Tailscale on hub + all nodes
- All nodes get stable Tailscale IPs (100.x.y.z)
- Works identically for LAN nodes (.246) and WAN nodes (Hostinger VMs)
- No port forwarding, no firewall config, no DNS headaches
- Hub dispatches to `http://100.x.y.z:11435` regardless of where node physically is

### Layer 2: Auth — Caddy Bearer Token Proxy (10 min setup per node)
- Each node runs Caddy in front of Ollama (port 11435 → 11434)
- Hub sends `Authorization: Bearer <node-specific-token>` with every dispatch
- Tokens stored in ARCHIE's `remote_nodes` table (encrypted)
- Even on Tailscale, defense-in-depth: if tailnet is compromised, tokens still protect
- Same pattern for ComfyUI: Caddy on :8189 → :8188

### Layer 3: Installer — Docker-Based curl|bash
```bash
# Node installer pattern
curl -fsSL https://archie.kytranempowerment.com/install-node.sh | bash -s -- \
  --hub-token "eyJ..." \
  --tailscale-key "tskey-auth-..." \
  --node-name "hostinger-vm-1"
```

**Script does**:
1. Installs Docker if missing
2. Installs Tailscale, joins tailnet with pre-auth key
3. Pulls `docker-compose.node.yml` from hub
4. Generates Caddy bearer token, registers with hub via API
5. Starts Ollama + Caddy + (optionally ComfyUI) containers
6. Sends first heartbeat to hub

### Why NOT LiteLLM or Hive?
- **LiteLLM**: Excellent but overkill — ARCHIE already has `bridge_dispatcher.py` doing model routing, escalation, and load balancing. Adding LiteLLM = duplicate routing layer. Only worth it if you want OpenAI-compatible API for external consumers
- **Hive**: Architecturally perfect (outbound-only connections!) but too immature (17 stars, Java dependency). Worth watching. Could replace ARCHIE's fleet dispatch in 1-2 years if it matures
- **OLOL**: Same — interesting but too early

### Why NOT Cloudflare Tunnel?
- Adds latency (all traffic through Cloudflare edge). For LLM inference generating 100+ tokens/response, the per-packet overhead adds up
- MITM by design — Cloudflare decrypts your traffic
- Tailscale is peer-to-peer (lower latency) and end-to-end encrypted
- **Exception**: Use Cloudflare Tunnel if you want to expose ARCHIE platform (:3000) publicly

### Future Option: LiteLLM as External API Gateway
If you ever want to sell API access or let external users hit your fleet:
```
External Users → Cloudflare Tunnel → LiteLLM (:4000) → Tailscale → Nodes
```
LiteLLM handles: virtual API keys, spend tracking, rate limits, OpenAI-compatible API

---

## Quick Reference: Solution Matrix

| Solution | Auth | LAN | WAN | Setup | Maturity | Best For |
|----------|------|-----|-----|-------|----------|----------|
| **Tailscale** | Network ACL | Yes | Yes | 5min | Production | Private fleet mesh |
| **WireGuard** | Key pairs | Yes | Manual | 30min | Production | Static site-to-site |
| **Cloudflare Tunnel** | Service tokens | No | Yes | 15min | Production | Public endpoints |
| **Caddy + Bearer** | API key | Yes | Yes* | 10min | Production | Per-service auth |
| **LiteLLM Proxy** | Virtual keys | Yes | Yes* | 30min | Production | API gateway + analytics |
| **Hive** | Admin/Client keys | Yes | Yes | 45min | Early | Ollama-specific cluster |
| **K3s** | RBAC | Yes | Yes | 30min | Production | K8s ecosystem |
| **Docker Swarm** | Swarm tokens | Yes | Yes | 10min | Maintenance | Simple orchestration |
| **ngrok** | OAuth/OIDC | No | Yes | 2min | Production | Quick testing |

*Requires network layer (Tailscale/WireGuard) for WAN

---

## Sources

- [Ollama API Key Auth Issue #8536](https://github.com/ollama/ollama/issues/8536)
- [Ollama API Key Auth Issue #1053](https://github.com/ollama/ollama/issues/1053)
- [Securing Ollama API: Auth & Rate Limiting (2025)](https://dasroot.net/posts/2025/12/securing-ollama-api-authentication-rate-limiting/)
- [Building Private LLM Server with Ollama Auth (2026)](https://dasroot.net/posts/2026/01/building-private-llm-server-ollama-authentication/)
- [Caddy + Ollama Bearer Auth](https://github.com/bartolli/ollama-bearer-auth-caddy)
- [Ollama Nginx Proxy + Cloudflare Tunnel](https://github.com/kesor/ollama-proxy)
- [LiteLLM Virtual Keys Docs](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [LiteLLM + Ollama Setup](https://medium.com/@qdrddr/ollama-with-apikey-litellm-proxy-c675c32ce7e8)
- [ComfyUI Auth Issue #10653](https://github.com/comfyanonymous/ComfyUI/issues/10653)
- [ComfyUI Docker Auth (JWT)](https://github.com/Fab1can/comfyui-docker-authentication)
- [Hive: Distributed Ollama Inference (Paper)](https://www.sciencedirect.com/science/article/pii/S2352711025001505)
- [HiveCore](https://github.com/VakeDomen/HiveCore) / [HiveNode](https://github.com/VakeDomen/HiveNode)
- [OLOL Ollama Load Balancer](https://github.com/K2/olol)
- [Tailscale Funnel Docs](https://tailscale.com/kb/1223/funnel)
- [Cloudflare Tunnel vs ngrok vs Tailscale](https://dev.to/mechcloud_academy/cloudflare-tunnel-vs-ngrok-vs-tailscale-choosing-the-right-secure-tunneling-solution-4inm)
- [ngrok vs Cloudflare Tunnel vs Tailscale (2025-26)](https://instatunnel.my/blog/comparing-the-big-three-a-comprehensive-analysis-of-ngrok-cloudflare-tunnel-and-tailscale-for-modern-development-teams)
- [ZeroTier vs Tailscale for Homelab](https://www.xda-developers.com/why-zerotier-is-the-best-tailscale-alternative-for-your-home-lab/)
- [K3s vs Docker Swarm vs Nomad Analysis](https://medium.com/@veritasautomata/k3s-vs-other-lightweight-container-orchestration-solutions-a-comparative-analysis-for-distributed-b80810309d91)
- [Coolify Installation](https://coolify.io/docs/get-started/installation)
- [Coolify vs CapRover vs Dokku](https://selfhostable.dev/blog/coolify-vs-caprover-vs-dokku/)
- [Snyk: Hacking ComfyUI Through Custom Nodes](https://labs.snyk.io/resources/hacking-comfyui-through-custom-nodes/)
- [Secure Remote Access Comparison (2026)](https://www.lowerhomeserver.vip/blog/use-cases/secure-remote-access-comparison)
