# Phase 3 — OmniRoute contractor (A/B lane + ask-first coding lane) Implementation Plan

> **Executed 2026-09-09** — see the Execution record at the end; task text below is the as-planned version.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Self-host OmniRoute on the hub as ONE `contractor_providers` row, make it usable in the Agent Academy A/B lane and a new ask-first cloud coding lane, and make `task_execution_log.model_used` record the model that actually served every contractor call — never the literal `auto`.

**Architecture:** OmniRoute is a plain OpenAI-compatible HTTP gateway reached at `http://omniroute:20128/v1` on `archie_internal`; it rides the existing generic adapter (`_call_openai_compatible`) via a DB row, so there is no bespoke adapter. The one real code change is a two-helper served-model attribution fix threaded through the three places `model_used` is set. The coding lane mirrors the A/B lane (#4661): a `bridge_jobs` row + a Tier-2 `autonomy_approval_queue` row linked by `metadata.approval_id`, drained by a 30 s worker that dispatches with an explicit `model_override` — so `escalation_mode` stays `local_only` and nothing auto-escalates. 3a ships keyless; paid keys are 3b, gated on a V.I.G.I.L. audit.

**Tech Stack:** Python 3.11 / Flask (`platform_v2/app.py`), psycopg2 + Postgres (`bridge_jobs`, `contractor_providers`, `autonomy_approval_queue`), APScheduler (`ai_bridge/agent_loop.py`), Docker Compose, pytest (run in-container: `docker exec -i archie_platform python3 -m pytest …`).

**Spec:** `docs/superpowers/specs/2026-09-09-phase3-omniroute-contractor-design.md` (executors read both; this plan corrects the spec's `is_cloud_proxy` value — see Global Constraints).

## Global Constraints

- **`escalation_mode` stays `local_only`.** Verified live: `platform_settings.escalation_mode = local_only`. No task changes it. Contractor auto-routing fires only when `escalation_mode == "auto"` (`department_dispatcher.py:7969`); both lanes use explicit `model_override`, which is a different entry point.
- **`is_cloud_proxy = false` for OmniRoute.** In this codebase `is_cloud_proxy=true` means "route via `call_ollama_cloud`" (`ai_bridge/external_providers.py:458`, `department_dispatcher.py:4379`) and would bypass the gateway entirely. (Spec said `true`; this plan corrects it — Task 4 also amends the spec text.)
- **Cloud never carries company data.** The live allowlist `platform_settings.cloud:capability_allowlist = code,code_review,code_fix,debug,creative,visual_design,ux_scoring,ux_audit,image,image_generation,image_edit,video_generation` contains `code` and NOT `fact_check`/`bias_analysis`/civic capabilities; `_cloud_capability_allowed` fails CLOSED. The coding lane is pinned to `capability="code"`.
- **Never record the literal `auto`.** `model_used` must be the served model; an unresolved auto-router id records the requested id AND `served_model_resolved=false` so the live proof (Task 10) can catch it.
- **Compression OFF globally** on the gateway (dashboard `enabled=false`, `defaultMode=off` — OmniRoute 3.8.50 has no exclusions field). Per-call compression opt-in is deferred (see Deferred).
- **No paid credential in 3a.** Only keyless/free upstream providers may be connected until V.I.G.I.L. clears (Task 12). Every prompt sent is treated as public.
- **Pinned image `diegosouzapw/omniroute:3.8.50`** (release v3.8.50, 2026-08-26; tag verified to exist on Docker Hub; `v3.8.50` does not). Never `:latest`.
- **No host port on the gateway.** Platform reaches it as `http://omniroute:20128`; the dashboard is reached only through an SSH tunnel to the container IP.
- **Secrets never committed.** `OMNIROUTE_*` values live in ROOT `.env` (0600, untracked); `OMNIROUTE_API_KEY` is mirrored into `platform_v2/.env` (the two files must match rule). Env changes need `docker compose up -d --no-deps <svc>`, never `restart`.
- **Branch + PR, never main; F.O.R.G.E. clean APPROVE to merge;** absolute paths in `git add`; never pre-format with host Black (the pre-commit hook's pinned Black reformats — re-stage and commit again when it does). The live platform bind-mounts the working tree: keep the checkout on `main` and NEVER `docker compose up` while on a feature branch.
- **All inference via the DHQ dispatcher (ADR-013).** OmniRoute's Ollama-compatible `/api/chat` alias must never be used.

---

## File structure (locked decomposition)

| File | Responsibility |
|---|---|
| `docker-compose.yml` (Modify) | `omniroute` service + named volume `omniroute_data`. Infra only. |
| `scripts/omniroute/seed_contractor_row.sql` (Create) | Idempotent seed of the ONE `contractor_providers` row. Parameterised on the concrete default model. |
| `ai_bridge/external_providers.py` (Modify) | `is_auto_router()`, `resolve_served_model()`; `_call_openai_compatible` returns the served model + `served_model_resolved` + raw `routing_decision`. |
| `platform_v2/tools/department_hq/services/department_dispatcher.py` (Modify) | module-level `served_or_requested()`; used at the three `model_used` sites (`_dispatch_to_contractor` ×2, request_work builder); provenance keys copied into result metadata. |
| `platform_v2/services/cloud_code_lane.py` (Create) | Pure lane helpers + three thin, monkeypatchable adapters (`code_allowed`, `active_provider`, `request_tier2_approval`). No DB, no Flask. |
| `platform_v2/services/internal_auth.py` (Modify) | New scope `cloud:code`, granted to `archie_comms`. |
| `platform_v2/app.py` (Modify) | `POST /api/internal/cloud-code/run` (202 async) + `GET /api/internal/cloud-code/run/<id>` (poll). Thin handlers. |
| `platform_v2/tools/department_hq/services/approvals_bulk.py` (Modify) | `cloud_code_dispatch` → Ship tab. |
| `ai_bridge/agent_loop.py` (Modify) | `cloud_code_worker` method + 30 s registration. |
| `platform_v2/tests/test_served_model_attribution.py` (Create) | Helper unit tests + structural tests pinning the three call sites. |
| `platform_v2/tests/test_cloud_code_lane.py` (Create) | Pure lane-helper tests + worker registration + approval category. |
| `platform_v2/tests/test_internal_auth_scopes.py` (Modify) | `cloud:code` probe + endpoint behaviour tests (fixtures `client`, `keys`, `_comms` already live at the top of that file — reuse, do not redefine). |

Two PRs: **PR-1 (infra)** = Tasks 1–3 (compose + seed script), deployed first so the gateway exists. **PR-2 (code)** = Tasks 4–9. Then Task 10 = live proof. Task 11 optional. Task 12 = 3b, gated.

---

### Task 1: Compose service + named volume (PR-1 part 1)

**Files:**
- Modify: `docker-compose.yml` (insert after the `archie_llamacpp` service, i.e. before the line `  # Headscale — Self-hosted Tailscale coordination server (Fleet Mesh VPN)`; and the top-level `volumes:` block)

**Interfaces:**
- Produces: a container named `omniroute` on network `archie_internal`, reachable from `archie_platform`/`archie_scheduler` as `http://omniroute:20128`; env contract `OMNIROUTE_JWT_SECRET`, `OMNIROUTE_API_KEY_SECRET`, `OMNIROUTE_STORAGE_ENCRYPTION_KEY`, `OMNIROUTE_INITIAL_PASSWORD` read from ROOT `.env`.

- [ ] **Step 1: Create the branch off main**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main
git checkout -b feat/phase3-omniroute-gateway
```

- [ ] **Step 2: Add the service block**

Insert this block immediately BEFORE the line `  # Headscale — Self-hosted Tailscale coordination server (Fleet Mesh VPN)` in `docker-compose.yml`:

```yaml
  # OmniRoute — self-hosted OpenAI-compatible AI gateway (#6653, master-command Phase 3).
  # A CONTRACTOR provider for the Agent Academy A/B comparison lane and the ask-first
  # cloud CODING lane. Deliberately NOT a roster dispatch path: escalation_mode stays
  # local_only, so nothing auto-escalates here — every call is an explicit selection.
  # NO host port: the platform reaches it as http://omniroute:20128 on archie_internal;
  # the dashboard is reached only via an SSH tunnel to the container IP (see the
  # Phase 3 plan, Task 2). Pinned release — 554 open issues on a 7-month-old repo means
  # never :latest (which follows the newest published SemVer, not git main).
  # Secrets (JWT/API-key/storage encryption/initial password) come from ROOT .env.
  # OMNIROUTE_MEMORY_MB: this deployment uses /v1/chat/completions only (short prompts),
  # not the /v1/responses coding-agent surface that needs 8-12 GB heap — 2 GB suffices.
  omniroute:
    image: diegosouzapw/omniroute:3.8.50
    container_name: omniroute
    restart: unless-stopped
    stop_grace_period: 40s
    mem_limit: 4g
    cpus: 2.0
    volumes:
      - omniroute_data:/app/data
    environment:
      - TZ=America/Toronto
      - NODE_ENV=production
      - PORT=20128
      - OMNIROUTE_SERVER_HOST=0.0.0.0
      - REQUIRE_API_KEY=true
      - AUTH_COOKIE_SECURE=false
      - BASE_URL=http://omniroute:20128
      - OMNIROUTE_MEMORY_MB=2048
      - INPUT_SANITIZER_ENABLED=true
      - INPUT_SANITIZER_MODE=warn
      - PROXY_FAIL_OPEN=false
      - JWT_SECRET=${OMNIROUTE_JWT_SECRET}
      - API_KEY_SECRET=${OMNIROUTE_API_KEY_SECRET}
      - STORAGE_ENCRYPTION_KEY=${OMNIROUTE_STORAGE_ENCRYPTION_KEY}
      - INITIAL_PASSWORD=${OMNIROUTE_INITIAL_PASSWORD}
    networks:
      - archie_internal

```

`AUTH_COOKIE_SECURE=false` because the dashboard is only ever reached over plain HTTP through the tunnel — secure-only cookies would make login impossible. `read_only: true` is deliberately NOT set yet: OmniRoute is a Node/Next.js app whose writable paths are unknown until first boot; Task 2 enumerates them with `docker diff` and files the hardening follow-up.

- [ ] **Step 3: Declare the named volume**

In the top-level `volumes:` block, change

```yaml
volumes:
  whisper_models:
    driver: local
    name: archie_whisper_models
```

to

```yaml
volumes:
  omniroute_data:
    driver: local
    name: archie_omniroute_data
  whisper_models:
    driver: local
    name: archie_whisper_models
```

- [ ] **Step 4: Validate the compose file parses (with placeholder env so `${…}` resolves)**

Run:
```bash
cd /mnt/archie_brain && OMNIROUTE_JWT_SECRET=x OMNIROUTE_API_KEY_SECRET=x OMNIROUTE_STORAGE_ENCRYPTION_KEY=x OMNIROUTE_INITIAL_PASSWORD=x docker compose config --services | grep -c '^omniroute$'
```
Expected: `1`

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/docker-compose.yml
git commit -m "feat(infra): self-hosted OmniRoute gateway service on archie_internal, pinned 3.8.50, no host port (#6653 Phase 3a)"
```

---

### Task 2: Seed script (PR-1 part 2), open PR-1, merge, deploy the gateway, first-run config

**Files:**
- Create: `scripts/omniroute/seed_contractor_row.sql`
- Modify (untracked, never committed): ROOT `/mnt/archie_brain/.env`, `/mnt/archie_brain/platform_v2/.env`

**Interfaces:**
- Produces: a running, key-protected gateway; `OMNIROUTE_API_KEY` in both `.env` files; compression off; only keyless/free upstreams connected; the list of concrete model ids from `GET /v1/models` (input to Task 3).

- [ ] **Step 1: Write the seed script**

Create `scripts/omniroute/seed_contractor_row.sql`:

```sql
-- #6653 Phase 3a: OmniRoute as ONE contractor_providers row. Idempotent (upsert).
-- Run with the concrete default model chosen from GET /v1/models (NEVER an auto/* id):
--   docker exec -i archie_database psql -U archie -d archie \
--     -v default_model='<concrete id>' -f - < scripts/omniroute/seed_contractor_row.sql
--
-- is_cloud_proxy MUST be false: in this codebase true means "route via call_ollama_cloud"
-- (external_providers.call_external / dispatcher._execute_llm), which would bypass the
-- gateway. tier_position 9 => the A/B lane's free_tier bucket (>= 8 AND NOT is_cloud_proxy).
-- models[] feeds external_providers._model_provider_map (model name -> provider_key);
-- OmniRoute ids are provider/model-namespaced, so they cannot collide with other rows'
-- bare ids. auto/coding variants are SELECTABLE (attribution reads back the served model);
-- the DEFAULT stays concrete per the owner rule.
INSERT INTO contractor_providers
  (provider_key, display_name, base_url, default_model, auth_method, auth_env_var,
   is_cloud_proxy, tier_position, models, rate_limits, is_active, capabilities,
   creed_compliance_tier)
VALUES
  ('omniroute', 'OmniRoute (self-hosted gateway)', 'http://omniroute:20128/v1',
   :'default_model', 'api_key', 'OMNIROUTE_API_KEY',
   false, 9,
   jsonb_build_array(
     jsonb_build_object('name', :'default_model'),
     jsonb_build_object('name', 'auto/coding'),
     jsonb_build_object('name', 'auto/coding:free')),
   '{}'::jsonb, true, '["text_chat"]'::jsonb, 2)
ON CONFLICT (provider_key) DO UPDATE SET
  display_name          = EXCLUDED.display_name,
  base_url              = EXCLUDED.base_url,
  default_model         = EXCLUDED.default_model,
  auth_method           = EXCLUDED.auth_method,
  auth_env_var          = EXCLUDED.auth_env_var,
  is_cloud_proxy        = false,
  tier_position         = EXCLUDED.tier_position,
  models                = EXCLUDED.models,
  is_active             = true,
  capabilities          = EXCLUDED.capabilities,
  creed_compliance_tier = EXCLUDED.creed_compliance_tier,
  updated_at            = NOW();
```

- [ ] **Step 2: Commit, push, open PR-1, register + review**

```bash
git add /mnt/archie_brain/scripts/omniroute/seed_contractor_row.sql
git commit -m "feat(infra): idempotent contractor_providers seed for OmniRoute (#6653 Phase 3a)"
git push -u origin feat/phase3-omniroute-gateway
gh pr create --title "feat(infra): self-hosted OmniRoute gateway + contractor seed (#6653 Phase 3a, PR-1)" --body "$(cat <<'EOF'
## Summary
- `omniroute` compose service, pinned `diegosouzapw/omniroute:3.8.50`, `archie_internal` only, NO host port, secrets from ROOT .env, compression/config done post-boot (plan Task 2).
- `scripts/omniroute/seed_contractor_row.sql` — the ONE `contractor_providers` row, `is_cloud_proxy=false` (true would route via call_ollama_cloud and bypass the gateway).
- Infra only; no platform code. `escalation_mode` stays `local_only`.

## Test Plan
- [ ] `docker compose config --services` lists `omniroute`
- [ ] gateway boots; `/v1/models` 401 without Bearer, 200 with
- [ ] seed applied; `get_provider_for_model('auto/coding') == 'omniroute'`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```
Then register + review (backgrounded; F.O.R.G.E. takes 10+ min):
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs; print(poll_open_prs())"
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr(<PR-1 number>); print(r.get('ok'), r.get('verdict'), r.get('error'))"
```
Merge ONLY on a clean APPROVE with no coverage demotion (the assert below refuses anything else):
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import get_review, coverage_only_demotion
from tools.repair_bay.services.github_service import merge_pr
n = <PR-1 number>
s = (get_review(n) or {}).get('ai_summary') or ''
assert 'VERDICT: APPROVE' in s and not coverage_only_demotion(s), 'NOT a clean APPROVE:\n' + s[-400:]
print(merge_pr(n, method='squash', human_override=True))"
```
If F.O.R.G.E. returns REQUEST CHANGES, fix and re-review; never merge over it. Then on the hub:
```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main
```

- [ ] **Step 3: Generate the gateway secrets into ROOT .env (append only, 0600 preserved)**

```bash
cd /mnt/archie_brain
for kv in "OMNIROUTE_JWT_SECRET=$(openssl rand -base64 48)" \
          "OMNIROUTE_API_KEY_SECRET=$(openssl rand -hex 32)" \
          "OMNIROUTE_STORAGE_ENCRYPTION_KEY=$(openssl rand -hex 32)" \
          "OMNIROUTE_INITIAL_PASSWORD=$(openssl rand -base64 18)"; do
  k="${kv%%=*}"; grep -q "^${k}=" .env || echo "$kv" >> .env
done
stat -c '%a %n' .env   # expect 600 .env
grep -c '^OMNIROUTE_' .env   # expect 4
```

- [ ] **Step 4: Start the gateway and confirm it listens**

```bash
docker compose up -d --no-deps omniroute
sleep 20; docker compose ps omniroute
docker logs omniroute --since 2m 2>&1 | tail -20
docker exec -i archie_platform python3 - <<'PY'
import urllib.request as u, urllib.error as e
try:
    u.urlopen("http://omniroute:20128/v1/models", timeout=10); print("NO-AUTH -> 200 (unexpected)")
except e.HTTPError as ex: print("NO-AUTH ->", ex.code)
PY
```
Expected: container `Up`; NO-AUTH → `401` (REQUIRE_API_KEY is enforced).

- [ ] **Step 5: Enumerate what the container writes (input for the read_only hardening follow-up)**

```bash
docker diff omniroute | head -40
```
Record the paths in the Dev HQ follow-up task "OmniRoute container: read_only + tmpfs hardening" (create it with `mcp__archie__create_task`). Not done in this plan.

- [ ] **Step 6: Reach the dashboard through an SSH tunnel to the container IP, mint the API key**

On the hub, get the container IP:
```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' omniroute
```
From the OWNER's machine (remote): `ssh -N -L 20128:<container-ip>:20128 kytran@192.168.1.200`, then browse `http://localhost:20128`. Log in with `OMNIROUTE_INITIAL_PASSWORD` (from ROOT `.env`). **Dashboard → Endpoints → create an API key** and copy it.

- [ ] **Step 7: Store the API key for the platform (both .env files), reload the platform env**

```bash
cd /mnt/archie_brain
read -rs -p "OMNIROUTE_API_KEY: " OK; echo
for f in .env platform_v2/.env; do grep -q '^OMNIROUTE_API_KEY=' $f || echo "OMNIROUTE_API_KEY=$OK" >> $f; done
unset OK
docker compose up -d --no-deps archie_platform archie_scheduler   # env change => up -d, NOT restart
docker exec archie_platform sh -c 'test -n "$OMNIROUTE_API_KEY" && echo "platform has OMNIROUTE_API_KEY"'
```

- [ ] **Step 8: Gateway configuration in the dashboard (compression OFF, keyless providers only)**

In the dashboard (still via the tunnel):
1. **Compression:** set `enabled=false` and `defaultMode=off` (verified against the management API — OmniRoute 3.8.50 has no exclusions field; there is no Exclusions pattern to set). Reload the page and confirm both persisted.
2. **Providers:** connect ONLY providers that require no key (the catalog marks 56 "recurring/keyless free-forever" providers) and that are NOT marked `avoid` on `/dashboard/free-tiers`. Connect NO paid provider and enter NO API key of ours (3b, Task 12).

- [ ] **Step 9: Prove auth + catalog from inside the platform, capture the concrete model ids**

```bash
docker exec -i archie_platform python3 - <<'PY'
import os, json, urllib.request as u
req = u.Request("http://omniroute:20128/v1/models", headers={"Authorization": f"Bearer {os.environ['OMNIROUTE_API_KEY']}"})
d = json.load(u.urlopen(req, timeout=15))
ids = [m.get("id") for m in d.get("data", [])]
print("count:", len(ids))
concrete = [i for i in ids if i and not (i == "auto" or i.startswith("auto/"))]
print("first concrete ids:", concrete[:10])
PY
```
Expected: `count` > 0 and at least one concrete (non-`auto`) id. **Write down the first concrete id — it is `:default_model` for Task 3.** If `count` is 0, no provider is connected yet — return to Step 8.

---

### Task 3: Seed the contractor row and prove auto-surface

**Files:**
- Uses: `scripts/omniroute/seed_contractor_row.sql` (Task 2)

**Interfaces:**
- Produces: `contractor_providers.provider_key='omniroute'` (`is_active=true`, `is_cloud_proxy=false`, concrete `default_model`, `models` = default + `auto/coding` + `auto/coding:free`). Consumed by `get_provider_for_model` (dispatch routing), the A/B models endpoint, and the Contractors tab.

- [ ] **Step 1: Apply the seed with the concrete default from Task 2 Step 9**

```bash
cd /mnt/archie_brain
docker exec -i archie_database psql -U archie -d archie -v default_model='<first concrete id from Task 2>' \
  -f - < scripts/omniroute/seed_contractor_row.sql 2>&1
docker exec archie_database psql -U archie -d archie -c \
  "SELECT provider_key, base_url, default_model, is_cloud_proxy, tier_position, is_active, models FROM contractor_providers WHERE provider_key='omniroute';" 2>&1
```
Expected: `INSERT 0 1`; the SELECT shows `is_cloud_proxy = f`, `is_active = t`, `tier_position = 9`, three `models` entries, and a non-`auto` `default_model`.

- [ ] **Step 2: Prove the routing map and the A/B-lane query both see it (the same SQL the endpoint runs)**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from ai_bridge.external_providers import invalidate_provider_cache, get_provider_for_model, _get_provider_config
invalidate_provider_cache()
print('auto/coding ->', get_provider_for_model('auto/coding'))
cfg = _get_provider_config('omniroute'); print('default_model ->', cfg['default_model'], '| default ->', get_provider_for_model(cfg['default_model']))
print('is_cloud_proxy ->', cfg.get('is_cloud_proxy'))"
docker exec archie_database psql -U archie -d archie -tAc \
  "SELECT provider_key FROM contractor_providers WHERE capabilities ? 'text_chat' AND is_active = true AND provider_key='omniroute';"
```
Expected: `auto/coding -> omniroute`, `default -> omniroute`, `is_cloud_proxy -> False`, and the SQL prints `omniroute` (that predicate is exactly `benchmark_routes.py:748`, so the A/B dropdown now lists it; `/api/external-providers` lists every row, so the Contractors tab does too).

- [ ] **Step 3: Confirm nothing auto-escalates (sovereign default untouched)**

```bash
docker exec archie_database psql -U archie -d archie -tAc "SELECT value FROM platform_settings WHERE key='escalation_mode';"
```
Expected: `local_only`.

---

### Task 4: `resolve_served_model()` in the generic adapter (PR-2 begins)

**Files:**
- Modify: `ai_bridge/external_providers.py` (insert helpers immediately before `def _call_openai_compatible(` at line 338; edit the return dict at lines 409–418)
- Modify: `docs/superpowers/specs/2026-09-09-phase3-omniroute-contractor-design.md` (correct `is_cloud_proxy`)
- Test: `platform_v2/tests/test_served_model_attribution.py` (create)

**Interfaces:**
- Produces: `is_auto_router(model_id: str) -> bool`; `resolve_served_model(data: dict, requested: str) -> tuple[str, bool]`; `_call_openai_compatible(...)` result gains `"requested_model"`, `"served_model_resolved"`, `"routing_decision"`, and `"model"` becomes the SERVED model.

- [ ] **Step 1: Create the branch off main**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main
git checkout -b feat/phase3-omniroute-lane
```

- [ ] **Step 2: Write the failing tests**

Create `platform_v2/tests/test_served_model_attribution.py`:

```python
"""#6653 Phase 3 — task_execution_log.model_used records the model that actually
SERVED a contractor call, never an auto-router id like "auto/coding".

OmniRoute's whole value is quota-aware auto-fallback, so the served model differs
from the requested one. Before this, the served model was discarded at THREE
layers (external_providers._call_openai_compatible, dispatcher._dispatch_to_contractor,
and the request_work result builder) and a default_model of "auto" would have logged
the literal string "auto" into the accounting spine (ADR-034).

Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q
"""
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))          # /app (platform_v2); ai_bridge is already importable in-container

from ai_bridge import external_providers as ep     # noqa: E402

_DISPATCHER_SRC = _HERE.parents[1] / "tools" / "department_hq" / "services" / "department_dispatcher.py"


# --- external_providers helpers -------------------------------------------------

@pytest.mark.parametrize("mid", ["auto", "auto/coding", "auto/coding:free", "AUTO/fast"])
def test_auto_router_ids_are_recognised(mid):
    assert ep.is_auto_router(mid) is True


@pytest.mark.parametrize("mid", ["gpt-4o-mini", "deepseek/deepseek-chat", "autopilot-x", "", None])
def test_concrete_ids_are_not_auto_routers(mid):
    assert ep.is_auto_router(mid) is False


def test_served_model_comes_from_the_response_body():
    model, resolved = ep.resolve_served_model({"model": "deepseek/deepseek-chat"}, "auto/coding")
    assert (model, resolved) == ("deepseek/deepseek-chat", True)


def test_body_echoing_an_auto_id_falls_back_to_requested_and_is_flagged():
    model, resolved = ep.resolve_served_model({"model": "auto/coding"}, "auto/coding")
    assert model == "auto/coding" and resolved is False


def test_missing_body_model_with_concrete_request_is_resolved():
    model, resolved = ep.resolve_served_model({}, "gpt-4o-mini")
    assert (model, resolved) == ("gpt-4o-mini", True)


def test_missing_body_model_with_auto_request_is_unresolved():
    model, resolved = ep.resolve_served_model({}, "auto")
    assert model == "auto" and resolved is False


# --- _call_openai_compatible threads the served model through --------------------

class _Resp:
    def __init__(self, body, headers=None, status=200):
        self._body, self.headers, self.status_code = body, headers or {}, status
        self.text = ""
    def raise_for_status(self): pass
    def json(self): return self._body


def _neutralise(monkeypatch, served):
    monkeypatch.setattr(ep, "_get_provider_config", lambda p: {"base_url": "http://omniroute:20128/v1", "default_model": "auto/coding"})
    monkeypatch.setattr(ep, "_get_api_key", lambda p: "k")
    monkeypatch.setattr(ep, "_check_budget", lambda p: True)
    monkeypatch.setattr(ep, "check_weekly_budget", lambda p: True)
    monkeypatch.setattr(ep, "_update_cost", lambda *a, **k: None)
    logged = {}
    monkeypatch.setattr(ep, "_log_usage", lambda prov, model, *a, **k: logged.update({"model": model}))
    monkeypatch.setattr(ep, "_calculate_cost", lambda *a, **k: 0.0)
    body = {"model": served, "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    monkeypatch.setattr(ep.requests, "post", lambda *a, **k: _Resp(body, {"X-OmniRoute-Decision": "strategy=lkgp provider=deepseek"}))
    return logged


def test_call_openai_compatible_returns_the_served_model_not_the_requested(monkeypatch):
    logged = _neutralise(monkeypatch, served="deepseek/deepseek-chat")
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["success"] is True
    assert r["model"] == "deepseek/deepseek-chat"
    assert r["requested_model"] == "auto/coding"
    assert r["served_model_resolved"] is True
    assert r["routing_decision"] == "strategy=lkgp provider=deepseek"
    assert logged["model"] == "deepseek/deepseek-chat"   # usage ledger keyed by the served model


def test_call_openai_compatible_never_reports_auto_as_resolved(monkeypatch):
    _neutralise(monkeypatch, served="auto/coding")
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["served_model_resolved"] is False
    assert r["model"] == "auto/coding"      # the requested id, flagged — never silently "resolved"


# --- dispatcher: served_or_requested + the three call sites ----------------------

def test_served_or_requested_prefers_the_served_model():
    from tools.department_hq.services.department_dispatcher import served_or_requested
    assert served_or_requested({"model": "deepseek/deepseek-chat"}, "auto/coding") == "deepseek/deepseek-chat"


def test_served_or_requested_falls_back_when_served_is_an_auto_router_or_missing():
    from tools.department_hq.services.department_dispatcher import served_or_requested
    assert served_or_requested({"model": "auto/coding"}, "auto/coding") == "auto/coding"
    assert served_or_requested({}, "qwen2.5:7b") == "qwen2.5:7b"
    assert served_or_requested(None, "qwen2.5:7b") == "qwen2.5:7b"


def test_every_model_used_site_on_the_contractor_and_hub_paths_uses_the_helper():
    src = _DISPATCHER_SRC.read_text(encoding="utf-8")
    # _dispatch_to_contractor: both branches
    assert len(re.findall(r"model_used=served_or_requested\((llm_result|result), model or provider_key\)", src)) == 2
    # request_work success builder (the explicit model_override / A-B lane path)
    assert re.search(r"model_used=served_or_requested\(llm_result, model\)", src) is not None
    # the old literal forms must be gone from those sites
    assert "model_used=model or provider_key," not in src
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q 2>&1 | tail -5`
Expected: FAIL — `AttributeError: module ... has no attribute 'is_auto_router'` (and `ImportError` for `served_or_requested`).

- [ ] **Step 4: Add the helpers and thread the served model**

In `ai_bridge/external_providers.py`, insert immediately BEFORE `def _call_openai_compatible(`:

```python
def is_auto_router(model_id) -> bool:
    """True for a gateway auto-routing id (`auto`, `auto/<variant>[:<tier>]`).

    Such an id names a POLICY, not a model. It must never be recorded as
    task_execution_log.model_used (#6653) — that column is the accounting spine.
    """
    m = (str(model_id).strip().lower() if model_id else "")
    return m == "auto" or m.startswith("auto/")


def resolve_served_model(data: dict, requested: str) -> tuple[str, bool]:
    """Which upstream model actually served an OpenAI-compatible response?

    OpenAI-compatible gateways echo the CONCRETE served model in the body's
    ``model`` field. Returns ``(model_id, resolved)``: ``resolved`` is False only
    when the best id we have is still an auto-router — the caller then records
    the requested id AND the flag, so a live check can catch a gateway that does
    not echo the served model instead of silently logging ``auto``.
    """
    body_model = (data or {}).get("model") if isinstance(data, dict) else None
    body_model = str(body_model).strip() if body_model else ""
    if body_model and not is_auto_router(body_model):
        return body_model, True
    req = (requested or "").strip()
    return req, not is_auto_router(req)


```

(Python 3.11: the builtin `tuple[str, bool]` annotation needs no `typing` import.)

Then in `_call_openai_compatible`, replace the block

```python
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = _calculate_cost(model, prompt_tokens, completion_tokens)

        _update_cost(provider, cost)
        _log_usage(provider, model, prompt_tokens, completion_tokens, cost)

        return {
            "success": True,
            "response": choice["message"]["content"],
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost,
            "duration_ms": duration_ms,
        }
```

with

```python
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        # #6653: record what SERVED the call, not what we asked for. An auto-routing
        # gateway (OmniRoute `auto/*`) resolves to a concrete upstream model per call.
        served_model, served_resolved = resolve_served_model(data, model)
        cost = _calculate_cost(served_model, prompt_tokens, completion_tokens)

        _update_cost(provider, cost)
        _log_usage(provider, served_model, prompt_tokens, completion_tokens, cost)

        return {
            "success": True,
            "response": choice["message"]["content"],
            "model": served_model,
            "requested_model": model,
            "served_model_resolved": served_resolved,
            "routing_decision": resp.headers.get("X-OmniRoute-Decision"),
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost,
            "duration_ms": duration_ms,
        }
```

- [ ] **Step 5: Confirm the spec carries the `is_cloud_proxy=false` correction (applied when this plan was written)**

Run: `grep -c "is_cloud_proxy=true" /mnt/archie_brain/docs/superpowers/specs/2026-09-09-phase3-omniroute-contractor-design.md`
Expected: `0` (and `grep -c "Correction (plan, 2026-09-09)"` on the same file prints `1`). Nothing to edit.

- [ ] **Step 6: Run the adapter-level tests (the dispatcher ones still fail until Task 5)**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q -k "not served_or_requested and not model_used_site" 2>&1 | tail -3`
Expected: `15 passed`

- [ ] **Step 7: Mutation check (authoring-time only — never bake into a test)**

Temporarily change `"model": served_model,` back to `"model": model,`, re-run Step 6, confirm `test_call_openai_compatible_returns_the_served_model_not_the_requested` FAILS, then restore.

- [ ] **Step 8: Commit**

```bash
git add /mnt/archie_brain/ai_bridge/external_providers.py /mnt/archie_brain/platform_v2/tests/test_served_model_attribution.py /mnt/archie_brain/docs/superpowers/specs/2026-09-09-phase3-omniroute-contractor-design.md
git commit -m "fix(external_providers): return the SERVED model from OpenAI-compatible calls, never an auto-router id (#6653)"
```

---

### Task 5: `served_or_requested()` + the three `model_used` sites in the dispatcher

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_dispatcher.py` — module-level helper before `class DispatchResult:` (line 756); `_dispatch_to_contractor` lines 5612–5633 and 5647–5668; request_work builder around line 8875 (the `result = DispatchResult(` that follows `if llm_result is None: llm_result = self._execute_llm(` at line 8594)
- Test: `platform_v2/tests/test_served_model_attribution.py` (Task 4 — the remaining tests)

**Interfaces:**
- Produces: `served_or_requested(llm_result: dict | None, requested: str) -> str` (module-level, importable); `DispatchResult.metadata` gains `served_model_resolved` and `routing_decision` on contractor/cloud results (→ `task_execution_log.request_metadata`).

- [ ] **Step 1: Run the dispatcher tests to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q -k "served_or_requested or model_used_site" 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'served_or_requested'`.

- [ ] **Step 2: Add the helper**

Insert immediately BEFORE `class DispatchResult:` in `department_dispatcher.py`:

```python
def served_or_requested(llm_result, requested):
    """model_used for a DispatchResult (#6653): the model the provider SAYS served the
    call, unless that is an auto-router id — then the requested id. Local Ollama
    results echo the requested model, so this is a no-op for them; it only changes
    contractor/gateway rows, where the served model is the accounting truth (ADR-034).
    """
    from ai_bridge.external_providers import is_auto_router

    served = llm_result.get("model") if isinstance(llm_result, dict) else None
    served = str(served).strip() if served else ""
    if served and not is_auto_router(served):
        return served
    return requested or ""


```

- [ ] **Step 3: Wire the two `_dispatch_to_contractor` branches**

In the cloud-proxy branch replace
```python
                        model_used=model or provider_key,
```
(the one directly under `agent_id=None,` following `llm_result = self._execute_llm(`) with
```python
                        model_used=served_or_requested(llm_result, model or provider_key),
```
and extend that branch's `metadata={` dict with two keys after `"is_cloud_proxy": True,`:
```python
                            "served_model_resolved": bool(llm_result.get("served_model_resolved", True)),
                            "routing_decision": llm_result.get("routing_decision"),
```

In the standard branch replace
```python
                        model_used=model or provider_key,
```
with
```python
                        model_used=served_or_requested(result, model or provider_key),
```
and extend its `metadata={` dict after `"is_cloud_proxy": False,` with
```python
                            "served_model_resolved": bool(result.get("served_model_resolved", True)),
                            "routing_decision": result.get("routing_decision"),
```

- [ ] **Step 4: Wire the request_work builder (the explicit `model_override` path the A/B lane and coding lane use)**

Find the `result = DispatchResult(` block that begins right after `if agentic_info: result_metadata["agentic"] = agentic_info` (≈ line 8875). Replace
```python
            model_used=model,
```
in THAT block with
```python
            model_used=served_or_requested(llm_result, model),
```
and, immediately BEFORE `result = DispatchResult(` in that block, insert:
```python
        # #6653: carry served-model provenance from a gateway/contractor call into
        # task_execution_log.request_metadata so the live proof can read it back.
        if isinstance(llm_result, dict) and "served_model_resolved" in llm_result:
            result_metadata["served_model_resolved"] = bool(llm_result.get("served_model_resolved"))
            result_metadata["routing_decision"] = llm_result.get("routing_decision")
```

- [ ] **Step 5: Run the whole attribution file**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q 2>&1 | tail -3`
Expected: `18 passed`

- [ ] **Step 6: Behaviour test for `_dispatch_to_contractor` (append to the same test file)**

Append to `platform_v2/tests/test_served_model_attribution.py`:

```python
def test_dispatch_to_contractor_records_the_served_model(monkeypatch):
    from tools.department_hq.services import department_dispatcher as dd
    disp = dd.DepartmentDispatcher()
    monkeypatch.setattr(disp, "_cloud_capability_allowed", lambda cap: True)
    monkeypatch.setattr(disp, "_cloud_budget_ok", lambda *a, **k: True)
    monkeypatch.setattr(ep, "call_external", lambda **kw: {
        "success": True, "response": "ok", "model": "deepseek/deepseek-chat",
        "requested_model": "auto/coding", "served_model_resolved": True,
        "routing_decision": "provider=deepseek", "provider": "omniroute",
        "prompt_tokens": 3, "completion_tokens": 2,
    })
    contractor = {"provider_key": "omniroute", "display_name": "OmniRoute", "default_model": "auto/coding",
                  "is_cloud_proxy": False, "tier_position": 9, "creed_compliance_tier": 2}
    res = disp._dispatch_to_contractor(contractor, "write a fizzbuzz", "code", "cloud_code_lane")
    assert res is not None and res.success
    assert res.model_used == "deepseek/deepseek-chat"
    assert res.provider == "contractor:omniroute"
    assert res.metadata["served_model_resolved"] is True
    assert res.metadata["routing_decision"] == "provider=deepseek"
```

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q 2>&1 | tail -3`
Expected: `19 passed`

- [ ] **Step 7: Existing suites still green**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_dispatcher_stream_work.py tests/test_cloud_capability_allowlist.py tests/test_token_provenance.py -q 2>&1 | tail -3`
Expected: all pass (no failures).

- [ ] **Step 8: Mutation check (authoring-time only)**

Temporarily revert the request_work builder line to `model_used=model,`; run Step 5; confirm `test_every_model_used_site_on_the_contractor_and_hub_paths_uses_the_helper` FAILS; restore.

- [ ] **Step 9: Commit**

```bash
git add /mnt/archie_brain/platform_v2/tools/department_hq/services/department_dispatcher.py /mnt/archie_brain/platform_v2/tests/test_served_model_attribution.py
git commit -m "fix(dispatcher): model_used records the SERVED model at all three contractor/cloud sites (#6653)"
```

---

### Task 6: `services/cloud_code_lane.py` — pure lane helpers

**Files:**
- Create: `platform_v2/services/cloud_code_lane.py`
- Test: `platform_v2/tests/test_cloud_code_lane.py` (create)

**Interfaces:**
- Produces (consumed by Tasks 7–8): constants `JOB_TYPE="cloud_code"`, `MODULE_ID="cloud_code_lane"`, `CAPABILITY="code"`, `ACTION_TYPE="cloud_code_dispatch"`, `EXPIRE_SECONDS`; `build_job_metadata(*, prompt, system_prompt, provider_key, model, requested_by) -> dict`; `plan_worker_action(job_status, approval_status, age_seconds) -> "run"|"cancel"|"skip"`; `summarize_result(res) -> dict`; adapters `code_allowed() -> bool`, `active_provider(provider_key) -> dict|None`, `request_tier2_approval(*, job_id, provider_key, model, prompt, requested_by) -> int|None`.

- [ ] **Step 1: Write the failing tests**

Create `platform_v2/tests/test_cloud_code_lane.py`:

```python
"""#6653 Phase 3a — the ask-first cloud CODING lane, decision logic (pure)."""
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))          # /app (platform_v2)

import ai_bridge                                   # noqa: E402  (package __init__ only — agent_loop itself is heavy)
from services import cloud_code_lane as lane       # noqa: E402

_AGENT_LOOP_SRC = Path(ai_bridge.__file__).resolve().parent / "agent_loop.py"


def test_constants_pin_the_lane_to_code_and_a_distinct_action_type():
    assert lane.CAPABILITY == "code"
    assert lane.JOB_TYPE == "cloud_code"
    assert lane.ACTION_TYPE == "cloud_code_dispatch"
    assert lane.MODULE_ID == "cloud_code_lane"


def test_job_metadata_carries_everything_the_worker_needs():
    m = lane.build_job_metadata(prompt="p", system_prompt=None, provider_key="omniroute",
                                model="auto/coding", requested_by="cockpit:archie_comms")
    assert m == {"lane": "cloud_code_lane", "provider": "omniroute", "model": "auto/coding",
                 "capability": "code", "prompt": "p", "system_prompt": "", "requested_by": "cockpit:archie_comms"}


@pytest.mark.parametrize("approval,expected", [
    ("approved", "run"), ("rejected", "cancel"), ("denied", "cancel"), ("timeout", "cancel"),
    ("expired", "cancel"), ("cancelled", "cancel"), ("pending", "skip"), (None, "skip"),
])
def test_plan_worker_action_resolves_the_linked_approval(approval, expected):
    assert lane.plan_worker_action("pending", approval, 10.0) == expected


def test_a_pending_job_older_than_the_horizon_is_cancelled():
    assert lane.plan_worker_action("pending", "pending", lane.EXPIRE_SECONDS + 1) == "cancel"


def test_only_pending_jobs_are_ever_acted_on():
    assert lane.plan_worker_action("running", "approved", 1.0) == "skip"
    assert lane.plan_worker_action("completed", "approved", 1.0) == "skip"


class _Res:
    success = True; response = "def f(): pass"; model_used = "deepseek/deepseek-chat"
    provider = "omniroute"; prompt_tokens = 10; completion_tokens = 5; error = None
    metadata = {"served_model_resolved": True, "routing_decision": "provider=deepseek"}


def test_summarize_result_is_json_safe_and_keeps_provenance():
    s = lane.summarize_result(_Res())
    assert s == {"success": True, "response": "def f(): pass", "model_used": "deepseek/deepseek-chat",
                 "provider": "omniroute", "prompt_tokens": 10, "completion_tokens": 5, "error": None,
                 "served_model_resolved": True, "routing_decision": "provider=deepseek"}


def test_summarize_result_flags_missing_provenance_as_unresolved():
    class R(_Res):
        metadata = {}
    assert lane.summarize_result(R())["served_model_resolved"] is False


def test_cloud_code_worker_is_defined_and_scheduled():
    src = _AGENT_LOOP_SRC.read_text(encoding="utf-8")
    assert re.search(r"^\s{4}def cloud_code_worker\(self\):", src, re.M) is not None
    assert 'id="cloud_code_worker"' in src
    assert "with_app_context(self.cloud_code_worker)" in src


def test_cloud_code_dispatch_approvals_land_in_the_ship_tab():
    from tools.department_hq.services.approvals_bulk import category_of, CATEGORY_SHIP
    assert category_of("cloud_code_dispatch") == CATEGORY_SHIP
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_lane.py -q 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.cloud_code_lane'`.

- [ ] **Step 3: Write the module**

Create `platform_v2/services/cloud_code_lane.py`:

```python
"""Cloud coding lane (#6653 Phase 3a) — pure helpers, no DB, no Flask.

An explicit, ask-first path that sends ONE coding task to a cloud contractor
(OmniRoute) WITHOUT changing escalation_mode (it stays local_only — this is not
auto-escalation). Mirrors the A/B Cloud Comparison lane (#4661): the job is a
bridge_jobs row, the approval is an autonomy_approval_queue row linked by
metadata.approval_id, and a 30 s worker (agent_loop.cloud_code_worker) drains
approved jobs. Everything decision-shaped lives here so it is testable without
a database; the three adapters at the bottom are the ONLY places that touch
other subsystems, and tests monkeypatch them.

The cockpit button for this lane is Phase 4; app.py exposes the backend path.
"""

from __future__ import annotations

from typing import Optional

JOB_TYPE = "cloud_code"
MODULE_ID = "cloud_code_lane"
CAPABILITY = "code"                 # on the cloud allowlist; never company data
ACTION_TYPE = "cloud_code_dispatch"  # Tier-2 approval type (Ship tab)
EXPIRE_SECONDS = 24 * 3600          # same horizon as the A/B lane


def build_job_metadata(*, prompt: str, system_prompt: Optional[str], provider_key: str,
                       model: str, requested_by: str) -> dict:
    return {
        "lane": MODULE_ID,
        "provider": provider_key,
        "model": model,
        "capability": CAPABILITY,
        "prompt": prompt,
        "system_prompt": system_prompt or "",
        "requested_by": requested_by,
    }


def plan_worker_action(job_status: str, approval_status: Optional[str], age_seconds: float) -> str:
    """'run' | 'cancel' | 'skip' for one job, from its linked approval's state."""
    if job_status != "pending":
        return "skip"
    st = (approval_status or "pending").strip().lower()
    if st == "approved":
        return "run"
    if st in ("rejected", "denied", "timeout", "expired", "cancelled"):
        return "cancel"
    if age_seconds > EXPIRE_SECONDS:
        return "cancel"
    return "skip"


def summarize_result(res) -> dict:
    """Shape a DispatchResult into the JSON-safe record stored on the job."""
    meta = getattr(res, "metadata", None) or {}
    return {
        "success": bool(getattr(res, "success", False)),
        "response": getattr(res, "response", "") or "",
        "model_used": getattr(res, "model_used", "") or "",
        "provider": getattr(res, "provider", "") or "",
        "prompt_tokens": int(getattr(res, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(res, "completion_tokens", 0) or 0),
        "error": getattr(res, "error", None),
        # A cloud coding call MUST carry provenance; absence is flagged, not assumed.
        "served_model_resolved": bool(meta.get("served_model_resolved", False)),
        "routing_decision": meta.get("routing_decision"),
    }


# --- adapters (the only subsystem touchpoints; monkeypatched in tests) -----------

def code_allowed() -> bool:
    """The sovereignty boundary: may 'code' leave the cluster? Fails closed."""
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    return bool(get_dispatcher()._cloud_capability_allowed(CAPABILITY))


def active_provider(provider_key: str) -> Optional[dict]:
    from ai_bridge.external_providers import _get_provider_config

    cfg = _get_provider_config(provider_key)
    return cfg if cfg and cfg.get("is_active") else None


def request_tier2_approval(*, job_id: int, provider_key: str, model: str, prompt: str,
                           requested_by: str) -> Optional[int]:
    """Ask-first. Returns the approval id, or None when request_approval() could not
    enqueue (its per-action_type dedup: one pending cloud_code approval at a time)."""
    from ai_bridge.agent_loop import request_approval

    return request_approval(
        action_type=ACTION_TYPE,
        action_data={
            "job_id": job_id,
            "provider": provider_key,
            "model": model,
            "prompt_preview": prompt[:200],
            "requested_by": requested_by,
        },
        reason=f"Cloud coding task via {provider_key}:{model}",
        requested_by="cloud_code_lane",
        tier=2,
    )
```

- [ ] **Step 4: Run the tests**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_lane.py -q 2>&1 | tail -3`
Expected: 14 passed, **2 failed** (`test_cloud_code_worker_is_defined_and_scheduled`, `test_cloud_code_dispatch_approvals_land_in_the_ship_tab`) — those are Tasks 7–8.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/cloud_code_lane.py /mnt/archie_brain/platform_v2/tests/test_cloud_code_lane.py
git commit -m "feat(services): cloud_code_lane — pure helpers for the ask-first cloud coding lane (#6653 Phase 3a)"
```

---

### Task 7: `cloud:code` scope, the two endpoints, the approvals category

**Files:**
- Modify: `platform_v2/services/internal_auth.py` (`SCOPES` frozenset + `CALLER_SCOPES["archie_comms"]`)
- Modify: `platform_v2/app.py` (insert before `@app.route("/api/internal/delegation/submit", methods=["POST"])`)
- Modify: `platform_v2/tools/department_hq/services/approvals_bulk.py` (`ACTION_CATEGORY`)
- Test: `platform_v2/tests/test_internal_auth_scopes.py` (modify), `platform_v2/tests/test_cloud_code_lane.py`

**Interfaces:**
- Consumes: Task 6 helpers/adapters.
- Produces: `POST /api/internal/cloud-code/run` → `202 {success, status:"pending_approval", job_id, approval_id}` | `400` (no prompt/model) | `404` (inactive provider) | `409` (`code` not allowlisted, or approval dedup → `status:"approval_unavailable"`); `GET /api/internal/cloud-code/run/<int:job_id>` → `200 {job_id, status, approval_id, model, provider, result, error, created_at, completed_at}` | `404`. Scope `cloud:code` (archie_comms only).

- [ ] **Step 1: Add the scope + grant**

In `platform_v2/services/internal_auth.py`, in the `SCOPES` frozenset add after the `"agents:manage",` line:
```python
        "cloud:code",  # cockpit ask-first cloud CODING lane: explicit, per-call, never auto-escalation (#6653 Phase 3a)
```
and change the `archie_comms` entry of `CALLER_SCOPES` to
```python
    "archie_comms": frozenset(
        {"dhq:chat", "coo", "mail", "approvals:read", "approvals:decide", "delegation", "repair:read", "agents:manage", "cloud:code"}
    ),
```

- [ ] **Step 2: Add the failing tests to `test_internal_auth_scopes.py`**

Add to the `PROBES` dict:
```python
    "cloud:code": ("GET", "/api/internal/cloud-code/run/0"),
```
Append these tests at the end of the file (`client`, `keys`, `_comms` are existing fixtures/helpers at the top of this file — reuse them):

```python
# --- #6653 Phase 3a: the ask-first cloud coding lane --------------------------------

class _LaneCur:
    """Records SQL; RETURNING id -> 41, SELECT job -> a canned row."""
    def __init__(self, log): self.log = log
    def execute(self, sql, params=None): self.log.append((sql, params))
    def fetchone(self):
        last = self.log[-1][0]
        if "RETURNING id" in last:
            return {"id": 41}
        if last.lstrip().startswith("SELECT id, status"):
            return {"id": 41, "status": "completed", "metadata": {"approval_id": 77, "model": "auto/coding",
                    "provider": "omniroute", "result": {"success": True}}, "error_message": None,
                    "created_at": None, "completed_at": None}
        return None


class _LaneDB:
    def __init__(self, log): self.log = log
    def __call__(self, *a, **k): return self
    def __enter__(self): return (None, _LaneCur(self.log))
    def __exit__(self, *a): return False


def _lane_patches(monkeypatch, *, allowed=True, provider=True, approval_id=77):
    log = []
    monkeypatch.setattr("services.cloud_code_lane.code_allowed", lambda: allowed)
    monkeypatch.setattr("services.cloud_code_lane.active_provider",
                        lambda pk: {"provider_key": pk, "default_model": "auto/coding", "is_active": True} if provider else None)
    seen = {}
    monkeypatch.setattr("services.cloud_code_lane.request_tier2_approval",
                        lambda **kw: (seen.update(kw), approval_id)[1])
    monkeypatch.setattr("database.get_db_cursor", _LaneDB(log))
    return log, seen


def test_cloud_code_run_requires_a_prompt(client, keys, monkeypatch):
    _lane_patches(monkeypatch)
    r = client.post("/api/internal/cloud-code/run", headers=_comms(keys), json={})
    assert r.status_code == 400


def test_cloud_code_run_refuses_when_code_is_not_on_the_cloud_allowlist(client, keys, monkeypatch):
    log, _ = _lane_patches(monkeypatch, allowed=False)
    r = client.post("/api/internal/cloud-code/run", headers=_comms(keys), json={"prompt": "fizzbuzz"})
    assert r.status_code == 409
    assert not any("INSERT INTO bridge_jobs" in sql for sql, _ in log)   # refused BEFORE any row exists


def test_cloud_code_run_enqueues_a_job_and_a_tier2_approval(client, keys, monkeypatch):
    log, seen = _lane_patches(monkeypatch)
    r = client.post("/api/internal/cloud-code/run", headers=_comms(keys), json={"prompt": "fizzbuzz"})
    assert r.status_code == 202
    body = r.get_json()
    assert body == {"success": True, "status": "pending_approval", "job_id": 41, "approval_id": 77}
    assert any("INSERT INTO bridge_jobs" in sql and params[0] == "cloud_code" and params[3] == "pending" for sql, params in log)
    assert seen["job_id"] == 41 and seen["model"] == "auto/coding" and seen["provider_key"] == "omniroute"
    assert any("'{approval_id}'" in sql for sql, _ in log)   # linked back onto the job for the worker


def test_cloud_code_run_fails_honestly_when_an_approval_is_already_pending(client, keys, monkeypatch):
    log, _ = _lane_patches(monkeypatch, approval_id=None)
    r = client.post("/api/internal/cloud-code/run", headers=_comms(keys), json={"prompt": "fizzbuzz"})
    assert r.status_code == 409
    assert r.get_json()["status"] == "approval_unavailable"
    assert any("SET status='failed'" in sql for sql, _ in log)


def test_cloud_code_status_returns_the_job(client, keys, monkeypatch):
    _lane_patches(monkeypatch)
    r = client.get("/api/internal/cloud-code/run/41", headers=_comms(keys))
    assert r.status_code == 200
    j = r.get_json()
    assert j["job_id"] == 41 and j["status"] == "completed" and j["approval_id"] == 77 and j["result"] == {"success": True}
```

- [ ] **Step 3: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q 2>&1 | tail -5`
Expected: the five new tests FAIL with 404 (route missing); the per-caller table test for `cloud:code` FAILS.

- [ ] **Step 4: Add the endpoints to `app.py`**

Insert immediately BEFORE `@app.route("/api/internal/delegation/submit", methods=["POST"])`:

```python
# ---------------------------------------------------------------------------
# Phase 3a (#6653): the ask-first cloud CODING lane. Explicit and per-call —
# never auto-escalation (escalation_mode stays local_only). Mirrors the A/B Cloud
# Comparison lane (#4661): a bridge_jobs row (status 'pending', NOT
# 'pending_approval' — the autonomy row is the ONE approval item, so the
# Approvals tab never double-lists) + a Tier-2 approval linked by
# metadata.approval_id; agent_loop.cloud_code_worker (30 s) drains approved jobs.
# The cockpit button is Phase 4; this is the backend path.
# ---------------------------------------------------------------------------
@app.route("/api/internal/cloud-code/run", methods=["POST"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_run():
    import json as _json
    from psycopg2.extras import Json
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt required"}), 400
    system_prompt = (data.get("system_prompt") or "").strip() or None
    provider_key = (data.get("provider") or "omniroute").strip()

    # Sovereignty boundary first (fail-closed); the dispatcher re-checks at dispatch time.
    if not lane.code_allowed():
        return jsonify({"success": False, "error": "capability 'code' is not on the cloud allowlist"}), 409
    cfg = lane.active_provider(provider_key)
    if not cfg:
        return jsonify({"success": False, "error": f"provider {provider_key!r} is not an active contractor"}), 404
    model = (data.get("model") or cfg.get("default_model") or "").strip()
    if not model:
        return jsonify({"success": False, "error": "no model: pass one or set the provider's default_model"}), 400

    requested_by = f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}"
    meta = lane.build_job_metadata(
        prompt=prompt, system_prompt=system_prompt, provider_key=provider_key, model=model, requested_by=requested_by
    )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO bridge_jobs (job_type, module_source, description, status, agent_name, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (lane.JOB_TYPE, lane.MODULE_ID, f"cloud code via {provider_key}:{model}", "pending", "CONTRACTOR→cloud", Json(meta)),
        )
        job_id = cur.fetchone()["id"]

    approval_id = lane.request_tier2_approval(
        job_id=job_id, provider_key=provider_key, model=model, prompt=prompt, requested_by=requested_by
    )
    if approval_id is None:
        # request_approval()'s per-action_type dedup: one pending cloud_code approval at
        # a time. Fail the job honestly rather than leave a poller waiting forever.
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE bridge_jobs SET status='failed', completed_at=NOW(), updated_at=NOW(), error_message=%s WHERE id=%s",
                ("approval_unavailable: a cloud coding approval is already pending", job_id),
            )
        return (
            jsonify({"success": False, "status": "approval_unavailable", "job_id": job_id,
                     "error": "A cloud coding task is already awaiting approval — decide that one first."}),
            409,
        )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb), '{approval_id}', %s::jsonb), "
            "updated_at=NOW() WHERE id=%s",
            (_json.dumps(approval_id), job_id),
        )
    return jsonify({"success": True, "status": "pending_approval", "job_id": job_id, "approval_id": approval_id}), 202


@app.route("/api/internal/cloud-code/run/<int:job_id>", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_status(job_id):
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, status, metadata, error_message, created_at, completed_at FROM bridge_jobs WHERE id=%s AND job_type=%s",
            (job_id, lane.JOB_TYPE),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "job not found"}), 404
    meta = row["metadata"] or {}
    return jsonify(
        {
            "success": True,
            "job_id": row["id"],
            "status": row["status"],
            "approval_id": meta.get("approval_id"),
            "model": meta.get("model"),
            "provider": meta.get("provider"),
            "result": meta.get("result"),
            "error": row["error_message"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }
    )


```

- [ ] **Step 5: Approvals category**

In `platform_v2/tools/department_hq/services/approvals_bulk.py`, inside `ACTION_CATEGORY` after `"restart_container": CATEGORY_SHIP,` add:
```python
    "cloud_code_dispatch": CATEGORY_SHIP,  # #6653 ask-first cloud coding lane — it is code work
```

- [ ] **Step 6: Run both test files**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py tests/test_cloud_code_lane.py -q 2>&1 | tail -4`
Expected: `test_internal_auth_scopes.py` all pass (31 existing + 5 new + the widened table); `test_cloud_code_lane.py` — 15 passed, 1 failed (`test_cloud_code_worker_is_defined_and_scheduled`, Task 8).

- [ ] **Step 7: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/internal_auth.py /mnt/archie_brain/platform_v2/app.py /mnt/archie_brain/platform_v2/tools/department_hq/services/approvals_bulk.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(internal-api): ask-first cloud coding lane — cloud:code scope, run/poll endpoints, Ship-tab approval (#6653 Phase 3a)"
```

---

### Task 8: `cloud_code_worker` in agent_loop + 30 s registration

**Files:**
- Modify: `ai_bridge/agent_loop.py` (method inserted immediately BEFORE `    def _run_ab_comparison(self, run_id, cfg):` at line 3324; registration inserted immediately BEFORE the `self.scheduler.add_job(` whose first argument is `with_app_context(self._model_dispatch_worker),`)
- Test: `platform_v2/tests/test_cloud_code_lane.py` (`test_cloud_code_worker_is_defined_and_scheduled`)

**Interfaces:**
- Consumes: `cloud_code_lane.{JOB_TYPE, MODULE_ID, CAPABILITY, plan_worker_action, summarize_result}`; `department_dispatcher.dispatch(capability, prompt, module_id=, system_prompt=, model_override=)`.
- Produces: `bridge_jobs` rows move `pending → running → completed|failed|cancelled`, with `metadata.result` = `summarize_result(...)`.

- [ ] **Step 1: Add the method (before `def _run_ab_comparison`)**

```python
    def cloud_code_worker(self):
        """#6653 Phase 3a — drain approved cloud CODING jobs (the ask-first lane).

        Mirrors ab_compare_worker: claims bridge_jobs(job_type='cloud_code',
        status='pending') whose linked autonomy_approval_queue row resolved,
        dispatches the approved ones through the DHQ dispatcher with an explicit
        model_override (escalation_mode stays local_only — this is NOT
        auto-escalation), and stores the result on the job. Toggle via
        work:cloud_code_worker:enabled (work_control_service).
        """
        from services.work_control_service import is_enabled

        if not is_enabled("cloud_code_worker", default=True):
            return

        from services import cloud_code_lane as lane
        from database import get_db_cursor
        import json

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT j.id, j.status, j.metadata, "
                    "  EXTRACT(EPOCH FROM (NOW() - j.created_at)) AS age, "
                    "  a.status AS approval_status "
                    "FROM bridge_jobs j "
                    "LEFT JOIN autonomy_approval_queue a "
                    "  ON a.id = (j.metadata->>'approval_id')::int "
                    "WHERE j.job_type = %s AND j.status = 'pending' "
                    "ORDER BY j.created_at ASC LIMIT 10",
                    (lane.JOB_TYPE,),
                )
                pending = cur.fetchall()
        except Exception as e:
            logger.warning("cloud_code_worker fetch failed: %s", e)
            return

        # Reaper: a job claimed 'running' then orphaned by a worker restart must reach
        # a terminal state (same shape as the A/B lane's 15-minute reaper).
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE bridge_jobs SET status='failed', completed_at=NOW(), updated_at=NOW(), "
                    "error_message='worker_timeout' "
                    "WHERE job_type = %s AND status = 'running' AND updated_at < NOW() - INTERVAL '15 minutes'",
                    (lane.JOB_TYPE,),
                )
        except Exception as e:
            logger.warning("cloud_code_worker reaper failed: %s", e)

        for job in pending:
            action = lane.plan_worker_action(job["status"], job["approval_status"], float(job["age"] or 0))
            if action == "skip":
                continue
            job_id = job["id"]
            if action == "cancel":
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE bridge_jobs SET status='cancelled', cancelled_at=NOW(), updated_at=NOW(), "
                        "cancellation_reason=%s WHERE id=%s AND status='pending'",
                        (f"approval {job['approval_status'] or 'expired'}", job_id),
                    )
                continue
            # action == 'run': idempotent claim — another tick may have taken it.
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE bridge_jobs SET status='running', updated_at=NOW() "
                    "WHERE id=%s AND status='pending' RETURNING id",
                    (job_id,),
                )
                claimed = cur.fetchone()
            if not claimed:
                continue
            meta = job["metadata"] or {}
            try:
                from tools.department_hq.services.department_dispatcher import dispatch

                res = dispatch(
                    lane.CAPABILITY,
                    meta.get("prompt", ""),
                    module_id=lane.MODULE_ID,
                    system_prompt=meta.get("system_prompt") or None,
                    model_override=meta.get("model"),
                )
                summary = lane.summarize_result(res)
                status = "completed" if summary["success"] else "failed"
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE bridge_jobs SET status=%s, completed_at=NOW(), updated_at=NOW(), "
                        "error_message=%s, completed_steps=%s, failed_steps=%s, "
                        "metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb), '{result}', %s::jsonb) "
                        "WHERE id=%s",
                        (status, summary.get("error"), 1 if summary["success"] else 0,
                         0 if summary["success"] else 1, json.dumps(summary, default=str), job_id),
                    )
            except Exception as e:
                logger.warning("cloud_code_worker job %s failed: %s", job_id, e)
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE bridge_jobs SET status='failed', completed_at=NOW(), updated_at=NOW(), "
                        "error_message=%s WHERE id=%s",
                        (str(e)[:500], job_id),
                    )

```

- [ ] **Step 2: Register it (before the `_model_dispatch_worker` add_job)**

```python
        # #6653 Phase 3a: drains approved cloud CODING jobs (the ask-first lane).
        # Toggle via work:cloud_code_worker:enabled; no-ops with nothing pending.
        self.scheduler.add_job(
            with_app_context(self.cloud_code_worker),
            trigger=IntervalTrigger(seconds=30),
            id="cloud_code_worker",
            name="Agent Loop: Cloud Coding Lane Worker (#6653)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

```

- [ ] **Step 3: Compile + run the lane tests**

Run:
```bash
python3 -m py_compile /mnt/archie_brain/ai_bridge/agent_loop.py && echo "agent_loop parses"
docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_lane.py -q 2>&1 | tail -3
```
Expected: `agent_loop parses`; `16 passed`.

- [ ] **Step 4: Full PR-2 test sweep**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py tests/test_cloud_code_lane.py tests/test_internal_auth_scopes.py tests/test_dispatcher_stream_work.py tests/test_cloud_capability_allowlist.py tests/test_token_provenance.py -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/ai_bridge/agent_loop.py
git commit -m "feat(agent_loop): cloud_code_worker drains approved cloud coding jobs every 30s (#6653 Phase 3a)"
```

---

### Task 9: PR-2 — push, review, merge, deploy

**Files:** none new.

- [ ] **Step 1: Push + open PR-2**

```bash
git push -u origin feat/phase3-omniroute-lane
gh pr create --title "feat(phase3): OmniRoute contractor — served-model attribution + ask-first cloud coding lane (#6653 Phase 3a, PR-2)" --body "$(cat <<'EOF'
## Summary
- **Served-model attribution (3 layers):** `resolve_served_model`/`is_auto_router` in the generic adapter; `served_or_requested` at `_dispatch_to_contractor` (both branches) and the request_work builder. `model_used` is now the model that served the call — never `auto/*`; provenance (`served_model_resolved`, `routing_decision`) lands in `request_metadata`.
- **Ask-first cloud coding lane:** scope `cloud:code` (archie_comms), `POST /api/internal/cloud-code/run` (202, async) + `GET …/run/<id>`; `bridge_jobs` row + Tier-2 approval (Ship tab) linked by `metadata.approval_id`; `cloud_code_worker` (30 s) dispatches with an explicit `model_override`. `escalation_mode` stays `local_only` — this is not auto-escalation.
- Spec corrected: `is_cloud_proxy=false` (true would route via call_ollama_cloud).

## Test Plan
- [x] tests/test_served_model_attribution.py (19) · tests/test_cloud_code_lane.py (16) · tests/test_internal_auth_scopes.py (+5, table widened)
- [x] existing dispatcher/allowlist/provenance suites green
- [ ] live proof after deploy (plan Task 10)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```

- [ ] **Step 2: Register in Repair Bay + F.O.R.G.E. review (background), merge on clean APPROVE**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs; print(poll_open_prs())"
# backgrounded — F.O.R.G.E. takes 10+ minutes; a review reads the PR head at call time
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr(<PR-2 number>); print(r.get('ok'), r.get('verdict'), r.get('error'))"
```
When it reaches `reviewed`, merge ONLY on a clean APPROVE with no coverage demotion:
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import get_review, coverage_only_demotion
from tools.repair_bay.services.github_service import merge_pr
n = <PR-2 number>
s = (get_review(n) or {}).get('ai_summary') or ''
assert 'VERDICT: APPROVE' in s and not coverage_only_demotion(s), 'NOT a clean APPROVE:\n' + s[-400:]
print(merge_pr(n, method='squash', human_override=True))"
```
If F.O.R.G.E. returns REQUEST CHANGES, fix and re-review; never merge over it. If you push a fix after triggering a review, let that review finish, then re-run `review_pr` — the verdict must be against the head that merges.

- [ ] **Step 3: Deploy (bind-mounted code → pull main + restart)**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main
git log --oneline -1
docker compose restart archie_platform archie_scheduler
for i in $(seq 1 20); do c=$(docker exec archie_platform python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:3000/health', timeout=3).status)" 2>/dev/null); [ "$c" = "200" ] && break; sleep 6; done; echo "health=$c"
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.department_hq.services.department_dispatcher import served_or_requested; print('live helper:', served_or_requested({'model':'x/y'}, 'auto'))"
docker logs archie_scheduler --since 2m 2>&1 | grep -c "cloud_code_worker"
```
Expected: `health=200`; `live helper: x/y`; the scheduler log mentions `cloud_code_worker` ≥ 1 (job registered).

---

### Task 10: Live proof (3a acceptance) + Dev HQ

**Files:** none.

- [ ] **Step 1: Coding-lane round trip from inside `archie_comms`**

```bash
docker exec -i archie_comms python3 - <<'PY'
import os, json, urllib.request as u, urllib.error as e
BASE, KEY = os.environ.get("PLATFORM_URL", "http://archie_platform:3000"), os.environ["INTERNAL_API_KEY"]
def call(method, path, body=None):
    req = u.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None, method=method,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try: r = u.urlopen(req, timeout=20); return r.status, json.loads(r.read())
    except e.HTTPError as ex: return ex.code, json.loads(ex.read() or b"{}")
print(call("POST", "/api/internal/cloud-code/run", {"prompt": "Write a Python fizzbuzz(n) with a docstring. Reply with code only."}))
PY
```
Expected: `(202, {'success': True, 'status': 'pending_approval', 'job_id': N, 'approval_id': M})`. A Telegram Approve/Deny arrives and the item shows under DHQ → Approvals → **Ship**. **Approve it.**

- [ ] **Step 2: Poll until terminal (≤ 2 worker ticks after approval)**

```bash
docker exec -i archie_comms python3 - <<'PY'
import os, json, time, urllib.request as u
BASE, KEY = os.environ.get("PLATFORM_URL", "http://archie_platform:3000"), os.environ["INTERNAL_API_KEY"]
N = int(input("job_id: "))
for _ in range(12):
    r = json.load(u.urlopen(u.Request(f"{BASE}/api/internal/cloud-code/run/{N}", headers={"Authorization": f"Bearer {KEY}"}), timeout=15))
    print(r["status"], (r.get("result") or {}).get("model_used"), (r.get("result") or {}).get("served_model_resolved"))
    if r["status"] in ("completed", "failed", "cancelled"): print(json.dumps(r, indent=1)[:800]); break
    time.sleep(15)
PY
```
Expected: `completed`, a concrete `model_used` (never `auto…`), `served_model_resolved: True`, a code response.

- [ ] **Step 3: The accounting spine — read it back**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, model_used, provider, success, module_source,
       request_metadata->>'served_model_resolved' AS resolved,
       LEFT(request_metadata->>'routing_decision', 60) AS decision
FROM task_execution_log
WHERE provider IN ('omniroute','contractor:omniroute') ORDER BY id DESC LIMIT 5;" 2>&1
```
Expected: the row for the coding job with `module_source='cloud_code_lane'`, `provider='omniroute'`, a concrete `model_used`, `resolved = true`.

**GATE:** if `resolved` is `false` (the gateway did not echo a concrete served model) → set a concrete default now and re-run Step 1:
```bash
docker exec archie_database psql -U archie -d archie -c "UPDATE contractor_providers SET default_model='<a concrete id from Task 2 Step 9>', updated_at=NOW() WHERE provider_key='omniroute' RETURNING default_model;"
```
and record the raw `decision` string in the Dev HQ follow-up "parse X-OmniRoute-Decision" so a later commit can derive the served model from the header.

- [ ] **Step 4: A/B lane — OmniRoute is selectable and a run records the real model**

In the browser (`http://192.168.1.200:3000/tools/agent-academy` → A/B Testing): confirm **OmniRoute (self-hosted gateway)** is in the cloud model list; run local `qwen2.5:7b` vs OmniRoute on a short coding prompt; approve the Telegram prompt; wait for completion. Then:
```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, model_used, provider, request_metadata->>'served_model_resolved' AS resolved
FROM task_execution_log WHERE module_source LIKE 'agent_academy:ab_compare%' ORDER BY id DESC LIMIT 4;" 2>&1
```
Expected: the OmniRoute side shows a concrete `model_used` and `resolved = true`.

- [ ] **Step 5: Sovereignty negatives (must FAIL closed)**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.department_hq.services.department_dispatcher import get_dispatcher
d = get_dispatcher()
print('code ->', d._cloud_capability_allowed('code'))
print('fact_check ->', d._cloud_capability_allowed('fact_check'), '| bias_analysis ->', d._cloud_capability_allowed('bias_analysis'), '| conversation ->', d._cloud_capability_allowed('conversation'))"
docker exec archie_database psql -U archie -d archie -tAc "SELECT value FROM platform_settings WHERE key='escalation_mode';"
```
Expected: `code -> True`; the other three `False`; `local_only`.

- [ ] **Step 6: Contractors tab + Token Economy**

Browser: DHQ → Contractors lists **OmniRoute**; master toggle still OFF (Sovereign). Consciousness → Token Economy: the new rows count as **cloud** (provider `omniroute` is not on `LOCAL_PROVIDERS`).

- [ ] **Step 7: Dev HQ + handoff**

- `mcp__archie__add_work_note(task_id=6653, note="Phase 3a SHIPPED: PR-1 (gateway+seed) + PR-2 (attribution+coding lane) merged+deployed; live proof passed — coding-lane job completed with a concrete model_used and served_model_resolved=true, the A/B run records the served model, fact_check/bias_analysis/conversation refused fail-closed, escalation_mode=local_only. 3b (paid keys) BLOCKED on the V.I.G.I.L. audit.")` — leave #6653 open; Task 12 completes it.
- `mcp__archie__log_decision(title="Phase 3a: OmniRoute contractor + served-model attribution + ask-first coding lane", decision="OmniRoute is ONE contractor_providers row with is_cloud_proxy=false (true would route through call_ollama_cloud and bypass the gateway). task_execution_log.model_used records the SERVED model at all three sites (_call_openai_compatible, _dispatch_to_contractor x2, request_work builder) via is_auto_router/resolve_served_model/served_or_requested; an unresolved auto-router records the requested id plus served_model_resolved=false. The coding lane rides an explicit model_override plus a Tier-2 approval linked on bridge_jobs.metadata.approval_id (job status 'pending', never 'pending_approval', so the Approvals tab never double-lists); escalation_mode stays local_only.", context="Master-command Phase 3 (#6653). Owner decisions 2026-09-09: A/B lane + gated coding lane; keyless plumbing first, paid keys after V.I.G.I.L.", task_id=6653)`
- `mcp__archie__create_task` ×3 follow-ups: "OmniRoute container read_only+tmpfs hardening (paths from docker diff)", "parse X-OmniRoute-Decision into served model (if resolved=false ever observed)", "per-call compression opt-in for the coding lane (needs extra_headers through call_external)".
- Rewrite `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` state: Phase 3a done, 3b pending V.I.G.I.L.

---

### Task 11 (optional, self-contained): honest `worker_type` for contractor rows

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_dispatcher.py` (`_dispatch_to_contractor` metadata, both branches)
- Test: `platform_v2/tests/test_served_model_attribution.py`

`_log_execution` derives `worker_type = "contract" if meta.get("is_cloud") else "internal"` (line 4798), but contractor metadata only sets `is_cloud_proxy`, so contractor rows log `worker_type='internal'`. Token Economy is provider-based (ADR-037) so this is cosmetic — do it only if the owner wants K.I.N./worker-type views honest.

- [ ] **Step 1: Failing test** — append:
```python
def test_contractor_results_are_flagged_is_cloud_for_worker_type(monkeypatch):
    from tools.department_hq.services import department_dispatcher as dd
    disp = dd.DepartmentDispatcher()
    monkeypatch.setattr(disp, "_cloud_capability_allowed", lambda cap: True)
    monkeypatch.setattr(disp, "_cloud_budget_ok", lambda *a, **k: True)
    monkeypatch.setattr(ep, "call_external", lambda **kw: {"success": True, "response": "ok", "model": "x/y",
                                                           "served_model_resolved": True, "provider": "omniroute"})
    contractor = {"provider_key": "omniroute", "display_name": "OmniRoute", "default_model": "x/y",
                  "is_cloud_proxy": False, "tier_position": 9}
    assert disp._dispatch_to_contractor(contractor, "p", "code", "m").metadata["is_cloud"] is True
```
- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q -k is_cloud 2>&1 | tail -3`
Expected: FAIL with `KeyError: 'is_cloud'`.

- [ ] **Step 3: Add the flag to BOTH `metadata={` dicts in `_dispatch_to_contractor`**

In each of the two `metadata={` dicts (cloud-proxy branch and standard branch), add this line directly after the `"escalation": "contractor_capability",` entry:
```python
                            "is_cloud": True,  # _log_execution -> worker_type='contract' (#6653)
```

- [ ] **Step 4: Run the attribution file and the provenance suite**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py tests/test_token_provenance.py -q 2>&1 | tail -3`
Expected: all pass (`20 passed` in the attribution file).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/tools/department_hq/services/department_dispatcher.py /mnt/archie_brain/platform_v2/tests/test_served_model_attribution.py
git commit -m "fix(dispatcher): contractor results carry is_cloud so worker_type logs 'contract' (#6653)"
```
(Fold into PR-2 if it is still open; otherwise open its own PR through the same review/merge flow as Task 9.)

---

### Task 12: Phase 3b — V.I.G.I.L. security gate, then paid keys (separate PR; BLOCKED until the verdict)

**Files:** ROOT `.env` (untracked) · OmniRoute dashboard config · a Dev HQ task.

- [ ] **Step 1: Delegate the audit to V.I.G.I.L. (do NOT proceed until it lands in `work_notes`)**

```python
mcp__archie__delegate_task(
  capability="security",
  reason=("Security review of OmniRoute 3.8.50 (self-hosted at container 'omniroute', image diegosouzapw/omniroute:3.8.50) BEFORE any paid credential is configured (#6653 Phase 3b). "
          "Deliver: (1) dependency audit of the Node project (npm audit / lockfile CVEs at that tag); (2) egress behaviour — enumerate every outbound destination the container contacts at rest and under one /v1/chat/completions call (background services such as pricing/model-catalog sync, telemetry, update checks), and state whether anything other than upstream provider calls leaves; "
          "(3) confirm API keys are stored encrypted at rest (API_KEY_SECRET / STORAGE_ENCRYPTION_KEY) and never appear in logs or outbound requests other than to their own provider; (4) a go/no-go verdict."),
  delegation_source="claude",
)
```

- [ ] **Step 2: On a GO verdict only — connect curated PAID providers**

In the dashboard (tunnel, Task 2 Step 6): connect the chosen paid providers, each key entered ONLY in the OmniRoute dashboard (never in the platform `.env`). Never connect a provider marked `avoid` on `/dashboard/free-tiers`. Compression stays off.

- [ ] **Step 3: Re-run Task 10 Steps 1–5** (attribution + guards must still hold with paid upstreams).

- [ ] **Step 4: Dev HQ** — `mcp__archie__complete_task(6653, notes="3a+3b complete; V.I.G.I.L. verdict <id>; paid providers <list>")`, `mcp__archie__log_decision` for 3b, handoff rewrite.

---

## Deferred (explicitly not in this plan)

- `read_only: true` + tmpfs for the `omniroute` container (needs the `docker diff` paths from Task 2 Step 5).
- Parsing `X-OmniRoute-Decision` into the served model (only needed if `served_model_resolved=false` is ever observed; the raw header is already stored).
- Per-call compression opt-in for coding (needs an `extra_headers` path through `call_external` → `_call_openai_compatible`).
- A cockpit UI for the coding lane (Phase 4). `vision` on the cloud allowlist (held for owner sign-off since Phase 1b). Any change to `escalation_mode`.

## Execution record (2026-09-09)

- PR-1 #3271 → `a828a8a7d` (compose service + seed script; docs reverted out of it after a false hardening claim).
- PR-2 #3272 → `3974653e0` (served-model attribution at 3 sites; `cloud:code` scope; run/poll endpoints; `cloud_code_worker`). F.O.R.G.E. original APPROVE, coverage-demoted (2/10 files read) → discharged by an independent full read of the 7 dropped files (CLEAR, 0 Critical/Important).
- PR-3 #3273 → `9705f4e9c` (executor acknowledgement for `cloud_code_dispatch` + `cloud_comparison`; planners accept `executed`/`failed`) — found by the live proof, clean APPROVE.
- Live proof (21:58 EDT): job 1198308 `pending → running → completed` in 30 s; `model_used=big-pickle`, `served_model_resolved=true`, `routing_decision="strategy=single; provider=oc; latency_ms=14334"`, 454/922 tokens; `task_execution_log` 1542648 `provider=omniroute module_source=cloud_code_lane`. Sovereignty: `code→True`, `fact_check/bias_analysis/conversation→False`, `escalation_mode=local_only`.
- Follow-ups: #6664 hardening · #6665 fleet-first spurious failed row per run · #6666 approve-route 500 · #6667 X-OmniRoute-Decision parser · #6668 per-call compression · #6669 L8101 attribution + SQL tests · #6670 is_cloud flag. Phase 3b gate: V.I.G.I.L. audit #6671 — paid keys only on GO.
