# Node Docker-Only Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy ARCHIE nodes to Windows/Mac/Linux using only Docker images pulled from a registry — zero local files, zero build steps, zero bind mounts for code.

**Architecture:** Publish `ghcr.io/kytranempowerment/archie-node:latest` via GitHub Actions. Rewrite docker-compose.node.yml to use `image:` instead of `build:`. Starship UI serves a ZIP with pre-configured compose + .env + start scripts. OTA updates = image pull, not file manipulation.

**Tech Stack:** Docker, GitHub Actions, GitHub Container Registry (ghcr.io), Python/Flask (hub endpoints), YAML (compose)

**Spec:** `docs/superpowers/specs/2026-03-22-node-docker-only-deployment-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/build-node-image.yml` | CREATE | Build + push Docker image to ghcr.io |
| `node_client/docker-compose.node.yml` | REWRITE | Pull-only compose, zero build/bind mounts |
| `node_client/start.bat` | CREATE | Windows one-click start |
| `node_client/start.command` | CREATE | Mac one-click start |
| `node_client/stop.bat` | CREATE | Windows graceful stop |
| `node_client/stop.command` | CREATE | Mac graceful stop |
| `node_client/update.bat` | CREATE | Windows pull + restart |
| `node_client/update.command` | CREATE | Mac pull + restart |
| `platform_v2/tools/starship/node_routes.py` | MODIFY | Add ZIP download endpoint |
| `node_client/node_sync.py` | MODIFY | Add `docker_cleanup` OTA handler |

---

### Task 1: GitHub Actions Workflow — Build and Push Node Image

**Files:**
- Create: `.github/workflows/build-node-image.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Build & Push ARCHIE Node Image

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'node_client/node_sync.py'
      - 'node_client/node_api.py'
      - 'node_client/node_triage.py'
      - 'node_client/requirements.txt'
      - 'node_client/Dockerfile.node'
      - 'node_client/migrations/**'

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: kytranempowerment/archie-node

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest
            type=sha,prefix=

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: node_client
          file: node_client/Dockerfile.node
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- [ ] **Step 2: Verify the workflow is valid YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/build-node-image.yml'))"`
Expected: No error

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/build-node-image.yml
git commit -m "feat(node): add GitHub Actions workflow to build and push node Docker image to ghcr.io"
```

---

### Task 2: Rewrite docker-compose.node.yml — Pull-Only, Zero Build

**Files:**
- Rewrite: `node_client/docker-compose.node.yml`

- [ ] **Step 1: Replace the entire compose file**

Write the new compose file with these changes from the old one:
- `sync` service: `image: ghcr.io/kytranempowerment/archie-node:latest` instead of `build:`
- `node_api` service: same image, instead of `build:`
- Remove ALL bind mounts for `.py` files (`./node_sync.py:/app/node_sync.py` etc.)
- Remove bind mount for `./docker-compose.node.yml:/app/docker-compose.node.yml:ro`
- Remove bind mount for `./migrations:/app/migrations`
- Keep Docker socket mount (`/var/run/docker.sock`) — needed for container management
- Keep named volumes (`ollama_data`, `pg_data`, `comfyui_data`)
- Remove Tailscale service (defer)
- Remove `tailscale_data` volume
- Rename containers: `archie_node_*` instead of `archie_starship_*`
- Remove `starship_net`, use `archie_net`

The full compose is in the spec file. Write it exactly as specified.

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('node_client/docker-compose.node.yml'))"`
Expected: No error

- [ ] **Step 3: Verify no bind mounts for Python files**

Run: `grep -n 'node_sync.py\|node_api.py\|node_triage.py\|Dockerfile' node_client/docker-compose.node.yml`
Expected: Zero matches (none of these files referenced as bind mounts)

- [ ] **Step 4: Verify image references**

Run: `grep 'ghcr.io' node_client/docker-compose.node.yml`
Expected: Two lines — sync and node_api both referencing `ghcr.io/kytranempowerment/archie-node:latest`

- [ ] **Step 5: Commit**

```bash
git add node_client/docker-compose.node.yml
git commit -m "feat(node): rewrite compose to pull-only — zero build steps, zero code bind mounts"
```

---

### Task 3: Create Start/Stop/Update Scripts

**Files:**
- Create: `node_client/start.bat`
- Create: `node_client/start.command`
- Create: `node_client/stop.bat`
- Create: `node_client/stop.command`
- Create: `node_client/update.bat`
- Create: `node_client/update.command`

- [ ] **Step 1: Create Windows scripts**

`start.bat`:
```batch
@echo off
echo Starting A.R.C.H.I.E. Node...
docker compose up -d
echo.
echo Node started! You can close this window.
pause
```

