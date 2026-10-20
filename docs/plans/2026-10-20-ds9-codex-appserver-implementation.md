# DS9 Codex app-server — implementation record

Status: **deployed, authenticated, and verified through the full tool
round trip.** The app-server is running isolated, DS9's own adapter reports
`valid: true`, and gates 1–6 of the plan's checklist pass. Gate 7 — the host
`ds9` client profile — is the next phase and is deliberately not started.

Parent: [integration plan](2026-10-20-ds9-codex-integration.md) ·
[operator setup package](2026-10-20-ds9-codex-operator-setup.md).

---

## What was actually built, and why it differs from the operator plan

The operator package was written at 15:24 on 2026-10-20 and specified a **Docker
Compose sidecar** on a private network, reached by the gateway at
`ws://ds9-codex-appserver:1456`.

Two facts made that shape inapplicable:

| Plan assumed | Actual state at implementation (2026-10-20) |
|---|---|
| DS9 = the `omniroute` container, Compose project `archie_brain` | Commit `cbf519c23` (08:15) **removed** the `omniroute` service from `docker-compose.yml`. DS9 was redeployed at 08:22 as a **host-native systemd service**, `deep-space-9.service` (v16.3.8), port **20129**. The old container still runs on 20128 but is no longer Compose-managed. |
| Gateway reaches the sidecar by Compose DNS name | A **host process cannot resolve a private Docker network's DNS name**. The specified transport was not reachable even with the sidecar built exactly as written. |

The gateway the platform actually uses is the systemd one: `docker-compose.yml`
points the codex lane at `host.docker.internal:20129`.

**Decision (owner-approved): run the app-server as a host systemd unit with a
loopback-only listener.** This keeps every security property the plan asked for
and is *stricter* than the Compose shape would have been:

- the port is **not published at all** — there is no `ports:` mapping to abuse;
- it sits on **no shared network**, container, or LAN interface;
- a host process can reach loopback; a container could not have been reached by
  DNS name at all.

---

## Deployed artifacts

| Artifact | Path | Purpose |
|---|---|---|
| systemd unit | `scripts/systemd/ds9-codex-appserver.service` | the isolated upstream |
| installer | `scripts/systemd/install-ds9-codex-appserver.sh` | idempotent provisioning; prints no secret |
| gateway drop-in | `scripts/systemd/deep-space-9.ds9-codex-appserver.conf` | DS9 adapter env + credential |

Installed on the host at:

- `/etc/systemd/system/ds9-codex-appserver.service`
- `/etc/systemd/system/deep-space-9.service.d/ds9-codex-appserver.conf`
- `/usr/local/lib/ds9-codex/bin/codex` — pinned **codex-cli 0.163.0**
  (from `@openai/codex@0.163.0-linux-x64`, npm integrity
  `sha512-uwRaOsrYogLQh[...]FdJ0LCJ0N6e8w==`); the sibling
  `bin/codex-code-mode-host` is installed alongside it and is required for
  harness tool calls
- `/var/lib/ds9-codex` — the isolated `CODEX_HOME` (system user `ds9-codex`)
- `/srv/ds9-codex/work` — empty scratch cwd
- `/etc/ds9-codex/ws.token` — the WS capability token, `0640 root:ds9-codex`

### The token never appears in a unit file or an environment value

Both services receive it as a **systemd credential**
(`LoadCredential=ws_token:/etc/ds9-codex/ws.token`), so it is not in
`systemctl show`, not in the unit file, and not in the process environment. The
sidecar reads it from `/run/credentials/ds9-codex-appserver.service/ws_token`;
DS9 reads it from `/run/credentials/deep-space-9.service/ws_token`.

### DS9 adapter settings (all read by the gateway's own resolver)

`open-sse/executors/codex/appServerConfig.ts` — these names are not invented:

```text
OMNIROUTE_CODEX_APPSERVER_WS=ws://127.0.0.1:1456
OMNIROUTE_CODEX_APPSERVER_WS_TOKEN_FILE=/run/credentials/deep-space-9.service/ws_token
OMNIROUTE_CODEX_APPSERVER_CWD=/srv/ds9-codex/work
OMNIROUTE_CODEX_APPSERVER_SANDBOX=read-only
```

> ⚠️ **Credential/URL binding** (gateway hardening after its #11205 security
> review): an env-sourced token is only paired with an env-sourced URL, or an
> operator-local host. Both ours are env-sourced, so the pair is accepted. If the
> URL is later moved into a connection's `providerSpecificData` while the token
> stays env-sourced, the resolver **returns null** and the provider silently
> stops being an app-server.

