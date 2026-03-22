# OTA & Node .246 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 6 critical OTA gaps (#1249-#1254) so the hub can reliably manage node .246 (USS-Kytran) remotely — see results of commands, survive errors, detect checkpoints, and manage firewall/connectivity.

**Architecture:** Hub stores OTA results in a new JSONB column on `mesh_sync_log`. Node poller gets stale-sync expiry and full traceback logging. Checkpoint pulls auto-restart ComfyUI. Firewall management routes through BEACON (node_api) with localhost-only auth. SSH toggle neutered; Tailscale status queryable.

**Tech Stack:** Python/Flask, PostgreSQL, Docker Engine API (Unix socket), psycopg2

**Spec:** `docs/superpowers/specs/2026-03-22-ota-node-fixes-design.md`

---

### Task 1: DB Migration — Add result_payload column (#1249)

**Files:**
- Create: `database/migrations/183_mesh_sync_result_payload.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 183: Add result_payload JSONB to mesh_sync_log
-- Stores the full result dict from node ACKs (shell output, exit codes, download stats)
ALTER TABLE mesh_sync_log
ADD COLUMN IF NOT EXISTS result_payload JSONB;

COMMENT ON COLUMN mesh_sync_log.result_payload IS 'Full result dict from node handler ACK (output, exit_code, etc.)';
```

- [ ] **Step 2: Run the migration**

Run: `docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/183_mesh_sync_result_payload.sql`

Note: The migrations dir is mounted at `/docker-entrypoint-initdb.d/` in the container. If not, copy the file first:
`docker cp database/migrations/183_mesh_sync_result_payload.sql archie_database:/tmp/ && docker exec archie_database psql -U archie -d archie -f /tmp/183_mesh_sync_result_payload.sql`

Expected: `ALTER TABLE`

- [ ] **Step 3: Verify column exists**

Run: `docker exec archie_database psql -U archie -d archie -c "\d mesh_sync_log" | grep result_payload`

Expected: `result_payload | jsonb |`

- [ ] **Step 4: Commit**

```bash
git add database/migrations/183_mesh_sync_result_payload.sql
git commit -m "feat(db): add result_payload JSONB to mesh_sync_log (#1249)"
```

---

### Task 2: Hub ACK handler — Store result payload (#1249)

**Files:**
- Modify: `platform_v2/tools/starbase/mesh_routes.py:640-647`

- [ ] **Step 1: Update the UPDATE statement to include result_payload**

In `mesh_ack_sync()` at line 640-647, change the UPDATE to also store `ack_payload` (already extracted at line 612 as `data.get("result")`):

```python
                # Update status
                cur.execute(
                    """
                    UPDATE mesh_sync_log
                    SET status = %s, acknowledged_at = NOW(), error_message = %s,
                        result_payload = %s
                    WHERE id = %s
                    RETURNING id, acknowledged_at
                    """,
                    (status, error_message, psycopg2.extras.Json(ack_payload), sync_id),
                )
```

**IMPORTANT**: `mesh_routes.py` does NOT import `psycopg2`. Add `import psycopg2.extras` to the imports section (around line 13, alongside the other stdlib imports). Without this, the `psycopg2.extras.Json()` call will raise `NameError` at runtime.

- [ ] **Step 2: Add psycopg2.extras import**

Add to the imports section of `mesh_routes.py` (around line 13):
```python
import psycopg2.extras
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starbase/mesh_routes.py
git commit -m "feat(mesh): store OTA result_payload in ACK handler (#1249)"
```

---

### Task 3: Sync log endpoint — Return result_payload (#1249)

**Files:**
- Modify: `platform_v2/tools/starship/ota_routes.py:385-409`

- [ ] **Step 1: Add result_payload to SELECT query**

In `api_get_sync_log()` at line 385-394, add `result_payload` to the SELECT:

```python
                cur.execute(
                    """
                    SELECT id, sync_type, status, sent_at, acknowledged_at,
                           error_message, result_payload
                    FROM mesh_sync_log
                    WHERE node_id = %s
                    ORDER BY sent_at DESC
                    LIMIT 10
                    """,
                    (node_id_str,),
                )
```

- [ ] **Step 2: Add result_payload to JSON response**

In the `logs.append()` block at line 400-408, add the field:

