# DS9 tab: the Codex app-server as a first-class card (Dev HQ #7395)

**Status:** shipped in this PR. Live and verified against the running DS9.

## The gap

The platform's DHQ "Deep Space 9 (DS9)" tab listed the PLATFORM's external AI
upstreams (`engineer_providers` — cerebras, groq, openrouter, the `omni*`
aliases, opencode_zen, …). The Codex **app-server** was not among them, and it
could not be: the app-server is not a platform provider. It is a CONNECTION
inside DS9's own store (`provider_connections`, provider `codex-app-server`) —
the upstream that lets DS9 drive the OpenAI Codex CLI directly instead of
replaying a ChatGPT session token (Dev HQ #7378).

The consequence was that an operator working in the platform's DS9 pane could
see the app-server *used* (it appears as a line item in the observation-only
quota card) but could not tell:

- which account the sidecar is authorized as,
- whether the upstream is actually reachable right now,
- which models it offers,
- or where to go to change any of it.

## What shipped

| File | Role |
|---|---|
| `platform_v2/services/ds9_app_server_service.py` | The read-only view of DS9's app-server connections. |
| `platform_v2/tools/department_hq/engineer_routes.py` | `GET /api/engineers/app-server-connections`. |
| `platform_v2/tools/department_hq/templates/department_hq.html` | The `ds9AppServerCard` placeholder in the DS9 panel. |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | `loadAppServerConnections()` — paints the card. |

### Two read paths, both read-only

**DS9's SQLite** — `provider_connections` where `provider = 'codex-app-server'`.
The platform is a READER of DS9's data and there is no INSERT/UPDATE anywhere
in the service. The platform must never write to DS9's store.

**DS9's own API** — the live health verdict comes from DS9's own provider
test (`POST /api/providers/<id>/test`), which already distinguishes the three
states that need different operator actions:

| DS9 diagnosis | `auth_state` | What the operator sees |
|---|---|---|
| `valid: true` | `authenticated` | green, with the round-trip latency |
| `app_server_login_required` | `signed_out` | amber — the CLI is up but not signed in |
| `app_server_unconfigured` | `not_configured` | red — the adapter has no URL/token |
| (no verdict) | `unknown` | dim — DS9 could not be reached |

That probe is DS9's code, and it is side-effect-free: it probes, it does not
mutate the connection. Re-implementing it here would give the platform a
second, drifting copy of the same logic, so the service CALLS it.

### Two details that are easy to get wrong

**`OMNIROUTE_BASE_URL` is the wrong variable.** It is the *inference* base and
carries a `/v1` suffix (`http://host.docker.internal:20129/v1`). Building the
provider-test URL from it yields `…/v1/api/providers/<id>/test`, which 404s.
The service uses a dedicated `DS9_API_BASE_URL` (API root, no `/v1`) and a
separate `DS9_DASHBOARD_URL` for the link the operator's browser opens —
the browser runs on the host and cannot resolve the container's
`host.docker.internal`.

**`immutable=1` reads a STALE snapshot.** DS9 runs SQLite in WAL mode.
`immutable=1` tells SQLite the file can never change, which makes it ignore
the `-wal` file and read the last checkpointed snapshot instead. Measured on
the live store: `mode=ro` saw 9356 `call_logs` rows, `immutable=1` saw 9355.
The service prefers `mode=ro` and falls back to `immutable=1` for a
deployment where the `-shm` sidecar is not readable.

(The existing `omniroute_quota_service` uses `immutable=1`. That is a
narrower read than it looks, but it is not wrong in a way that matters for
per-provider throttle counts, and it is out of scope here.)

### The card

Shows the connection's name, whether it is active, its auth state, the
round-trip latency, its base models, the count of its reasoning-effort
variants, and a link to DS9's own provider page. DS9 lists the app-server's
models as a base model plus a reasoning variant of each (`-ultra`, `-max`,
`-xhigh`, `-high`, `-medium`, `-low`) — 8 base models and 44 variants. The
card separates the two so the base models, which are what an operator picks,
are not crowded out by 50 near-duplicates.

DS9 being down, missing, or slow must NOT break the tab. The tab reports on a
gateway; it degrades to "unavailable", never to a 500.

## The infrastructure bug this uncovered

While verifying the card against the real DS9, the connection did not appear.
The cause was not the new code:

> The running `archie_platform` container was mounting the Docker volume
> `archie_omniroute_data` at `/omniroute-data` — the **orphaned** 20128
> container gateway's data directory. `docker-compose.yml` had declared
> `/home/kytran/.omniroute` (the live systemd DS9's data dir) since
> `cbf519c23` (08:15 on 2026-10-20), but the container had been created on
> 2026-10-17 and **`docker compose restart` does not re-apply mounts** — only
> `docker compose up -d` recreates the container.

So the platform's DS9 view — the quota card, and `omniroute_telemetry` — had
been reading the orphan's database instead of the live DS9's. The live DS9's
call traffic, including all app-server traffic, was invisible to the platform.

Fixed at runtime by recreating both affected services:

```
docker compose up -d --no-deps archie_platform archie_scheduler
```

Both came back healthy in 10s, and the platform now sees the live store.

**The general trap, worth remembering:** a container's mounts and environment
are fixed at CREATE time. `docker compose restart` re-runs the container with
the mounts and env it was created with. Any deploy that changes a mount or an
env var needs `docker compose up -d --no-deps <svc>`, and a plain `restart`
will silently leave the old value in place. The repo's own deploy rule
already says this for env vars (`env_file`); the same holds for mounts.

## Verification

- 13 new/existing tests pass on the HOST (Python 3.12) and inside the
  platform container (Python 3.11) — the test files derive the platform root
  from the filesystem so the same suite runs in both layouts.
- `test_dhq_ds9_app_server_endpoint.py` proves the endpoint refuses an
  unauthenticated caller (no connection data leaks) and serves a real
  connection to an admin.
- `test_ds9_app_server_service.py` proves the read is read-only (the store's
  bytes are unchanged after a read, and a write through a `mode=ro` handle is
  refused), that the three diagnoses map to three distinct auth states, and
  that a missing or unreachable DS9 degrades instead of raising.
- The endpoint was exercised against the LIVE DS9: HTTP 200, the
  `DS9 Codex app-server` connection, active, `authenticated`, 46 ms
  round-trip, 8 base models, 44 reasoning variants.
- The rendered DHQ page was checked for the DS9 tab, the DS9 panel, the
  `ds9AppServerCard` placeholder, the providers grid and the quota card.
- Regression: the DHQ test selection was run with and without these changes —
  identical results (7 failures both ways, all pre-existing: 5 are a
  host-3.12/container-3.11 `ast.dump` difference in golden-hash fixtures and
  2 predate this work entirely).
