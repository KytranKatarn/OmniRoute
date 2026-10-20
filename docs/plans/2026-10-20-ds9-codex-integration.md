# DS9 gateway integration with Codex CLI

Status: upstream implemented by OpenCode; opt-in host profile installed and tested.
Host shell acceptance remains blocked by task #7381. Sandbox policy is preserved.

## Gate 7 implementation — 2026-10-20

Codex created a dedicated inference credential through `POST /api/keys`:

- Dedicated credential identifier is retained in private connection metadata and task #7380.
- Model mode: `restricted`; `allowedModels: ["cxa/gpt-6.1-sol"]`.
- `allowedConnections: ["3eb3148b-3493-45b0-ba58-42963169e35e"]`.
- Scope: `self:usage`; no `manage` or `admin` scope.
- Verified restrictions through management GET and a read-only SQLite row check.
- A request for `cxa/gpt-6-luna` was rejected as not allowed before inference.

Installed user-local artifacts:

| File | Purpose |
|---|---|
| `~/.codex/ds9.config.toml` | opt-in provider profile, no credential value |
| `~/.local/share/codex-ds9/api-key` | private credential file, mode 0600 in a 0700 directory |
| `~/.local/share/codex-ds9/connection.json` | non-secret key/connection identifiers |
| `~/.local/bin/codex-ds9` | loads the private key into `DS9_CODEX_API_KEY` then launches Codex with `--profile ds9 -a on-request` |

Launch:

```sh
codex-ds9
# Resume an existing DS9 session, retaining the explicit approval policy:
codex-ds9 resume <DS9-session-id>
```

If the launcher is not on PATH, use `/home/kytran/.local/bin/codex-ds9`.
Plain `codex --profile ds9` requires `DS9_CODEX_API_KEY` to already be supplied;
the launcher provides it without changing shell startup files or exposing it in
command arguments. Normal `codex` continues using the existing direct setup.

Acceptance evidence with the dedicated credential:

- Fresh noninteractive session and a separate resume returned their expected
  markers; resume recalled `GATE7-MEMORY-6248`. Session identifier is retained in the task note.
- Fresh interactive TUI returned `GATE7-TUI-6248`. Its persisted turn context
  confirms `model=cxa/gpt-6.1-sol`, `approval_policy=on-request`,
  `sandbox_policy=workspace-write`, network access false. Session identifier is retained in the task note. The test TUI was shut down normally.
- `codex exec` persists `approval_policy=never` for its noninteractive run;
  do not confuse that record with the independently checked interactive policy.
- The noninteractive answer reported a clock result, but its outer rollout did
  not contain a function-call/result event. This run is recorded as text and
  resume acceptance, not additional proof of outer-client tool execution.
  OpenCode's earlier tool-transport evidence remains attributed to that handoff.
- Existing `~/.codex/config.toml` and `~/.codex/auth.json` hashes were unchanged
  by profile installation. No upstream restart, rebuild or routing toggle occurred.

Known limits remain: #7381 blocks host sandboxed shell execution; #7379 reports
incorrect usage for the adapter. No production coding readiness, cost attribution,
MCP invocation, image or native web-search acceptance is claimed by these tests.
The old shared platform credential was used only to authorize management creation,
never installed as the Codex client credential.

Rollback the client by exiting its session and launching normal Codex. Revoke only
the dedicated credential identified in private metadata through DS9 management, then remove its profile,
launcher and private credential files if retiring the integration. Leave the
working upstream, platform key and existing ChatGPT login intact.

### Namespace diagnosis update

The existing read-only `scripts/provision_bwrap_userns_apparmor.sh --check`
passes on this host: **system `/usr/bin/bwrap` works** with the current AppArmor
profile. The profile grants `userns` only to that executable path.
The same sandbox probe using Codex 0.163.0's bundled executable at
`~/.codex/packages/standalone/releases/0.163.0-x86_64-unknown-linux-musl/codex-resources/bwrap`
fails with `loopback: Failed RTM_NEWADDR: Operation not permitted`.

