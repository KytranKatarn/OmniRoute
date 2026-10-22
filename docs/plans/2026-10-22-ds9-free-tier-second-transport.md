# DS9 free tier: give it a second transport that is not the browser

**Date:** 2026-10-22 · **Task:** #7424 · **Lane:** opencode

## Outcome

**The throat is broken, and proven in the live gateway's own proxy log.**

```
03:02:48 aihorde success | level=direct | upstream=200 | 44839ms | acct=noauth
03:03:40 aihorde success | level=direct | upstream=200 | 51916ms | acct=noauth
03:04:09 aihorde success | level=direct | upstream=200 | 16186ms | acct=noauth
03:06:49 aihorde success | level=direct | upstream=200 | 103775ms | acct=noauth
03:08:04 aihorde success | level=direct | upstream=200 | 33066ms | acct=noauth
```

Six successful calls through the **second transport** — plain anonymous HTTPS,
no browser, no account, no owner subscription — while `cloudflare-playground`
served 40 more over its Chromium page. Two transports, one free tier. The
latencies (16 s–104 s) are the volunteer queue doing what a volunteer queue
does.

The free auto pool went from **42 candidates to 48**: 40 `cfp` + 2 `uncloseai`
+ **6 `aihorde`**.

**Also proved:** a chat through aihorde against the deployed gateway returns a
real completion (`"content":"ALOVE"`), and the tool-bearing path now reaches
both the upstream and the parser — with **two** dialects handled, because the
models vary (the same model emitted both shapes on consecutive calls).

**The residual, unchanged:** `cfp` and `aihorde` both run on this host, so a
*host* failure still takes out both. True host independence is a second gateway
on a second node.

