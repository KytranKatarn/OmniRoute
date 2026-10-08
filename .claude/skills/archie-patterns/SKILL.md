---
name: archie-patterns
description: Quick reference for A.R.C.H.I.E. platform code patterns — Bridge dispatcher imports, LCARS modal classes, SaaS per-user data isolation, agent budget increment/decrement pair, Blueprint template_folder, DB table gotchas. Invoke when writing new code, creating a module, touching dispatch/agent/translation/budget code, or any time you hear "how do I" / "what's the convention for".
---

# A.R.C.H.I.E. Patterns — Code Conventions Cheat Sheet

Canonical patterns for the platform. Match these before writing new code — saves re-learning on every session.

## Bridge dispatch (ADR-013)

All LLM inference routes through Dept HQ dispatcher. NEVER call Ollama directly from modules (except `/api/tags` + `/api/ps` for status).

```python
# Canonical (new code):
from tools.department_hq.services.department_dispatcher import dispatch_json, get_dispatcher

result = dispatch_json(
    capability="translate",          # not task=, not preferred_model=
    prompt=prompt,
    module_id="your_module",
)
# result is a dict (parsed JSON), None on failure. NOT an object with .success/.response.

# Inside tools/department_hq/services/ — use relative:
from .department_dispatcher import get_dispatcher
```

**Forbidden:** `from ai_bridge.bridge_dispatcher import ...` — K.I.N. guardrail blocks this on new files.

## Agent budget increment/decrement pair (post-2026-04-18)

Every increment needs a paired decrement or the agent eventually gets budget-blocked:

```python
# Job-tracked dispatch — matched automatically:
dispatcher.create_job(...)          # increments budget
dispatcher.complete_job(job_id, ...) # decrements budget (added in commit 5a003831)

# Immediate dispatch (no job_id) — request_work() pairs internally:
result = dispatcher.request_work(capability=..., prompt=..., json_mode=True)
# increment + decrement happen automatically, net zero unless in flight
```

If you write NEW code that calls `agent_service.increment_budget()` directly, you MUST pair it with `agent_service.decrement_budget()` or use `try/finally` to guarantee it fires.

Safety net: `fleet_jobs.budget_reconciliation` runs hourly.

## LCARS modal pattern (ADR)

```html
<bm-overlay class="bm-overlay">
  <bm-shell class="bm-shell" style="--bm-accent: #00bcd4;">
    <bm-frame class="bm-frame">
      <bm-content class="bm-content">
        <bm-header>...</bm-header>
        <bm-body>...</bm-body>
        <bm-footer>...</bm-footer>
      </bm-content>
    </bm-frame>
  </bm-shell>
</bm-overlay>
```

Reference: `bridge.html` lines 9209-9249. Set `--bm-accent` per module (purple=Consciousness, teal=Archie, orange=F.O.R.G.E., red=alert).

## SaaS module — per-user data isolation

EVERY table + query must be scoped by `user_id`. No global/shared content tables.

```python
cur.execute(
    "SELECT * FROM crm_customers WHERE user_id = %s AND id = %s",
    (current_user.id, customer_id)
)
```

Forgetting this = cross-tenant data leak. Non-negotiable.

## Blueprint with templates subdir (ADR-021)

If your module has `templates/` subdir, set `template_folder` explicitly:

```python
# tools/media_studio/__init__.py
bp = Blueprint("media_studio", __name__,
               template_folder="templates",   # REQUIRED if templates/ exists
               static_folder="static")
```

Without this → `TemplateNotFound` on first render. Use `tools/` prefix in render_template paths.

## DB table gotchas