This narrows task #7381: the earlier statement that bubblewrap is broken for
every user/path is too broad. The existing exception does not cover the bundled
path; the operator should correlate its denial and evaluate a narrowly attached
profile for the actual executable, including any missing network-namespace
permissions. Do not grant a broad home-directory wildcard, replace the bundled
binary, disable host userns restrictions or bypass Codex's sandbox. Verify the
exact failing command and a real client shell call after any operator change.
No AppArmor policy was changed during this diagnosis.

## Current handoff — supersedes the original container baseline

Read [OpenCode's implementation record](2026-10-20-ds9-codex-appserver-implementation.md)
before following the historical setup sections below. The gateway in use is
host-native `deep-space-9.service`, port **20129**. The `omniroute` container on
20128 is an old orphan and must not be used for this integration. The separate
upstream is `ds9-codex-appserver.service`; both services were independently checked
as active by Codex after receiving the operator handoff.

- Host client base URL: `http://127.0.0.1:20129/v1`.
- Container client base URL reported by OpenCode:
  `http://host.docker.internal:20129/v1`; recheck host alias mapping and reachability
  from the particular container before configuring it.
- Exact accepted model reported: `cxa/gpt-6.1-sol`.
- Client protocol remains `wire_api = "responses"`.
- Working inference key creation path: `POST /api/keys`, not
  `POST /api/v1/registered-keys`. OpenCode reports registered keys fail inference
  authentication even though their creation succeeds.
- Restriction field names are **`allowedModels` / `allowedConnections`**.
  OpenCode reports snake_case fields were silently discarded. Verify the stored
  restriction metadata and test a denied model, without printing the key.
- OpenCode reports real CLI text and `clock.sleep` call/result replay succeeded
  using an isolated `CODEX_HOME`. Shell tool execution failed on user-namespace
  creation. Codex independently reproduced an unsandboxed host
  `unshare --user --map-root-user /usr/bin/id -u` failure at `/proc/self/uid_map`.
  This proves a limitation for the tested host user, not that every user or
  possible sandbox configuration has been tested.
- Test against the real client's advertised tools: its observed tool family
  includes `functions.exec`, `functions.wait`, `clock.sleep` and collaboration
  tools. Do not require an invented `read_file` tool. Read/edit behavior is still
  the acceptance goal, using whichever tools the client actually exposes.
- Non-shell round trips are transport evidence, not evidence that sandboxed
  file edits and command execution work. Do not replace `workspace-write` with
  a bypass flag to obtain a green host acceptance result.

Next coding-readiness gate: have the infrastructure operator diagnose the host namespace denial,
or validate the existing externally isolated container lane as a separate target.
Any host security-policy change needs its own scoped operator review. Resume the
coding rollout only after its actual shell tool can execute a harmless
command under the intended sandbox. The opt-in profile itself is installed as
recorded above. Keep normal direct-login configuration intact.

The original plan's container-sidecar implementation was replaced by OpenCode's
isolated native systemd implementation. The original operator package remains
historical design material; it is not the deployment recipe for the current state.

The [operator setup package](2026-10-20-ds9-codex-operator-setup.md) records the
original design. Use the implementation record above for actual services, login,
verification and rollback. Infrastructure changes remain outside Codex lane scope.

## Initial readiness inspection — 2026-10-20

- Running DS9 container is healthy. Its published model endpoint is
  `http://192.168.1.200:20128/v1/models`; a host request without credentials
  returns HTTP 401, proving reachability and an authentication requirement.
  This is not an authenticated model-list or inference test.
- No separate Codex app-server container appears in the running or stopped
  container inventory. `archie_codex_terminal` is present; it is not evidence
  of a configured DS9 app-server connection.
- DS9's `OMNIROUTE_CODEX_APPSERVER_WS`, its WS token-file setting and inline
  WS token are unset in the running gateway environment.
- Read-only SQLite inspection found zero provider connections whose provider
  identifier contains `codex`, including app-server connections. No account
  identities or credential values were printed.
- Conclusion: DS9 is reachable, but its Codex app-server upstream is not
  configured. Authentication/readiness RPC cannot be tested until that upstream
  exists. The host's separate Codex login was not changed or tested here.
- Next deliverable: prepare the scoped operator setup for an isolated app-server,
  its private authenticated transport, durable configuration and owner sign-in.
  Do not add the client DS9 profile or claim upstream readiness yet.

## Outcome

Provide an opt-in `codex --profile ds9` launch that sends model requests through
the existing DS9/OmniRoute gateway. Keep the normal Codex launch available for
direct OpenAI use. Start with one explicitly selected GPT model and account;
expand to other providers only after their compatibility is measured.

## Verified baseline

- Host Codex CLI is 0.163.0. Its help confirms that `--profile ds9` overlays
  `$CODEX_HOME/ds9.config.toml` on the base user configuration.
- The inspected user configuration has `approval_policy = "on-request"`, no
  explicit model/provider override, no custom provider blocks and no profile files.
  This is file inspection, not proof of effective settings in every saved session.
- Gateway container `omniroute` uses `diegosouzapw/omniroute:3.8.50` and persists
  `/app/data` in its existing Docker volume.
- Installed gateway source includes `OpenAI Codex` OAuth/device-login support,
  an `OpenAI Codex (App-Server)` provider, and a Codex CLI configuration guide.
- Provider login state, app-server availability, current available models and
  end-to-end inference have not been verified. Installed source is not acceptance
  evidence. Earlier platform health records include gateway failures.

## Architecture and defaults

```text
Codex CLI, ds9 profile
  -> existing internal DS9 endpoint, Responses API, dedicated gateway credential
  -> pinned OpenAI Codex app-server connection
  -> OpenAI using the account authorized by the owner
```

Use the installed app-server integration as the first candidate; verify it against
current OpenAI authentication guidance before activating it. The gateway also has
a direct OAuth-token provider, but its own guide flags proxy/session-replay usage
limitations. Do not silently substitute token replay when app-server is unavailable.

The upstream app-server must have an isolated configuration and credential store.
Its model provider connects directly to OpenAI, never back to DS9. Do not inherit
the client `ds9` profile, gateway environment overrides or client configuration.
Never mount the owner's entire Codex home into a new service as a shortcut.

The DS9 profile uses a gateway credential, not the ChatGPT OAuth token. An owner
browser sign-in authorizes the upstream account. Plan entitlement and usage limits
still apply; connecting DS9 does not increase them or unlock every GPT model.

Keep platform agent dispatch under Department HQ. This profile concerns the
interactive coding client; it does not replace dispatch or enable a fleet-wide
provider. Existing headless scripts remain outside the initial rollout.

## Phase 1: inspect and prepare

1. Verify the gateway's current private listening endpoint from the host; do not
   assume localhost works or use a public/CDN hostname.
2. Inspect only non-secret connection metadata: app-server presence, health,
   provider availability and authentication status. Determine whether the existing
   connection can be used or whether an operator service change is required.
3. Verify the current OpenAI-supported authentication route and account entitlement.
   An ordinary website identity login is not by itself inference authorization.
4. Identify DS9's exact model ID for the selected connection, supported reasoning
   levels and context limit. Confirm model routing can be pinned to that connection.
5. Prepare a redacted change list and backups of only the files to be modified.
   Preserve the shared repository's unrelated work and the existing direct login.

Gate: a supported upstream path, reachable private endpoint and explicit model
binding are established. If new service/compose changes are needed, hand off that
scoped operator change; infrastructure remains outside the coding lane allowlist.

## Phase 2: connect the account

1. Configure or select the isolated app-server connection.
2. Have the owner complete the provided OpenAI browser/device login. Do not ask
   for a password or copy OAuth credentials into chat, repository files or logs.
3. Verify the account/workspace selected matches the intended subscription and
   that the running app-server reports authenticated readiness.
4. Create a dedicated gateway credential for the host Codex client, using any
   available provider/model restrictions. If DS9 cannot enforce such restrictions,
   record that limitation and use explicit model routing without automatic fallback.
5. Load the credential through the approved host secret mechanism; reference it
   from the profile using an environment-variable name. Do not add a plaintext key
   to shell history, TOML, a PR or a shared environment file.

Gate: account authorization and an authenticated upstream health check succeed.
Credential activation and service deployment are separate from approving this plan.

## Phase 3: add the opt-in client profile

Target: `~/.codex/ds9.config.toml`, using the installed CLI's profile-file syntax.
Illustrative content only; placeholders must be resolved in Phase 1:

```toml
model = "<verified DS9 model ID>"
model_provider = "ds9"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[model_providers.ds9]
name = "Deep Space 9"
base_url = "<verified private gateway base URL>/v1"
env_key = "DS9_CODEX_API_KEY"
requires_openai_auth = false
wire_api = "responses"
```

Do not guess context-window overrides, reasoning capabilities or a model catalog.
Add them only if the chosen model and installed client require verified values.
Preserve existing MCP, plugins, scope rules, approval handling and sandbox settings.
Validate effective profile layering, including project config and saved-session
overrides; file contents alone do not prove those settings are active.

First launch: `codex --profile ds9 -a on-request` in a disposable workspace.
Use a new session initially. Test resuming a DS9 session separately before
documenting resume commands; do not assume an old direct-provider session switches.

## Phase 4: acceptance tests

Use synthetic prompts and disposable files. Limit the first test to one connection
and model; no automatic paid fallback or routing across accounts.

| Test | Required evidence |
|---|---|
| Configuration | Installed CLI accepts the profile; base direct launch still works |
| Streaming | Real response streams to completion through `/v1/responses` |
| Route identity | Correlated DS9 request shows actual upstream account/connection and model; no loop |
| Tools | Model reads a fixture, edits a disposable file and runs a harmless check |
| Permissions | Safe controlled escalation still follows the approval policy; no bypass flags introduced |
| MCP | Existing read-only KB tool works through a real DS9-backed session |
| Conversation | A follow-up tool result is accepted; multi-turn state remains consistent |
| Resume | A saved DS9 session resumes with the intended provider and permissions |
| Model selection | Configured model is selectable; any picker/catalog limitation is documented |
| Failure handling | Invalid test gateway key is rejected; upstream unavailable/limit errors are visible with bounded retries |
| Usage | DS9 records the call and usage; platform telemetry capture or its specific gap is measured |
| Isolation | Upstream app-server uses its own configuration and does not recurse into the gateway |
| Rollback | Exit DS9 session and launch direct Codex successfully |

Test gateway translation before claiming support for images, native web search,
parallel tool calls, reasoning controls or automatic compaction. Those features
remain unverified until exercised against the selected upstream. Do not mutate
production credentials or exhaust a real subscription to test an error response.
Use an isolated mock/test connection for destructive fault injection.

## Phase 5: rollout and rollback

- Deliver a redacted setup guide with the tested launch/resume commands, exact
  model IDs, verified features, usage limits and troubleshooting steps.
- Keep `ds9` opt-in. Switching the default or integrating headless workers is a
  later decision after acceptance results are reviewed.
- Rollback: exit the DS9 session and launch normal Codex. If retiring the setup,
  revoke only its dedicated gateway credential and remove only its profile/secret
  reference. Retain other DS9 connections and the owner's existing direct login.
- Remove or stop a newly added app-server service only through its operator change
  and rollback procedure. Do not tear down shared gateway services.

## Delivery boundaries

This plan does not authorize production service changes, secret edits, API spend,
or replacement of existing login credentials. The owner must personally complete
interactive account consent. Coding, documentation and reviewable artifacts can
be prepared ahead of that step; activation follows the project's operator rules.

Documentation work can ship from an isolated `codex/*` worktree. The live shared
checkout contains other-lane work and must not be swept into a commit.

## References

- OpenAI custom providers and profile configuration:
  https://learn.chatgpt.com/docs/config-file/config-advanced
- OpenAI ChatGPT-plan authentication with Codex app-server:
  https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- Installed gateway guides (read-only inspected in `omniroute`):
  `/app/docs/guides/CODEX-APP-SERVER-PROVIDER.md` and
  `/app/docs/guides/CODEX-CLI-CONFIGURATION.md`.
- Existing platform routing handoff:
  `docs/superpowers/specs/2026-09-22-claude-cli-omniroute-wiring.md`.
  Historical wiring evidence must be reverified, not treated as current health.
