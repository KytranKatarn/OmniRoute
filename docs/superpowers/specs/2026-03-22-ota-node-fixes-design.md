# OTA & Node .246 Fix Design

**Date**: 2026-03-22
**Tasks**: #1249, #1250, #1251, #1252, #1253, #1254
**Decision**: #256 (Node OTA critical gaps)
**Approach**: All 6 fixes in one pass

---

## Problem

The OTA system is architecturally sound (hub queues commands in `mesh_sync_log`, node polls every 60s, processes handlers, sends ACK) but has 6 gaps that make it unreliable for production use with node .246 (USS-Kytran, RTX 3070, Windows host).

## Fix 1: OTA Result Visibility (#1249, P10)

**Root cause**: Hub ACK handler (`mesh_routes.py:640-648`) stores only `status` and `error_message`. The `result` dict (shell output, exit codes, download stats) sent by the node is discarded. The `mesh_sync_log` table has no column for it.

**Changes**:
- **Migration**: Add `result_payload JSONB` column to `mesh_sync_log`
- **`mesh_routes.py`** (`mesh_ack_sync`, ~line 640): Store `data.get("result")` into `result_payload` in the UPDATE statement
- **`ota_routes.py`** (`api_get_sync_log`, ~line 385): Add `result_payload` to the SELECT query and include it in the JSON response

**Verification**: Push a `shell_exec` command (e.g., `echo hello`), confirm the output appears in the sync log API response.

## Fix 2: Sync Poller Resilience (#1250, P10)

**Root cause**: The main loop (`node_sync.py:2032-2036`) already has crash protection. Per-sync error handling (`node_sync.py:707-714`) also catches handler exceptions. The actual issue was a handler crash that left stale `sent` entries (IDs 157-162 in DB, all `cancelled` manually).

**Changes**:
- **`node_sync.py`** (`poll_syncs`, handler try/except block): Log full traceback via `logger.exception()` instead of `logger.error("...: %s", exc)` for better post-mortem debugging
- **`node_sync.py`** (`poll_syncs`, after fetching syncs): Add stale sync expiry — if a sync's `sent_at` is >24h old, auto-ACK as `expired` instead of executing. Prevents stale commands from re-executing after a node restart.

**Verification**: Trigger a handler error (e.g., invalid payload), confirm poller logs full traceback and continues processing remaining syncs. Confirm stale entries are auto-expired.

## Fix 3: ComfyUI Checkpoint Visibility (#1251 + #1253, P10/P8)

**Root cause**: Volume mapping is correct — both sync (`/comfyui/models`) and ComfyUI (`/app/models`) containers mount the `comfyui_data` volume. Files land in the right place but ComfyUI doesn't hot-reload; it needs a container restart to detect new checkpoints. Additionally, hub code references `archie_comfyui` but node containers use `archie_starship_comfyui`.

**Changes**:
- **`node_sync.py`**: Add constant `NODE_COMFYUI_CONTAINER = "archie_starship_comfyui"` near top of file
- **`node_sync.py`** (`_handle_checkpoint_pull`, after successful move ~line 1372): Call `_restart_container(NODE_COMFYUI_CONTAINER)` to trigger ComfyUI to rescan models. Include restart result in the return dict.
- **Hub code**: Any hub references to node ComfyUI container names should use metadata from `remote_nodes` rather than hardcoding `archie_comfyui`. Hub's own ComfyUI name stays as-is.

**Verification**: Push a `checkpoint_pull` for a known model, confirm ComfyUI auto-restarts and the model appears in ComfyUI's `/object_info` or checkpoint list.

## Fix 4: Firewall via BEACON (#1252, P9)

**Root cause**: `shell_exec` runs inside Docker — cannot modify Windows host firewall. BEACON (`node_api.py`, port 3001) runs on the host but only serves health and compose-recreate endpoints.

**Changes**:
- **`node_api.py`**: Add `POST /api/firewall-rule` endpoint that accepts `{port, protocol, action, name}` and executes `netsh advfirewall firewall add rule` (Windows) or `ufw allow` (Linux). Restricted to ports 11434, 8188, 3001 only (allowlist).
- **`node_sync.py`**: Add `firewall_rule` sync type handler that forwards the request to BEACON's new endpoint via HTTP POST to `localhost:3001/api/firewall-rule`.

**Verification**: Push a `firewall_rule` sync command for port 8188, confirm BEACON executes the netsh command and returns success.

## Fix 5: SSH Toggle Removal + Tailscale Status (#1254, P9)

**Root cause**: `_handle_ssh_toggle` calls `systemctl start sshd` — fails inside container and not available on Windows. Tailscale container exists in `docker-compose.node.yml` but needs an auth key.

**Changes**:
- **`node_sync.py`** (`_handle_ssh_toggle`): Replace implementation with a platform-aware response: return `{"status": "not_supported", "error": "SSH toggle not available on this platform. Use Tailscale or BEACON for remote access."}`. Keep the handler registered so hub doesn't get "unknown sync_type" errors.
- **`node_sync.py`**: Add `tailscale_status` sync type handler that checks if the `archie_starship_tailscale` container is running via Docker socket API and returns its status.
- **Tailscale auth**: Auth key provisioning is an installer concern, not an OTA concern. Document that `HEADSCALE_AUTHKEY` must be set in `.env` during node setup.

**Verification**: Push `ssh_toggle` → get clear "not supported" message. Push `tailscale_status` → get container running/stopped status.

## Files Modified

| File | Type | Changes |
|------|------|---------|
| `database/migrations/XXX_mesh_sync_result.sql` | New | Add `result_payload JSONB` column |
| `platform_v2/tools/starbase/mesh_routes.py` | Edit | Store result in ACK handler (~line 640) |
| `platform_v2/tools/starship/ota_routes.py` | Edit | Include `result_payload` in sync-log query |
| `node_client/node_sync.py` | Edit | 5 changes: traceback logging, stale expiry, ComfyUI restart, container name constant, SSH toggle neuter, tailscale_status handler |
| `node_client/node_api.py` | Edit | Add firewall-rule endpoint |

## Not In Scope

- No UI changes — sync log API already feeds Starship Operations tab
- No docker-compose.node.yml changes — volume mappings are correct
- No arbitrary Windows firewall manipulation — installer handles initial rules
- No SSH on Windows — use BEACON + Tailscale instead
- No changes to hub's own ComfyUI container name (`archie_comfyui`)

## Risk Assessment

- **Low risk**: All changes are additive (new DB column, new fields in responses, new handlers)
- **No breaking changes**: Existing ACK payloads without `result` store NULL; existing SSH toggle calls get a clean "not supported" response
- **Rollback**: Migration adds a column (can be dropped); code changes are independent per-fix

## Verification Plan

1. Push `shell_exec` via OTA → confirm output in sync log API
2. Push `checkpoint_pull` → confirm ComfyUI restarts and detects model
3. Trigger handler error → confirm poller continues + logs full traceback
4. Verify stale syncs from previous session auto-expire
5. Push `tailscale_status` → get container status
6. Push `firewall_rule` via BEACON → confirm netsh execution
