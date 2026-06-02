# A.R.C.H.I.E. DR RUNBOOK — recover the platform on boston-2 when the Starbase is down
*Lives OFF the hub: boston-2:/opt/archie-dr/ + (TODO) a git remote + a copy on the owner's machine.*
*Companion: dr-plan-boston2.md (the 7-phase plan). DR node: boston-2 = 2.25.133.122 / mesh 100.64.0.10 / root@ / KVM8 32GB.*

## When the hub (Starbase) is DOWN — FAILOVER
1. **Confirm it's really down** (not a blip). From your laptop / any node:
   `ssh root@2.25.133.122` then check the hub isn't reachable: `timeout 5 bash -c 'echo > /dev/tcp/100.64.0.4/3000' ; echo $?` (non-zero = down).
2. **Run failover** (it re-checks + refuses if the hub is up — split-brain guard):
   `ssh root@2.25.133.122 /opt/archie-dr/failover.sh`
   (only if you are CERTAIN the hub is dead but it still pings: `... /opt/archie-dr/failover.sh --force`)
3. failover.sh does: promote replica→primary (RW) → start the standby platform → verify `/login`=200 + a DB write.
4. **Phase 5 (public access — not yet built):** start Caddy/ingress on boston-2 and flip `platform.kytranempowerment.com` A-record → `2.25.133.122` via Hostinger DNS API. Until then the recovered platform serves locally on boston-2:127.0.0.1:3000 only.
5. **(Optional) Point the fleet at boston-2** so the recovered dispatcher sees the nodes (Phase 5b — manual until automated). For each SURVIVING node (`root@<ip>`, e.g. singapore/lithuania/uk; or `kytran@76.13.107.109` for outpost-boston):
   ```
   ssh root@<node-ip> "sed -i 's#100.64.0.4:3000#100.64.0.10:3000#g' /opt/archie-node/.env && docker restart archie_outpost_sync"
   ```
   Use the raw mesh IP `100.64.0.10` (NOT a `*.mesh.archie` name — MagicDNS dies with the hub). The Tailscale data plane is peer-to-peer, so nodes still reach `100.64.0.10`. On FAILBACK, change `100.64.0.10:3000` back to `100.64.0.4:3000` and restart sync on each node.
6. Expect **degraded mode**: no GPU (cloud/CPU inference only), some hub-only integrations (telegram, hub DNS names) error — non-fatal.

## When the hub COMES BACK — FAILBACK (avoid split-brain!)
**Invariant: exactly ONE primary at a time. Never run both read-write.**
1. **Fence the old hub first** — stop the hub `archie_database` accepting writes (or keep it down) before promoting/rebuilding, so two primaries never coexist.
2. Decide the new source of truth:
   - If boston-2 took writes during the outage, it is now authoritative. Rebuild the **hub** as a replica of boston-2 (reverse the Phase 2 setup), let it catch up, then switch back in a maintenance window.
   - If no real writes happened on boston-2, simpler: stop the standby platform, re-clone boston-2 from the hub (re-run `/opt/archie-dr/setup_replica.sh`), resume normal NORMAL mode.
3. Drop the failover test marker if present: `DROP TABLE IF EXISTS _dr_failover_marker;`
4. Restore DNS to the hub; demote boston-2 back to a streaming replica.

## After ANY drill or real failover
- Re-establish replication boston-2 ← hub (or hub ← boston-2) so the warm standby is live again.
- Confirm: `pg_stat_replication` shows streaming + lag low; standby platform container is `Exited` (stopped) again.

## Key facts
- Replica container: `archie_dr_replica` on **:5433** (psql needs `-p 5433`). Slot `boston2_replica`.
- Standby platform: `archie_platform_standby` via `/opt/archie-dr/platform/docker-compose.standby.yml` (DB→127.0.0.1:5433, no GPU).
- Replication user `replicator`; pw at boston-2:/opt/archie-dr/.replpw. Hub pg_hba allows source 172.27.0.1 (docker-proxy gateway) for replication.
- Recipes/gotchas: KB #270036 (replica), #270035 (Watch auth pip pkg). Plan: dr-plan-boston2.md.