`stop.bat`:
```batch
@echo off
echo Stopping A.R.C.H.I.E. Node...
docker compose down
echo.
echo Node stopped.
pause
```

`update.bat`:
```batch
@echo off
echo Updating A.R.C.H.I.E. Node...
docker compose pull
docker compose up -d
echo.
echo Node updated!
pause
```

- [ ] **Step 2: Create Mac scripts**

`start.command`:
```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "Starting A.R.C.H.I.E. Node..."
docker compose up -d
echo ""
echo "Node started! You can close this window."
```

`stop.command`:
```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "Stopping A.R.C.H.I.E. Node..."
docker compose down
echo ""
echo "Node stopped."
```

`update.command`:
```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "Updating A.R.C.H.I.E. Node..."
docker compose pull
docker compose up -d
echo ""
echo "Node updated!"
```

- [ ] **Step 3: Make Mac scripts executable**

Run: `chmod +x node_client/start.command node_client/stop.command node_client/update.command`

- [ ] **Step 4: Commit**

```bash
git add node_client/start.bat node_client/stop.bat node_client/update.bat
git add node_client/start.command node_client/stop.command node_client/update.command
git commit -m "feat(node): add one-click start/stop/update scripts for Windows and Mac"
```

---

### Task 4: Add ZIP Download Endpoint to Starship

**Files:**
- Modify: `platform_v2/tools/starship/node_routes.py`

This endpoint generates a ZIP file containing docker-compose.yml, .env (pre-filled), and start/stop/update scripts for a specific node. The admin clicks "Download" in Starship UI and gives the ZIP to the node operator.

- [ ] **Step 1: Read the existing node_routes.py to find where to add the endpoint**

The file already has `download_node_package()` at line ~489 and setup script routes at line ~698. Add the new endpoint near these.

- [ ] **Step 2: Add the ZIP download endpoint**

Add this route inside `register_node_routes()`:

```python
@bp.route("/api/nodes/<node_id>/download-zip")
@login_required
def api_download_node_zip(node_id):
    """Generate and serve a ZIP with everything needed to run a node.

    Contains: docker-compose.yml, .env (pre-filled), start/stop/update
    scripts for Windows and Mac. Zero build steps required.
    """
    import io
    import zipfile

    # Get node info
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT node_id, node_name, setup_token FROM remote_nodes WHERE node_id = %s",
            (node_id,),
        )
        node = cur.fetchone()
        if not node:
            return jsonify({"error": "Node not found"}), 404

        api_key = node.get("setup_token", "")
        node_name = node.get("node_name", "archie-node")

    # Hub URL for node to connect to
    hub_url = request.host_url.rstrip("/")
    # Prefer external URL if configured
    external_url = os.environ.get("EXTERNAL_URL", hub_url)

    # Read the compose template
    compose_path = os.path.join(NODE_CLIENT_DIR, "docker-compose.node.yml")
    if not os.path.exists(compose_path):
        return jsonify({"error": "Compose template not found"}), 500
    with open(compose_path) as f:
        compose_content = f.read()

    # Generate .env
    env_content = (
        f"NODE_ID={node_id}\n"
        f"NODE_NAME={node_name}\n"
        f"HUB_URL={external_url}\n"
        f"HUB_API_KEY={api_key}\n"
        f"DB_PASSWORD=archie_node_default\n"
        f"OLLAMA_PORT=11434\n"
        f"NODE_API_PORT=3001\n"
        f"COMFYUI_PORT=8188\n"
    )

    # Read script templates
    scripts = {}
    for script_name in ["start.bat", "stop.bat", "update.bat",
                        "start.command", "stop.command", "update.command"]:
        script_path = os.path.join(NODE_CLIENT_DIR, script_name)
        if os.path.exists(script_path):
            with open(script_path) as f:
                scripts[script_name] = f.read()

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docker-compose.yml", compose_content)
        zf.writestr(".env", env_content)
        for name, content in scripts.items():
            zf.writestr(name, content)
        zf.writestr("README.txt",
            "A.R.C.H.I.E. Node — by Kytran Empowerment\n"
            "==========================================\n\n"
            "Prerequisites:\n"
            "  1. Install Docker Desktop from https://docker.com/products/docker-desktop\n"
            "  2. Start Docker Desktop\n\n"
            "Setup:\n"
            "  1. Extract this folder anywhere on your computer\n"
            "  2. Double-click start.bat (Windows) or start.command (Mac)\n"
            "  3. Wait ~2 minutes for containers to download and start\n"
            "  4. Your node will appear in the fleet automatically\n\n"
            "Commands:\n"
            "  start.bat / start.command   — Start the node\n"
            "  stop.bat / stop.command     — Stop the node\n"
            "  update.bat / update.command — Update to latest version\n\n"
            f"Node ID: {node_id}\n"
            f"Hub: {external_url}\n"
        )
    buf.seek(0)

    safe_name = node_name.replace(" ", "-").lower()
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="ARCHIE-Node-{safe_name}.zip"'
        },
    )
```