| Table | Gotcha |
|---|---|
| `unified_projects` | `name` NOT `title`; `slug` NOT NULL |
| `unified_tasks` | `priority` is INTEGER (1-10) |
| `project_decisions` | `decision`/`context` NOT `description`/`rationale` |
| `telegram_users` | NOT `telegram_linked_accounts` |
| `system_notifications` | CHECK constraint: info/warning/error/success/reminder/alert/briefing only |
| `agents` | `worker_type` (ai/internal/contractor), NOT `agent_type`; `model` NOT NULL |
| `translations` | UNIQUE (source_label, key, language) — migration 323 |
| `translation_gaps` | UNIQUE NULLS NOT DISTINCT (source, gap_type, language, key, suggested_key, file_path, line_number) — migration 322 |
| JSONB fields | Wrap values with `psycopg2.Json(dict)` when inserting |

## Module registration (mandatory pair)

When adding a new module:
1. Add to `platform_v2/rbac.py` — Permission entry + role mapping
2. Add to `platform_v2/module_registry.py` — ModuleCategory + metadata
3. Both required — missing either = module doesn't show up in dashboard

## CSS prefixes per module

| Module | Prefix | Accent |
|---|---|---|
| Consciousness | `cs-` | purple #8b5cf6 |
| Dev HQ | `devhq-` | green |
| Dept HQ | `dh-` | teal |
| Backup Manager | `bm-` | (overloaded with modal classes, careful) |
| Repair Bay | `rb-` | orange |
| Security Network | `sn-` | red |
| Account Center | `ac-` | blue |

Always use `var(--archie-*)` from `lcars-tokens.css` for colors. Don't hardcode.

## Ollama model naming convention

| Suffix | Meaning |
|---|---|
| `:cloud` | External API (minimax, anthropic) — skip local load |
| `:cpu` | Force CPU inference via `num_gpu 0` Modelfile |
| `:latest` | Default pull |
| (none / `:Nb`) | GPU-preferred, param size in name |

Example: `mistral-cpu` (CODEX+ROSETTA dual-lane pattern) is a Modelfile variant of `mistral:7b` with `PARAMETER num_gpu 0`.

## Verifying inside an image-baked, read-only container

Product containers `COPY` their code (a merge is not a deploy), and some run
`read_only: true` — so the live tree is NOT what the process executes, and
`docker cp` into the container fails with *"container rootfs is marked read-only"*
(only the `/tmp` tmpfs is writable, and `docker cp` cannot target it). Recipe
used for PRs #3751/#3752 — embed the edited source over stdin and load it with
package context so relative imports still resolve:

```bash
B64=$(base64 -w0 <edited-file>) && docker exec -i -e B64="$B64" <container> python3 - <<'EOF'
import base64, os, sys, asyncio, types
sys.path.insert(0, '/app')
src = base64.b64decode(os.environ['B64']).decode()
mod = types.ModuleType('mcp_server.tools.<module>_new')  # unique name, no clash
mod.__package__ = 'mcp_server.tools'                     # enables `from . import ...`
sys.modules[mod.__name__] = mod
exec(compile(src, '<module>_new.py', 'exec'), mod.__dict__)
r = asyncio.run(mod.<handler>_handler({...}))            # handlers are async
print(r)
EOF
```

Notes:

- `register_tool` calls firing at import time are harmless in a throwaway process.
- Container env (DB_HOST/DB_USER/DB_PASSWORD_FILE) is the point: you test with the
  same config and grants the running process has (`archie_mcp_gateway` connects as
  **`codex_ro`** — test grants there, never as `archie`).
- `archie_mcp_gateway` is `FROM archie_brain-archie_platform:latest` and has **no
  repo mount**: rebuild the base image first (or you serve stale code looking
  healthy), and git commands inside it return empty — tools must report n/a, not
  a fake clean status.
- **Never "verify" by reading the file inside the container.** Prove it where it
  executes (`.claude/rules/deploy-provenance.md`).

## When in doubt

- Search KB: `mcp__archie__search_knowledge` with category=architecture or the module name
- Read existing code in a neighbor module — the pattern is almost always there already
- Per Rule #2: **Read Before Building** — answer usually exists