---

## TIER 2 — COLD RESTORE from Backup Manager (when the warm standby is NOT enough)
*The boston-2 replica is HOT failover (RPO seconds). It is NOT a backup — it copies corruption/`DROP TABLE`/accidental deletes in seconds. For those, AND for the case where boston-2 itself is lost, restore from the nightly Backup Manager snapshot.*

**Where the backups live (hub):** `/mnt/data2/backups/<YYYYMMDD_HHMMSS>_Daily_Triage/` — nightly ~06:00 ET. Each contains:
- `database/archie_<ts>.dump` — pg **custom-format** dump of the brain DB (~590 MB)
- `gitbundles/{archie_brain,creed,business-suite}_<ts>.bundle` — git history (clone with `git clone <bundle>`)
- `code/archie_code_<ts>.tar.gz` — platform source · `config/config_<ts>.tar.gz`
- GFS retention 7 daily / 4 weekly / 3 monthly; cloud copy (GDrive AES-256-GCM) + USB.

**Restore the DB (CRITICAL — pgvector image, NOT plain postgres):**
```bash
# knowledge_base.embedding needs the vector extension. postgres:16-alpine FAILS
# ("CREATE EXTENSION vector" → not available). KB #256851 / #256850.
docker run -d --name archie_restore -e POSTGRES_PASSWORD=<pw> -e POSTGRES_USER=archie \
  -e POSTGRES_DB=archie -v <dump>:/backup.dump:ro pgvector/pgvector:pg16
docker exec archie_restore pg_restore --no-owner --no-privileges -U archie -d archie /backup.dump
# verify: SELECT count(*) FROM knowledge_base;  (should match the live row count)
```
Then point the standby platform at the restored DB (or promote it as the new primary, observing the single-primary fence).

**Verified restorable:** 2026-06-02 — non-destructive test-restore of the 06:00 nightly dump into a throwaway `pgvector/pgvector:pg16` container: knowledge_base **31,216 rows**, **30,992 embeddings intact**, vector extension present, users 36, agents 156. (4 fewer KB rows than live = rows added since the 06:00 snapshot, expected.) pg_restore exit clean aside from benign role/ownership notices.

---

## 5b DRILL FINDINGS (2026-06-02) — two gaps the fleet-repoint drill exposed (NOT yet fixed)
The "Phase 5b — point the fleet at boston-2" procedure in Step 5 above **does not work as written.** A full end-to-end drill on outpost-lithuania found:

1. **Nodes ignore `/opt/archie-node/.env`.** The sync client (v3.0.0) reads its hub URL from **`/etc/archie-node/config.json`**, not `.env`. After `sed`+restart the node kept heartbeating to `100.64.0.4` (its log still showed `Hub URL: http://100.64.0.4:3000`). **FIX the Step-5 repoint to edit `config.json` (the `hub_url` field) — or whatever writes it — then `docker restart archie_outpost_sync`.** (Silver lining: the node never went offline, so the drill was harmless.)

2. **The standby platform binds loopback-only.** `docker-compose.standby.yml` runs `gunicorn --bind 127.0.0.1:3000`, so boston-2's platform is **unreachable over the mesh** — a repointed node gets `Connection refused`. For real fleet takeover the standby must bind `0.0.0.0:3000` (or `100.64.0.10:3000`) AND boston-2 UFW must `allow from 100.64.0.0/10 to any port 3000`. failover.sh's `/login` check only hits `127.0.0.1`, so it passes while nodes still can't reach it.

**Until both are fixed, "fleet follows boston-2" (Phase 5b) is NOT functional.** Promote + standby + DB-write failover (Phase 4) IS proven; user-facing DNS flip (Phase 5) is staged. The gap is only node→boston-2 dispatch.

---

