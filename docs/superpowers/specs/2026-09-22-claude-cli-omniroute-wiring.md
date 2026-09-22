# Claude-CLI → OmniRoute (DS9) wiring handoff

Status: **handoff awaiting apply by Claude/Kytran on the host.** Prepared by the
opencode lane 2026-09-22. This lane has no write access to `/home/kytran/.claude/`
(no sudo, deliberate isolation) — so the change is documented here, ready to paste.

## What is true right now (verified by probing the live gateway)

- Claude-CLI on this platform runs as host user `kytran`, launched by
  `scripts/start_ttyd.sh` (tmux session `claude-code`), binary
  `/home/kytran/.local/bin/claude`. It connects to Anthropic natively. No
  OmniRoute fallback is configured anywhere in `.claude/settings*.json`.
- The OmniRoute gateway **does** speak the Anthropic Messages API (Claude's
  wire format), confirmed live:
  - `GET http://omniroute:20128/v1/models` → 200
  - `POST http://omniroute:20128/v1/messages` → routes into the provider pool
    when given `Authorization: Bearer $OMNIROUTE_API_KEY` (401/`AUTH_002`
    without it; `bad_gateway` only when every upstream in the pool is refused).
- Model alias `auto/coding:free` resolves through the gateway (the 403/400s in
  the probe are today's saturated upstream pool — the exact throttling the DS9
  quota scan tracks now). Local mesh name `omniroute` resolves inside the
  platform net; host name is `192.168.1.200` → gateway published on the LAN.

## The goal

Point Claude-CLI at OmniRoute so that when Anthropic is maxed/rate-limited,
Claude Code can drop onto the free cloud pool instead of failing. Two modes:

- **A — always via OmniRoute**: Claude sends everything through the gateway's
  `auto/coding:free` pool (best-free routing, quota-aware, tracks in DS9).
- **B — fallback on demand**: keep native Anthropic as primary; flip to
  OmniRoute in the settings file only when Anthropic reports maxed/tier-full.

## Change to apply (Mode B is the recommended default — safest)

Edit **`/home/kytran/.claude/settings.json`** (or `settings.local.json`) `env`
block:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://192.168.1.200:20128",
    "ANTHROPIC_AUTH_TOKEN": "<OMNIROUTE_API_KEY>",
    "ANTHROPIC_MODEL": "auto/coding:free",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "auto/coding:free",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "auto/coding:free",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "auto/coding:free"
  }
}
```

Notes:
- Get the token from the platform container's `OMNIROUTE_API_KEY` env
  (`docker exec archie_platform printenv OMNIROUTE_API_KEY`). It is the **same**
  shared `archie-platform` key the gateway logs for every call, so usage shows up
  in `call_logs` → task_execution_log → DS9 quota snapshots automatically.
- Keep the base URL on the **LAN**, not the public hostname — the public route
  (`platform.kytranempowerment.com`) goes through a CDN with a 60s cap and
  bypasses the queue. `http://192.168.1.200:20128` (or mesh `omniroute:20128`
  from any container) is the durable choice.
- For **Mode A**, apply the env changes and leave them; for **Mode B**, apply
  them only at the moment of fallback (or keep two snippets to swap).
- Claude Code does not need OpenAI-format config here — OmniRoute implements the
  Anthropic endpoint natively, so this is a base-URL redirect, not a proxy shim.

## Verify (after applying, in the running Claude session)

1. Start/reload Claude Code; run `echo $ANTHROPIC_BASE_URL` in the session.
2. Send any prompt. It should stream, and in OmniRoute's admin:
   `call_logs` shows the call with `api_key_name='archie-platform'` and your
   model alias.
3. Confirm it lands in DS9: after DB-side up to the next 15-min scan,
   `SELECT provider,status,rate FROM omniroute_quota_snapshots ORDER BY created_at DESC LIMIT 10;`
   in `archie_database` shows the upstream provider and its throttle band.
4. If you see `AUTH_002` → wrong key. `bad_gateway` → pool is currently
   saturated (that is today's real state; the scan/telegram alert will say so).

## Not solved here (living work)

- **codex** lane has `OMNIROUTE_*` env set but `auth_mode: chatgpt_signin` —
  not wired.
- **archie-tui** resolves through `archie_engine` → BridgeDispatcher → local
  Ollama only; no OmniRoute path yet.
- **opencode** has the OmniRoute provider configured but this session ran on the
  built-in `opencode/big-pickle` provider.

All four lanes lack a genuine DS9 fallback. The DS9 Phase 2 (quota awareness)
deliverable — `omniroute_quota_service.py`, snapshot table, 15-min scan job,
DHQ Contractors quota card, Telegram exhaustion alert — is being built in
parallel and is what makes each lane's fallback *visible* when it engages.