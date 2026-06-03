# P.R.O.B.E. — Standalone QA Suite Scope & Implementation Blueprint

_Authored 2026-06-02 (session e60c95da). Grounded against live code + live probes._
_Companion KB: mistake_learned #270283 (the empty-site bug), vault_note #270284 (DB topology)._

## 1. Why this exists (and the one non-negotiable rule)

Tonight `legal.kytranempowerment.com` and `civic.kytranempowerment.com` both served a **completely empty site** after login — page rendered (200), `/api/health` was 200, but **every `/api/*` data route 404'd** (gunicorn ran `app:app`, skipping the `create_app()` factory that registers the data blueprints).

**P.R.O.B.E. did not catch it — because the existing suite cannot.** The current `watch-legal-e2e.yaml` checks only:
```
/  [200,302] · /login [200,302] · /api/health [200,404] · /dashboard [200,302,401]
```
It even *accepts* `/api/health` = 404. **A totally empty legal site passes this suite green.** The other `watch-*-e2e` / `*-smoke` suites have the same shape.

> **THE RULE (KB #270283):** Every standalone suite MUST assert **data-nonempty** on its real data routes — the data route returns 200 **and** a non-empty payload (array length ≥ 1 / a count > 0). Health-200 + page-load-200 is necessary but **never sufficient**. This single check class is the entire point of this effort.

## 2. The framework (verified, `qa_spec_runner.py`)

- **Suites = YAML** at `platform_v2/qa_suites/<name>.yaml`, upserted into the `qa_test_suites` table (JSONB `spec`) by an idempotent `platform_v2/scripts/register_<name>_qa_suite.py` (match by `suite.name`).
- **Run:** MCP `run_qa_suite` → `services/qa_service.py:run_suite()` → `services/qa_spec_runner.py:execute_spec()`. Executes **inside the `archie_platform` container** using `requests`.
- **Reach:** proven to hit **public URLs through Caddy** (e.g. `wtf-consumer-smoke` → what-the-fact.com), the **mesh** (`100.64.0.x`), and `localhost:3000`. So suites target each standalone's **public HTTPS URL** directly — no SSH in the suite itself.
- **Results:** `qa_test_runs` + `qa_test_results` tables → Repair Bay **P.R.O.B.E./QA** tab.
- **Auth:** `ARCHIE_QA_TOKEN` env (fast path) or CSRF web login; session reused across a batch.

### Supported `expect.*` assertions TODAY
| Test type | Keys |
|---|---|
| `api` | `status`, `json_contains` (dict **exact key==value** only), `max_response_ms` |
| `page_load` | `status`, `title_contains`, `body_contains`, `max_load_ms` |

## 3. ⛔ Linchpin: the framework cannot express "non-empty" yet — add it first

`json_contains` does `resp.json().get(key) == value` (exact equality, dict-only). It **throws on a top-level JSON array** (`.get()` on a list) and **cannot** assert "array non-empty" or "count > 0". **Without a new assertion, the data-nonempty check is impossible to write.**

**Minimal additive patch** to `platform_v2/services/qa_spec_runner.py` `_run_api_test()`, inserted right after the `json_contains` block (~line 675), before the `max_response_ms` block:

```python
        # data-nonempty assertions (standalone coverage — KB #270283)
        #   expect.json_nonempty: true  -> JSON must be a non-empty list or dict
        #   expect.min_items: N         -> top-level JSON array (or dict) length >= N
        #   expect.json_gt: {key: N}    -> resp_json[key] > N  (numeric, for stats dicts)
        if expect.get("json_nonempty") or expect.get("min_items") is not None or expect.get("json_gt"):
            try:
                rj = resp.json()
            except ValueError:
                result["assertions"]["json_parse"] = "fail"; result["status"] = "fail"
                result["error_message"] = (result.get("error_message") or "") + " Response is not valid JSON."
                rj = None
            if rj is not None:
                if expect.get("json_nonempty"):
                    ok = bool(rj)
                    result["assertions"]["json_nonempty"] = "pass" if ok else "fail"
                    if not ok:
                        result["status"] = "fail"
                        result["error_message"] = (result.get("error_message") or "") + " Expected non-empty JSON."
                mi = expect.get("min_items")
                if mi is not None:
                    n = len(rj) if isinstance(rj, (list, dict)) else 0
                    if n < mi:
                        result["assertions"]["min_items"] = "fail"; result["status"] = "fail"
                        result["error_message"] = (result.get("error_message") or "") + f" Expected >= {mi} items, got {n}."
                    else:
                        result["assertions"]["min_items"] = "pass"
                jg = expect.get("json_gt")
                if jg and isinstance(rj, dict):
                    for k, thr in jg.items():
                        av = rj.get(k); ok = isinstance(av, (int, float)) and av > thr
                        result["assertions"][f"json_gt_{k}"] = "pass" if ok else "fail"
                        if not ok:
                            result["status"] = "fail"
                            result["error_message"] = (result.get("error_message") or "") + f" Expected {k} > {thr}, got {av!r}."
```
Pure addition, backward-compatible. **This patch ships first; the suites depend on it.**

## 4. Coverage matrix (real routes, verified via grep/probe this session)

| Standalone | Public URL | Container / transport | Existing suite | Confirmed data routes | State |
|---|---|---|---|---|---|
| **legal_watch** | legal.kytranempowerment.com | `kytran_legal_api` @ boston-2 (mesh) | `watch-legal-e2e` | `/api/stats`✅(dict counts), `/api/events`✅(array), `/api/regulations`✅(array), `/api/ethics/stats`✅ | **Confirmed live** (`/api/stats`→1021/1975/631/390). `/api/scc/stats`={no_data} → do NOT assert. |
| **civic_watch** | civic.kytranempowerment.com | `kytran_watch_api` @ outpost-us (mesh) | `watch-civic-e2e` | `/api/events`, `/api/contracts`, `/api/lobbying/overview`, `/api/lobbying/top-clients`, `/api/data` | routes confirmed by grep; **not** `/api/stats` (doesn't exist) |
| **market_watch** | market.kytranempowerment.com | `kytran_market_api` @ outpost-us | `watch-market-e2e` | `/api/analysis/cycles`, `/api/alerts`, `/api/analysis` (much is **per-user** — pick a public/aggregate route) | routes by grep; verify which are non-auth |
| **gov_watch** | gov.kytranempowerment.com | `kytran_gov_watch` @ outpost-us (DB=`gov_watch_db`) | `watch-gov-e2e` | `/api/ag/reports`, `/procure/api/proactive/recent`, `/procure/api/proactive/trends` (35k+ records) | proactive routes are the strong non-empty target |
| **wtf_consumer** | what-the-fact.com | container @ outpost-us (**name TBD** — `wtf-consumer` not found; verify) | `wtf-consumer-smoke` | feed/cluster routes (verify real names) | container name + routes need confirming |
| **wtf_tech** | what-the-fact.tech | container @ outpost-us | **none** | — | **pure gap — create suite** |
| **kso** | server.kytranempowerment.com | `kytran-system-operations` @ hub | `kso-smoke`/`kso-e2e` | `/api/apps/catalog`, `/api/apps/installed`, `/api/audit-log`, `/api/alerts/unified` | routes by grep |
| **kbs** | business.kytranempowerment.com | `kbs_app` @ hub | `kbs-*` | `/api/accounts`, `/api/analytics`, `/api/appointments`, `/api/plugins` (mostly **per-user** — pick aggregate) | routes by grep |
| **creed** | creed.kytranempowerment.com | `kytran_creed` @ hub | **none** | `/api/v1/scores`✅(public, `{overall,grade,by_category}`), `/api/public/score`✅, `/api/platform-stats`, `/api/ethics/by-department` | **public no-auth → easiest, highest-value non-empty target** |
| **media_hub** | media.kytranempowerment.com | `mediahub_app` @ hub | `media-hub-standalone-smoke` | `/api/discover`, `/api/calendar/upcoming`, `/api/downloads`, `/api/library` | routes by grep |

## 5. Per-suite check template (apply to each)

1. `home-loads` — `GET /` → status [200,302] (low)
2. `health-ok` — `GET /api/health` → status [200] + `json_contains:{status: ok}` (high; **drop the 404 acceptance**)
3. `dashboard-renders` — `page_load /dashboard` → status [200] + `body_contains: "<product word>"` (medium)
4. **`<route>-nonempty` — for EACH confirmed data route → status [200] + `min_items: 1` (arrays) or `json_gt:{<count_key>: 0}` (stat dicts) — `critical: true`** ← the point
5. `auth-gate` — owner (ARCHIE_QA_TOKEN) reaches a gated route 200; anonymous gets 302/401 (high)
6. `caddy-public-tls` — the public URL responds 200 with valid cert (implicit in every https `api` test)

## 6. Ready-to-register: upgraded `watch-legal-e2e.yaml`

```yaml
suite:
  name: "watch-legal-e2e"
  description: "Legal Watch — availability, login gate, AND data-nonempty (anti-empty-site, KB #270283)"
  base_url: "https://legal.kytranempowerment.com"
tests:
  - { name: "home-loads",        type: api, method: GET, path: /,            skip_auth: true, expect: { status: [200, 302] } }
  - { name: "health-ok",         type: api, method: GET, path: /api/health,  skip_auth: true, expect: { status: [200], json_contains: { status: "ok" } } }
  - { name: "dashboard-renders", type: page_load,        path: /dashboard,   skip_auth: true, expect: { status: [200], body_contains: "Legal" } }
  # --- data-nonempty: these FAIL on an empty site (require the §3 patch) ---
  - { name: "stats-has-data",    type: api, method: GET, path: /api/stats,        skip_auth: true, critical: true, expect: { status: [200], json_gt: { total_events: 0, regulations: 0 } } }
  - { name: "events-nonempty",   type: api, method: GET, path: /api/events,       skip_auth: true, critical: true, expect: { status: [200], min_items: 1 } }
  - { name: "regs-nonempty",     type: api, method: GET, path: /api/regulations,  skip_auth: true, critical: true, expect: { status: [200], min_items: 1 } }
  - { name: "ethics-present",    type: api, method: GET, path: /api/ethics/stats, skip_auth: true, expect: { status: [200], json_gt: { total: 0 } } }
```
Register: `docker exec archie_platform python3 /app/scripts/register_watch_legal_e2e_qa_suite.py` (copy an existing `register_*_qa_suite.py`; it upserts by `suite.name`). Then `run_qa_suite('watch-legal-e2e')`.

## 7. Scheduling (per `.claude/rules/module-work-pattern.md`)

Don't run suites synchronously on the web thread. Add a scheduled job (e.g. `probe_standalone_suites`, hourly or 4×/day, `timezone="America/Toronto"`) in `ai_bridge/agent_loop.py` that dispatches each suite run to **P.R.O.B.E.** via `delegate_task(capability='run_qa_suite', args={'suite_name': '<name>'}, delegation_source='automation')` (known-tool shortcut → `qa_service.run_suite`, no LLM). On a `critical` failure → Telegram alert (the empty-site early-warning you didn't have tonight).

## 8. Security / transport notes

- Suites hit **public HTTPS via Caddy** from the container — no SSH, no LAN `192.168.1.200`, no raw mesh in YAML.
- `auth-gate` checks use `ARCHIE_QA_TOKEN` (already supported); the tier gate itself depends on each watch app's `AC_API_URL=http://100.64.0.4:3000` (mesh) — a separate runtime env, not a suite concern, but document it as a prerequisite for the `auth-gate` check to pass for the owner.
- No secrets in YAML. Never assert exact volatile counts (use `> 0` / `min_items`, not `== 1021`).

## 9. Rollout order

1. **§3 framework patch** (`json_nonempty`/`min_items`/`json_gt`) — everything depends on it. One PR, with a unit test.
2. **legal + civic** upgraded suites (both just fixed tonight; highest value — these are the regressions to guard). Register + run, confirm green.
3. **creed** (public APIs, trivial, high signal) + **gov** (`/procure/api/proactive/*`).
4. **kso, kbs, media_hub, market, wtf** — confirm real non-auth data routes per app (several are per-user; pick an aggregate/public route), fill `wtf_tech` (no suite today) + verify the wtf container names.
5. Wire the scheduled `probe_standalone_suites` job + critical-fail Telegram alert.

## 10. Open questions

- **wtf containers:** `wtf-consumer`/`wtf-tech` weren't found by name on outpost-us — confirm the real container names + their data routes before writing those suites.
- **market / kbs:** most routes are per-user (watchlists, accounts). Which aggregate/public route is a stable non-empty signal? (or run authed as a seeded QA user.)
- **auth-gate depth:** assert just the gate (200 vs 302) — or also that the owner sees `has_access:true` from `/tools/account-center/api/access/check`? The latter would have caught the earlier "subscription not recognized" issue too.
