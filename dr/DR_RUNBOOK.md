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
