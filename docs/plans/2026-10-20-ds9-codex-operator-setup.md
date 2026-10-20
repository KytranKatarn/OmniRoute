# DS9 Codex app-server: operator setup package

Status: original design, superseded by the
[native systemd implementation record](2026-10-20-ds9-codex-appserver-implementation.md).
Do not deploy the Docker design below over the existing native services.
The current client acceptance state is recorded in the parent integration plan.
Parent: [integration plan](2026-10-20-ds9-codex-integration.md).

## Verified inputs and implementation choice

The running `omniroute` container belongs to the Compose project rooted at
`/mnt/archie_brain/docker-compose.yml`. Its image is
`diegosouzapw/omniroute:3.8.50`; its existing `/app/data` volume must be retained.
The gateway is attached to `archie_network` and both coder-terminal networks.
No Codex connection, app-server service or app-server endpoint is configured.
`command -v codex` in that image returns no executable. Do not use its guide's
assumption that the currently deployed image already contains Codex.

Host Codex 0.163.0 confirms these flags in local help:

```text
codex app-server --listen ws://IP:PORT
                 --ws-auth capability-token --ws-token-file ABSOLUTE_PATH
codex login --device-auth
```

Build a separate pinned runtime; do not install tools inside the running gateway.
Use a new private Docker network shared only by gateway and sidecar. Do not
publish the app-server port. Keep direct OpenAI outbound access for authentication
and inference; an `internal: true` network alone would prevent that access.
Keep the gateway's existing networks and persistent volume intact.

## Scope and operator responsibilities

Codex lane policy (`AGENTS.md`, infrastructure/Compose/secret restrictions) prevents
this lane from applying the following service and secret changes. This document
is the concrete handoff; an authorized infrastructure operator must implement it
through the infrastructure review/deployment workflow. Do not run broad Compose
commands from this document against the shared live stack.

The required changes are:

1. A build definition for `ds9-codex-appserver:0.163.0` using the official
   `@openai/codex@0.163.0` package in an appropriate Linux runtime. Pin the base
   image digest at implementation time and verify `codex --version` in the built
   image. Do not bundle the owner's configuration or credentials into the image.
2. One new `ds9-codex-appserver` service, a dedicated bridge network and an isolated
   persistent Codex home. Use a non-root runtime user and an empty writable scratch
   directory; no repository, Docker socket, SSH agent or owner-home mounts.
3. A generated private WebSocket capability token, readable only by the sidecar
   runtime user and gateway runtime user through narrowly scoped secret mounts.
   Provision it through the existing operator secret mechanism; never store the
   value in Git, command arguments, chat, image layers or logs.
4. A gateway environment/secret-mount change enabling its existing app-server
   adapter. Preserve all existing settings; recreate only the gateway when that
   operator change is applied. This can interrupt gateway users, so schedule it.
5. One DS9 provider connection created through its normal dashboard/API, with
   provider ID `codex-app-server`, no direct OAuth/API credential, no automatic
   fallback and no broader pool enrollment. Leave routing disabled until ready.

## Runtime contract to render into the operator's service definition

| Property | Required value/behavior |
|---|---|
| Service/DNS | `ds9-codex-appserver` |
| Image | locally built and verified `ds9-codex-appserver:0.163.0`, record image digest |
| User | non-root, matching permissions on the isolated home and token mount |
| `CODEX_HOME` | `/var/lib/ds9-codex` (new dedicated persistent volume) |
| Working directory | `/work` (empty scratch mount; not a host repository) |
| Listener | `ws://0.0.0.0:1456`, private Docker network only |
| Authentication | `--ws-auth capability-token --ws-token-file /run/secrets/ds9_codex_ws_token` |
| Token mount | same secret material available read-only to gateway and sidecar |
| Root filesystem | read-only where supported; writable isolated home, scratch and required temp paths |
| Privileges | no privileged mode, Docker socket, host networking or additional capabilities |
| Resource limits | start at 1 CPU and 768 MiB; measure before increasing |
| Restart | bounded operator-managed service restart policy; no login loop |

App-server command, after verifying the pinned image supports every flag:

```text
codex app-server
  --listen ws://0.0.0.0:1456
  --ws-auth capability-token
  --ws-token-file /run/secrets/ds9_codex_ws_token
```

The upstream Codex home is independent of `~/.codex` on the host. Configure direct
OpenAI routing there; do not inherit a `ds9` profile, gateway base URL, credential
helper, `OPENAI_BASE_URL`, or owner MCP/plugin configuration. The sidecar is the
upstream, not another client of DS9. Audit the effective configuration for loops.