```python
            logs = []
            for r in rows:
                logs.append(
                    {
                        "id": r["id"],
                        "sync_type": r["sync_type"],
                        "status": r["status"],
                        "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                        "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
                        "error_message": r["error_message"],
                        "result_payload": r["result_payload"],
                    }
                )
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/ota_routes.py
git commit -m "feat(ota): return result_payload in sync-log endpoint (#1249)"
```

---

### Task 4: Sync poller resilience — Traceback + stale expiry (#1250)

**Files:**
- Modify: `node_client/node_sync.py:697-714`

- [ ] **Step 1: Upgrade error logging to full traceback**

At line 711-712, change `logger.error` to `logger.exception` for full traceback:

```python
        except Exception as exc:
            logger.exception("Sync #%s handler failed", sync_id)
            ack_status = "failed"
            error_message = str(exc)
```

`logger.exception()` automatically includes the traceback — no need for `import traceback`.

- [ ] **Step 2: Add stale sync expiry after fetching syncs**

After the `if not syncs: return` block (line 693) and before the `for sync_item in syncs:` loop (line 697), add stale detection. Insert between lines 695 and 697:

First, add `from datetime import datetime, timezone, timedelta` to the **top-level imports** of `node_sync.py` (after line 28, with the other stdlib imports). The `datetime` module is NOT currently imported despite `time` being there.

```python
    # Filter out stale syncs (>24h old) — auto-expire them
    now = datetime.now(timezone.utc)
    fresh_syncs = []
    for sync_item in syncs:
        sent_at_str = sync_item.get("sent_at")
        if sent_at_str:
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                age = now - sent_at
                if age > timedelta(hours=24):
                    sync_id = sync_item.get("id")
                    logger.warning(
                        "Sync #%s is stale (%.1fh old) — auto-expiring",
                        sync_id, age.total_seconds() / 3600,
                    )
                    # ACK as expired
                    ack_url = f"{config['hub_url']}/tools/starbase/api/mesh/sync/{sync_id}/ack"
                    ack_payload = {
                        "node_id": config["node_id"],
                        "status": "expired",
                        "error_message": f"Stale sync expired after {age.total_seconds() / 3600:.1f}h",
                        "result": {"status": "expired"},
                    }
                    http_post(ack_url, ack_payload, _auth_headers(config))
                    continue
            except (ValueError, TypeError):
                pass  # If we can't parse sent_at, process normally
        fresh_syncs.append(sync_item)
    syncs = fresh_syncs
```

Then update the existing `for sync_item in syncs:` loop — it now iterates over filtered syncs automatically (no changes needed to the loop itself).

