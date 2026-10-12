# Fleet Rules

**Authoritative fleet reference.** (The old `starbase.md` was retired; its few unique facts — node RAM budget split, status badge labels — are not restated here, see git history.)

## Architecture

Department HQ Fleet tab owns all fleet management (merged from Starbase Command 2026-04-08).
- 7 route files inside `tools/department_hq/`
- Hub = primary; nodes join via Headscale mesh (100.64.0.x)

## Mesh Node Map (ALWAYS use mesh IPs for inter-cluster calls)

Names below are the 2026-06-04 canonical set (display `node_name` + headscale `given_name`). `node_id` is unchanged (renames are display-only). Full roster + audit: KB #270521.

| Display name | mesh given_name | LAN/Public IP | Mesh IP | DB id | GPU / VRAM | RAM | Role |
|------|------|--------|---------|-----|-----|-----|------|
| Archie Starbase (hub) | archie-starbase | 192.168.1.200 | 100.64.0.4 | 68 | **TITAN X (Pascal) 12GB + Quadro M4000 8GB** (20GB total) | 128GB | Platform core / dispatch hub. `BRIDGE_URL=100.64.0.4:3000` |
| Outpost - United States | outpost-us | 76.13.107.109 | 100.64.0.2 | 93 | None | 8GB | CPU outpost (Ashburn). **SSH `kytran@`** |
| Starship - Defiant - USS-246 | starship-246 | 192.168.1.246 | 100.64.0.3 | 115 | RTX 3070 8GB (**Defiant**) | 32GB | LAN GPU, 7B. SSH `Famil@` |
| Starship - Runabout - USS-245 | starship-245 | 192.168.1.245 | 100.64.0.6 | 120 | RTX 3050 4GB (**Runabout**) | 12GB | LAN GPU, small. SSH `Famil@` |
| ~~Outpost - Singapore~~ | outpost-singapore | 156.67.217.86 | 100.64.0.5 | 125 | None | 8GB | 🔴 **RETIRED 2026-08-29** (`remote_nodes.status='retired'`) |
| ~~Outpost - Lithuania~~ | outpost-lithuania | 72.62.112.210 | 100.64.0.7 | 126 | None | 8GB | 🔴 **RETIRED 2026-08-29** |
| ~~Outpost - United Kingdom~~ | outpost-uk | 2.24.130.153 | 100.64.0.8 | 127 | None | 8GB | 🔴 **RETIRED 2026-08-29** |
| Citadel - United States | citadel-us | 2.25.133.122 | 100.64.0.10 | 128 | None | 31GB | **DR warm-standby base** (boston-2): watch products + DR replica + ingress Caddy. SSH `root@` |
| ~~Beacon~~ | beacon | 2.25.170.252 | 100.64.0.11 | 129 | None | 4GB | 🔴 **GONE — the VPS was removed by Hostinger 2026-08-28.** Citadel inherited the front door as a container literally named `beacon`. Do NOT ssh to this IP; 5 DR scripts did and the whole ingress layer was inert (#3245/#3248). |

**NEVER** use public hostnames (`platform.kytranempowerment.com`) for inter-cluster traffic — Hostinger CDN caps at 60s, bypasses queue.

### Naming tiers & ship-class
- Tiers by role/scale: **Starbase** (hub) > **Citadel** (DR warm-standby base) > **Outpost** (CPU VPS, regional) > **Starship - `<class>` - USS-`<lan-octet>`** (LAN GPU) > ~~**Beacon** (ingress satellite)~~ — tier retired with the node; Citadel now holds the front door.
- GPU nodes auto-class from live `remote_nodes.gpu_vram_gb` via `ship_classes` table + `v_fleet_ship_class` view (migration 398). Ladder by VRAM: Runabout ≤4 / Nova 6 / Defiant 8 / Intrepid 12 / Constitution 16 / Galaxy 24 / Sovereign 48 / Dreadnought 80 / **Armada ≥81**. Re-tune via `UPDATE ship_classes` (no deploy). Hub + CPU outposts = NULL class.
  - ⚠️ **Armada is a VRAM tier (`min_vram_gb = 81`), NOT a "multi-GPU" class** — this file claimed the latter until 2026-07-25. A dual-GPU node classes on its LARGEST SINGLE card, not the sum.
  - ⚠️ **`remote_nodes.gpu_vram_gb` means LARGEST SINGLE GPU, not total.** `node_provisioning._fits()` (`gpu_vram_gb >= model.vram_gb + GPU_HEADROOM_GB`) and `agent_service.get_agents_for_hardware()` (`vram_need <= gpu_vram_gb`) both size ONE model against it. Writing the sum there tells the router a model fits in a card that cannot hold it. Total VRAM lives in `extra_capabilities.gpu_vram_total_gb` for reporting only.
    🔴 **CORRECTED 2026-08-15 — the old justification "on a mixed-architecture host a model generally cannot span cards anyway" is FALSE.** Ollama spans the hub's 6.1/5.2 cards routinely: `GPULayers:49[Quadro Layers:31(0..30), TITAN Layers:18(31..48)]` → `offloaded 49/49 layers to GPU` (live, `journalctl -u ollama`). **Keep `gpu_vram_gb = 12`** — the single-card value is still the right SAFETY input for `_fits()`/`get_agents_for_hardware()`, which size one model at a time — but keep it for that reason, not for a spanning limit that does not exist.
    **Operational consequence:** a spanning model eats headroom on BOTH cards simultaneously, which the placement logic does not anticipate. On 2026-08-15 that drove VRAM budget to **0.0 GB** and pushed `qwen2.5:7b` to CPU, causing an 89%-failure fact_check hour (`timeout after 240s`). Task **#5623**; detail in `ai-bridge.md`.

### Hub has THREE tailscale presences (don't confuse — KB #270520)
- `.4 archie-starbase` = host headscale tailscaled (`/var/lib/tailscale-hs`, `--tun=tailscale1`) — THE platform/dispatch hub (`BRIDGE_URL`, :3000, direct via public IP).
- `.1 archie-starbase-subnet` = the `archie_tailscale` Docker container (docker-compose.yml ~L760-800) — hub-LAN subnet router (`--advertise-routes=192.168.1.0/24 --ssh`). Route currently **Enabled=false** (dormant; platform reaches hub via `.4`). Do NOT delete — re-registers via authkey.
  - ⚠️ **Control-plane pin (PR #2344, task #4998).** Docker DNS forwards to the host's Tailscale resolver, which **SERVFAILs** for this zone, so `mesh.kytranempowerment.com` MUST be pinned in `extra_hosts` → **currently Citadel `2.25.133.122`** (measured live 2026-09-08: `HostConfig.ExtraHosts` = `["mesh.kytranempowerment.com:2.25.133.122"]`). ⚠️ This line said **Beacon `2.25.170.252`** until then — a host removed 2026-08-28 — and reading it cost real time during the 09-08 outage. Verify with `docker inspect archie_tailscale -f '{{json .HostConfig.ExtraHosts}}'`, never from this file. It previously pinned the hub `192.168.1.200` to reach NPM on :443; **NPM was decommissioned 2026-06-27 and the hub has no :443 listener**, which silently killed this node for 23 days (RestartCount 219, `last seen` frozen at the decommission timestamp).
  - **Keep `--login-server=https://mesh.kytranempowerment.com` byte-identical** to headscale's `config.yaml` `server_url`. Do NOT "simplify" it to the hub's `:8095` — headscale hands clients back its configured `server_url`, so a mismatch is a latent break. Only the DNS pin may move.
  - **`docker compose restart` does NOT apply `extra_hosts`** — use `docker compose up -d --no-deps archie_tailscale`. Identity survives (state in named volume `tailscale_hub_data`), so no re-registration → the identity invariants below stay intact.
  - Verify: `docker exec archie_headscale headscale nodes list` → node 15 `connected=online`. KB #282680 (user) / #282681 (coder) / #282676 (mistake).
- `100.79.11.3` = host's Tailscale.com client — a SEPARATE tailnet, not the mesh.
- `.9 shuttle-kytran` = Kytran personal device (not a fleet node).

### 🔴 `mesh.kytranempowerment.com` is PROTECTED — never repoint it in bulk (task #5219)

`mesh.` is the Headscale **control plane** and is **TLS-only**: clients are handed back
headscale's configured `server_url` (`https://mesh…`) and must reach it on **443**. Point it
at a host with no TLS listener and node enrollment/key rotation die.

**2026-07-26:** a bulk AdGuard repoint of all 15 rewrites → `192.168.1.200` swept `mesh.` in.
The recovery hub Caddy was HTTP-only (`auto_https off`), so **both LAN Starships dropped off
the mesh**. Reverting that ONE rewrite to Beacon (`2.25.170.252`) brought them back in ~2 min.
Kytran had flagged it in advance — *"wasnt this on beacon ?"* — and the general Caddy question
was answered without checking that specific hostname. **A categorical answer cannot discharge
a specific warning** (see `feedback_bulk-ops-are-n-decisions`).

This is the SAME failure class as the `archie_tailscale` `extra_hosts` pin above, which
silently killed that node for 23 days when NPM was decommissioned and the hub lost its `:443`
listener. Same hostname, same shape: a DNS/pin change made against a host that cannot serve
the scheme.

Now machine-enforced in three places — a remembered rule was not enough:
1. **`adguard_service.PROTECTED_REWRITES`** — `add_rewrite()` probes the new target for a
   443 listener and raises `ProtectedRewriteError` (route → **409** with the reason) unless
   the caller passes an explicit `force=True`. Fail-closed.
2. **`failover.sh` step 4f** — flips `mesh.` to boston-2 ONLY after Headscale DR actually
   ANSWERS on `:8095`; `docker compose up -d` exiting 0 means the container was *created*,
   not that anything is listening.
3. **`beacon_flip.sh`** — `:8095` is never part of the blanket/platform flip.

**Rule: `mesh.` must never resolve to a host with no TLS listener.** Adding a hostname to
`PROTECTED_REWRITES` is the way to extend this to any other control-plane name.

#### The control-plane UPSTREAM must be an outbound persistent tunnel (2026-07-26, task #5260)

DNS protection says what `mesh.` resolves to; the proxy's upstream is the other half. Never point
it at the mesh IP (`100.64.0.4:8095` — bootstrap deadlock: a hub reboot takes the fleet down and it
cannot self-recover) or the hub's public IP (a dynamic residential lease). The hub dials OUT via a
persistent `ssh -R` unit (`archie-mesh-tunnel.service`, `Restart=always`, **`ExitOnForwardFailure=yes`**
— without it the unit reads `active` while serving nothing; the peer needs `ClientAliveInterval 30` /
`CountMax 3` so a dead bind is reaped). `systemctl is-active` is NOT proof: verify by serving
`https://mesh.kytranempowerment.com/key?v=118` → 200 from an off-hub vantage. Never leave an ad-hoc
`ssh -L` running by hand.
⚠️ Written for Beacon, which was removed 2026-08-28 (Citadel now fronts as container `beacon`) — verify
the unit and its target before relying on the details. Full narrative: **KB #377830**.

## Fleet Route Files (`tools/department_hq/`)

| File | Purpose |
|------|---------|
| `fleet_dashboard_routes.py` | Overview, stats, map |
| `fleet_node_routes.py` | Node status, settings, onboarding, disconnect |
| `fleet_crew_routes.py` | Crew manifest, agent profiles, node stations |
| `fleet_mesh_routes.py` | Node lending, sync, Headscale mesh |
| `fleet_provider_routes.py` | Cloud providers, routing, ComfyUI |
| `fleet_dispatch_routes.py` | Cross-node dispatch, activity, analytics |
| `fleet_mission_routes.py` | SSE, command, profiles, flows |
| `fleet_ota_routes.py` | OTA push, sync, model pull |
| `fleet_helpers.py` | Shared constants + node lookup functions |

## Model Tiers by Node

| Tier | Nodes | Models |
|------|-------|--------|
| GPU small | Hub + Starship-246 + Starship-245 | `qwen2.5:1.5b`, `llama3.2:3b` |
| GPU mid | Starship-246 | `qwen2.5:7b`, `mistral:7b` |
| GPU large | Hub | `gemma3:12b`, `dolphin3:latest` + ComfyUI SDXL |
| CPU only | Outpost-us (VPS) | `qwen2.5:1.5b` (no GPU) |

## Cross-Node Dispatch

- `_find_fleet_agent()` + `_dispatch_to_node()` — cross-node dispatch in `fleet_dispatch_routes.py`
- Fleet agents keyed as `fleet:node_xxx:Name` — excluded from hub manifest
- `model-control` endpoint accepts `node_id` — routes to node Ollama when provided
- Escalation tier order: hub home dept → capability → cross-dept → **fleet node** → cloud

## Node Health + Lifecycle

- `check_fleet_health()` — job #45, every 30s
- Node offline (heartbeat stale >2min): agents → barracks, `node_agents` inactive
- Node online: agents restored from barracks; `_restore_model_state()` reloads models
- Heartbeat payload: `cpu_model, gpu_model, gpu_vram_gb, ram_gb, ollama_models`
- `model_load_state` table: tracks loaded models per host for restart recovery

## DB Tables (Fleet-specific)

| Table | Key columns |
|-------|-------------|
| `remote_nodes` | `hostname` (MUST be IP, not hostname), `deployment_mode`, `mesh_ip` |
| `node_agents` | `hub_agent_id`, `source_agent_id`, `node_id` |
| `model_load_state` | `node_host`, `model_name`, `loaded_at` |

## Headscale Mesh Admin

- Headscale UI: `http://192.168.1.200:8095` (or mesh.kytranempowerment.com)
- Enroll new node: `headscale nodes register --user default --key <machinekey>`
- Mesh IP assignment: auto from `100.64.0.0/10` range

## Key Gotchas

- `remote_nodes.hostname` MUST be IP (e.g. `192.168.1.246`) — NOT `starship-246.local`
- OTA URL bug: CORRECT path is `/tools/department-hq/api/fleet/checkpoints/<file>`. WRONG: `/api/fleet/checkpoints/<file>` returns 200 + HTML login page (KB #266408)
- ComfyUI VRAM swap: unload Ollama GPU models before SDXL, restore after
- K.I.N. auto-rest at >80% capacity (task_queue_limit=500, trigger at 400)
- After OTA model pull: manually update `extra_capabilities.comfyui_models` JSONB for the node
- Starship-246 SSH: `Famil@192.168.1.246` (different username than hub)
- FLEET_RESOURCE_ROUTING_ENABLED env gates fleet resource routing enforcement

## Fleet Identity Invariants (2026-06-05, PR #1464 — HARD RULES)

A DR window orphaned 7/9 nodes via a re-registration storm. Postmortem:
`.claude/dr-postmortem-and-remediation.md`. KB mistakes **#270611** (storm) + **#270617**
(connection leak). These invariants are NON-NEGOTIABLE — violating them re-breaks the fleet.

- **`remote_nodes` has BOTH `id` (int PK) and `node_id` (varchar, e.g. `'outpost_us_001'`).**
  NEVER pass the int `id` to a `WHERE node_id = %s` query — the varchar→int cast errors,
  aborts the txn, and (without a `finally` cleanup) leaks the connection → pool exhaustion →
  hub 96% CPU → heartbeats time out → nodes flap. This id-vs-node_id confusion is a recurring trap.
- **Re-registration is IDENTITY-DESTRUCTIVE — reclaim, never recreate.** The hub
  (`register_node`) MUST refresh an existing row + return its ORIGINAL `node_id`/`approval_status`
  on a **verifying api-key**; it must NEVER mint a fresh `pending` id for known hardware. A node_id
  alone (no key) → 401. Set `deployment_mode` explicitly on INSERT (never the `'standard'` default —
  a node showing `standard` is a junk/orphan row).
- **Heartbeat self-heals ONLY from `'pending'`.** A credential-valid node orphaned into `pending`
  (with `approved_at`) re-approves on heartbeat; a `'rejected'` node STAYS rejected (no authz bypass);
  a genuinely-new node gets `409` (not `404`) so it backs off instead of re-registering.
- **node_sync must NEVER adopt a hub-returned `node_id` that differs from its env/established
  identity** (FIX3, OTA pending). An established node backs off; only first-ever enrollment registers.
- **REPOINT = recreate, not restart** (`HUB_URL` is baked env): `/opt/archie-node/repoint.sh <hub_mesh_ip>`
  preserves `NODE_ID`+`HUB_API_KEY`. `docker restart` reloads env `NODE_ID` (clears an adopted junk id).
- **Any raw DB connection MUST `rollback`+`close` in a `finally`** — a bare `except: log` leaks the conn.
- **NEVER run `failover.sh` wholesale** — it flips prod DNS. Interactive runs require `--force`/
  `DR_CONFIRM=FAILOVER-NOW` (FIX6); the watchdog/cron (no TTY) pass through.
- **Recovery tool**: `scripts/dr/reconcile_fleet_identity.sh` (dry-run default) on the hub. After any
  storm: deploy hub fixes FIRST → restart each sync container → `repoint.sh` DR-mispointed nodes →
  delete FK-safe junk rows. **Monitor**: `fleet_identity_monitor` job (FIX8) alerts on mass-offline +
  duplicate-identity. KB ref docs **#270612–270616**.

---

## 🔧 Adding a NODE or a new GPU — placement checklist (2026-08-19, KB #291799)

Written after a live session where a **100%-healthy node was capped on the strength of one log
line**, and two "sensible" cap values would each have silently broken a different model. Run
this before touching `remote_nodes.extra_capabilities` or enrolling new hardware.

### 1. MEASURE FIRST — a node is judged by its success rate, never by one log line

🔴 **EXCLUDE ADMISSION-GATE SHEDS OR THE NUMBER IS MEANINGLESS.** When the hub's in-flight cap is
reached the dispatcher writes a `success=false` row with `model_used` and no inference. Counting those
measures the GATE, not the node or model (`gemma3:12b`: 50% → 94% once the 46% shed rows were removed).
The predicate is `services/infra_failure_filter.not_backpressure_sql()` — that module is the source of
truth. Run a per-node (3h) and a per-node×per-model (24h, hourly) query before AND after any change,
plus a shed-share sanity query. Full SQL: **KB #377833**.
⚠️ A NULL `error_message` breaks a naive `NOT (error_message ILIKE …)` filter (NULL drops every success →
impossible rates); use the `NOT (NOT success AND …)` form or `COALESCE`.
⚠️ A cold-load log line is a MOMENT; a success rate is a FACT — USS-245 was capped on one
`still cold-loading` line while doing qwen2.5:7b 50/50, and the cap was reverted the same hour.

### 2. `max_model_gb` semantics — it is a CPU CEILING, not a disk size

`fleet_resource_router.can_node_run_model()`:

```python
if footprint.prefer_gpu and gpu_avail and footprint.vram_gb <= gpu_vram:
    return True                       # GPU path — checked FIRST, cap is irrelevant here
cap = float(declared_cap) if declared_cap is not None else ram_gb
required = max(footprint.vram_gb, footprint.ram_gb)
return required <= cap
```

**Always look up the REAL footprints before choosing a number** — never guess from the model's
name or its disk size:

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.model_sizes import lookup
for m in ['qwen2.5:1.5b','llama3.2:3b','qwen2.5:7b','gemma3:12b','arctic-embed-cpu:latest','dolphin3:latest']:
    f=lookup(m); print(m, 'required=', max(f.vram_gb,f.ram_gb), 'vram=', f.vram_gb)"
```

Measured 2026-08-19 (`required = max(vram_gb, ram_gb)`):

| model | required | trap |
|---|---|---|
| `qwen2.5:1.5b` | 3.0 | |
| **`llama3.2:3b`** | **5.0** | a "sensible" cap of **4 silently disqualifies it** — and it is in several nodes' documented warm set |
| `qwen2.5:7b` / `mistral:7b` / `qwen2.5-coder:7b` | 8.0 | |
| **`arctic-embed-cpu:latest`** | **16.0** | a cap of **12 silently kills embeddings** on that node |
| **`dolphin3:latest`** | **16.0** | same |
| `gemma3:12b` | 24.0 | |

Pick a cap in the OPEN INTERVAL between what you want to keep and what you want to block, with
margin on both sides — e.g. to admit `llama3.2:3b` (5.0) and block 7B (8.0), use **6**, not 5
(zero margin) and never 4.

### 3. Who gets a cap

- **CPU-only nodes** (outposts, Citadel, Beacon) — capped. Historically all at `4`.
- **GPU nodes** (hub, Starships) — **deliberately UNCAPPED** so an oversized model can CPU-demote
  onto ample RAM (KB #270009, and there is a test pinning this). Do NOT cap a GPU node without
  step-1 evidence that it is actually failing that model.
- ⚠️ **Size the cap to the NODE, not to its tier.** Citadel sat at `4` (copied from the 7.8GB
  outposts) despite **31.3GB RAM**, so a box taking 377 real dispatches/30d could only ever run
  `qwen2.5:1.5b`. Raised to `6` on 2026-08-19 — purely additive, removed nothing.

### 4. The cap binds BOTH dispatch paths (#5809 — resolved 2026-08-22)

`can_node_run_model` is enforced by `BridgeDispatcher` AND on the warm-up path, because the gate lives
at the DRAIN (`model_dispatch_service.py`, inside `if node_id:`), which preferred-pinned and
warm-discovery rows both pass through. There is no "planner class" to find: `warmup_fleet` is
capability-driven (no code names the model) and `kin_warmth` raw-INSERTs into `dispatch_pending_queue`
with no producer-side check. `_WARMUP_MODULES` gates log attribution only, not placement. Residual
waste: `kin_warmth` can queue a pin the drain then refuses (bounded by the 12-min TTL).
`node_has_model` is fail-OPEN, so a presence check alone lists nodes that run no Ollama — read it
together with the capacity predicate. Full history, line refs, live proof: **KB #377831**.

### 5. Adding a GPU / a new card

- `remote_nodes.gpu_vram_gb` = **LARGEST SINGLE GPU, never the sum** (see the ship-class section
  above). Total goes in `extra_capabilities.gpu_vram_total_gb` for reporting only.
- Ship-class re-derives automatically from `gpu_vram_gb` via `ship_classes` — no deploy needed.
- A model CAN span cards (Ollama does it routinely on the hub), and a spanning model eats headroom
  on BOTH cards at once, which placement does not anticipate. Keep the single-card value anyway —
  it is the right SAFETY input for `_fits()` / `get_agents_for_hardware()`, which size one model
  at a time.

### 6. Verify the BEHAVIOUR, not the row

A correct `remote_nodes` row proves nothing. Prove it through the predicate in the running code:

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from database import get_db_cursor
from services.fleet_resource_router import can_node_run_model
with get_db_cursor() as (conn,cur):
    cur.execute(\"SELECT node_name,gpu_available,gpu_vram_gb,ram_gb,extra_capabilities FROM remote_nodes WHERE status='online'\")
    rows=[dict(r) for r in cur.fetchall()]
for m in ['qwen2.5:7b','gemma3:12b','llama3.2:3b','arctic-embed-cpu:latest']:
    print(m, '->', [n['node_name'] for n in rows if can_node_run_model(n,m)])"
```

Then re-run the step-1 query ~30 min later and confirm the node's success rate moved the way you
predicted. **If you cannot state the prediction in advance, you are not ready to make the change.**

### 7. Model choice is a separate question from placement

Placement cannot make an oversized model fit, and a success rate that includes admission-gate sheds
does not measure the model: `gemma3:12b` read 50% but ran at 94% once sheds were excluded (the true
spread across models is 91–94%, i.e. noise). Compare the SAME capability, never fleet-wide averages.
**Current guidance**: move `fact_check` off `gemma3:12b` (its failures are 100% timeouts, avg 572s vs
a 300s wall — too slow, not wrong); **keep it for `translate` (99–100%) and `beat_classification`
(96%)**. Retiring it would not reduce shedding — that lever is the producer's burst rate or the cap
(#5903). Tables and measurements: **KB #377832**.

---

## 🔥 Warm residency profiles (2026-08-31, PRs #2987–#2992)

Placement decides WHERE work runs. Residency decides whether the model is already
**warm** when it gets there — and on this fleet a cold 7B costs roughly **45x** a warm one.
Three services, each doing one thing:

| service | verb | notes |
|---|---|---|
| `services/residency_monitor.py` | **observe** | pure `derive_findings()`; findings carry `confidence` |
| `services/residency_profiles.py` | **declare** | `all_profiles()` / `nodes_for()` / `active_name()`; RLock-safe |
| `services/residency_activation.py` | **act** | `activate()` **dry-run by DEFAULT**, `status()`, `plan()`, `warm_for_backlog()` |

Activation asks nodes to load via `model_service.ensure_model_ready` (ADR-013 — never a
direct Ollama call). It **never evicts**, never changes routing, never pins VRAM: the worst
case of a wrong profile is wasted warm-up. **Both** `can_node_run_model` (capacity) and
`node_has_model` (presence) gate every request before it is queued — see #5809/#5862; the two
predicates answer different questions and disagree on real nodes.

**Only caller today**: the three WTF backlog producers in `tools/department_hq/jobs.py`
(`_run_wtf_{factcheck,bias,geo}_backlog`), each calling `warm_for_backlog()`. **OFF by
default** — `platform_settings warmboot:wtf_backlog:enabled='true'` arms it;
`…:profile` (default `default`) and `…:ttl_min` (default 90) tune it. **The TTL is the
throttle**, DB-backed on purpose: `archie_platform` runs `--workers 4`, so an in-memory timer
would warm up to 4x (KB #282671). Operator guide **KB #300144**, contract **KB #300146**.

### ⚠️ Four traps, all of them already made once

- **`status()['active']` means "we asked", NOT "it is warm."** `_record_active()` fires on
  every non-dry activation, including one where every model was refused by the gates. For
  actual residency use `residency_monitor.check_residency()`.
- **`ensure_model_ready`'s `tier` is the tier FOUND, not achieved.** Its warm-boot SUCCESS
  path hardcodes `{"ready": True, "tier": "cold"}` — so `ready=True, tier='cold'` means "it
  WAS cold, we loaded it, it is now resident". Surfaced as **`found_tier`** for exactly this
  reason. And `model_service.py:806` returns **`warm_boot_ms=150000` on a LOCK TIMEOUT**, so a
  ~143,000ms reading is a lock wait, not a load.
- 🔴 **`with ThreadPoolExecutor(...)` makes a deadline DECORATIVE** — `__exit__` calls
  `shutdown(wait=True)`, so the caller is held until the slowest task finishes regardless of
  any wall on `as_completed`. Use `shutdown(wait=False, cancel_futures=True)`.
  ⚠️ **`fleet_jobs.warmup_fleet_models` still has this — its 90s bound is not real.**
- 🔴 **A profile NAME in a constant is a REFERENCE; assert it resolves.**
  `_BACKLOG_DEFAULT_PROFILE` shipped as `'news'`, a profile that does not exist. An absent
  profile makes `activate()` answer *"declares no nodes"*, which read as `nothing requestable`
  — **indistinguishable from "every model refused by the gates"**. Armed, it would have warmed
  nothing forever while logging plausibly. Same family as the phantom `backups` table and the
  declared-but-unapplied gdrive/vps retention tiers. KB mistake **#300145**.

### Not built yet
Step 4 — an A.R.M.A.D.A. Fleet-tab profile selector. Step 5 — `warmup_fleet_models` reading
the active profile instead of its hardcoded capability list. A `news` profile does not exist
yet; writing one is what makes step 4 worth having.