## 5b RESOLVED + Tier-2 auto-ship (2026-06-02, drilled end-to-end)
Phase 5b "fleet follows boston-2" is PROVEN. The three procedure bugs from the earlier findings are fixed:
1. **Node repoint** — use **`/opt/archie-node/repoint.sh <hub_mesh_ip>`** on each node (created this session). It edits `sync.env` AND **recreates** the sync container — a `docker restart` does NOT re-read `--env-file`, so a restart is a no-op. failover.sh Step 5 should call `ssh root@<node> /opt/archie-node/repoint.sh 100.64.0.10` (revert: `... 100.64.0.4`).
2. **Standby mesh reachability** — `docker-compose.standby.yml` binds `127.0.0.1:3000` (Caddy + failover health check) **+ `100.64.0.10:3000`** (fleet over mesh) explicitly — NOT `0.0.0.0` (no public-interface exposure; security-review fix). boston-2 UFW also allows `100.64.0.0/10 → 3000` as defense-in-depth. Backup of the old compose: `docker-compose.standby.yml.bak-pre5b`.
3. **Standby boots** — the staged platform was missing the `ai_bridge/` sibling package; it is now staged at `/opt/archie-dr/platform/ai_bridge/`. Without it, `tools/consciousness/language_routes.py` import kills the gunicorn worker.

**DRILL RESULT:** promote → standby (RW, 0.0.0.0) → `repoint.sh 100.64.0.10` → lithuania heartbeat PERSISTED on boston-2 (last_heartbeat advanced to ~2s) → reverted → failback re-clone, streaming restored. Fully reversible.

## Tier-2 cold copy now AUTO-SHIPPED here (PR #1380)
The hub nightly `backup_triage.sh` now rsyncs each Daily_Triage backup to **`/opt/archie-dr/backups/`** over the mesh (`100.64.0.10`), keep-7. So this node holds BOTH DR tiers locally: the live streaming replica AND last-night's cold dump (DB `.dump` + code incl `ai_bridge` + gitbundles + config). Restore per the TIER 2 section above (pgvector image). This also gives a warm starting point for failback instead of a full 4.2 GB re-clone.

---

## FAILOVER now auto-repoints the fleet (failover.sh Step 4) + FAILBACK procedure
- `failover.sh` Step 4 SSHes the 3 global outposts (root@100.64.0.5/7/8) and runs `/opt/archie-node/repoint.sh 100.64.0.10` — recreates each sync container to point at boston-2. Uses the DR key `/opt/archie-dr/.ssh/id_ed25519`. Non-fatal per node.
- **FAILBACK — revert the fleet to the hub:** on each repointed node run
  `ssh root@<node> /opt/archie-node/repoint.sh 100.64.0.4`
  (or from boston-2 with the DR key). This recreates the sync container back to the hub. A `docker restart` will NOT work — the hub URL is a baked env var; `repoint.sh` recreates.

## Known DR gaps — TRACKED (Project #368)
- **#3679 (P7)** — NO scheduler runs on the standby: in DR, only web/dispatch runs; autonomous APScheduler jobs (WTF ingest, embedding, fleet_health, delegate_task_worker…) PAUSE. API/manual dispatch still works. Add archie_scheduler to docker-compose.standby.yml.
- **#3680 (P5)** — Starships 245/246 are NOT repointed (LAN, Famil@, divergent). In a hub-BOX-only outage they survive but show offline on boston-2 until a Starship repoint path is built. (In a full Montreal SITE outage they die with the hub — moot.)
- **#3681 (P3)** — Headscale control-plane standby for LONG outages (P2P tunnels persist short-term; new joins/re-auth need the coordinator). Deferred, drill-required.
- **#3682 (P6)** — secrets in the config tar are PLAINTEXT and now ship to boston-2 + USB. Encrypt at rest with a key the recovery operator holds off-hub.

## What auto-ships to boston-2 now (steady state, NORMAL)
- Nightly `backup_triage.sh` (hub, 02:00) → `/opt/archie-dr/backups/<TS>_Daily_Triage` (keep-7): DB `.dump` (archie + wtf) + code (incl ai_bridge) + gitbundles + config.
- Same nightly REFRESHES the warm-standby source: rsync live `platform_v2` + `ai_bridge` → `/opt/archie-dr/platform/` (prevents staged-source drift — the ai_bridge boot blocker).
