# Cockpit (archie-comms) → mesh + LAN only, deny external

**Owner ask (2026-06-17):** archie.* is the admin cockpit / engine. Restrict to **mesh + LAN
only**; everyone else gets an "Access Denied — secure connection required" landing page.
Two layers: (1) network gate (mesh/LAN), (2) admin OAuth login on top. Owner device is on
mesh (`shuttle-kytran 100.64.0.9`); hub mesh = `100.64.0.4`. Scope decision: **cockpit now,
platform-wide next** (template across platform :3000, KSO, Backup Manager, Security Network
as a tracked follow-up project — do NOT big-bang).

## Recon (verified 2026-06-17)
- `archie_comms` publishes `3002:3002` on `0.0.0.0` → **`100.64.0.4:3002` reachable over mesh**
  (confirmed MESH_3002_OPEN); platform `100.64.0.4:3000` also open (MESH_3000_OPEN).
- LAN subnet route is **disabled** → a *remote* mesh device CANNOT reach `192.168.1.200`;
  it reaches the hub at `100.64.0.4`. That's why OAuth hardcoded to `192.168.1.200:3000`
  fails for mesh/external (ERR_NETWORK_CHANGED) but works on home wifi (on-LAN).
- No reverse proxy / `X-Forwarded-For` in front of archie_comms on the hub (direct port).
- External reaches archie.* only via **Beacon** (public edge, `100.64.0.11` / `2.25.170.252`).
- Platform OAuth provider `oauth_provider.py`: `oauth_clients` has a **single `redirect_uri`
  per client**, exact-match. Current `archie-comms` = `https://archie.kytranempowerment.com/auth/kytran/callback`.
- ⚠️ Side-finding: `KYTRAN_CLIENT_SECRET` is plaintext in docker-compose.yml → move to a
  Docker secret in a later pass.

## Target architecture: pure-mesh cockpit
Owner reaches the cockpit at **`http://100.64.0.4:3002`** over mesh (WireGuard-encrypted).
OAuth round-trips entirely over mesh. External → Beacon serves the access-denied page.

## Steps (each verified; never remove a working path until the next is proven)

### Increment 1 — make mesh login work (reversible: 1 env block + 1 DB row)
1. `UPDATE oauth_clients SET redirect_uri='http://100.64.0.4:3002/auth/kytran/callback'
   WHERE client_id='archie-comms';`  (rollback value above)
2. archie_comms env (root .env / compose):
   - `KYTRAN_AUTH_URL=http://100.64.0.4:3000`  (browser-facing authorize, mesh)
   - `KYTRAN_REDIRECT_URI=http://100.64.0.4:3002/auth/kytran/callback`  (mesh callback)
   - `KYTRAN_AUTH_INTERNAL_URL=http://archie_platform:3000`  (server-side token/userinfo, docker-internal)
3. `docker compose up -d archie_comms` (env reload; NOT restart).
4. Verify from hub: `GET http://100.64.0.4:3002/auth/kytran/login` → 302 → authorize at
   `100.64.0.4:3000` with mesh redirect_uri. Owner confirms end-to-end login on mesh.
   NOTE: this BREAKS the public-hostname login path (intended). Owner uses the mesh URL.

### Increment 2 — network gate + access-denied page (after Increment 1 verified)
- App-level `before_request` in app_comms.py: allow mesh `100.64.0.0/10` + LAN
  `192.168.1.0/24` + loopback + docker bridge; else serve the "Access Denied — secure
  connection required" page (403). Env kill-switch `COMMS_NETWORK_GATE`.
- BLOCKER: must first confirm what `request.remote_addr` shows behind Docker's published
  port (NAT source-preservation is uncertain without a proxy). Determine empirically with a
  temporary `/api/whoami` echo before trusting it. If real IP isn't visible at the app, gate
  at the host firewall / interface-bind instead.

### Increment 3 — deny external at Beacon (riskiest; backup + validate; confirm first)
- On Beacon, change the `archie.kytranempowerment.com` Caddy block from `reverse_proxy` to
  `respond` with the access-denied page (403). Beacon is the shared public front door —
  back up the Caddyfile, `caddy validate` before reload, reload (not restart).

### Increment 4 — platform-wide follow-up (separate tracked project)
- Template the mesh/LAN gate across the other admin surfaces.

## Safety invariants
- LAN/home-wifi remains a working path until mesh is proven.
- Every change reversible; keep rollback values.
- Beacon: validate before reload; never break the shared front door.
- Don't trust spoofable `X-Forwarded-For` for the IP gate.

## OUTCOME (2026-06-17)
- ✅ **Increment 1 DONE + MERGED** (PR feat/cockpit-mesh-lockdown): owner logs in over
  mesh at **`http://100.64.0.4:3002`** (WireGuard-encrypted; no padlock but genuinely
  secure). compose OAuth → mesh hub; app_comms cookie env-driven (host-only/non-Secure
  default); `oauth_clients.archie-comms.redirect_uri = http://100.64.0.4:3002/auth/kytran/callback`
  (rollback: `https://archie.kytranempowerment.com/auth/kytran/callback`).
- ⏸️ **Padlock (Option C) PARKED — blocked on AdGuard topology.** Gate check failed: from
  the hub, `dig @100.64.0.4 archie.*` AND `dig @192.168.1.200 archie.*` both **time out**.
  AdGuard publishes `53/5354` with NO docker port map for :53 → likely a **macvlan/dedicated
  IP**, not the host IP. So I could NOT verify AdGuard answers on the mesh IP, and pushing
  `100.64.0.4` as the Headscale resolver would risk breaking DNS for all 9 mesh nodes
  (DR-class change — KB #270611). Owner chose **A: merge Increment 1, park the padlock**.
- **Padlock follow-up (do FIRST next time):** map AdGuard's real network mode + bind_hosts +
  access-control (`docker inspect network_adguard` networks; AdGuardHome.yaml `bind_hosts`,
  `access` allowed_clients) and find the IP it actually answers on. ONLY then: (1) AdGuard
  rewrites archie.*/platform.* → mesh-reachable IP, (2) Headscale `dns.nameservers.global`
  `192.168.1.200`→that IP + restart, (3) revert comms OAuth to public hostnames + cookie env
  `COMMS_COOKIE_SECURE=true`/`COMMS_COOKIE_DOMAIN=.kytranempowerment.com` (NPM already serves
  `archie.*`+`platform.*` TLS on `0.0.0.0:443`, mesh-reachable), (4) owner toggles Tailscale to
  re-sync DNS. Blast radius: rewrite change affects non-mesh LAN devices for those 2 hosts.
- MagicDNS alt (no fleet-DNS change): `magic_dns:true base_domain:mesh.archie` → hub node
  `archie-starbase` → `http://archie-starbase.mesh.archie:3002` (hides IP, no TLS). Verify it
  resolves on the Fold BEFORE repointing OAuth.
- Increments 2 (app IP-gate, friendly deny page — needs real-IP visibility behind Docker NAT,
  undetermined) + 3 (Beacon deny page) also still open.
