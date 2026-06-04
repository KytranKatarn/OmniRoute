# Front-Door Ingress Node — Setup Runbook (#3730, Option A)

**Decision (2026-06-03):** dedicated lightweight Hostinger **KVM1** (1 vCPU / 4 GB / 50 GB NVMe / 4 TB BW), **US/Canada-East DC**, as the platform's **stable static front-door**. Public DNS for the hub subdomains points ONCE at this node's static IP and never chases the volatile home-hub IP again.

**Role = INGRESS ONLY.** Mesh client + Caddy. **NO** agent stack, **NO** `node_api`, **NO** Ollama, **NO** products, **NO** DB. (This is the #3224 "satellite / connect-only mesh client" tier.) It is **stateless** — holds only the Caddyfile + Let's Encrypt certs (auto-reissued). If it dies: rebuild + re-point DNS.

---

## Live identity (provisioned 2026-06-03)
- Hostinger KVM1 `srv1730304` · VM id `1730304` · DC 24 (Boston)
- `FRONTDOOR_PUBLIC_IP` = `2.25.170.252`
- `FRONTDOOR_MESH_IP`   = `100.64.0.11` (Headscale host `frontdoor-kvm1`, user `archie-fleet`)
- Fleet node_id = `ingress_01699263f6cd9dc9` (DB id 129) — approved/online, `bridge_enabled=false`
- SSH = `root@2.25.170.252` (hub ed25519 key, baked via recreate)
- Root pw + node token in gitignored root `.env` (`FRONTDOOR_KVM1_*`)
- Hub mesh = `100.64.0.4:3000` · boston-2 (DR) mesh = `100.64.0.10`
- Headscale control plane (public) = `https://mesh.kytranempowerment.com`
- STATUS: **Phase 1 COMPLETE (2026-06-03)** ✅ — Caddy installed; `fdtest.kytranempowerment.com` reverse-proxies over mesh to hub `100.64.0.4:3000`, valid Let's Encrypt cert, verified end-to-end `GET → 200` (A.R.C.H.I.E. hub login over valid TLS). **`fdtest` left up as a permanent front-door HEALTH ENDPOINT** (200 = front-door + hub reachable). Real 27-subdomain cutover NOT yet done (see Step 6).

---

## Step 1 — base + firewall
```bash
apt update && apt -y upgrade
ufw allow 22 && ufw allow 80 && ufw allow 443
ufw allow from 100.64.0.0/10           # mesh peers
ufw default deny incoming
ufw --force enable
```
No 11434 (no Ollama). No Docker agent stack.

## Step 2 — join Headscale mesh (ingress, no agent stack)
```bash
curl -fsSL https://tailscale.com/install.sh | sh    # tailscale client only
# On HUB, mint a key:
#   docker exec archie_headscale headscale preauthkeys create --user archie-fleet --expiration 24h --reusable
tailscale up --login-server https://mesh.kytranempowerment.com --authkey <KEY> --hostname frontdoor-us
tailscale ip -4          # record FRONTDOOR_MESH_IP
```
Verify reachability (mesh-only transport rule): `curl -so /dev/null -w '%{http_code}' http://100.64.0.4:3000/` should be 200/302; same for `100.64.0.10`.
- **Do NOT** `--advertise-routes` on a healthy mesh (mistake #250231).
- DR note: once joined, tailscale is peer-to-peer — the front-door keeps reaching boston-2 even if the hub (and Headscale control plane) are down. Good for the hub-outage case. (#3681 = control-plane standby for *new* joins during long outages.)

## Step 3 — install Caddy
```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https
# add Caddy apt repo, then:
apt update && apt install -y caddy
```

## Step 4 — Caddyfile (hub subdomains → hub over mesh)
`/etc/caddy/Caddyfile` — one block per hub subdomain. Upstream is the **mesh IP**, never a public hostname.
```
platform.kytranempowerment.com {
    reverse_proxy http://100.64.0.4:3000
}
# ...repeat for every hub subdomain. Canonical list lives in
# scripts/hub_dns_update.sh (it already enumerates the 27 hub subdomains).
```
Caddy auto-provisions Let's Encrypt certs on first hit (needs 80/443 open + DNS already pointing here for that subdomain).

## Step 5 — smoke test ONE subdomain first
1. Point ONE low-risk subdomain's A record → `FRONTDOOR_PUBLIC_IP` (Hostinger MCP `DNS_updateDNSRecordsV1`).
2. `dig +short <sub>` → FRONTDOOR_PUBLIC_IP; then load it in a browser, confirm 200 + valid LE cert + correct page (proxied from hub over mesh).
3. Check `X-Forwarded-For` / Host handling on the hub side is sane.

## Step 6 — cut over the rest (USE DNS-01 PRE-ISSUE — do NOT flip-then-ACME)
The watch-series migration proved that flipping a LIVE subdomain's DNS and letting Caddy ACME-issue *after* causes a TLS gap + Let's Encrypt caching the old IP (KB #270474, ADR-001/#691). fdtest worked flip-then-ACME only because it was a brand-new name with no prior service.

For the real 27 hub subdomains (live, currently served by the hub's NPM):
1. Install Caddy's **Hostinger DNS plugin** (xcaddy build w/ a Hostinger/libdns provider) so Caddy can solve **DNS-01** challenges via the Hostinger API.
2. **PRE-ISSUE** every hub subdomain's cert on the front-door via DNS-01 **while DNS still points at the hub** (DNS-01 doesn't need the domain pointing here). Add all subdomains to the Caddyfile with `tls { dns hostinger ... }`.
3. Verify each cert is present in Caddy's store + forced-IP HTTPS to the front-door returns 200.
4. **THEN** batch-flip DNS → `2.25.170.252`. Zero gap (cert already present), no flip-then-ACME race. Sidesteps the NPM→Caddy copy-cert hassle entirely.

### ⛔ Cutover EXCLUSIONS — NEVER flip these through the front-door
(From the 2026-06-03 DNS audit. Hub public IP currently `173.182.133.96`; ~25 hub subdomains point there. Watch products gov/market/legal/wtf/civic are on boston-2 `2.25.133.122` — already static, NOT in scope.)
- **`mesh.kytranempowerment.com`** — Headscale CONTROL PLANE the front-door itself uses to stay on the mesh. Flipping it through the front-door is circular and can brick the mesh. Leave direct to hub.
- **`mail` / `webmail` / `mta-sts`** — Stalwart SMTP/IMAP + mail TLS. Not HTTP-proxy material. Leave direct.
- **`plex` / `jellyfin` / `media`** — heavy media streams; do NOT funnel through the 1-core KVM1. Leave direct.
- Per-subdomain backends differ (platform:3000, creed:8086, nagios:8082, KBS/business:8091, server/KSO:8085, mediahub:8105, archie/comms:3002, adguard→network_adguard:3000…). Pull the hub NPM proxy-host table to get exact host:port before configuring each Caddy site. Verify `100.64.0.4:<port>` is mesh-reachable per subdomain before flipping.
- STAGE it: one low-risk subdomain at a time, P.R.O.B.E.-test each. Routing everything through the 1-core box = platform-wide SPOF (mitigate later w/ HA second front-door, #3681).

### Status: cutover DEFERRED (owner, 2026-06-03)
Phase 1 proven (fdtest health endpoint live). Real cutover on hold by owner decision — resume by picking a low-risk subdomain, wiring its backend, pre-issuing cert, flipping, P.R.O.B.E.-testing.

---

## Scope notes
- **v1 = hub subdomains only.** The 5 watch products live on **boston-2** (#3727) and already sit on a *static* IP (2.25.133.122), so they don't chase a volatile IP — leave them direct for now. Optionally front them later for uniformity/HA.
- **DR integration (Phase 2, follow-on):** instead of flipping 27 DNS records on a hub move/outage, the failover path flips the **front-door's Caddy upstream** `100.64.0.4` → `100.64.0.10` and reloads Caddy. This *replaces* the `hub_dns_update.sh` DNS-chase for the move scenario (DNS now only ever points at the front-door). Wire this into `dr/failover.sh` + `dr/failback.sh`.
- **HA (Phase 4, #3681 overlap):** v2 = a second front-door (EU) with health-checked DNS round-robin so the front-door itself isn't a SPOF. KVM1 is cheap enough to run two.

## Phase 3 (optional) — co-located ultra-light CPU agent
Owner idea: use the spare 1 vCPU / 4 GB so the box isn't single-purpose. **Feasible, but DEFER until ingress is proven stable under real traffic, and bound it hard** — availability of the front-door outranks a small agent's capacity.
- **Model: `qwen2.5:0.5b` only** (wizard-verified 2026-06-03: on 4 GB with HOST_RESERVE 1.5 GB → ~2.5 GB free, even `qwen2.5:1.5b` does NOT fit per `recommend(cpu=1,ram=4)`; `llama3.2:3b` needs ~8 GB, 7B/8B are GPU-gated). `nomic-embed-text` for embeds. With Caddy also resident on the single core, 0.5b is the practical ceiling and still marginal — reinforces "pure ingress first".
- **cgroup-bound** the Ollama/`node_api` stack: `mem_limit` ~2 GB, `cpus <= 0.4`, plus `nice`/`OOMScoreAdj` so **Caddy always wins the single core**.
- **Ollama mesh-only**: `ufw allow from 100.64.0.0/10 to any port 11434` — NEVER public. This is the most-exposed box (public 80/443); keep attack surface minimal.
- Register the agent as **lowest-priority / opportunistic** so the dispatcher routes only trivial overflow here (classify / summarize / embed).
- **Reality check:** 1 core → inference pegs CPU for seconds per task → proxied traffic jitters during inference. The capacity add is marginal. If in any doubt, leave it pure ingress.
- This is exactly the **#3224 satellite tier** + **#2516 resource-routing** intersection; the #371 node baseline (`node_api` mem/cpu limits) already gives the bounding mechanism.

## Watch list
- **Bandwidth (4 TB/mo)** is the real constraint — ALL public traffic funnels here. CPU/RAM are over-spec'd for Caddy. Monitor BW as traffic grows.
- Register in `remote_nodes` with an **ingress/satellite tier tag** so the fleet/ARMADA map shows it but the agent baseline (model limits, node_auto_provision) does NOT target it.