- [ ] **Step 3: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(node): add full traceback logging + stale sync expiry (#1250)"
```

---

### Task 5: ComfyUI restart after checkpoint pull (#1251 + #1253)

**Files:**
- Modify: `node_client/node_sync.py:1-30` (constant), `node_client/node_sync.py:1372-1386` (restart), `node_client/node_sync.py:1675` (existing hardcode)

- [ ] **Step 1: Add NODE_COMFYUI_CONTAINER constant**

Near the top of node_sync.py, after the imports block (around line 30), add:

```python
# Container name for ComfyUI on starship nodes
NODE_COMFYUI_CONTAINER = "archie_starship_comfyui"
```

- [ ] **Step 2: Add ComfyUI restart after checkpoint move**

In `_handle_checkpoint_pull()`, after the move log at line 1372 (`logger.info("[checkpoint_pull] Moved to %s", dest)`) and before the elapsed calculation at line 1374 (`elapsed = time.time() - start`), insert:

```python
        # Restart ComfyUI so it detects the new checkpoint
        restart_ok, restart_msg = _restart_container(NODE_COMFYUI_CONTAINER)
        if restart_ok:
            logger.info("[checkpoint_pull] ComfyUI restarted to detect %s", filename)
        else:
            logger.warning("[checkpoint_pull] ComfyUI restart failed: %s", restart_msg)
```

Then update the return dict at line 1380-1386 to include restart status:

```python
        return {
            "status": "completed",
            "filename": filename,
            "size_bytes": dl_size,
            "elapsed_seconds": round(elapsed, 1),
            "speed_mbps": round(speed_mbps, 1),
            "comfyui_restarted": restart_ok,
        }
```

- [ ] **Step 3: Update _handle_comfyui_setup hardcode**

At line 1675, change:
```python
    container_name = "archie_starship_comfyui"
```
to:
```python
    container_name = NODE_COMFYUI_CONTAINER
```

- [ ] **Step 4: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(node): auto-restart ComfyUI after checkpoint pull + container name constant (#1251, #1253)"
```

---

### Task 6: BEACON firewall endpoint (#1252)

**Files:**
- Modify: `node_client/node_api.py` (add new route, ~after line 346)

- [ ] **Step 1: Add firewall-rule endpoint to node_api.py**

Add after the existing `compose_recreate()` route:

```python
@app.route("/api/firewall-rule", methods=["POST"])
def firewall_rule():
    """Add a firewall rule on the host. Localhost-only, port-restricted."""
    # Security: only accept from localhost (sync container)
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"success": False, "error": "Forbidden: localhost only"}), 403

    data = request.get_json() or {}
    port = data.get("port")
    protocol = data.get("protocol", "tcp")
    rule_name = data.get("name", f"ARCHIE-{port}-{protocol}")

    # Port allowlist
    ALLOWED_PORTS = {11434, 8188, 3001}
    if not port or int(port) not in ALLOWED_PORTS:
        return jsonify({
            "success": False,
            "error": f"Port not in allowlist. Allowed: {sorted(ALLOWED_PORTS)}",
        }), 400

    port = int(port)
    import subprocess
    import platform as _platform

    try:
        if _platform.system() == "Windows":
            cmd = [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={rule_name}",
                "dir=in", "action=allow",
                f"protocol={protocol}",
                f"localport={port}",
            ]
        else:
            cmd = ["ufw", "allow", f"{port}/{protocol}"]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        output = result.stdout + result.stderr

        return jsonify({
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": output[:1000],
            "command": " ".join(cmd),
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        logger.exception("Firewall rule failed")
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Add firewall_rule sync handler to node_sync.py**

In the `handlers` dict in `handle_sync()` (node_sync.py:738-752), add:

```python
        "firewall_rule": _handle_firewall_rule,
```

Then add the handler function after `_handle_shell_exec` (around line 1543):

```python
def _handle_firewall_rule(config, payload):
    """
    Forward a firewall rule request to BEACON (node_api) on localhost.
    BEACON runs on the host and can modify the OS firewall.

    Expected payload:
        port (int): Port to open (must be in allowlist: 11434, 8188, 3001)
        protocol (str): tcp or udp (default tcp)
        name (str): Rule name (optional)
    """
    port = payload.get("port")
    if not port:
        return {"status": "failed", "error": "port is required"}

    beacon_url = "http://localhost:3001/api/firewall-rule"
    beacon_payload = {
        "port": int(port),
        "protocol": payload.get("protocol", "tcp"),
        "name": payload.get("name", f"ARCHIE-{port}"),
    }

    try:
        status_code, resp = http_post(beacon_url, beacon_payload, {})
        if 200 <= status_code < 300:
            return {
                "status": "completed",
                "beacon_response": resp,
            }
        else:
            return {
                "status": "failed",
                "error": f"BEACON returned HTTP {status_code}",
                "beacon_response": resp,
            }
    except Exception as e:
        return {"status": "failed", "error": f"BEACON unreachable: {e}"}
```

- [ ] **Step 3: Commit**

```bash
git add node_client/node_api.py node_client/node_sync.py
git commit -m "feat(node): add BEACON firewall endpoint + OTA handler (#1252)"
```

---

### Task 7: Neuter SSH toggle + add Tailscale status (#1254)

**Files:**
- Modify: `node_client/node_sync.py:1495-1542` (SSH toggle), `node_client/node_sync.py:738-752` (handlers dict)

- [ ] **Step 1: Replace _handle_ssh_toggle implementation**

Replace the entire `_handle_ssh_toggle` function (lines 1545-end of function) with:

```python
def _handle_ssh_toggle(config, payload):
    """
    SSH toggle is not supported on containerized/Windows nodes.
    Kept as a registered handler to avoid 'unknown sync_type' errors.
    Use Tailscale or BEACON (port 3001) for remote access instead.
    """
    logger.info("[ssh_toggle] Not supported on this platform — use Tailscale or BEACON")
    return {
        "status": "not_supported",
        "error": "SSH toggle not available on this platform. Use Tailscale or BEACON for remote access.",
        "platform": platform.system(),
    }
```

- [ ] **Step 2: Add tailscale_status handler**

Add to the `handlers` dict in `handle_sync()` (node_sync.py:738-752):

```python
        "tailscale_status": _handle_tailscale_status,
```

Add the handler function after the neutered `_handle_ssh_toggle`:

```python
def _handle_tailscale_status(config, payload):
    """
    Check if the Tailscale container is running on this node.
    Uses Docker Engine API via Unix socket.
    """
    container_name = "archie_starship_tailscale"
    logger.info("[tailscale_status] Checking container %s", container_name)

    try:
        code, body = _docker_api("GET", f"/containers/{container_name}/json")
        if code == 200:
            info = json.loads(body)
            state = info.get("State", {})
            return {
                "status": "completed",
                "container_running": state.get("Running", False),
                "container_status": state.get("Status", "unknown"),
                "started_at": state.get("StartedAt", ""),
            }
        elif code == 404:
            return {
                "status": "completed",
                "container_running": False,
                "container_status": "not_found",
                "error": "Tailscale container does not exist",
            }
        else:
            return {
                "status": "completed",
                "container_running": False,
                "error": f"Docker API returned HTTP {code}",
            }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Docker API error: {e}",
        }
