# DS9 free tier: give it a second transport that is not the browser

**Date:** 2026-10-22 · **Task:** #7424 · **Lane:** opencode

## The headline

**The task's premise was wrong in three ways, and correcting it changes the fix.**

1. The free pool is **42 candidates, not 21** — 40 `cfp/*` + 2 `uncloseai`.
   `cfp`'s registry grew from 20 to 40 models since the task was written.
2. **249 free candidates exist; only 42 are reachable.** The gap is six
   providers, each blocked by one specific, measured gate.
3. **The fix the task proposed — install the Devin CLI — would have put the
   owner's PAID Devin subscription behind the "free tier".** `devin-cli-agentic`
   is `hasFree: false`. It is not a free path; it is a second bill.

## Measured inventory

The live candidate pool, read out of the gateway's own code against the live
store (`prepareVirtualAutoComboInputs` + the real allowlist and readiness gates):

| provider | free candidates | transport | free? | reachable? | blocked by |
|---|---|---|---|---|---|
| `cloudflare-playground` | 40 | **one** Chromium page | yes | **40** | — |
| `uncloseai` | 1 | HTTP | yes | **1** | — (rate-limits) |
| `duckduckgo-web` | 6 | HTTP | yes | **0** | DuckDuckGo grants **no VQD token** from this host |
| `aihorde` | 3 registry / **30 live** | HTTP, anonymous | yes | **0** | not opted into emulated tool calling |
| `auggie` | 28 | local CLI | ? | 0 | not opted into emulated tool calling |
| `zcode` | 14 | local CLI | ? | 0 | not opted into emulated tool calling |
| `codex-app-server` | 52 | local CLI | **no** — owner's ChatGPT account | 0 | not opted into emulated tool calling |
| `devin-cli-agentic` | 110 | local CLI | **no** — owner's Devin subscription | 0 | readiness probe: no devin CLI |

**The throat is real.** `cfp`'s executor keeps exactly one page
(`private page: Page | null`, one `browser.newContext()` + `newPage()`), so all
40 models ride one Chromium session. One browser crash removes 95% of the free
tier at once. Spreading across models protects against a *per-model* limit; it
cannot protect against the transport.

## What died, and why (each measured, not assumed)

**The Devin CLI.** It needs the CLI installed *and* `devin auth status` to
report `authenticated` inside an isolated home (`DEVIN_AGENTIC_HOME`, which
must be an absolute path inside the bridge sandbox). Even installed, it is
`hasFree: false` — its 110 models are priced at the real Claude rates in the
gateway's own pricing table (`claude-opus-5` at $5/$25 per 1M). Routing
free-tier traffic there spends the owner's Devin subscription. It is also
`isLocalCli`, which the transport-gate comment in the gateway calls out as a
transport that "can stall the combo until the per-target timeout (~120s)
fires".

**`duckduckgo-web`.** Already allowlisted, already free, and with
`WEB_COOKIE_USE_BROWSER` unset it would use its plain HTTP path — genuinely
independent of `cfp`'s browser. But `GET https://duck.ai/duckchat/v1/status`
from this host returns `{"status":"0","statusV2":0,"grant":null}` and **no
`x-vqd-4` token**, so the HTTP path cannot authenticate. Its fallback is the
browser — the same Chromium dependency. Not independent.

**`codex-app-server`.** Free-tier, ready, and 52 candidates — blocked only by
the allowlist. But it is the owner's ChatGPT account, and #7414 already found
it returns an opaque 502 when the account hits its usage limit. Adding it
would route free-tier traffic at the owner's subscription and inherit that
outage mode.

**`auggie` / `zcode`.** Free and ready, 42 candidates between them, blocked only
by the allowlist — but both are local-CLI bridges, so they are a different
flavour of local dependency, and neither is installed.

## The fix that survives: `aihorde`

`aihorde` is the only free candidate that is **genuinely independent**: plain
HTTPS, anonymous (`Bearer 0000000000`), no account, no browser, no CLI, no
owner subscription. Verified answering live:

```
POST https://oai.aihorde.net/v1/chat/completions
  -> 200, real completion, usage.kudos: 3
GET  https://oai.aihorde.net/v1/models
  -> 30 models live right now
```

It is blocked by one flag — `toolCalling: "emulated"` — because the auto-router
dispatches with tools and `aihorde` does not take a `tools` array (it already
declares `unsupportedParams: ["tools", "tool_choice", "parallel_tool_calls"]`,
so the gateway strips them and the model never hears about tools).

### The models DO emit tool calls — in a dialect the parser doesn't know

Measured against `google/gemma-4-31b` with the gateway's real prompt contract
(`prepareToolMessages`), the model emitted:

```
<tool>
<get_weather>
{"location": "Toronto"}
</tool>
```