### The DS9 provider connection

```text
id           3eb3148b-3493-45b0-ba58-42963169e35e
provider     codex-app-server
name         DS9 Codex app-server
is_active    0        ← routing disabled until every gate below passes
psd          {}        ← no per-connection URL/token override
```

Created through the normal management API (`POST /api/providers`, with
`allowNoCredential: true` — `codex-app-server` is a `noAuth` provider, so DS9
never stores or replays the ChatGPT token). The pre-existing `opencode-zen`
connection was not modified.

---

## Verification evidence

All checks run on 2026-10-20 against the deployed services.

### Pinned runtime

| Check | Result |
|---|---|
| `codex --version` | `codex-cli 0.163.0` |
| `codex app-server --help` advertises `--ws-auth` | yes (`capability-token`, `signed-bearer-token`) |
| `codex app-server --help` advertises `--ws-token-file` | yes |
| `codex login --device-auth` supported | yes |
| `sandbox_mode=read-only` accepted by the CLI | yes |

### Transport gates (the plan's own list)

| # | Gate | Result |
|---|---|---|
| 1 | app-server port is not published | **pass** — `ss` shows `127.0.0.1:1456` only; a LAN request to `192.168.1.200:1456` is **refused** |
| 2 | process has no host mounts | **pass** — in the service's own mount namespace `/mnt/archie_brain`, `/mnt/standalone` and `/home` are `inaccessible`; the owner Codex home and the platform tree are unreadable |
| 3 | unauthenticated WebSocket is rejected | **pass** — handshake with a wrong/absent bearer fails |
| 4 | authenticated JSON-RPC `initialize` succeeds | **pass** — returns `codexHome: /var/lib/ds9-codex` (the isolated home, not the owner's) |
| 5 | `account/read` reports no account before login | **pass** — `NO ACCOUNT (logged out)`, exactly as expected pre-consent |
| 6 | direct OpenAI egress, no loop | **pass** — the app-server reached `https://chatgpt.com/...` and got a real `401` (unauthenticated), proving it is talking to OpenAI directly and not back into DS9 |

### DS9's own adapter (the strongest single signal)

`POST /api/providers/<id>/test` runs the gateway's real health path
(`/readyz` + `account/read` over the same WS transport the executor uses):

```json
{"valid": false,
 "error": "Codex app-server is running but its Codex CLI is not signed in.",
 "diagnosis": {"type": "auth_required", "source": "app_server",
                "code": "app_server_login_required"},
 "latencyMs": 53}
```

This is the decisive result: **DS9 reached the sidecar, found it healthy, ran
`account/read`, and correctly classified the one remaining gap as
authentication** — not as a transport, config, or routing fault.

### After owner consent

The same provider test flipped to:

```json
{"valid": true, "error": null, "latencyMs": 49,
 "diagnosis": {"type": "ok", "source": "local", "code": null}}
```

`codex login --device-auth` in the isolated home wrote
`/var/lib/ds9-codex/auth.json` (mode 0600, owner `ds9-codex`); the owner's own
`~/.codex/auth.json` was not read or written. The running app-server picked the
login up **without a restart**.

`account/read` then reports `type: chatgpt, planType: plus`.

### Tool round trip (gate 5)

| Step | Result |
|---|---|
| tool **call** | `FUNCTION_CALL read_file`, `args {"path":"/srv/ds9-codex/work/fixture.txt"}`, with a `call_id` |
| tool **result** replayed | model answered `The file contains: DS9-FIXTURE-4417` with **no re-call** |
| upstream execution | **none** — no `exec_command`/`apply_patch` in the sidecar log; the scratch cwd stayed empty |

Two implementation defects were found and fixed to get here. Both are recorded
below because both are invisible to a text-only test.

---

## Two defects found while verifying (both fixed)

### 1. The installer dropped a required binary

The npm package ships **two** executables in `bin/`: `codex` and
`codex-code-mode-host`. The installer copied only `codex`.

The first symptom was the model reporting *"the `read_file` call failed because
the tool host executable is missing"* — the app-server launches
`codex-code-mode-host` as the tool host for harness tool calls and could not
find it.

The installer now installs the whole `bin/` directory and **asserts**
`codex-code-mode-host` is present at install time, so this cannot silently
regress.

### 2. `MemoryDenyWriteExecute=yes` broke the tool path

Even with the binary present, the tool host died with `SIGTRAP` / "code-mode
host closed its stdout", and the model reported *"the tool host crashed"*.

Bisected directive-by-directive against a real tool call (18 systemd
properties, each in isolation). Result: **every** hardening directive left the
tool round trip working — `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`,
`ProtectSystem=strict`, `ProtectHome`, `ProtectProc=invisible`,
`RestrictNamespaces`, `SystemCallFilter=@system-service`,
`RestrictAddressFamilies`, `LockPersonality`, `RestrictRealtime`,
`RestrictSUIDSGID`, `ProtectKernel*`, `ProtectControlGroups`, `ProtectClock`,
`ProtectHostname`, `SystemCallArchitectures=native` — **except**
`MemoryDenyWriteExecute=yes`, which alone produced a TIMEOUT.

That directive denies writable+executable memory; the code-mode host needs it.
It is now **deliberately not set**, with the equivalent protections retained
where they matter (upstream sandbox pinned to `read-only`, `approvalPolicy`
`never`, non-root user, read-only rootfs, no host mounts). The reasoning is
recorded in the unit file so a future "tidy the hardening" pass does not
reintroduce it.

> ⚠️ **Why this mattered:** the text path keeps working with the tool path
> broken, so the provider still looks healthy, `valid: true`, and every
> liveness check passes. Only an actual tool call exposes it. **A green
> provider test is not evidence of tool compatibility.**

---

## Known gap in the installed gateway adapter (not a deployment defect)

`tokens_out` is recorded as **0** for every `codex-app-server` call, while
`tokens_in` is correct.

This is an adapter gap in the installed DS9, upstream of this work:

- the upstream **does** report output tokens — probed directly, codex 0.163.0
  emits `thread/tokenUsage/updated` with
  `{"total":{"inputTokens":15071,"outputTokens":8,"cachedInputTokens":12288,...}}`
- the adapter's `extractTurnUsage()` reads usage **only** from
  `turn/completed`, and codex 0.163.0's `turn/completed` carries **no** usage
  field (`turn keys: id,rootTurnId,items,itemsView,status,error,startedAt,completedAt,durationMs`)

Fixing it means teaching the adapter to consume
`thread/tokenUsage/updated` — a change in the DS9 source tree
(`/mnt/standalone/deep-space-9`), outside this deployment's scope. Until then,
output-token accounting for this provider is under-reported while input
accounting is correct.

---

## Transport constraint discovered while testing the result replay

`turn/start` in codex 0.163.0 accepts **only** content variants. The upstream
rejects a structured tool result outright:

```text
Invalid request: unknown variant `function_call_output`, expected one of
`text`, `image`, `localImage`, `audio`, `localAudio`, `skill`, `mention`
```

The DS9 adapter reflects this: `extractPromptText()` flattens the whole
Responses `input` array into a single text prompt, so a `function_call_output`
item is dropped before it reaches codex.

**Consequence for harness clients:** the tool result must be replayed as
**text** in the next request. Replaying it as a `function_call_output` item
(what the OpenAI Responses API would normally take) results in the model
re-issuing the tool call, because the adapter never tells it the call already
happened. The working shape is a user message carrying the result, e.g.
`"Tool read_file was already called with {...} and returned: <output>"` —
verified: the model then answers from the result without re-calling.

This is a property of the installed adapter, not of this deployment, and it is
recorded here so the CLI-integration work that follows does not rediscover it
the hard way.

### Service stability

| Service | State | Restarts |
|---|---|---|
| `ds9-codex-appserver.service` | active | 0 |
| `deep-space-9.service` | active | 0 |

---

## The owner sign-in gate — COMPLETED

The CLI is **not** signed in, and only the owner can complete this. Run it in
your own terminal — it prints a device code, which must not be pasted into a
chat, a PR, or a log:

```sh
sudo -u ds9-codex env \
  CODEX_HOME=/var/lib/ds9-codex HOME=/var/lib/ds9-codex \
  /usr/local/lib/ds9-codex/bin/codex login --device-auth
```

Open the URL it shows (`https://auth.openai.com/codex/device`), enter the
one-time code it prints, and approve the workspace you intend the sidecar to
use.

This writes `auth.json` into `/var/lib/ds9-codex` — the **isolated** home. The
owner's existing `~/.codex/auth.json` is never read or written by the sidecar
and stays exactly as it was.

> **Do not use the dashboard's "Sign in with ChatGPT" button for this
> connection.** It resolves `.codex/auth.json` against `getCliConfigHome()`,
> which honours `CLI_CONFIG_HOME` but **not** `CODEX_HOME` — and the DS9
> service sets neither, so it falls back to `os.homedir()` = `/home/kytran`,
> i.e. **the owner's own login**. The guarded writer also skips the write
> entirely when the existing `auth.json` is healthy, so the button would appear
> to work while the sidecar stayed logged out. The CLI path above targets the
> isolated home directly.

If the running app-server does not pick up a new login, restart **only** the
app-server (`sudo systemctl restart ds9-codex-appserver.service`) and recheck.
Do not restart unrelated platform services. (In this run the login was picked up
**without** a restart.)


---

## Gates (the plan's ready-to-enable checklist)

| # | Gate | Result |
|---|---|---|
| 1 | Authenticated WS readiness + negative unauthenticated control | ✅ |
| 2 | `account/read` returns an account for the intended workspace | ✅ `type: chatgpt, planType: plus` |
| 3 | Available models read from the running upstream; one exact model ID selected | ✅ 7 models; **`cxa/gpt-6.1-sol`** (`cxa` = `codex-app-server`; ctx 872000) |
| 4 | A bounded synthetic text request completes through the chosen connection | ✅ returned `DS9-OK-7291` verbatim in 5 s |
| 5 | A complete tool-call/result round trip succeeds | ✅ call → result → `The file contains: DS9-FIXTURE-4417`, no re-call, **no upstream execution** |
| 6 | DS9 records the intended connection/model and actual usage; no fallback or loop | ✅ `provider: codex-app-server`, `model: gpt-6.1-sol`, `status: 200`, correct `connection_id`/`api_key_id`, real `tokens_in`; `combo_name`/`combo_step_id` null (no fallback). `tokens_out` reads 0 — adapter gap, see above |
| 7 | Only then prepare/enable the host `ds9` profile | ⬜ **not started** — the client profile is the next phase, owned by the CLI-integration work |

The host `ds9` client profile is **not** created yet, by design.

**Routing state:** the connection is `is_active=1` (it had to be, to exercise
gates 4–6). There is no automatic fallback and no broader pool enrollment — the
provider is pinned to a single connection and the API key is the platform's
existing one, not a new credential. If the rollout is abandoned, removing the
connection is the first rollback step below.

### Verified isolation (final state)

| Check | Result |
|---|---|
| `/mnt/archie_brain` readable in the service namespace | denied |
| `/home/kytran/.codex/auth.json` readable | denied |
| docker socket usable by the service user | denied (`ds9-codex` is not in the `docker` group; `Permission denied`) |
| scratch cwd `/srv/ds9-codex/work` | empty — nothing executed upstream |
| WS port | `127.0.0.1:1456` only; LAN refused |


---

## Rollback

Disable/remove only the new connection and undo only the new drop-in. Recreate
only the gateway if required, then verify its existing connections.

```sh
# 1. remove the new provider connection (routing was never enabled)
curl -s -X DELETE http://127.0.0.1:20129/api/providers/3eb3148b-3493-45b0-ba58-42963169e35e \
  -H "Authorization: Bearer $OMNIROUTE_API_KEY"

# 2. undo the gateway adapter settings (drop-in only — the base unit is untouched)
sudo rm -f /etc/systemd/system/deep-space-9.service.d/ds9-codex-appserver.conf
sudo systemctl daemon-reload
sudo systemctl restart deep-space-9.service      # interrupts gateway users; schedule it

# 3. stop the sidecar; KEEP /var/lib/ds9-codex until the owner decides on the login
sudo systemctl disable --now ds9-codex-appserver.service

# 4. revoke the token and the pinned runtime
sudo rm -f /etc/ds9-codex/ws.token
sudo rm -rf /usr/local/lib/ds9-codex
```

Never remove the shared DS9 data volume (`/home/kytran/.omniroute`) and never
alter the owner's normal Codex login.

---

## References

- Gateway source (read-only, inspected live): `open-sse/executors/codex/appServerConfig.ts`,
  `appServerAuthProbe.ts`, `appServerClient.ts`,
  `src/app/api/providers/[id]/test/codexAppServerHealth.ts`
- Gateway guide (read-only): `docs/guides/CODEX-APP-SERVER-PROVIDER.md`
- Upstream reference sidecar: `docker-compose.yml` in the DS9 tree, profile `codex-app-server`
- <https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server>
