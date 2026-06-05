# DR Cluster-Orphaning Incident — Postmortem & Remediation (date 2026-06-05)

---

## TL;DR

- **What broke:** 7 of 9 fleet nodes (outpost-us, USS-246, Singapore, Lithuania, UK, Citadel/boston-2, Beacon) went `OFFLINE` in ARMADA with frozen `last_heartbeat`; only USS-245 stayed healthy. Their approved DB rows are intact but stale, and the storm spawned junk `pending` duplicate rows (229, 312, 314, `node_dc513b…`).
- **Why:** A DR failover/failback + Headscale split-brain window on 2026-06-04 made the hub heartbeat (`100.64.0.4:3000`) transiently unreachable. `node_sync`'s 5-strike re-registration then nuked each approved node's identity into a fresh `pending` duplicate that can never self-heal, because heartbeat hard-gates on `approval_status='approved'`.
- **Blast radius:** Fully recoverable (credentials/identity for all originals are intact), but the fleet cannot self-heal — the `pending` state is terminal until a human acts. Tier identity (`deployment_mode`) was also silently downgraded to `standard` on every duplicate.
- **One-line root cause:** The hub's `register_node()` mints a brand-new `pending` identity on every re-registration (ignoring `re_register` + the supplied `node_id`), and `node_sync` blindly adopts that junk identity onto disk — so a transient hub blip permanently orphans approved nodes.
- **One-line fix:** Make `register_node()` reclaim-aware (UPSERT the existing approved row, **api-key-verified**, never downgrade to `pending`), make `node_sync` refuse to overwrite an established `node_id` + back off instead of re-registering, and stop DR from leaning on re-registration as the node self-heal path.

---

## What happened — the cascade timeline

The failure was **staged, not simultaneous** — each node orphaned itself the moment its own heartbeat crossed 5 consecutive failures. This is the single most important fact: the trigger is a *per-node* threshold crossing, not one fleet-wide event.