- [ ] **Step 3: Add NODE_CLIENT_DIR constant if not already defined**

Check if `NODE_CLIENT_DIR` exists in the file. If not, add near the top of `register_node_routes()`:
```python
NODE_CLIENT_DIR = "/mnt/archie_brain/node_client"
```

- [ ] **Step 4: Verify the endpoint loads without syntax errors**

Run: `docker exec archie_platform python3 -c "from tools.starship.node_routes import register_node_routes; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/starship/node_routes.py
git commit -m "feat(node): add ZIP download endpoint — pre-configured compose + scripts per node"
```

---

### Task 5: Add docker_cleanup OTA Handler to node_sync.py

**Files:**
- Modify: `node_client/node_sync.py`

- [ ] **Step 1: Add docker_cleanup to the handler dispatch table**

In `handle_sync()` (line ~769), the `handlers` dict maps sync types to functions. Add:

```python
"docker_cleanup": _handle_docker_cleanup,
```

- [ ] **Step 2: Add the handler function**

Add near the other handler functions (after `_handle_shell_exec`):

```python
def _handle_docker_cleanup(config, payload):
    """Clean up Docker debris — dangling images, unused volumes, build cache.

    Actions:
        prune_all: docker system prune -af --volumes (nuclear — removes everything unused)
        prune_images: docker image prune -af (dangling + unused images only)
        prune_volumes: docker volume prune -f (unused volumes only)
        report: just report disk usage, don't clean
    """
    action = payload.get("action", "report")
    logger.info("[docker_cleanup] Action: %s", action)

    commands = {
        "prune_all": ["docker", "system", "prune", "-af", "--volumes"],
        "prune_images": ["docker", "image", "prune", "-af"],
        "prune_volumes": ["docker", "volume", "prune", "-f"],
    }

    result = {"action": action}

    # Get disk usage before
    try:
        df_out = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=10,
        )
        result["disk_before"] = df_out.stdout.strip()
    except Exception as e:
        result["disk_before"] = str(e)

    # Get docker disk usage
    try:
        du_out = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True, text=True, timeout=30,
        )
        result["docker_usage"] = du_out.stdout.strip()
    except Exception as e:
        result["docker_usage"] = str(e)

    if action == "report":
        logger.info("[docker_cleanup] Report only — no cleanup performed")
        return json.dumps(result)

    cmd = commands.get(action)
    if not cmd:
        logger.warning("[docker_cleanup] Unknown action: %s", action)
        return json.dumps({"error": f"Unknown action: {action}"})

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        result["output"] = proc.stdout.strip()
        result["exit_code"] = proc.returncode
        logger.info("[docker_cleanup] %s completed (exit %d)", action, proc.returncode)
    except subprocess.TimeoutExpired:
        result["error"] = "Cleanup timed out after 300s"
        logger.error("[docker_cleanup] Timed out")
    except Exception as e:
        result["error"] = str(e)
        logger.error("[docker_cleanup] Failed: %s", e)

    # Get disk usage after
    try:
        df_out = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=10,
        )
        result["disk_after"] = df_out.stdout.strip()
    except Exception:
        pass

    return json.dumps(result)
```

- [ ] **Step 3: Verify handle_sync dispatch table includes all types**

Run: `grep -A 20 "def handle_sync" node_client/node_sync.py | grep '"'`
Expected: Should show `docker_cleanup` in the handlers dict

- [ ] **Step 4: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(node): add docker_cleanup OTA handler — prune images, volumes, build cache"
```

---

### Task 6: Add pull_and_restart Action to container_restart Handler

**Files:**
- Modify: `node_client/node_sync.py`

The existing `_handle_container_restart` handler needs a new action that pulls fresh images before restarting. This is how OTA code updates work with the new image-based approach.

- [ ] **Step 1: Read the existing _handle_container_restart function**

It's at line ~834 in node_sync.py. Read it to understand the current structure.

- [ ] **Step 2: Add pull_and_restart action**

Inside `_handle_container_restart`, add a case for `action == "pull_and_restart"`:

```python
if action == "pull_and_restart":
    # Pull latest images then recreate containers
    logger.info("[container_restart] Pulling latest images...")
    pull_result = subprocess.run(
        ["docker", "compose", "pull"],
        capture_output=True, text=True, timeout=300,
        cwd="/app" if os.path.exists("/app/docker-compose.yml") else None,
    )
    logger.info("[container_restart] Pull: %s", pull_result.stdout[:200])

    logger.info("[container_restart] Restarting with new images...")
    up_result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        capture_output=True, text=True, timeout=120,
        cwd="/app" if os.path.exists("/app/docker-compose.yml") else None,
    )
    return json.dumps({
        "action": "pull_and_restart",
        "pull_output": pull_result.stdout[:500],
        "up_output": up_result.stdout[:500],
        "exit_code": up_result.returncode,
    })