```

- [ ] **Step 3: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(node): neuter SSH toggle + add tailscale_status handler (#1254)"
```

---

### Task 8: Restart platform + end-to-end verification

**Files:** None (verification only)

- [ ] **Step 1: Restart the platform to pick up hub-side changes**

```bash
docker compose restart archie_platform
```

Wait 15s for startup, then verify:
```bash
docker logs archie_platform --tail 20 2>&1 | grep -i "running\|error"
```

- [ ] **Step 2: Test result visibility — push shell_exec**

Via the Starship UI or direct API call:
```bash
curl -s -X POST http://192.168.1.200:3000/tools/starship/api/nodes/2/push-shell-exec \
  -H "Content-Type: application/json" \
  -d '{"command": "echo OTA_TEST_OK && hostname"}' \
  -b "session=<admin_session_cookie>"
```

Wait 60s (one poll cycle), then check the sync log:
```bash
curl -s http://192.168.1.200:3000/tools/starship/api/nodes/2/sync-log \
  -b "session=<admin_session_cookie>" | python3 -m json.tool
```

Expected: Latest entry shows `result_payload` with `output` containing "OTA_TEST_OK".

- [ ] **Step 3: Test stale sync expiry**

Check DB for any stale `sent` entries:
```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT id, sync_type, status, sent_at
  FROM mesh_sync_log
  WHERE status = 'sent' AND sent_at < NOW() - INTERVAL '24 hours'
"
```

If any exist, they should be auto-expired on next poll cycle.

- [ ] **Step 4: Test checkpoint pull + ComfyUI restart**

This requires a real checkpoint URL. Use a small test file first:
```bash
curl -s -X POST http://192.168.1.200:3000/tools/starship/api/nodes/2/pull-checkpoint \
  -H "Content-Type: application/json" \
  -d '{"url": "https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors", "filename": "sd_xl_turbo_1.0_fp16.safetensors"}' \
  -b "session=<admin_session_cookie>"
```

After completion, check sync log for `comfyui_restarted: true` in `result_payload`.

- [ ] **Step 5: Test tailscale_status**

Push via mesh sync or direct DB insert, then check result after poll cycle.

- [ ] **Step 6: Update Dev HQ tasks**

Use MCP tools:
- `complete_task` for #1249, #1250, #1251, #1252, #1253, #1254
- `update_project_understanding` for the node fleet project
- `log_decision` if any design choices changed during implementation

- [ ] **Step 7: Final commit — bump version if needed**

```bash
git add database/migrations/183_mesh_sync_result_payload.sql \
       platform_v2/tools/starbase/mesh_routes.py \
       platform_v2/tools/starship/ota_routes.py \
       node_client/node_sync.py \
       node_client/node_api.py
git status  # Review what's staged — no unintended files
git commit -m "feat(ota): complete 6-fix OTA overhaul for node .246 (#1249-#1254)"
```