Gateway adapter settings, supplied in the reviewed operator deployment:

```text
OMNIROUTE_CODEX_APPSERVER_WS=ws://ds9-codex-appserver:1456
OMNIROUTE_CODEX_APPSERVER_WS_TOKEN_FILE=/run/secrets/ds9_codex_ws_token
OMNIROUTE_CODEX_APPSERVER_CWD=/work
OMNIROUTE_CODEX_APPSERVER_SANDBOX=read-only
```

Start with the upstream sandbox read-only: client tool execution belongs to the
outer Codex CLI. The installed gateway's app-server adapter defaults to a
noninteractive `never` approval policy; that is separate from the host client's
`on-request` policy. If this adapter requires upstream command execution or cannot
relay tools under these constraints, stop and document that incompatibility.
Do not solve it by granting host access or disabling the outer client's sandbox.

Avoid per-connection URL/token overrides initially. The installed resolver prefers
connection-specific settings over environment settings, so verify they are absent
or match the approved private endpoint before testing.

## Build and isolated validation gates

Before production activation, the operator must:

- Validate the rendered Compose configuration and changed services; keep secret
  values out of the validation output saved for review.
- Confirm the image reports Codex 0.163.0 and its app-server help includes the
  capability-token flags. Record the built image and base-image digests.
- Check volume ownership and secret readability without displaying contents.
- Prove the app-server port is not published and the process has no host mounts.
- Prove unauthenticated WebSocket access is rejected and authenticated JSON-RPC
  `initialize` succeeds. Use a short timeout; never print the bearer token.
- Call `account/read`. Before login, expect no account. Process readiness alone
  is not authenticated readiness. Do not assume a health endpoint exists without
  checking it in the pinned runtime.

Do not modify or test the owner's normal Codex home to satisfy these checks.

## Owner sign-in

After the isolated service is deployed and its credential storage is verified,
the operator can open its device-login flow:

```sh
docker compose exec ds9-codex-appserver codex login --device-auth
```

Run that from the reviewed service's Compose project, with the service's configured
non-root user and `CODEX_HOME`. The owner completes the URL/code shown in their own
terminal/browser. Do not paste device codes, tokens or auth-file contents into the
assistant conversation. Keep the same service home for future token refreshes.

This CLI sign-in avoids relying on DS9's dashboard `Apply auth` writing into a
different, unshared home. The gateway does not need the ChatGPT credential volume;
only the sidecar does.

After consent, probe `account/read` through the gateway's actual WS route. Record
only authenticated/not-authenticated and whether the owner verified the intended
workspace. If the running server does not reload the new login, restart only the
new app-server service, then recheck. Do not restart unrelated platform services.

## Ready-to-enable checklist

1. Authenticated WS readiness passes with a negative unauthenticated control.
2. `account/read` returns an account for the intended workspace.
3. Available models are read from the running upstream; select one exact model ID.
4. A bounded synthetic text request completes through the chosen DS9 connection.
5. A complete tool-call/result round trip succeeds without tools executing on the
   gateway or sidecar unexpectedly. The installed adapter translates Responses
   inputs, so a text-only success does not establish Codex CLI compatibility.
6. DS9 records the intended connection/model and actual usage; no fallback or loop.
7. Only then prepare/enable the host `ds9` profile from the parent plan.

Do not advertise general model access, native web search, images or production
coding readiness from a successful text probe alone.

## Rollback

Disable/remove only the new DS9 provider connection and undo only the new gateway
adapter settings/secret mount using the recorded pre-change operator deployment.
Recreate only the gateway if required, then verify its existing connections.
Stop only `ds9-codex-appserver`; preserve its isolated login volume until the owner
chooses whether to keep or revoke that authorization. Revoke/remove the dedicated
WS token when retiring the connection. Never remove the shared gateway data volume
or alter the owner's normal Codex login.

## Handoff to the infrastructure operator

Implement the service/image/network/secret changes above in your authorized
infrastructure workflow, preserving the live shared tree's unrelated changes.
Return the scoped diff, image version/digests, authenticated and unauthenticated
readiness results, mount/network inventory, selected model, and rollback evidence.
Pause for the owner's browser consent when login is required. Do not create the
host client profile until the upstream and tool round trip pass.

References:

- https://learn.chatgpt.com/docs/app-server
- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- Installed gateway: `/app/open-sse/executors/codex/appServerConfig.ts`,
  `appServerAuthProbe.ts` and `/app/docs/guides/CODEX-APP-SERVER-PROVIDER.md`.