```

Note: The sync container needs access to Docker socket AND the compose file. The compose file location depends on deployment — check if `/app/docker-compose.yml` exists (old style) or use Docker socket API directly.

Actually, since we removed bind mounts, the compose file lives on the HOST at wherever the user extracted the ZIP. The sync container can't directly run `docker compose` without knowing the compose file path on the host.

**Alternative approach:** Use Docker Engine API via the socket (already mounted) instead of `docker compose` CLI:

```python
if action == "pull_and_restart":
    # Use Docker Engine API to pull and restart
    import urllib.request

    # List our containers
    containers = ["archie_node_sync", "archie_node_api"]
    results = []

    for name in containers:
        try:
            # Pull the image
            req = urllib.request.Request(
                f"http+unix:///var/run/docker.sock/images/create?fromImage=ghcr.io/kytranempowerment/archie-node&tag=latest",
                method="POST",
            )
            # ... (use _docker_api helper if it exists)
        except Exception as e:
            results.append({"container": name, "error": str(e)})

    return json.dumps({"action": "pull_and_restart", "results": results})
```

**Simpler approach:** Since Docker socket is mounted, use `subprocess.run(["docker", "pull", "ghcr.io/kytranempowerment/archie-node:latest"])` then signal the hub that the node needs a restart. The user's `update.bat` handles the compose restart from the host side. For OTA-triggered updates, the sync container can pull the image but the actual restart has to come from the host's Docker Compose context.

**Recommended:** The OTA sends a notification to the user (via Starship UI) saying "Update available — click Update or run update.bat". For automated restarts, the sync container can use the Docker API to restart individual containers with the new image.

- [ ] **Step 3: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(node): add pull_and_restart action for image-based OTA updates"
```

---

### Task 7: Verify and Test End-to-End

**Files:** None (verification only)

- [ ] **Step 1: Validate all YAML files**

```bash
python3 -c "import yaml; yaml.safe_load(open('node_client/docker-compose.node.yml')); print('compose OK')"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/build-node-image.yml')); print('workflow OK')"
```

- [ ] **Step 2: Verify compose has zero build directives**

```bash
grep -c 'build:' node_client/docker-compose.node.yml
```
Expected: `0`

- [ ] **Step 3: Verify compose has zero Python file bind mounts**

```bash
grep -c '\.py:' node_client/docker-compose.node.yml
```
Expected: `0`

- [ ] **Step 4: Verify image references**

```bash
grep 'ghcr.io' node_client/docker-compose.node.yml
```
Expected: Two lines for sync and node_api

- [ ] **Step 5: Verify ZIP endpoint loads**

```bash
docker exec archie_platform python3 -c "from tools.starship.node_routes import register_node_routes; print('OK')"
```

- [ ] **Step 6: Verify node_sync.py has docker_cleanup handler**

```bash
grep 'docker_cleanup' node_client/node_sync.py
```
Expected: At least 2 matches (dispatch table + function def)

- [ ] **Step 7: Test ZIP endpoint manually**

```bash
curl -s -o /tmp/test-node.zip "http://localhost:3000/tools/starship/api/nodes/NODE_ID_HERE/download-zip" -b "session=..."
unzip -l /tmp/test-node.zip
```
Expected: ZIP contains docker-compose.yml, .env, start.bat, start.command, stop.bat, stop.command, update.bat, update.command, README.txt

---

## Notes for Implementation

1. **GitHub Container Registry requires the repo to have packages enabled.** The `GITHUB_TOKEN` secret is automatic for public repos. For private repos, a PAT with `write:packages` scope may be needed.

2. **The compose file path problem in Task 6:** The sync container can pull Docker images but can't run `docker compose up -d` because it doesn't have the compose file (it's on the host). Two options:
   - Mount the compose file read-only: `- ./docker-compose.yml:/app/docker-compose.yml:ro` (one small bind mount, acceptable since it's config not code)
   - Use Docker API directly to pull images and recreate containers

3. **First push to ghcr.io:** After Task 1 is committed and pushed, manually trigger the workflow via GitHub Actions UI to build the initial image. All subsequent pushes that touch node_client/ files will auto-build.

4. **Testing on .245:** After all tasks are done, the test is:
   - Push to GitHub, let Actions build the image
   - In Starship, create a node, download the ZIP
   - On .245: install Docker Desktop, extract ZIP, double-click start.bat
   - Verify node appears in Starship within 2 minutes
