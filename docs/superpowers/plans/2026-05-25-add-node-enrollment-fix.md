# Add-Node Enrollment Flow Fix — Design
**Dev HQ Task #2930 | Status: Design Complete | Date: 2026-05-25**

## Problem Summary

The Fleet tab "Add Node" enrollment has 3 independent failure modes:

1. The enrollment form never accepts `mesh_ip` → nodes registered without mesh connectivity
2. `_generate_bash_installer` and `_generate_powershell_installer` are `raise RuntimeError("not yet implemented")` dead stubs → the `/install` token route crashes
3. `install-node.sh` uses a stale URL `/tools/starbase/api/nodes/register` and sends LAN IP instead of mesh IP

As a result, `node_inter_cluster_host()` at `fleet_helpers.py:314` (which correctly prioritizes `mesh_ip`) has nothing to return, and nodes never appear with mesh connectivity in the Fleet tab.

## Root Cause (One Sentence)

The enrollment form, the installer generator, and the legacy installer script all independently fail to establish `mesh_ip` — so the function that correctly prioritizes mesh routing has no data to work with.

---

## Architecture Decision

**Admin-declared mesh IP with self-contained generated script.**

The admin (Kytran) knows the Headscale mesh IP of each node — it is assigned by the Headscale dashboard and visible before enrollment. The enrollment form accepts `mesh_ip` up front, stores it immediately in `remote_nodes.mesh_ip`, and bakes it into the generated setup script. The setup script is fully self-contained: credentials embedded, hub URL = mesh IP, Headscale join included as a step within the script.

**Rationale:** The `node_repair_command` endpoint (fleet_node_routes.py:1077) already demonstrates this pattern correctly — it generates a complete one-liner with all credentials baked in, no hub-side file mutations. The new enrollment flow matches this pattern for fresh installs.

**Fallback:** If admin doesn't know the mesh IP yet, the script joins Headscale first, auto-discovers its mesh IP via `tailscale ip -4`, then calls `POST /api/nodes/{node_id}/mesh-ip` (already exists at fleet_node_routes.py:980) to register it.

---

## Files to Modify

### `platform_v2/tools/department_hq/fleet_node_routes.py`

**Change 1 — Lines 68–81: Remove dead stubs**

Replace both `raise RuntimeError("not yet implemented")` stubs with delegation to `_generate_setup_sh` / `_generate_setup_ps1`.

**Change 2 — Lines 113–132: Rewrite `_generate_setup_sh`**

Self-contained Bash script that:
- Installs Docker if missing
- Installs Tailscale if missing
- Joins Headscale mesh: `tailscale up --login-server=https://mesh.kytranempowerment.com --auth-key={headscale_authkey} --hostname={node_name}`
- Auto-discovers mesh IP: `MESH_IP=$(tailscale ip -4)` (with 3-retry, 5s sleep fallback)
- Falls back to provided `MESH_IP` env var if `tailscale ip -4` returns empty
- Calls `POST http://100.64.0.4:3000/tools/department-hq/api/nodes/{node_id}/mesh-ip {mesh_ip: MESH_IP}` (endpoint already exists, requires `X-Node-API-Key`)
- Writes `/opt/archie-node/.env` with `HUB_URL=http://100.64.0.4:3000`, `MESH_IP`, `NODE_ID`, `HUB_API_KEY`
- Downloads `docker-compose.node.yml` from hub (mesh URL)
- Starts containers: `docker compose up -d`
- Does NOT modify any hub-side docker-compose files

**Change 3 — Lines 3122–3188: `api/request-node` endpoint**

Accept `mesh_ip` from request JSON:
- Validate format: `^100\\.64\\.\\d{1,3}\\.\\d{1,3}$` if provided (use `validate_mesh_ip()` from fleet_helpers)
- Include `mesh_ip` in the INSERT
- Set `hostname = mesh_ip` when mesh_ip is provided (satisfies `node_inter_cluster_host()` fallback chain)
- Use `HUB_MESH_URL` env var (`http://100.64.0.4:3000`) for all hub references — NEVER `request.host`
- Generate Headscale auth key at this stage (currently generated later at `register_node`, too late to embed in response)
- Return: `{node_id, node_name, db_id, setup_token, headscale_authkey, hub_mesh_url, command_linux, command_windows}`

**Change 4 — Lines 55–65: Implement `_on_node_approved`**

Currently a stub that logs a warning and does nothing. Implement minimum post-approval orchestration:
- `auto_assign_agents_for_model(node_id, model_name)` for each model on the node
- Telegram notification: "Node {name} approved, agents assigned"
- Insert into `system_notifications`

---

### `platform_v2/tools/department_hq/fleet_helpers.py`

**Add after line 326: `validate_mesh_ip()` utility**

```python
import ipaddress

HEADSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")

def validate_mesh_ip(ip: str) -> bool:
    """Return True if ip is within the Headscale mesh range 100.64.0.0/10."""
    try:
        return ipaddress.ip_address(ip) in HEADSCALE_NETWORK
    except ValueError:
        return False
```

Use this in `api/request-node`, `update_mesh_ip` (line 980), and heartbeat handler (line 1177).

---

### `node_client/install-node.sh`

**Line 271:** Change stale URL:
- FROM: `/tools/starbase/api/nodes/register`
- TO: `/tools/department-hq/api/nodes/register`

**Line 369:** Change status message URL:
- FROM: `/tools/starship`
- TO: `/tools/department-hq#fleet`

---

### Fleet Tab UI (department_hq HTML template)

