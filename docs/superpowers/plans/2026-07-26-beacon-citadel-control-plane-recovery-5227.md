# Recover Beacon + Citadel onto the Headscale control plane (#5227)

**Risk class: HIGH.** Beacon is the front door for all 18 hub hostnames **and** serves the Headscale
control plane (`mesh.` :443) that the recovery depends on. The naive fix (`tailscale up` / re-register)
is the exact identity-destructive operation that orphaned 7/9 nodes on 2026-06-05.
**Invariant (fleet.md): reclaim, never recreate.**

## Measured state (2026-07-26)

| Node | headscale `Connected` | `last_seen` | tailscaled | `mesh.:443` from it | data plane |
|---|---|---|---|---|---|
| `beacon` (100.64.0.11, id 20) | **offline** | **2026-06-27 23:03** | active | reachable | works (ping+ssh) |
| `citadel-us` (100.64.0.10, id 19) | **offline** | **2026-07-02 13:35** | active | reachable | works (ping+ssh) |

Each node's own `tailscale status` reports **itself** offline. Every other node (hub, 3 outposts,
2 starships, shuttle-kytran, subnet router) is `online`.

**So: network path fine, control-plane SESSION dead.** The WireGuard data plane runs from cached peer
state, which is why every reachability probe passes and why this hid for a month. Reachability checks
structurally cannot detect this — that is the lesson, not an aside.

⚠️ `beacon.last_seen` = **2026-06-27**, the NPM decommission date. Same family as the documented
`archie_tailscale` `extra_hosts` pin that silently killed node 15 for 23 days once the hub lost :443.

## Step 0 — DO NOT, under any circumstances

- ❌ `headscale nodes delete` / `headscale nodes register` for either node — mints a new identity,
  breaks `remote_nodes` FKs, and is the 06-05 storm.
- ❌ `tailscale logout` — discards the node key, forcing exactly the re-registration above.
- ❌ Touch Beacon's Caddy or the `mesh.` DNS rewrite. They are correct and currently load-bearing.
- ❌ Run anything on Beacon that could interrupt :443 before Citadel is recovered — Citadel reaches the
  control plane *through* Beacon.

## Step 1 — Diagnose WHY the session is dead (read-only, no state change)

Determine which of three causes applies before acting; the remedy differs per cause.

1. **Node key expired.** `headscale nodes list` shows `Expiry`/`Expired` — currently `N/A` / `no` for
   both, which *argues against* expiry. Confirm with `headscale nodes list -o json` and read
   `expiry` + `pre_auth_key` per node.
2. **Client cannot complete the control-plane handshake** despite TCP reachability — e.g. it is
   pinned/configured at a stale `--login-server`, or TLS/SNI to `mesh.` fails from that host
   specifically. Check on each node: `tailscale debug prefs` (look at `ControlURL`) and
   `journalctl -u tailscaled --since '30 days ago' | grep -iE 'control|register|401|403|expired|cert'`.
   **Byte-compare `ControlURL` against headscale's `server_url`** — fleet.md: a mismatch is a latent
   break, and `https://mesh.kytranempowerment.com` must match exactly.
3. **Self-referential loop (Beacon only).** Beacon resolves `mesh.` to **itself** and must hairpin
   through its own Caddy to reach headscale on the hub. If that hairpin is broken (the same class as
   DERP-on-hub, #5220), Beacon can serve `mesh.` to the world while being unable to *use* it.
   Test from Beacon: TLS GET `https://mesh.kytranempowerment.com/key?v=118` — a 200 rules this out;
   anything else confirms it, and the fix is to give Beacon's tailscaled a direct path to the hub
   (`--login-server` via the hub's mesh IP is NOT valid — it must match `server_url`; instead add a
   host-level override so `mesh.` resolves to the hub for Beacon itself).

## Step 2 — Reclaim, in the least destructive order

Ordered by escalating invasiveness; **stop at the first that works** and re-verify before continuing.

1. `systemctl restart tailscaled` on **Citadel first** (not Beacon — Citadel is not in the control
   path for anything else). Wait 60s, re-check `headscale nodes list`. A restart preserves the node
   key in state; it does not re-register.
2. If Step 1 fixes Citadel, apply the same to **Beacon**, but only after confirming `mesh.:443` still
   serves from an off-Beacon vantage (the hub) — so a failed Beacon restart is detectable immediately.
3. If a restart is insufficient, `tailscale up --login-server=https://mesh.kytranempowerment.com`
   **without** `--force-reauth` and **without** an authkey. With existing state this re-establishes
   the session using the SAME node key. Verify the node id in `headscale nodes list` is **unchanged**
   (19 / 20) — a new id means it re-registered and must be reverted per
   `scripts/dr/reconcile_fleet_identity.sh`.
4. Only if the key is genuinely expired: `headscale nodes expire`-adjacent renewal, never delete.

## Step 3 — Verify (on the path that matters, not the convenient one)

- `headscale nodes list` → both `Connected=online`, **ids still 19 and 20**.
- From the hub: `100.64.0.10` / `100.64.0.11` still ping + ssh (data plane preserved).
- From **each** node: `tailscale status` no longer reports itself offline.
- All 18 hostnames still serve through Beacon (re-run the 20-host TLS sweep from this session).
- Owner-visible check: both go green in the Tailscale app. **That is the acceptance test** — the
  DHQ Fleet tab is a separate signal (#5218) and must not be used as proof here.

## Step 4 — Make it detectable (the actual deliverable)

A month of invisibility is the real defect. Add a monitor that alerts on
`headscale last_seen` older than N hours **per node**, distinct from reachability. Fold into the
`fleet_identity_monitor` job (FIX8) which already watches mass-offline + duplicate-identity.
Register it in `platform_registry_job` once the registry (see the living-registry spec) exists.

⚠️ Report `unknown` — never a false all-clear — for a node with no heartbeat history, so a fresh
enrollment cannot page. Same rule as the backup-freshness and gov-watch ingest monitors.