1. **Hub/mesh disturbance begins (2026-06-04).** All-day DR script redeploy churn (PRs #1437–#1454, 11:03–15:59) plus a Headscale-DR split-brain — `archie_headscale_dr` left running ~4+ hours concurrently with the hub Headscale (per `auto_failback.sh` Step 0) — makes the hub heartbeat endpoint transiently unreachable over the mesh. The dispatcher circuit-breaker OPENs for `node_id=archie-starbase`, corroborating a hub-reachability window. No single failover event — a rolling reachability gap.
2. **Phase-7 quorum watchdog arms (boston-2, ~06-04 17:29).** The 60s systemd-timer watchdog probes the 3 global outposts (Singapore `.5` / Lithuania `.7` / UK `.8`). All three become unreachable in the same minute — exactly the `K_BLACKOUT=5` all-unreachable condition. The watchdog arms the 5-min Telegram abort window; with no `/dr_abort` tap it is positioned to run `failover.sh`. Whether `failover.sh` fully fired or the mesh blackout alone broke heartbeats, the three quorum outposts + Beacon (also on the mesh) all cross their heartbeat-failure threshold together.
3. **node_sync trips strike-5 on 4 nodes (06-04 17:29–17:30).** On each node, `_heartbeat_thread` counts consecutive failures: at strike 3 it doubles the interval to 120s; at strike 5 (~2.5 min) `_handle_heartbeat_failure` calls `_maybe_dr_failover` then **unconditionally** `_attempt_re_registration` (`node_sync.py:2409`, outside the if/else). Singapore/Lithuania/UK/Beacon all POST `/api/nodes/register {node_id, re_register:True}` to the still-current hub `.4` (the DR hub `.10` either not promoted or loopback-bound, so `_maybe_dr_failover` returns False).
4. **Hub mints fresh pending duplicates.** `register_node()` (`fleet_node_routes.py:1331`) ignores `re_register` and the supplied `node_id`, mints a fresh `generate_node_id()` + new `api_key` (L1362-1363), and INSERTs a NEW row with `approval_status='pending'` (L1461) and `deployment_mode` omitted → DB default `'standard'`. The original approved rows (125/126/127/129) are untouched. The hub returns `{node_id:'node_xxx', api_key:…, approval_status:'pending'}`.
5. **Nodes adopt the junk identity on disk.** `_attempt_re_registration` blindly adopts the hub response: `config['node_id']=resp['node_id']`, `config['hub_api_key']=resp['api_key']`, `write_config()` to `/etc/archie-node/config.json` (`node_sync.py:2224-2227`). The env-var `NODE_ID` protection only guards `load_config()` at startup, NOT this live overwrite. The 4 nodes abandon their approved identities in-memory and on disk; their approved rows freeze at 06-04 17:29-17:30.
6. **Self-amplifying shred loop.** Every subsequent heartbeat from the pending id hits the approved-gate (L1815) → 404 `'Node not found'`; every sync poll → 403 `'Node not approved'`. The failure counter **resets at 10** (`node_sync.py:2410`) and re-arms at 5, so re-registration re-fires roughly every ~5 heartbeats, minting MORE pending junk rows. The 4 nodes are now permanently OFFLINE and cannot self-heal.
7. **USS-246 orphans later (06-04 22:52).** USS-246 (id 115, LAN node, different mesh path / failover-transition timing) crosses its own 5-strike threshold and re-registers the same way → pending duplicate (later seen as junk row 312, hostname `192.168.1.246`). Approved row 115 frozen at 22:52.
8. **DR coordinator itself goes down (06-05 00:00).** Citadel/boston-2 (id 128) — which *is* the DR coordinator host — goes offline at midnight. With boston-2 down, the auto-recovery coordinator (watchdog + `auto_failback`) is also gone for the second half of the storm, so no automated repoint/failback can rescue the fleet. Citadel orphaned; DR self-recovery now impossible.
9. **outpost-us orphans last (06-05 06:25).** Its env still says `NODE_ID=outpost_us_001` and its api_key SHA-256 still matches DB row 93 (**credentials never broke**). It re-registers; hub mints `node_dc513b62c7b2cb84` (pending); node_sync adopts it. Logs show the exact sequence: `404 Node not found` → 5× → `re-registration successful` (pending) → `config written` → `403 Node not approved` on sync.
10. **Junk rows accumulate; ARMADA shows 7/9 offline.** The storm leaves behind pending junk rows: 229 (USS-245 re-reg, `192.168.1.245`), 312 (USS-246, `192.168.1.246`), 314 (a `172.27.0.1` docker-bridge ghost), plus `node_dc513b62c7b2cb84` (outpost-us, heartbeating but uncommitted as a stable row) — all `deployment_mode='standard'` (tier identity lost). Only the hub (68) and USS-245 (120) are healthy.

---

## Root causes (ranked critical → low)

### RC1 — `register_node()` mints a NEW pending identity on every call *(critical, hub_endpoint)*
**Where:** `platform_v2/tools/department_hq/fleet_node_routes.py:1362-1363,1461` (and the L1384-1394 stale-cleanup that never matches the live approved row).
**Why it orphaned nodes:** This is the wound. A re-registration from an already-APPROVED node is treated as a brand-new enrollment: `generate_node_id()` + `secrets.token_urlsafe(32)` + hardcoded `approval_status='pending'`. The original approved row is left untouched and orphaned. The handler receives the original `node_id` AND a valid api_key (which could match `api_key_hash` by SHA-256, or match hostname/mesh_ip) but uses neither. Without this, the node's own self-heal would be harmless.

### RC2 — node_sync 5-strike re-registration runs unconditionally and ADOPTS the hub-minted pending identity *(critical, node_sync)*
**Where:** `node_client/node_sync.py:2409` (`_attempt_re_registration` runs outside the DR if/else) + `:2224-2227` (`config['node_id']=resp['node_id']`; `config['hub_api_key']=resp['api_key']`; `write_config()`).
**Why it orphaned nodes:** The node-side half of the nuke. On 5 consecutive heartbeat failures (~2.5 min) it re-registers even when DR failover did/should not happen, then blindly trusts the hub response and persists the junk pending id to `/etc/archie-node/config.json`. The live process throws away its real approved identity. The env-var `NODE_ID` "protection" only guards `load_config()` at startup, not this runtime overwrite — explaining why outpost-us's env still says `outpost_us_001` yet the process runs as `node_dc513…`.

### RC3 — heartbeat + mesh-sync endpoints hard-gate on `approval_status='approved'` with NO self-heal path *(critical, hub_endpoint)*
**Where:** `fleet_node_routes.py:1815/1822` (heartbeat `SELECT … approval_status='approved'` → 404 `'Node not found'`, BEFORE the api-key check); `fleet_mesh_routes.py:_verify_node_api_key:66-70` → `mesh_get_pending_syncs:568-573` (403 `'Node not approved'`).
**Why it orphaned nodes:** Converts a transient reachability blip into a permanent offline. Once a node holds a pending id, every heartbeat 404s and every sync 403s; the 404s re-feed the 5-strike counter (which resets at 10 instead of backing off) → repeated re-registration → more pending junk rows. There is no path from pending back to approved via heartbeat — only manual admin approval recovers it. Matches the live logs exactly.

### RC4 — DR design is silent on fleet-node IDENTITY, and `failover.sh` deliberately delegates Starship/outpost repoint to node_sync re-registration *(high, design)*
**Where:** `scripts/dr/failover.sh:87-91` ("NOT repointed here — self-heal via node_sync.py DR auto-failover … re-registers"); DR design docs KB #270037/#270232/#270238/#270239 (zero mentions of `node_id` / re-registration / pending / approval).
**Why it orphaned nodes:** The DR design scope was DB + platform container + `HUB_URL` repoint; it assumed nodes "just reconnect." By explicitly leaning on node_sync's re-registration as the Starship/outpost self-heal path, the design baked the identity-destroying behavior in as INTENDED. Every DR event (or any hub flap long enough to trip 5 strikes) is therefore guaranteed to orphan the fleet. This is the root-cause-enabling decision.

### RC5 — re-registration INSERT omits `deployment_mode` → DB default `'standard'`, silently downgrading tier *(high, hub_endpoint)*
**Where:** `fleet_node_routes.py:1405-1463` (INSERT column list lacks `deployment_mode`) + `database/migrations/069_node_mesh_network.sql:61` (`DEFAULT 'standard'`).
**Why it orphaned nodes:** Even a recovered/approved duplicate loses its classification: outpost/starbase_outpost/starship all reappear as `'standard'` (junk rows 229/312/314 confirm). The tier identity needed for routing, warm-set, and ComfyUI/provisioning is destroyed alongside the `node_id`, so re-approval alone wouldn't fully restore correct behavior.

### RC6 — Phase-7 watchdog can auto-fire failover on a fleet-wide connectivity blip with only a 5-min veto, and runs on boston-2 which itself went down mid-storm *(high, watchdog)*
**Where:** `dr/watchdog/dr_watchdog.sh` (`K_BLACKOUT=5` all-3-outposts-unreachable branch, commit `88917749` 2026-06-04) + `dr-watchdog.timer OnUnitActiveSec=60`; coordinator host = Citadel/boston-2 (id 128).
**Why it orphaned nodes:** The exact 06-04 17:29 event — Singapore/Lithuania/UK all unreachable in the same minute — is the BLACKOUT arm condition. An unattended arm auto-runs `failover.sh` (which flips prod DNS) and triggers the failover→failback churn that produced the transient-unreachable windows driving re-registration. boston-2 going offline at 00:00 then removed the only coordinator, so no `auto_failback`/repoint could rescue the fleet.

### RC7 — two divergent DR script trees (`dr/` vs `scripts/dr/`) — no single source of truth *(medium, dr_script)*
**Where:** `/mnt/archie_brain/dr/failover.sh` (164 lines, Jun 3) vs `/mnt/archie_brain/scripts/dr/failover.sh` (293 lines, Jun 4); `scripts/dr/` has `auto_failback.sh`/`force_reset_to_hub.sh`/`mesh_bootstrap.sh`; `dr/` has `repoint.sh` + `watchdog/`; both claim authority for `/opt/archie-dr`.
**Why it orphaned nodes:** Operational ambiguity. The identity-SAFE `repoint.sh` is in one tree while the newer automation is in another, and the deployed `/opt/archie-dr` copy on boston-2 can't be confirmed from the hub. If the wrong/stale copy ran, the safe SSH-repoint was skipped and nodes were left to the broken node_sync self-heal. Did not by itself orphan nodes, but widened the blast radius and made recovery harder. **Verified correction:** the trees are *backwards* from intuition — `dr/` is the git-tracked tree and the ONLY place `repoint.sh` + `watchdog/` exist; `scripts/dr/failover.sh` is the *newer* (293-line) copy that already force-recreates Starship sync containers and SSH-repoints global outposts via `repoint.sh`. Canonicalization must MOVE, never `git rm`, the only copy of `repoint.sh`.

### RC8 — no DR tool can repair an orphaned node *(low, dr_script)*
**Where:** `scripts/dr/force_reset_to_hub.sh` + `scripts/dr/mesh_bootstrap.sh` (no references to `remote_nodes`/`approval_status`/`node_id`).
**Why it orphaned nodes:** Not a trigger, but it prolonged the outage. The entire DR toolchain has a blind spot — no script re-approves or re-binds an orphaned pending duplicate onto its original approved row. The live fix requires manual DB surgery outside the DR toolset, so the fleet stayed down until human intervention.

### Contributing factors
- **Failure-counter RESETS at 10** instead of exponential back-off (`node_sync.py:2410`) — turns a one-shot orphaning into a perpetual re-registration STORM, spawning multiple pending duplicates per node (229/312/314 + `node_dc513…`), even a `172.27.0.1` docker-bridge ghost.
- **Dispatcher circuit-breaker OPENing for `node_id=archie-starbase`** (the hub itself) degraded hub-side routing during the window and masked the real cause — it looked like a hub problem rather than a node-identity problem.
- **DR_RUNBOOK 5b gap:** v3.0.0 node client reads `hub_url` from `/etc/archie-node/config.json` while `repoint.sh` edits `/opt/archie-node/sync.env` — so the sanctioned repoint can be a silent no-op; combined with boston-2's standby historically binding `127.0.0.1` only, a repointed node got Connection refused → heartbeats failed → `_maybe_dr_failover` returned False → unconditional re-registration against the real hub.
- **Headscale-DR split-brain** (`archie_headscale_dr` left running ~4+ hrs concurrently with the hub Headscale) caused a mesh outage that prolonged heartbeat failures and widened the re-registration window across nodes.
- **`/api/nodes/register` is UNAUTHENTICATED** and has no de-dup-by-node_id (no `ON CONFLICT`), so storming orphans could flood `remote_nodes` with pending rows unchecked; the 24h-stale cleanup can't keep up with fresh duplicates.
- **NO alerting on mass-offline:** 7 of 9 nodes going OFFLINE over ~13 hours (17:29 → 06:25) produced no escalation; the storm was only discovered by live ARMADA inspection on 06-05.
- **boston-2 (the DR coordinator) being a fleet node that itself went offline at 00:00** removed any chance of automated `auto_failback`/repoint recovery for the back half of the storm.
- **`deployment_mode` default `'standard'`** silently hid the tier downgrade — junk rows looked like ordinary `standard` nodes rather than obviously-corrupted outpost/starship rows, obscuring diagnosis.

---

## Why USS-245 survived

USS-245 (id 120) is the one fleet node whose heartbeats **never hit 5 consecutive failures** during the disturbance window, so `node_sync` never fired `_attempt_re_registration` on the live process and it kept its approved identity (still heartbeating HTTP 200 NOW).

- Its mesh path to the hub (`.4`) stayed reachable through the window — it was **not** part of the `.5`/`.7`/`.8` BLACKOUT quorum set, and as a LAN node its reachability gap (if any) stayed under the ~2.5-min / 5-strike fuse.
- The storm STILL touched it indirectly: junk row 229 (hostname `192.168.1.245`, pending) is a re-registration attempt against USS-245's hostname — but its live process never adopted a pending id, so its approved row 120 remained valid.
- **It is the control case** proving the trigger is per-node 5-strike threshold crossing, not a single fleet-wide event.

---

## Immediate recovery (bring the 7 nodes back NOW)

> Deploy the hub-side fixes (FIX1+FIX2) FIRST so node restarts *converge* instead of re-storming. The env `NODE_ID` is the source of truth for every node — `config.json` is reverted to env on reload because env wins at startup.

**STEP 0 — snapshot (hub, reversible):**
```bash
docker exec archie_database pg_dump -U archie -d archie -t remote_nodes > /tmp/remote_nodes_pre_recovery.sql
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id,node_id,node_name,approval_status,deployment_mode,hostname,last_heartbeat FROM remote_nodes ORDER BY id;"
```
Confirm the 7 stale approved rows (93,115,125,126,127,128,129) and the junk pending rows (229,312,314 + `node_dc513b62c7b2cb84`).

**STEP 1 — reactivate the real rows (hub, DB):** The 7 approved rows are still `approved`+`is_active` — just stale. Ensure none were flipped inactive:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "UPDATE remote_nodes SET is_active=TRUE WHERE node_id IN ('outpost_us_001','starship_76583490e36955ab','outpost_41947095e6995ef4','outpost_fb372c0209eadbe7','outpost_417762f2cf281b10','outpost_e834ff6949a3d7a6','beacon_01699263f6cd9dc9') AND approval_status='approved';"
```
Do NOT delete anything yet — junk rows are removed in STEP 6 only after live processes are back on their real identity.

**STEP 2 — neutralize the wound server-side FIRST (hub, code):** Deploy FIX1+FIX2 (reclaim-aware `register_node` + self-heal heartbeat, **with the migration-067 `approved_at` backfill from FIX2**) on a branch and restart:
```bash
docker compose restart archie_platform
docker logs --tail 50 archie_platform | grep -i register
```
With FIX1 live, the next re-registration from each orphaned node REFRESHES its existing approved row (returning its original `node_id`) instead of minting junk; with FIX2 + backfill, a credential-valid pending node auto-re-approves on heartbeat.

**STEP 3 — outpost-us (id 93, reachable, env intact):**
```bash
ssh kytran@76.13.107.109
cd /opt/archie-outpost && docker compose up -d --force-recreate --no-deps sync
# or, if enrolled with baked -e flags:
/opt/archie-node/repoint.sh 100.64.0.4
docker logs --tail 30 archie_outpost_sync   # expect "Node ID: outpost_us_001" + 200 heartbeats (not 404)
```

**STEP 4 — Singapore .5 / Lithuania .7 / UK .8 / Citadel .10 (root@ outposts):** For each:
```bash
ssh root@<public_ip> '/opt/archie-node/repoint.sh 100.64.0.4'
# fallback if repoint.sh absent:
ssh root@<public_ip> 'cd /opt/archie-node && docker compose up -d --force-recreate --no-deps sync'
```
`repoint.sh` preserves `NODE_ID`/`HUB_API_KEY` and recreates pointing at the hub mesh `.4`. Bring **Citadel/boston-2 (id 128) back LAST** among outposts and confirm its sync container points at HUB (`.4`), NOT DR (`.10`), so it does not stay in DR mode. After each, confirm the matching approved row's `last_heartbeat` updates to NOW on the hub.

**STEP 5 — USS-246 (id 115) / USS-245 (id 120) — Windows Docker Desktop, SSH currently failing:** With FIX1 live, restart the sync container locally on each Windows box:
```powershell
docker compose -f C:\archie-node\docker-compose.yml up -d --force-recreate --no-deps sync
```
On reload node_sync reads env `NODE_ID` (`starship_76583490e36955ab` / `starship_5501c2766526e746`) + `HUB_URL=http://100.64.0.4:3000`, and FIX1 refreshes the approved row. **USS-245 (120) is already healthy — only restart it if its live process is on a pending id; otherwise leave it.** If USS-246 is physically unreachable, it stays offline but harmless (no more junk rows are minted once FIX1 is live); recover when the box is reachable. Separately fix the Windows SSH path (OpenSSH service or SSH sidecar) for future DR.

**STEP 6 — delete junk ONLY after originals are heartbeating (hub, DB):** Check FK safety first (note: `model_load_state` joins on `node_db_id`, NOT `node_host`):
```bash
docker exec archie_database psql -U archie -d archie -c \
 "SELECT p.id,p.node_id FROM remote_nodes p
  WHERE p.approval_status='pending'
   AND p.node_id IN ('node_e9c25e1440b6da9c','node_bb94d032549b6c52','node_db8d6e66df7177c5','node_dc513b62c7b2cb84')
   AND NOT EXISTS (SELECT 1 FROM node_agents na WHERE na.node_id=p.id)
   AND NOT EXISTS (SELECT 1 FROM model_load_state m WHERE m.node_db_id=p.id);"
```
Then DELETE the rows it returns (by id): `DELETE FROM remote_nodes WHERE id IN (229,312,314) AND approval_status='pending';` plus the `node_dc513…` row by its id. This preserves `node_agents` + `model_load_state` FK history on the original rows.

**STEP 7 — verify:**
```bash
docker exec archie_database psql -U archie -d archie -c \
 "SELECT node_id,node_name,approval_status,deployment_mode,last_heartbeat FROM remote_nodes WHERE is_active ORDER BY id;"
```
Every approved fleet row should show `last_heartbeat` within ~1 min, correct `deployment_mode` (outpost/starbase_outpost/starship, NOT `standard`), and zero pending duplicates. Open ARMADA; confirm all online. If a node still 404s, its live process is still on a pending id — repeat STEP 3/4/5 (env `NODE_ID` is the source of truth).

---

## Remediation — the fixes

All adversarial-review corrections have been folded into the change descriptions below.

| id | layer | file | change | addresses RC | adversarial verdict (folded) |
|----|-------|------|--------|--------------|-------------------------------|
| FIX1 | hub_endpoint | `fleet_node_routes.py` | Idempotent **api-key-verified** reclaim before the mint-new path; add `deployment_mode` to INSERT; tighten stale-DELETE to never match approved rows; add DR hub-epoch fencing | RC1, RC5 | needs_revision → **gate is now `verify_api_key(...) AND` for any reclaim/key-rotation; re_register w/o key = heartbeat-refresh-only; IP-only never reclaims; hub_epoch fencing added** |
| FIX2 | hub_endpoint | `fleet_node_routes.py` | Self-heal heartbeat: fetch by node_id → verify key → branch on approval; auto-re-approve established hardware; distinct **409** (not 404) for genuinely-new | RC3 | needs_revision → **ship `approved_at` backfill migration; gate self-heal on `last_heartbeat IS NOT NULL` (ever-heartbeated), not nullable `approved_at`; guard against DR-standby auto-approve** |
| FIX3 | node_sync | `node_sync.py` | Refuse to adopt a differing `node_id`; gate re-registration to first-ever enrollment; treat 409/DR responses as keep-identity | RC2 | needs_revision → **persist/derive `_ever_approved` from durable identity in `write_config`/`load_config`; thread status code out of `send_heartbeat` so 409 is distinguishable; reconcile always-true env_lock** |
| FIX4 | node_sync | `node_sync.py` | Replace strike-10 reset with capped exponential backoff; never reset failures on failure | RC2 | needs_revision → **DECOUPLE: keep DR-failover retry firing on `>=5` independent of the removed reset; route the bare-except increment through backoff; add "DR hub reachable only after strike-5" test** |
| FIX5 | dr_script | `scripts/dr/failover.sh` | Single canonical DR tree; repoint ALL nodes (incl. Starships) via identity-safe `repoint.sh` | RC4, RC7 | needs_revision → **confirm boston-2 `/opt/archie-dr` rsync source FIRST; MOVE `repoint.sh`+`watchdog/` into the chosen tree, never `git rm` the only copy; author `repoint.ps1` or drop the SSH branch; mark non-load-bearing, hard-gate on FIX3** |
| FIX6 | dr_script | `scripts/dr/failover.sh` + `dr_watchdog.sh` | `DRILL_MODE`/`DR_CONFIRM` gate on wholesale runs; keep BLACKOUT auto-arm but lean on existing dual-port `probe_local` to discriminate split-brain | RC6 | needs_revision → **state dependency on FIX1/3/4 (+FIX5 path); do NOT force manual on genuine hub-death blackout; do NOT extend abort window; define the `AUTO=1` quorum-token contract** |
| FIX7 | dr_script | `scripts/dr/reconcile_fleet_identity.sh` (new) | Reconcile orphaned nodes: report, then `--apply` deletes FK-safe junk dupes + emits per-node repoint command | RC8 | needs_revision → **fix `model_load_state.node_db_id`; require node_id-equality (key-hash never matches the mint path); replace blanket `is_active` update w/ per-node heartbeat-fresh; emit repoint command (recovery is real); sequence after FIX1/FIX3** |
| FIX8 | monitoring | `services/fleet_identity_monitor.py` (new) | Mass-offline + duplicate-identity detectors, alert-only via A.R.C.H.I.E. unified voice | RC1, RC4 | needs_revision → **mass-offline keys on `<NOW()-3min` (no lower bound) + dedupe; lower/parameterize threshold; per-node rest exclusion (USS-245/246), not blanket; exclude `remote_addr`-derived hostnames from dup JOIN** |

### FIX1 — reclaim-aware, api-key-verified `register_node()`

> **Critical correction folded:** the original sketch's gate `if existing and (re_reg OR incoming_hash OR approved)` was vacuously true for every approved node (an unauthenticated `{node_id, re_register:True}` POST would rotate + leak the key — identity hijack). The gate below requires a **verifying api_key as a hard AND** for any reclaim that rotates the key. Unauthenticated `re_register` is downgraded to a heartbeat-refresh only. Hostname/mesh_ip never reclaims on IP alone (NAT/shared-egress). A monotonic `hub_epoch` fences stale-hub reclaims during DR split-brain.

```python
node_id_in   = (data.get('node_id') or '').strip()
re_reg       = bool(data.get('re_register'))
api_key      = request.headers.get('X-Node-API-Key')
incoming_hash = hash_api_key(api_key) if api_key else None

# RECLAIM requires a VERIFYING api_key (hard AND). node_id/hostname only NARROW the search.
if incoming_hash:
    cur.execute('''SELECT id,node_id,approval_status,deployment_mode,api_key_hash
        FROM remote_nodes
        WHERE api_key_hash=%s
        ORDER BY (approval_status='approved') DESC LIMIT 1''', (incoming_hash,))
    existing = cur.fetchone()
    if existing:                                  # credential verified → safe to reclaim+rotate
        new_key = secrets.token_urlsafe(32)
        cur.execute('''UPDATE remote_nodes
            SET api_key_hash=%s, hostname=COALESCE(%s,hostname),
                client_version=%s, last_heartbeat=NOW(), is_active=TRUE,
                hub_epoch=%s                       -- DR fencing: stamp the owning hub's epoch
            WHERE id=%s RETURNING node_id, approval_status, deployment_mode''',
            (hash_api_key(new_key), node_hostname, data.get('client_version'),
             CURRENT_HUB_EPOCH, existing['id']))
        row = cur.fetchone(); conn.commit()
        return jsonify({'success':True,'node_id':row['node_id'],'api_key':new_key,
                        'approval_status':row['approval_status'],   # KEEP as-is (approved stays approved)
                        'hub_epoch':CURRENT_HUB_EPOCH,'reclaimed':True})

# Unauthenticated re_register: heartbeat-refresh ONLY — never rotate key, never reclaim identity.
if re_reg and node_id_in:
    cur.execute('''UPDATE remote_nodes SET last_heartbeat=NOW()
        WHERE node_id=%s AND approval_status='approved' ''', (node_id_in,))
    if cur.rowcount:
        conn.commit()
        return jsonify({'success':True,'node_id':node_id_in,'refresh_only':True}), 200

# NEW HARDWARE ONLY — mint pending, but ALWAYS set deployment_mode explicitly (never default 'standard').
deployment_mode = data.get('deployment_mode') or 'standard'
cur.execute('''INSERT INTO remote_nodes
    (node_id, hostname, deployment_mode, api_key_hash, approval_status, hub_epoch, ...)
    VALUES (%s,%s,%s,%s,'pending',%s, ...)''',
    (generate_node_id(), node_hostname, deployment_mode, hash_api_key(new_key), CURRENT_HUB_EPOCH, ...))
```
Tighten stale-cleanup so it can never delete an approved or recently-heartbeated row:
```sql
DELETE FROM remote_nodes
 WHERE approval_status <> 'approved'
   AND last_heartbeat < NOW() - INTERVAL '24 hours';
```

### FIX2 — self-heal heartbeat (with migration-067 backfill)

> **Critical correction folded:** 4 of 9 approved nodes (the hub, outpost-us, USS-246, USS-245) have `approved_at IS NULL` because migration 067 approved them without setting it. Gating self-heal on `approved_at` would be dead-on-arrival for the exact primary victims. We (a) ship a backfill migration AND (b) gate on **`last_heartbeat IS NOT NULL`** — a node that has EVER heartbeated is established hardware. We also guard against a DR-standby silently auto-approving (split-brain).

Companion migration (ship first/with):
```sql
-- migrations/NNN_backfill_approved_at.sql
UPDATE remote_nodes SET approved_at = COALESCE(approved_at, created_at)
 WHERE approval_status = 'approved';
```
Heartbeat handler:
```python
cur.execute('''SELECT id,api_key_hash,approval_status,approved_at,last_heartbeat
    FROM remote_nodes WHERE node_id=%s AND is_active=TRUE''', (node_id,))
node = cur.fetchone()
if not node:
    return jsonify({'success':False,'error':'Node not found'}), 404           # genuinely unknown id
if not verify_api_key(api_key, node['api_key_hash']):
    return jsonify({'success':False,'error':'Invalid API key'}), 401          # bad creds
if node['approval_status'] != 'approved':
    established = node['last_heartbeat'] is not None or node['approved_at'] is not None
    if established and not IS_UNPROMOTED_DR_STANDBY:        # don't let a standby self-confirm ownership
        cur.execute("UPDATE remote_nodes SET approval_status='approved' WHERE id=%s", (node['id'],))
    else:
        return jsonify({'success':False,'error':'pending approval',
                        'approval_status':'pending'}), 409   # distinct 409 → client backs off, NOT 404
# ...proceed with normal heartbeat update
```
Mirror the same softening in `fleet_mesh_routes._verify_node_api_key` so sync returns **409** (not 403) for a credential-valid node, so it does not re-feed the failure counter.

### FIX3 — node_sync: never adopt a differing identity; durable `_ever_approved`

> **Critical correction folded:** the linchpin `_ever_approved` flag was in-memory only and reset on every restart (OTA/reboot/crash), re-opening the cascade for config-only outpost nodes. It must be persisted in `write_config`'s whitelist AND derived in `load_config` from durable identity (a persisted `node_id`+`api_key` means "established"). The 409 handling requires threading the status code out of `send_heartbeat`.

```python
def _attempt_re_registration(config):
    env_locked = bool(os.environ.get('NODE_ID')) or bool(config.get('node_id'))
    ...
    if 200 <= status < 300 and isinstance(resp, dict):
        if resp.get('api_key'):
            config['hub_api_key'] = resp['api_key']
        new_id = resp.get('node_id')
        if new_id and new_id != config.get('node_id'):
            if env_locked:
                logger.error('Hub returned DIFFERENT node_id %s but identity is locked to %s — REFUSING',
                             new_id, config['node_id'])
            else:
                config['node_id'] = new_id          # only true fresh enrollment ever reaches here
        write_config(config)                         # _ever_approved is in the whitelist now
        return True

# load_config(): derive established-ness from durable identity (survives restarts)
config['_ever_approved'] = bool(config.get('node_id') and config.get('hub_api_key'))

# _handle_heartbeat_failure, strike-5 branch:
elif failure_count == 5:
    if _maybe_dr_failover(config):
        logger.warning('[DR] now targeting %s', config['hub_url']); return
    if config.get('_ever_approved') or os.environ.get('NODE_ID'):
        logger.error('Heartbeat down %dx; identity locked — backing off, NOT re-registering', failure_count)
        _alert_once(config, 'heartbeat_down'); return
    _attempt_re_registration(config)                 # first-ever enrollment only
```
Add `_ever_approved` to the `write_config()` whitelist and set it `True` on the first 200 heartbeat. Thread the HTTP status out of `send_heartbeat` so a `409 'pending'` is handled as keep-identity-and-retry (vs the current "any non-2xx → bare `return False`").

### FIX4 — capped exponential backoff, DR-failover retry preserved

> **Critical correction folded:** the original wholesale removal of the strike-10 reset *also* disabled the only DR-failover retry site (`_maybe_dr_failover` at L2402, inside the `==5` branch), permanently pinning a node to a dead primary. Decouple: keep DR-failover attempts firing on `>=5` on an independent cadence, while preventing **re-registration** from re-arming. Also route the bare-except increment through the same backoff.

```python
else:
    heartbeat_failures += 1
    _handle_heartbeat_failure(config, heartbeat_failures, base_interval)
    current_interval = min(base_interval * (2 ** min(heartbeat_failures, 5)), 600)  # cap 600s, no reset-to-0
# REMOVE: `elif heartbeat_failures >= 10: heartbeat_failures = 0`

# DR-failover retry must NOT be coupled to the deleted reset — keep it on a periodic cadence:
if heartbeat_failures >= 5 and (heartbeat_failures % DR_REPROBE_EVERY == 0):
    _maybe_dr_failover(config)        # still retried while down; independent of re-registration

# bare-except path must increment through the same handler, not silently:
except Exception as e:
    logger.warning('heartbeat error: %s', e)
    heartbeat_failures += 1
    _handle_heartbeat_failure(config, heartbeat_failures, base_interval)
    current_interval = min(base_interval * (2 ** min(heartbeat_failures, 5)), 600)
```
A single SUCCESS still snaps `heartbeat_failures→0` and `current_interval→base`. New required test: "DR hub reachable only AFTER strike-5 → node still fails over."

### FIX5 — single canonical DR tree + identity-safe repoint for ALL nodes

> **Correction folded:** the trees are backwards from the original premise. `dr/` is git-tracked and the ONLY home of `repoint.sh` + `watchdog/`; `scripts/dr/failover.sh` (293 lines) is newer and already force-recreates Starship sync containers and repoints global outposts. **Confirm the boston-2 `/opt/archie-dr` rsync source FIRST; MOVE assets into the chosen canonical tree (never `git rm` the only `repoint.sh`); author `repoint.ps1` or drop the Starship SSH branch.** FIX5 is explicitly NON-load-bearing for the cascade — it is hard-gated on FIX3 (node_sync no longer re-registers).

```bash
# Canonicalization (run once, committed) — direction set by the actual boston-2 rsync source:
#   git mv dr/repoint.sh        scripts/dr/repoint.sh      # MOVE the only copy, never delete
#   git mv dr/watchdog          scripts/dr/watchdog
#   # collapse the older 164-line dr/failover.sh into a stub that execs scripts/dr/failover.sh
# failover.sh — repoint Starships via the same identity-safe path (PowerShell sibling required):
for starship in 'Famil@100.64.0.3' 'Famil@100.64.0.6'; do
  ssh -i "$FLEET_KEY" "$starship" 'powershell -c "& C:\archie-node\repoint.ps1 100.64.0.10"' \
    && log "  repointed $starship (NODE_ID/HUB_API_KEY preserved)" \
    || log "  WARN: $starship unreachable — node_sync DR failover (identity-safe under FIX3) is last resort"
done
```

### FIX6 — gated, split-brain-aware watchdog

> **Correction folded:** the existing `dr_watchdog.sh` already does own-vantage `probe_local` + dual-port `probe_hub` + the abortable window. Do NOT convert genuine hub-death blackout to manual-only (that raises RTO for the exact case DR exists for), and do NOT extend the abort window (every extra minute pointed at a dead primary orphans more nodes pre-FIX3). Instead, keep auto-arm but use the existing dual-port `probe_local` to reject split-brain, and **define the `AUTO=1` quorum-token contract**. The manual `DR_CONFIRM` gate is for *wholesale CLI* runs only.

```bash
# failover.sh head — block accidental wholesale CLI runs (drills/typos), NOT the gated watchdog path:
if [[ "${AUTO:-0}" != 1 && "${DR_CONFIRM:-}" != 'FAILOVER-NOW' ]]; then
  echo 'REFUSING wholesale failover (flips PRODUCTION DNS).'
  echo 'Manual DR: promote replica + start standby by hand, or re-run with DR_CONFIRM=FAILOVER-NOW'; exit 3
fi
# AUTO=1 is honored ONLY with a fresh signed quorum token the watchdog passes:
if [[ "${AUTO:-0}" == 1 ]]; then verify_quorum_token "${QUORUM_TOKEN:?}" || exit 4; fi

# dr_watchdog.sh blackout branch — discriminate split-brain from hub-death using existing probes:
if blackout_all_unreachable; then
  if probe_local_hub_up; then          # boston-2 can still reach hub HTTP+5432 → NOT a hub death
    alert CRITICAL 'Mesh blackout but hub reachable from boston-2 — split-brain, NOT failing over'; reset_state; exit 0
  fi
  arm_with_abortable_window 'BLACKOUT'  # genuine hub-death blackout still auto-arms (existing 300s veto)
fi
```

### FIX7 — `reconcile_fleet_identity.sh` (the missing recovery tool)

> **Correction folded:** `model_load_state` has no `node_host` column (use `node_db_id`); the mint path regenerates `api_key_hash`, so a key-hash match can NEVER identify the orphan — match on `node_id` equality only, leave hostname-only matches for manual review; replace the blanket `is_active` update with a per-node heartbeat-fresh condition; and **emit the per-node repoint command** so recovery is real (deleting the DB row alone does not restore the live process's identity). Run AFTER FIX1/FIX3 have stopped the storm.

```bash
#!/bin/bash
# scripts/dr/reconcile_fleet_identity.sh [--apply]   (dry-run by default)
set -euo pipefail
PSQL='docker exec archie_database psql -U archie -d archie -v ON_ERROR_STOP=1 -tAc'

# 1. REPORT orphans: approved rows stale, with a matching pending duplicate (node_id-narrowed; hostname only for review)
$PSQL "SELECT a.node_id AS approved, p.node_id AS junk, p.hostname
  FROM remote_nodes a JOIN remote_nodes p ON (a.hostname=p.hostname AND a.hostname IS NOT NULL)
  WHERE a.approval_status='approved' AND p.approval_status='pending' AND a.id<>p.id"

if [ "${1:-}" = --apply ]; then
  # 2. Delete ONLY FK-safe pending dupes that map to an approved original (node_db_id, not node_host)
  $PSQL "DELETE FROM remote_nodes p
    WHERE p.approval_status='pending'
      AND NOT EXISTS (SELECT 1 FROM node_agents na      WHERE na.node_id=p.id)
      AND NOT EXISTS (SELECT 1 FROM model_load_state m  WHERE m.node_db_id=p.id)
      AND EXISTS (SELECT 1 FROM remote_nodes a WHERE a.approval_status='approved' AND a.hostname=p.hostname)"
  # 3. Re-activate ONLY approved rows that are still heartbeat-fresh (do not wake dead/rested nodes)
  $PSQL "UPDATE remote_nodes SET is_active=TRUE
    WHERE approval_status='approved' AND last_heartbeat > NOW()-INTERVAL '5 minutes'"
  # 4. Recovery is REAL: print the repoint command each orphaned node still needs (its live process holds the junk id)
  echo 'Per-node action required (live process still on a junk identity):'
  $PSQL "SELECT '/opt/archie-node/repoint.sh 100.64.0.4   # on '||hostname FROM remote_nodes
    WHERE approval_status='approved' AND last_heartbeat < NOW()-INTERVAL '5 minutes'"
fi
```

### FIX8 — fleet-identity monitor (alert-only)

> **Correction folded:** mass-offline must key on `last_heartbeat < NOW()-3min` with no lower bound (a sustained outage drops out of a 3–10min band, going silent), with per-node dedupe; threshold parameterized (so single-node orphaning is catchable); per-node rest exclusion for USS-245/246 instead of blanket overnight suppression; and the duplicate JOIN must exclude `remote_addr`-derived hostnames (shared NAT/DC egress) to avoid false positives.

```python
REST_EXCLUDED = {'starship_5501c2766526e746', 'starship_76583490e36955ab'}  # per-node, not blanket
ALERT_THRESHOLD = 1   # parameterized; >1 still catches the cascade, =1 catches single-node

def check_fleet_identity():
    # MASS-OFFLINE: no lower bound; dedupe against already-alerted node_ids; exclude only rested nodes
    offline = q("""SELECT node_id FROM remote_nodes
        WHERE approval_status='approved' AND is_active
          AND last_heartbeat < NOW()-INTERVAL '3 min'""")
    new_offline = [n for n in offline if n not in _already_alerted and n not in _rested_now(REST_EXCLUDED)]
    if len(new_offline) > ALERT_THRESHOLD:
        send_system(f'FLEET ALERT: {len(new_offline)} approved nodes OFFLINE: {new_offline}')
        _already_alerted.update(new_offline)

    # DUPLICATE-IDENTITY (storm signature; impossible under FIX1 → an alert here means FIX1 regressed):
    dupes = q("""SELECT p.node_id, p.hostname FROM remote_nodes p
        JOIN remote_nodes a ON a.hostname=p.hostname AND a.id<>p.id
        WHERE p.approval_status='pending' AND a.approval_status='approved'
          AND p.hostname IS NOT NULL
          AND p.hostname NOT IN (SELECT remote_addr_hostname FROM ...)""")  # exclude shared-NAT hostnames
    if dupes:
        send_system(f'FLEET ALERT: {len(dupes)} pending DUPLICATE rows for approved hardware: {dupes}')
```

---

## Guardrails & invariants

So a DR flip can never orphan the fleet again:

- **INVARIANT (hub):** `register_node()` may only INSERT a new row for hardware it has **never** seen. A request carrying a **verifying `api_key_hash`** MUST UPDATE-in-place and return the existing `node_id` with `approval_status` unchanged. An unauthenticated `re_register` may only refresh `last_heartbeat` — never rotate the key, never be the sole match basis, never reclaim identity. *(FIX1; regression test fails if a re-registration from an approved node ever increases `remote_nodes` row count.)*
- **INVARIANT (hub):** A node with valid credentials can never be permanently locked out. Heartbeat/sync verify the api-key BEFORE/ALONGSIDE the approval gate; a credential-valid, ever-heartbeated node auto-re-approves (unless this process is an unpromoted DR standby); a genuinely-new node gets a distinct **409 `pending`** (not 404) so the client backs off. *(FIX2.)*
- **INVARIANT (node):** An env-protected or persisted `NODE_ID` is immutable at runtime. node_sync must NEVER persist a `node_id` from a re-registration response that differs from its locked id — it logs an error and keeps its identity. *(FIX3.)*
- **INVARIANT (node):** A previously-approved node (`_ever_approved`, derived from durable identity) never re-registers as a recovery action — it backs off exponentially (cap 600s) and alerts. Re-registration is reserved for first-ever enrollment. DR-failover retry remains active independently. *(FIX3+FIX4.)*
- **INVARIANT (DR):** `failover.sh` repoints ALL nodes via the identity-preserving `repoint.sh` (recreate, preserve `NODE_ID`/`HUB_API_KEY`); node_sync autonomous DR failover is last-resort only and, post-FIX3, cannot reset identity. *(FIX5.)*
- **INVARIANT (DR):** A fleet-wide connectivity BLACKOUT alone cannot auto-fire a wholesale failover unless boston-2 independently confirms hub Postgres+HTTP are down (dual-port, own vantage); otherwise it raises split-brain CRITICAL. Wholesale CLI failover requires `DR_CONFIRM`; `AUTO=1` requires a signed quorum token. *(FIX6.)*
- **INVARIANT (DR fencing):** Every reclaim/INSERT stamps a monotonic `hub_epoch`; a node echoes the epoch back, so a stale (un-promoted) hub's reclaim during split-brain is rejectable. *(FIX1.)*
- **INVARIANT (DB):** Enrollment/re-registration INSERTs must always set `deployment_mode` explicitly — never rely on the `'standard'` column default. *(FIX1; test asserts a re-enrolled outpost keeps `deployment_mode='outpost'`.)*
- **MONITOR:** Continuous duplicate-identity detector — any `pending` row matching an `approved` node's real hostname pages immediately (impossible under FIX1; an alert here means FIX1 regressed). *(FIX8.)*
- **MONITOR:** Mass-offline detector — approved nodes stale `>3 min` (per-node deduped, rest-excluded) page above threshold. *(FIX8.)*

---

## DR process changes

- **DR scope MUST include fleet-node IDENTITY as a first-class concern.** Every DR design doc and runbook (KB #270037/#270232/#270238/#270239) adds an explicit section answering: during failover/failback, how does each node KEEP its `node_id` + `approval_status` + `deployment_mode`? "Nodes just reconnect" is banned as an assumption — the reconnection path (`repoint.sh`, NOT node_sync re-registration) must be named.
- **Single canonical DR script tree (kill the two-copy drift).** Confirm the actual boston-2 `/opt/archie-dr` rsync source FIRST, then consolidate by **moving** `repoint.sh` + `watchdog/` into the chosen tree (never `git rm` the only copy); collapse the divergent `failover.sh` into a stub that execs the canonical one. Add a CI/pre-commit guard that fails if a second divergent copy of `failover.sh`/`failback.sh` reappears. Record which physical copy is deployed to boston-2 in the runbook and verify after every DR PR.
- **Never run `failover.sh` wholesale — enforced in code, not just docs.** The `DRILL_MODE`/`DR_CONFIRM` gate (FIX6) makes an accidental wholesale CLI run a no-op. All rehearsals use `DRILL_MODE=1` (no DNS flip, single test node).
- **Watchdog quorum tightening.** A fleet-wide BLACKOUT no longer trivially arms: boston-2 must independently confirm hub Postgres+HTTP down (dual-port `probe_local`) before arming; otherwise it raises split-brain CRITICAL. `AUTO=1` requires a signed quorum token. The abort window is **not** extended (it would orphan more nodes pre-FIX3).
- **Treat re-registration as IDENTITY-DESTRUCTIVE in code review.** Any future endpoint/client change that can mint a `node_id`, write `config.json` `node_id`, or set `approval_status` MUST be reviewed against the "reclaim, don't recreate" rule. Add to `.claude/rules/fleet.md` as a hard invariant.
- **Mass-node-state changes require an alert + human ack.** Wire FIX8; "more than 1 node offline in 10 min" pages, not a silent ARMADA color change.
- **Don't make the DR coordinator a fleet node that can orphan itself.** boston-2 (Citadel) is both the DR watchdog host AND a managed fleet node; when it went down at 00:00 the coordinator vanished. Either run the watchdog on an independent host, or ensure the coordinator's own node lifecycle can never be subject to the re-registration path.
- **Mandatory post-flight reconcile.** After any DR/failover event (real or drilled), run `scripts/dr/reconcile_fleet_identity.sh` (FIX7) in dry-run as a required check and attach its output to the incident/drill record before declaring "recovered."

---

## Safe drill plan

**PRECONDITION:** deploy FIX1–FIX4 (hub + the `approved_at` backfill migration + a test node running the patched node_sync image) to a branch/sandbox. Pick ONE disposable test node (e.g. outpost-lithuania, per the Phase 5b drill — NOT a production-critical node). Snapshot `remote_nodes`. Set `DRILL_MODE=1` / never pass `DR_CONFIRM` so `failover.sh`'s DNS-flip and wholesale promotion are skipped (FIX6 gate).

1. **Record baseline identity** — capture the test node's `node_id`, `approval_status`, `deployment_mode`, `api_key_hash` from `remote_nodes`, and its env `NODE_ID`/`HUB_URL` from the container. These MUST be unchanged at the end.
2. **Simulate hub-unreachability WITHOUT a real failover** — on the test node, block egress to the hub mesh IP (`iptables -A OUTPUT -d 100.64.0.4 -j DROP`) for ~6 minutes (crosses 5-strike). Assert node_sync backs off exponentially, under FIX3 does NOT call `_attempt_re_registration`, does NOT overwrite its `node_id`, and (FIX4) STILL attempts `_maybe_dr_failover` on the independent cadence.
3. **Exercise the repoint path (identity-safe)** — run `scripts/dr/repoint.sh 100.64.0.10` (point at the DR mesh; standby up read-only for the drill, DNS untouched). Assert the container recreates, `HUB_URL` flips in `sync.env`, `NODE_ID`/`HUB_API_KEY` are byte-identical to baseline, and the node heartbeats 200 against the DR standby with the SAME `node_id`, still `approved`.
4. **Restore + failback** — unblock the route, run `repoint.sh 100.64.0.4`. Assert `_probe_hub` sees the primary, fails back, heartbeats 200 on the hub; `remote_nodes` shows the ORIGINAL `node_id` heartbeating NOW, `approved`, `deployment_mode` unchanged.
5. **Assert ZERO new identities** — `SELECT count(*) FROM remote_nodes` equals baseline. No `pending` row matching the test node's hostname. `reconcile_fleet_identity.sh` (dry-run) reports no orphans. **Pass/fail gate.**
6. **Negative test of the watchdog guard** — simulate BLACKOUT in a sandbox (block boston-2→outpost SSH while leaving hub HTTP/5432 UP from boston-2's vantage). Assert `dr_watchdog.sh` (FIX6) raises split-brain CRITICAL and does NOT arm failover. Then simulate true hub death (hub 3000+5432 down) with quorum and assert it DOES auto-arm after the abort window — proving the guard discriminates a mesh blip from a real outage.
7. **Teardown + record** — restore the route, confirm 9/9 healthy in ARMADA, attach the drill log + reconcile dry-run output to the Project #368 record. **PASS criteria:** (a) no node changed `node_id`; (b) no node dropped to pending; (c) `remote_nodes` row count unchanged; (d) no production DNS touched; (e) watchdog refused to fire on the simulated blackout; (f) the down node still attempted DR failover during the blip.

---

## Open follow-ups / tasks to file

- **T-DR-1 (RC1/RC5, FIX1):** Land reclaim-aware, api-key-verified `register_node()` + `deployment_mode` INSERT column + stale-DELETE `approval_status<>'approved'` guard + `hub_epoch` fencing column/migration. Regression test: 50 rapid re-registers from one approved node → 0 new rows.
- **T-DR-2 (RC3, FIX2):** Self-heal heartbeat + mesh-sync 409 + **migration `NNN_backfill_approved_at.sql`** (ship first). Regression seeded from the migration-067 path (`approved_at` NULL).
- **T-DR-3 (RC2, FIX3):** node_sync identity-adoption refusal + persist/derive `_ever_approved` in `write_config`/`load_config` + thread HTTP status out of `send_heartbeat`. Push patched client image via OTA to all nodes.
- **T-DR-4 (RC2, FIX4):** Capped exponential backoff; decouple + preserve DR-failover retry on `>=5`; route bare-except increment through backoff. Test: "DR hub reachable only after strike-5 → still fails over."
- **T-DR-5 (RC4/RC7, FIX5):** Confirm boston-2 `/opt/archie-dr` rsync source; consolidate DR trees by MOVE; author `repoint.ps1` (Windows Starships) or drop the SSH branch; add CI guard against tree divergence.
- **T-DR-6 (RC6, FIX6):** Watchdog split-brain discrimination via `probe_local`; `DR_CONFIRM`/`AUTO=1` quorum-token gate; do NOT extend abort window.
- **T-DR-7 (RC8, FIX7):** Author `scripts/dr/reconcile_fleet_identity.sh` (dry-run default, `--apply`, `node_db_id` FK guard, per-node repoint emit). Wire into mandatory post-flight.
- **T-DR-8 (RC1/RC4, FIX8):** Author `services/fleet_identity_monitor.py` (DHQ scheduled job, mass-offline `<NOW()-3min` + dedupe + per-node rest exclusion; duplicate-identity detector excluding shared-NAT hostnames). Route via `telegram_service.send_system`.
- **T-DR-9 (infra):** Fix the Windows Docker Desktop SSH path on USS-245/246 (OpenSSH service or SSH sidecar container) so future DR can repoint Starships non-interactively.
- **T-DR-10 (design):** Move the DR watchdog/coordinator off boston-2 (a managed fleet node), or harden its own node lifecycle against the re-registration path.
- **T-DR-11 (docs):** Update DR runbook + KB #270037/#270232/#270238/#270239 with the fleet-node-identity section and add the "reclaim, don't recreate" + "never wholesale failover" invariants to `.claude/rules/fleet.md`.
- **T-DR-12 (auth):** Authenticate `/api/nodes/register` and add an `ON CONFLICT (node_id)` de-dup so a storm cannot flood `remote_nodes` even if FIX1 ever regresses.
