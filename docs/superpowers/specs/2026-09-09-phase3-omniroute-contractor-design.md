# Phase 3 — OmniRoute as a self-hosted contractor provider (comparison lane + gated coding lane)

**Task:** Dev HQ #6653 · **Date:** 2026-09-09 · **Build order:** master-command Phase 3 (0 engine floor / 0b scoped keys / 1 comms streaming / 1b studios cloud gate / 2 internal command API — all merged+deployed; **3 = this**).
**Owner decisions (2026-09-09):** scope = A/B comparison lane **and** a gated coding lane; sequencing = **keyless plumbing first (3a)**, curated **paid keys only after V.I.G.I.L. clears (3b)**.

## 1. Goal & non-goals

**Goal.** Register **OmniRoute** (`github.com/diegosouzapw/OmniRoute`, MIT — a self-hosted, OpenAI-compatible gateway fronting many providers/models) as ONE `contractor_providers` row, self-hosted on the hub, and make it usable in two deliberate, ask-first surfaces:
1. the **Agent Academy A/B Cloud Comparison lane** (#4661), and
2. a **gated cloud coding lane** — an explicit, per-call, ask-first path for routine coding work, to relieve Claude/Max quota.

**Non-goals (explicit — these are the reasons to scope narrowly, not to skip the work):**
- **No change to `escalation_mode`.** It stays `local_only`. OmniRoute is never part of the auto-escalation loop, never a roster/default dispatch path.
- **Never for Watch-product / civic / gov / legal / fact-check data.** Enforced by the existing cloud capability allowlist (§5), not by a promise.
- **No cockpit UI for the coding lane** — that is Phase 4. Phase 3 ships the backend path + an internal invocation surface.
- **No paid credentials in 3a.** Paid upstream keys wait for the V.I.G.I.L. audit verdict (3b).
- **No `vision` allowlist change** (still held for owner sign-off from Phase 1b).

## 2. What the codebase already gives us (verified anchors, `/mnt/archie_brain`)

- **Generic chat adapter — no new adapter function needed.** `ai_bridge/external_providers.py:365 _call_openai_compatible(provider, prompt, model, system_prompt, json_mode, timeout)` POSTs to `f"{base_url}/chat/completions"` (`:391`), config pulled from the `contractor_providers` DB row via `_get_provider_config` (`:132`)/`_load_all_providers` (`:47`). Public entry `call_external(provider_key, …)` (`:438`); a cloud-proxy row routes to `call_ollama_cloud`, else `_call_openai_compatible` (`:462`). `openrouter`/`groq`/`cerebras`/`together` are just DB rows through this one path. → **OmniRoute is a DB row + config, no bespoke adapter.**
- **Auto-surface, both consumers, no extra wiring.** A `contractor_providers` row with `capabilities ? 'text_chat' AND is_active=true` appears automatically in the A/B model list (`platform_v2/tools/agent_academy/benchmark_routes.py:748`; `free_tier` bucket = `tier_position >= 8 AND NOT is_cloud_proxy`) and in the Contractors tab via `/api/external-providers` (`fleet_provider_routes.py:1349`; toggle flips `is_active` at `:452`; master toggle `GET/POST /api/escalation-mode` at `:1278/:1291`).
- **Sovereign default holds for free.** Contractor auto-routing fires only when `routing_mode != local_only AND escalation_mode == "auto"` (`department_dispatcher.py:7969`). `escalation_mode` default `local_only` (`_get_escalation_mode` `:5295`). The A/B lane and the coding lane both use **explicit `model_override` selection** (`ab_compare_worker` at `ai_bridge/agent_loop.py:3235` calls `dispatch(..., model_override=sel["model"])`), which is a distinct entry from the auto-escalation loop — it works under `local_only`.
- **Cloud guards.** `_cloud_capability_allowed(capability)` (`:5345`, **fails CLOSED**, empty allowlist = kill switch, reads a `platform_settings` allowlist key); `_cloud_budget_ok(provider_key, capability)` (`:5386`, fails OPEN). Call sites: `_execute_llm` `:4360/:4370`, `_dispatch_to_contractor` `:5581/:5590`, routing loop `:7984/:7986`, `:6685/:6690`.
- **Compose template.** What SHIPPED (PR-1 #3271, `docker-compose.yml` service `omniroute`): image `diegosouzapw/omniroute:3.8.50`, `mem_limit: 4g`, `cpus: 2.0`, `stop_grace_period: 40s`, **no host port**, `networks: [archie_internal]` (real docker name `archie_network`, `docker-compose.yml:1404`), named volume `omniroute_data:/app/data`. `read_only: true` / `tmpfs /tmp` / `cap_drop: ALL` — the `archie_llamacpp` (`docker-compose.yml:814`) target shape for #6664 — are **DEFERRED to Dev HQ #6664** (the app writes under `/app/data` plus paths still to be enumerated with `docker diff omniroute`). `archie_platform` is on `archie_internal`, so the gateway is reachable as `http://omniroute:20128`.

## 3. The one real code change — served-model attribution (shared, benefits every contractor)

OmniRoute's whole value is quota-aware auto-fallback, so the served model differs from the requested one; `model:auto` is its native mode. But `task_execution_log.model_used` is the platform's accounting spine (ADR-034). Today the served model is discarded at **two** layers:

1. `external_providers.py:411-419` — `_call_openai_compatible` returns `"model": model` (the requested/default) and never reads `data.get("model")` from the response.
2. `department_dispatcher.py:5620/5665` — `_dispatch_to_contractor` sets `model_used = model or provider_key` where `model = contractor.get("default_model")`, ignoring `result.get("model")`.

**Fix (both layers):**
- `_call_openai_compatible` reads the response's `data.get("model")` and returns it as the served model (alongside the requested one for reference).
- `_dispatch_to_contractor` prefers `result.get("model")` (served) over `default_model` when recording `model_used`.
- If the gateway returns no model field, record the **requested** model explicitly — **never the literal `"auto"`**.
- The `contractor_providers.default_model` for OmniRoute is set to a concrete model, not `"auto"`, as belt-and-suspenders.

**Latent bug to fix alongside (optional but cheap):** `_log_execution:4795` derives `worker_type` from `meta.get("is_cloud")`, but contractor metadata only sets `is_cloud_proxy`, so contractor rows resolve `worker_type='internal'`. Token Economy already classifies by provider string (`omniroute` → cloud, per `token_provenance.py` ADR-037), so this is cosmetic, but setting `is_cloud` in the contractor meta makes `worker_type` honest. Deferred to Dev HQ #6670 (Ruling 20): Token Economy classifies by provider (`services/token_provenance.LOCAL_PROVIDERS`), so `omniroute` already counts as cloud; the flag is cosmetic.

## 4. Phase 3a — keyless plumbing (shippable now, no paid credentials)

1. **Compose service `omniroute`** — pinned release tag (554 open issues on a 7-month repo → never `main`), mem/cpu limits, **no host port**, on `archie_internal`. `read_only`+`tmpfs`+`cap_drop: ALL` (the `archie_llamacpp` target shape) are **DEFERRED to Dev HQ #6664** — not shipped in PR-1. Gateway config: **compression OFF globally** (dashboard `enabled=false`, `defaultMode=off` — OmniRoute 3.8.50 has no exclusions field; `RTK→Caveman` is lossy on prose, enable per-route for coding only later); **terms-risk catalog set to exclude the 15 "avoid" providers**; **free/keyless upstreams only** (no paid keys). Its own auth key in `OMNIROUTE_API_KEY` (ROOT `.env`, 0600, uncommitted).
2. **One `contractor_providers` row** — `provider_key='omniroute'`, `display_name='OmniRoute (self-hosted gateway)'`, `base_url='http://omniroute:20128/v1'`, `is_cloud_proxy=false`, `auth_method='api_key'`, `auth_env_var='OMNIROUTE_API_KEY'`, `default_model=<a concrete free model, not "auto">`, `capabilities=['text_chat']`, conservative `creed_compliance_tier` (≥2), `is_active=true`. **Correction (plan, 2026-09-09):** `is_cloud_proxy` must be **false** — in this codebase `true` routes the row through `call_ollama_cloud` (`external_providers.py:458`, `department_dispatcher.py:4379`), bypassing the gateway entirely; the flag is Ollama-cloud transport, not "aggregator".
3. **Attribution fix** (§3) — the shared code change; PR-reviewed by F.O.R.G.E.
4. **A/B lane** — verify auto-surface in `/api/ab-test/models` and that a comparison run records the *real* served upstream model (not `auto`).
5. **Gated coding lane (Approach A)** — an internal, ask-first action that dispatches a coding task to OmniRoute via explicit `dispatch(model_override='omniroute:<model>', capability='code')`, riding the same explicit-selection path the A/B worker uses (so `escalation_mode` stays `local_only`). Gated by ask-first Telegram approval + `_cloud_capability_allowed('code')` + `_cloud_budget_ok`. Optional per-call compression opt-in (coding only — code/JSON/URLs are preservation-guarded in OmniRoute's compressor). The cockpit button for this is Phase 4; Phase 3 exposes the path via an internal endpoint/action.

**Ask-first lane — a rule the live proof discovered.** Every new Tier-2 `action_type` MUST have a branch in `AgentLoop._execute_approved_action` (`ai_bridge/agent_loop.py`): the approval-queue drain claims EVERY `approved` row and marks unhandled types FAILED. Worker-drained lanes acknowledge with `{"executed": True, "drained_by": "<worker>"}`; the worker's planner treats `executed` as the human's yes and `failed` as a terminal cancel (`cloud_code_lane.plan_worker_action`, `ab_compare.decide_worker_action`). Shipped as PR-3 #3273; KB mistake_learned #313259; ADR-040. Also note the internal approve route takes a SOURCE-PREFIXED id (`POST /api/internal/approvals/autonomy:<id>/approve`); a bare id 500s today (#6666).

**3a live proof uses only keyless/free upstreams.** If no genuinely keyless upstream is available in OmniRoute's Free tier, 3a proves adapter + attribution against the gateway's `/v1/models` + a keyless echo/free model, and the first *paid* inference waits for 3b. Every prompt sent through it is treated as public.

## 5. Sovereignty enforcement — the allowlist IS the company-data guard (no new mechanism)

`_cloud_capability_allowed` fails closed against a `platform_settings` allowlist. Allowlisted capabilities (`code`, `creative`, `visual_design`, …) can reach OmniRoute; the COMPANY_DATA capabilities (`fact_check`, `bias`, civic/gov/legal analysis, `conversation`) are **not** on it and are refused. So:
- the coding lane is pinned to `capability='code'` (allowlisted, not company data);
- civic/gov/legal/fact-check dispatches structurally cannot reach OmniRoute;
- `escalation_mode` stays `local_only` (no auto-escalation);
- OmniRoute is never wired into any Watch-product dispatch path.

**Verification requirement:** the implementation must **read the live allowlist contents** (`platform_settings` cloud allowlist key) and confirm `code` is present and `fact_check`/civic are absent — never assert this from memory. A guard test pins that `capability='fact_check'` to OmniRoute is refused fail-closed.

## 6. Phase 3b — paid keys, gated on the V.I.G.I.L. audit (separate PR)

Delegate to **V.I.G.I.L.** (`delegate_task(capability='security', …)`): dependency audit on the 547 MB Node project, egress-behaviour analysis (confirm only upstream provider calls leave, nothing else), and confirmation that keys never leave OmniRoute's local AES-256-GCM store. **No paid credential is configured until that verdict is in.** On a clean verdict: add curated **paid** upstream keys (excluding the 15 "avoid" providers), enable those tiers, re-verify attribution + guards. 3b is its own PR referencing the audit.

## 7. Testing

**Unit / structural:**
- Attribution: `_call_openai_compatible` returns the response's served `model`; `_dispatch_to_contractor` records the served model; a response with a different served model than requested logs the served one; a missing model field logs the requested model, **never `"auto"`** (assert the literal string is never written). Mutation-check by reintroducing the discard on a copy.
- Auto-surface: a row with `text_chat`+`is_active` appears in the A/B model list; without them it does not.
- Guard: `capability='fact_check'` (and a civic capability) to OmniRoute is refused by `_cloud_capability_allowed` fail-closed; `capability='code'` is allowed.
- Coding lane: the ask-first gate is required before an OmniRoute coding dispatch executes.

**Live (3a, keyless):** an A/B run pitting a local model vs OmniRoute completes; a coding-lane call runs after approval; then `SELECT model_used, provider, request_metadata FROM task_execution_log WHERE provider = 'omniroute' ORDER BY id DESC LIMIT 3` shows the **real** served upstream model, `provider='omniroute'`, and no `"auto"`. Contractors tab lists OmniRoute and toggles it. Token Economy counts it as cloud.

## 8. Rollout

- **3a:** compose service (`docker compose up -d --no-deps omniroute`) → attribution-fix + DB-seed PR (F.O.R.G.E. review, merge on clean APPROVE) → platform reload (bind-mounted code: `git checkout main && git pull --ff-only` + restart platform+scheduler) → live proof above.
- **3b:** V.I.G.I.L. audit (blocking) → paid-keys PR → re-verify.
- **Env:** `OMNIROUTE_API_KEY` (gateway auth) in ROOT `.env` (0600, uncommitted); `up -d --no-deps` for env changes, never `restart` (KB #268829).

## 9. Standing constraints (carried)

REMOTE 192.168.1.200 · branch+PR never main · never commit secrets · 2 failures→STOP+ask · all inference via the DHQ dispatcher (ADR-013) — the Ollama-compatible `/api/chat` alias OmniRoute exposes must **not** be used to bypass it · `escalation_mode` stays `local_only` · cloud NEVER company/civic data · merge on clean F.O.R.G.E. APPROVE · never pre-format with host Black · absolute `git add` · security review BEFORE any credential goes near OmniRoute.

## Execution record (2026-09-09)

- PR-1 #3271 → `a828a8a7d` (compose service + seed script; docs reverted out of it after a false hardening claim).
- PR-2 #3272 → `3974653e0` (served-model attribution at 3 sites; `cloud:code` scope; run/poll endpoints; `cloud_code_worker`). F.O.R.G.E. original APPROVE, coverage-demoted (2/10 files read) → discharged by an independent full read of the 7 dropped files (CLEAR, 0 Critical/Important).
- PR-3 #3273 → `9705f4e9c` (executor acknowledgement for `cloud_code_dispatch` + `cloud_comparison`; planners accept `executed`/`failed`) — found by the live proof, clean APPROVE.
- Live proof (21:58 EDT): job 1198308 `pending → running → completed` in 30 s; `model_used=big-pickle`, `served_model_resolved=true`, `routing_decision="strategy=single; provider=oc; latency_ms=14334"`, 454/922 tokens; `task_execution_log` 1542648 `provider=omniroute module_source=cloud_code_lane`. Sovereignty: `code→True`, `fact_check/bias_analysis/conversation→False`, `escalation_mode=local_only`.
- Follow-ups: #6664 hardening · #6665 fleet-first spurious failed row per run · #6666 approve-route 500 · #6667 X-OmniRoute-Decision parser · #6668 per-call compression · #6669 L8101 attribution + SQL tests · #6670 is_cloud flag. Phase 3b gate: V.I.G.I.L. audit #6671 — paid keys only on GO.