Add `mesh_ip` field to Add Node modal:
- `mesh_ip` (text input, placeholder `100.64.x.x`, optional)
- `deployment_mode` (select: `starship` | `starbase_outpost`)

After submission, display `command_linux` / `command_windows` from the API response in a copy-paste panel.

---

## Environment Variable to Add

**`.env` (both root and platform_v2):**
```
HUB_MESH_URL=http://100.64.0.4:3000
```

Used by the hub to build setup scripts (never `request.host`), and embedded in the generated `.env` on each enrolled node.

**IMPORTANT:** Never use `https://platform.kytranempowerment.com` — Hostinger CDN caps at 60s, bypasses queue, hides from task_execution_log.

---

## No Schema Changes Needed

`remote_nodes` already has: `mesh_ip`, `deployment_mode`, `setup_token`, `user_id`. No migrations required.

---

## Data Flow (Post-Fix)

```
Admin opens Fleet tab → clicks "Add Node"
  → modal: node_name + deployment_mode + mesh_ip (optional)
  → POST /api/request-node {node_name, deployment_mode, mesh_ip}
    → validate_mesh_ip() if provided
    → INSERT remote_nodes (mesh_ip, hostname=mesh_ip, deployment_mode, setup_token)
    → docker exec archie_headscale headscale preauthkeys create --user archie-fleet --expiration 24h
    → return {node_id, setup_token, headscale_authkey, hub_mesh_url, command_linux, command_windows}

Admin copies command_linux → pastes on new node
  → bash runs _generate_setup_sh (self-contained):
    → install Docker + Tailscale if missing
    → tailscale up --auth-key={headscale_authkey} --login-server=https://mesh.kytranempowerment.com
    → MESH_IP=$(tailscale ip -4)  [retry 3× if empty, then use provided MESH_IP env var]
    → POST http://100.64.0.4:3000/tools/department-hq/api/nodes/{node_id}/mesh-ip {mesh_ip: MESH_IP}
      → UPDATE remote_nodes SET mesh_ip=MESH_IP, mesh_status='connected'
    → write /opt/archie-node/.env (HUB_URL=http://100.64.0.4:3000, MESH_IP, NODE_ID, HUB_API_KEY)
    → curl http://100.64.0.4:3000/tools/department-hq/api/nodes/docker-compose.node.yml
    → docker compose up -d
    → poll GET /api/nodes/{node_id}/status until approved

Admin approves in Fleet tab
  → PUT /api/nodes/{node_id}/approve
    → UPDATE remote_nodes SET approval_status='approved'
    → _on_node_approved() → auto_assign_agents_for_model() + Telegram notify

Node heartbeat starts (30s)
  → POST /api/nodes/{node_id}/heartbeat {mesh_ip, hardware, models}
    → COALESCE updates mesh_ip (already correct via existing handler)
    → agents assigned, node appears online in Fleet tab
```

---

## Build Sequence

- [ ] **Phase 1** — Validation utility: Add `validate_mesh_ip()` to `fleet_helpers.py` after line 326
- [ ] **Phase 2** — Fix dead stubs: Remove `raise RuntimeError` from `_generate_bash_installer` and `_generate_powershell_installer`; delegate to `_generate_setup_sh` / `_generate_setup_ps1`
- [ ] **Phase 3** — Rewrite `_generate_setup_sh`: self-contained script with Tailscale join, mesh IP discovery, `POST /mesh-ip` callback, `.env` write, Docker stack start — all using `http://100.64.0.4:3000`
- [ ] **Phase 4** — Update `api/request-node`: accept + validate + store `mesh_ip`; generate Headscale auth key; return `command_linux` and `command_windows`; use `HUB_MESH_URL` env (not `request.host`) for all hub references
- [ ] **Phase 5** — Implement `_on_node_approved`: agent assignment + Telegram + system notification
- [ ] **Phase 6** — Fix `install-node.sh`: update `/tools/starbase/` → `/tools/department-hq/`
- [ ] **Phase 7** — Fleet tab UI: add `mesh_ip` field to Add Node modal; display copy-paste commands after submission
- [ ] **Phase 8** — Add `HUB_MESH_URL=http://100.64.0.4:3000` to both `.env` files
- [ ] **Phase 9** — End-to-end test: enroll Node .245 or .246 (both currently online), verify `remote_nodes.mesh_ip` populated, verify `node_inter_cluster_host()` returns mesh IP, verify heartbeat succeeds, verify agent assignment fires on approval

---

## Key Notes for Implementation

- **Headscale auth key timing**: Generate at `api/request-node` call time (not at download-script time) so the key is in the JSON response and embedded in the displayed command. Key is ephemeral 24h reusable.
- **Mesh IP auto-discovery fallback**: Script retries `tailscale ip -4` 3× with 5s sleep, then falls back to `MESH_IP` env var if admin provided one at enrollment. Hard fail with clear error if both empty.
- **Security**: `POST /api/nodes/{node_id}/mesh-ip` requires `X-Node-API-Key` header — the setup script already has this as `HUB_API_KEY`. No new auth surface needed.
- **The `/install` token route (line 3213)**: Once `_generate_bash_installer` no longer raises, this route works again. Its call signature needs `headscale_authkey` fetched from DB for the node.
- **No docker-compose edits on hub**: The fix avoids hub-side file mutations entirely. The node downloads its own `docker-compose.node.yml` from the hub's file-serving endpoints (already exist at `/api/nodes/docker-compose.node.yml`).
