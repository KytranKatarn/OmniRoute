# DERP relay off the hub — evaluation + recommendation (task #5220)

**Status:** evaluated, prerequisites VERIFIED, **not applied**. Needs an owner decision on
the TLS/port arrangement before anything touches live Headscale.
**Date:** 2026-07-26 · **Project #368** · Related: #5214, #5218, #5219

---

## The finding

Every node's netcheck reports `Nearest DERP: ARCHIE Hub`. DERP is the relay used when two
peers cannot open a direct connection — so the relay of last resort lives on **the machine
the mesh exists to survive the loss of**.

Confirmed in `headscale/config.yaml`, and it is worse than "on the hub":

```yaml
derp:
  server:
    enabled: true              # EMBEDDED in the headscale process
    region_id: 900
    region_name: ARCHIE Hub
    stun_listen_addr: "0.0.0.0:3478"
    automatically_add_embedded_derp_region: true
  urls: []                     # <-- no external DERP map
  paths: []                    # <-- no local DERP map
```

`urls: []` + `paths: []` means there is **exactly one DERP region in the whole fleet and it
is inside the control-plane process**. So a hub outage removes, in one stroke:

1. the thing you are failing away from,
2. the control plane, and
3. the only relay you could have failed over *through*.

That is the deadlock seen on 2026-07-25/26: mesh recovery needed the control plane, and the
control-plane hostname needed the mesh. Nodes that could have kept talking to each other and
to Beacon/Citadel via relay went fully dark instead of degrading.

**Second-order consequence — netcheck is self-referential.** `netcheck` measures UDP by
STUNning against a DERP server, and the only DERP is the hub. A node therefore cannot use
netcheck to measure the hub. `UDP: false` was misread as a blocked port during the incident;
it is unmeasurable, not false. Any future diagnosis that leans on netcheck output inherits
this blind spot until there is a second region.

---

## Prerequisites — VERIFIED, not assumed

The task required these be checked before touching anything.

### 1. A DERP change is NOT identity-destructive ✅

This was the real risk (KB #270611 — re-registration orphaned 7/9 nodes on 2026-06-05).

Checked directly against the live Headscale SQLite (`v0.25.1`, read-only):

```
tables: migrations, users, pre_auth_keys, routes, api_keys, nodes, policies
columns mentioning derp: NONE
nodes columns: id, machine_key, node_key, disco_key, endpoints, host_info,
               ipv4, ipv6, hostname, given_name, user_id, register_method,
               forced_tags, auth_key_id, last_seen, expiry, created_at,
               updated_at, deleted_at
```

Node identity is `machine_key` / `node_key` / `disco_key` / `auth_key_id`. **No table in the
schema references DERP at all.** The DERP map is delivered to clients in the netmap at
runtime; `derp.update_frequency: 24h` only makes sense for a map that is re-read while
running. Changing DERP config therefore cannot alter node identity — it is config-only, and
the fleet-orphaning invariants in `.claude/rules/fleet.md` are not engaged.

`headscale` also has no DERP subcommand and no DERP-related node operation; DERP appears
nowhere under `headscale nodes`.

### 2. Beacon can host it ✅ (with one conflict)

Measured on Beacon 2026-07-26:

| Resource | Value | Verdict |
|---|---|---|
| RAM | 3915 MB total, **3261 MB available** | ample — `derper` is tens of MB |
| Disk | 45 G free of 48 G | ample |
| Load | 0.00 / 0.04 / 0.00, up 52 days | idle and stable |
| Docker | 29.5.3 present | can run `tailscale/derper` |
| `:3478` UDP (STUN) | **free** | no conflict |
| `:80`, `:443` TCP + `:443` UDP | **held by Caddy v2.11.4** | ⚠️ conflict — see below |

Beacon is already the sole external front door, already outside the hub failure domain, and
already terminates TLS. It is the architecturally correct home.

---

## The one open decision: how DERP gets its TLS on Beacon

`derper` conventionally owns `:443` so it can serve DERP-over-HTTPS and obtain its own
Let's Encrypt certificate. **Caddy already owns `:443` on Beacon** (TCP and UDP/HTTP-3), and
Caddy is what serves every public hostname the platform has. Options, none free of trade-offs:

| # | Approach | Pros | Cons |
|---|---|---|---|
| **A** | `derper` on a **non-standard port** (e.g. `:8443`) with its own cert; publish a custom DERP map with `DERPPort: 8443` | No Caddy changes; derper owns its TLS the supported way | Needs a cert path for a non-443 listener; a custom `derp.paths` map to maintain; some restrictive networks block odd ports — which is exactly when a relay matters |
| **B** | **Caddy terminates TLS** for `derp.kytranempowerment.com` and reverse-proxies to a local `derper` | Reuses existing cert automation + the port already open everywhere | DERP behind a reverse proxy is a finicky, less-travelled path; needs verification that Caddy passes the upgrade cleanly under load |
| **C** | Move **Caddy off 443** / give Beacon a second IP so derper can own 443 | Most standard derper deployment | Touches the front door for all ~20 hostnames — highest blast radius, on the node whose whole job is availability |

**I am not picking this unilaterally.** All three change how the fleet's fallback path works,
on live mesh infrastructure, days after an outage and while DR is disarmed. Option B looks
most aligned with existing architecture (Beacon = Caddy = TLS), but "looks aligned" is not
evidence, and DERP-behind-proxy is the option I have the least verified knowledge of.

---

## Recommended sequencing (lower risk than a move)

**Do not start by moving the relay. Start by ending the single point of failure.**

1. **ADD a second DERP region on Beacon, keep the hub's.** Purely additive: the hub region
   keeps working exactly as today, and the fleet gains a relay outside the hub failure
   domain. Nothing to roll back if it misbehaves — remove the region.
2. **Verify** with `netcheck` from Starship-246/245 and an outpost that Beacon appears as a
   region and is selected when the hub is unreachable. This also makes netcheck non-self-
   referential for the first time, which is a diagnostic win independent of failover.
3. **Only then** consider demoting or removing the hub's embedded region.

Validate any candidate config offline first — `headscale configtest` exists in v0.25.1 and
can be run in a throwaway container against a candidate file, with zero effect on prod.

### On option (c) from the task — public DERP fallback

`derp.urls: []` means Tailscale's public DERP mesh is **not** a fallback today. Adding it
would be a one-line change and would immediately remove the deadlock. It is rejected as a
*primary* answer on sovereignty grounds (traffic stays end-to-end encrypted, but the path
would be foreign-controlled, cutting against `company-vision.md`). Worth an explicit owner
decision as a **tertiary** last resort, since "the fleet is dark" is also a bad outcome.

---

## Blast radius if this goes wrong

The failure mode is the same one that severed both Starships on 2026-07-26 (#5219): change
something the control plane hands to clients, point it somewhere that cannot serve it, and
nodes lose the mesh. Mitigations already in place from this session: `mesh.` is now a
protected DNS rewrite, and `failover.sh` probes `:8095` before flipping the control-plane
hostname. Those guard the *hostname*; nothing yet guards the *DERP map*, which is why step 1
above is additive-only.

---

## Decision needed from Kytran

1. Which TLS/port arrangement (A / B / C) for `derper` on Beacon?
2. Is a public-DERP tertiary fallback acceptable, or sovereign-only even when the
   alternative is a dark fleet?
3. Confirm a window — this touches live mesh infrastructure and DR is currently disarmed
   (`/opt/archie-dr/.watchdog_disabled` still set, boston-2 a promoted fork with no
   replication).