The gateway's parser expects `<tool>{"name":...,"arguments":...}</tool>` and
returns `null` for the above. **But normalising that one shape makes the
existing parser accept it** — verified with the real `parseToolCallsFromText`:

```
as-emitted        -> null
after normalising -> [{"id":"t_0","type":"function",
                        "function":{"name":"get_weather","arguments":"{\"location\":\"Toronto\"}"}}]
```

There is precedent for exactly this: `parseToolCallsFromText` already
normalises DeepSeek's native dialect (`normalizeDsmlToolCalls`) before parsing.

## The change

**Status: edit 1 of 3 is committed to the DS9 tree** (`ade51b321`, branch
`release/v3.8.53`) — the dialect normalizer, with its own test file and the
existing 69-check translator suite still green. **Edits 2 and 3 must ship
together**: the catalog flag admits `aihorde` to the pool, and without the
executor the auto-router would dispatch with tools, `aihorde` would strip them,
and the leg would silently answer in prose instead of calling a tool.

### 1. The dialect normalizer — DONE (`ade51b321`)

`open-sse/translator/webTools.ts` — `normalizeNamedBlockToolCalls()` rewrites
the named-block dialect into the canonical shape, and `parseToolCallsFromText`
applies it after the existing DSML normalisation. **Additive by construction:**
it only rewrites a `<tool>` block whose inner content is not already a JSON
object carrying a `"name"` — text that currently parses to nothing. A canonical
block is left byte-for-byte alone.

Verified: the named form now parses; the canonical form is untouched; the DSML
dialect still parses; prose still parses to nothing. New test file
`tests/unit/aihorde-named-block-tool-dialect.test.ts` (5 checks).

### 2. The dedicated `aihorde` executor — NOT YET WRITTEN

**The shape**, following `open-sse/executors/maxai.ts` (the closest existing
pattern: OpenAI-compatible HTTP + prompt-emulated tool calling):

- `class AihordeExecutor extends BaseExecutor`, `super("aihorde", PROVIDERS["aihorde"])`.
- `override async execute(input)` — `BaseExecutor` has **no** response hook
  (checked: `transformRequest` exists at `base.ts:540`, there is no
  `transformResponse`), so the response side is parsed in the executor.
- Request: `POST https://oai.aihorde.net/v1/chat/completions`,
  `Authorization: Bearer 0000000000` (the `anonymousApiKey` the registry
  already declares), body `{ ...input.body, messages: effectiveMessages }`
  with `tools` / `tool_choice` / `parallel_tool_calls` **deleted** — AI Horde
  500s on a `tools` array.
- Tool contract: `prepareToolMessages(body, body.messages)` gives
  `{ hasTools, requestedTools, effectiveMessages }`; the contract travels in the
  prompt only, which is the same shim the web-cookie providers use.
- Response: `buildToolAwareResult(text, requestedTools, "aihorde")` →
  `{ content, toolCalls, finishReason }`, returned in the OpenAI
  `chat.completion` shape (`choices[0].message.tool_calls`).
- Register it in `open-sse/executors/index.ts` (`"aihorde": () => import("./aihorde.ts")...`)
  and point the registry entry at it with `executor: "aihorde"`.

### 3. The catalog flag — MUST SHIP WITH (2)

`src/shared/constants/providers/noauth.ts` — `toolCalling: "emulated"` on the
`aihorde` entry. The allowlist is *derived* from that flag
(`getAutoRoutableEmulatedNoAuthProviders()`), so there is no id list to
maintain.

### Then

A model sync so `aihorde` contributes its ~30 live models instead of its 3
static fallbacks; a build (`NEXT_DIST_DIR=.build/<name> npm run build`,
~25-35 min); a swap with the old build kept for rollback; and verification:
the readiness/allowlist gates admit `aihorde`, a free-tier call routes to it
and does **not** touch the browser, and the browser can be stopped to prove the
free tier still answers.

### One thing to decide before the build

The DS9 tree currently has **8 uncommitted files** from the branding work
(`README.md`, `package.json`, `src/app/layout.tsx`, `src/app/loading.tsx`,
`src/app/login/page.tsx`, `src/i18n/messages/en.json`,
`src/lib/db/rootLayoutSettings.ts`, `tsconfig.json`). A build bakes whatever
is in the tree, so the next build will carry those too. That is probably
intended, but it is worth confirming before a gateway swap.

## The residual, stated plainly

After this, the free tier has one browser-backed provider (`cfp`) and one
anonymous-HTTP provider (`aihorde`) — and **both run on the same host**. A host
failure still takes out both. True host independence is a different, larger
piece of work: a second gateway on a second node.

And `aihorde` is what the gateway's own description calls "a lottery ticket
rather than a known quantity" — quality and speed vary per endpoint. The
spread machinery from #7397 is what keeps a noisy pool from concentrating
traffic on one bad model, so the two changes compose.