**Still open:** a model sync, so `aihorde` contributes its ~30 *live* chat
models rather than the 3 static fallbacks (a passthrough model that is not in
the gateway's registry reaches the upstream as "Model None not known!"), and the
tool-emission *rate* per model — AI Horde's own description calls it "a lottery
ticket rather than a known quantity", and the #7397 spread machinery is what
keeps a noisy pool from concentrating traffic on one bad model.

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

**Status: all three edits are committed to the DS9 tree** (`ade51b321` the
dialect normalizer, `a8e21d16f` the executor + the catalog flag, `db829eb1e`
the two defects the first live run found) on branch `release/v3.8.53`. The patch
travels in PR #4040 as `scripts/patches/ds9-7424-aihorde-free-tier.patch`,
verified to apply **cleanly** to a pristine checkout of the pre-change state.

**Measured live against the deployed gateway:** a plain chat through aihorde
returns a real completion (`"content":"ALOVE"`). The tool-bearing path is what
the rebuild now bakes in — see "What the first live run found" below.

### What the first live run found (both now fixed in `db829eb1e`)

1. **The model id never reached the upstream.** The body arrived without a
   model and AI Horde answered `"Model None not known!"`. The executor now
   takes the id from `input.model` when the body has none, and strips **only**
   the provider prefix — model ids legitimately contain `/`
   (`aphrodite/TheDrummer/Cydonia-24B-v4.3`), so path segments must not be
   touched. The same rule the default executor follows.

2. **The gateway refused tool-bearing requests to aihorde.** `unsupportedParams`
   drives *two* things: the outbound sanitizer, and the request-level gate that
   refuses a direct tool-bearing request for a model declaring tools
   unsupported (`chatCore/toolCallingRequiredCheck.ts`). That gate exists
   because silently stripping tools yields a 200 that can never call anything —
   the model narrates a fake action instead — and **it cited AI Horde as the
   live incident**. It was right about the old behaviour: AI Horde had no tool
   support at all. It has one now, via prompt emulation, so declaring `tools`
   unsupported kept refusing exactly the requests the emulation exists to
   serve. The declaration is removed and the upstream strip moved into the
   executor, where it belongs — it is a property of the upstream, not of the
   gateway's API.

   Verified against the real resolver: `getUnsupportedParams()` for aihorde
   returns `["thinking"]`, never `["tools"]`, for every id shape (bare,
   provider-prefixed, alias-prefixed).

### 1. The dialect normalizer — DONE (`ade51b321`)

`open-sse/translator/webTools.ts` — `normalizeNamedBlockToolCalls()` rewrites
the named-block dialect into the canonical shape, and `parseToolCallsFromText`
applies it after the existing DSML normalisation. **Additive by construction:**
it only rewrites a `<tool>` block whose inner content is not already a JSON
object carrying a `"name"` — text that currently parses to nothing. A canonical
block is left byte-for-byte alone.

Verified: the named form now parses; the canonical form is untouched; the DSML
dialect still parses; prose still parses to nothing. New test file
`tests/unit/aihorde-named-block-tool-dialect.test.ts` (5 checks), and the
existing 69-check translator suite still green.

### 2. The dedicated `aihorde` executor — DONE (`a8e21d16f`, `db829eb1e`)

**The shape**, following `open-sse/executors/maxai.ts` (the closest existing
pattern: OpenAI-compatible HTTP + prompt-emulated tool calling):

- `class AihordeExecutor extends BaseExecutor`, `super("aihorde", PROVIDERS["aihorde"])`.
- `override async execute(input)` — `BaseExecutor` has **no** response hook
  (checked: `transformRequest` exists at `base.ts:540`, there is no
  `transformResponse`), so the response side is parsed in the executor.
- Request: `POST https://oai.aihorde.net/v1/chat/completions`,
  `Authorization: Bearer 0000000000` (the `anonymousApiKey` the registry
  already declares), body `{ ...body, model, messages: effectiveMessages }`
  with `tools` / `tool_choice` / `parallel_tool_calls` **deleted** — AI Horde
  500s on a `tools` array, and the strip belongs to the executor.
- Tool contract: `prepareToolMessages(body, body.messages)` gives
  `{ hasTools, requestedTools, effectiveMessages }`; the contract travels in the
  prompt only, which is the same shim the web-cookie providers use.
- Response: `buildToolAwareResult(text, requestedTools, "aihorde")` →
  `{ content, toolCalls, finishReason }`, returned in the OpenAI
  `chat.completion` shape.
- Registered in `open-sse/executors/index.ts`; the registry entry points at it
  with `executor: "aihorde"`.

### 3. The catalog flag — DONE (`a8e21d16f`)

`src/shared/constants/providers/noauth.ts` — `toolCalling: "emulated"` on the
`aihorde` entry. The allowlist is *derived* from that flag, so there is no id
list to maintain.

### Then

A model sync so `aihorde` contributes its ~30 live models instead of its 3
static fallbacks; the build; the swap with the old build kept for rollback;
and verification: the readiness/allowlist gates admit `aihorde`, a free-tier
call routes to it and does **not** touch the browser, and the browser can be
stopped to prove the free tier still answers.

### One thing to decide before the build

The DS9 tree currently has **8 uncommitted files** from the branding work
(`README.md`, `package.json`, `src/app/layout.tsx`, `src/app/loading.tsx`,
`src/app/login/page.tsx`, `src/i18n/messages/en.json`,
`src/lib/db/rootLayoutSettings.ts`, `tsconfig.json`). A build bakes whatever
is in the tree, so the next build will carry those too. That is probably
intended, but it is worth confirming before a gateway swap.

### And a build trap worth recording

`NEXT_DIST_DIR` alone does **not** aim the build. The `postbuild`
`colocate-standalone` step writes its ESM-scope files and worker bundles to
`OMNIROUTE_STANDALONE_DIR`, which defaults to `.build/next/standalone` — so a
build aimed elsewhere still writes 10+ files into the LIVE artifact, and the
new artifact comes out incomplete. The correct invocation is:

```
NEXT_DIST_DIR=.build/<name> OMNIROUTE_STANDALONE_DIR=.build/<name>/standalone npm run build
```

Measured the hard way: the first build wrote 10 files into the live
`.build/next/standalone` and left `.build/next-aihorde` missing them.

### And a second trap: the artifact carries the repo's `.build/`

A DS9 artifact **contains a copy of the repository's whole `.build/`**. The
standalone's `server.js` requires `./.build/<dist-name>` — the Next server
output is addressed by the dist dir's basename — so the standalone must carry a
nested copy of the build output, and the bundler brings every older artifact
along with it. Measured: the live artifact was **18 G**, of which **8.2 G** was
four nested previous builds (107,117 files against a fresh artifact's 81,676).

**The trap inside the trap:** the nested `.build/next-aihorde/` (4.8 G) inside
the live artifact is **not** junk — it *is* the running server's chunk
directory. Deleting the "obviously stale" nested dirs would have deleted the
code the gateway is serving.

> **The rule:** in every `*/standalone/.build/`, keep exactly the directory
> whose name matches the dist dir that artifact was built as, and delete the
> rest. `.build/next/standalone/.build/` keeps `next-aihorde`;
> `.build/next-pre-<name>/standalone/.build/` keeps `next`.

### And a third: two load paths in one artifact

Hot-patching the standalone's TypeScript works for the **executor** (it is
imported dynamically) and does **not** work for the **provider registry** (it
is bundled into the server chunks). That is exactly why the plain chat worked
while the tool gate kept firing: the executor's fix was live, the registry's
was not. A hot-patch is a diagnostic aid, not a deployment — but it is a fast
one, and it isolates which half of the change is broken.

### And a consequence: 100% full disk

Two builds plus the bloat filled the 443 G filesystem to **0 bytes free**. That
killed a build mid-flight *and* broke the shell's stdout capture — commands
ran but reported nothing. The platform's Postgres shares that filesystem, so a
100%-full disk is a platform-wide incident, not just a build problem.

**Check the disk before a DS9 build**, and count the nested copies:
`du -sh .build/*/` plus `du -sh .build/*/standalone/.build/*/`.

## The residual, stated plainly

After this, the free tier has one browser-backed provider (`cfp`) and one
anonymous-HTTP provider (`aihorde`) — and **both run on the same host**. A host
failure still takes out both. True host independence is a different, larger
piece of work: a second gateway on a second node.

And `aihorde` is what the gateway's own description calls "a lottery ticket
rather than a known quantity" — quality and speed vary per endpoint. The
spread machinery from #7397 is what keeps a noisy pool from concentrating
traffic on one bad model, so the two changes compose.
