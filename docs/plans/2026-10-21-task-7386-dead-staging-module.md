# Dev HQ #7386 — the fix is DELETE, not MIGRATE (patch ready to apply)

**Status: the work is done and verified, but it is OUT OF THIS LANE'S SCOPE.**
`archie_engine_staging/` is not in the opencode lane's `allowed_paths`
(`config/agents/opencode.yaml`), and the scope guard confirms it refuses the
path:

```
archie_engine_staging/command_router.py  -> ['archie_engine_staging/command_router.py']   # REFUSED
archie_engine_staging/session.py         -> ['archie_engine_staging/session.py']          # REFUSED
scripts/check_agent_single_writer.py     -> []                                            # allowed
```

So this lane cannot land the change. The patch is prepared and verified, ready
for the owning lane (or the owner) to apply with one command.

## The finding that changes the task

The task was written as "migrate `archie_engine_staging/command_router.py` off
raw agents writes, the stale dispatch import, and a raw `/api/chat` fallback".
**It does not need migrating — it needs deleting.**

Every `.py` in the repository outside the package was scanned for importers:

| file | live? | importers |
|---|---|---|
| `archie_engine_staging/intent_parser.py` | **LIVE** | `platform_v2/tools/department_hq/services/orchestration_engine.py` (a lazy `_get_intent_parser()`) |
| `archie_engine_staging/session.py` | **DEAD** | none |
| `archie_engine_staging/command_router.py` | **DEAD** | none |

`session.py` imported `command_router`, and nothing imported `session` — so
`command_router.py` (1,157 lines) was reachable only from another dead module.
It is the file carrying all three guardrail violations, and it is dead code.

**The fix is therefore smaller and safer than the task assumed:** delete the two
dead files, keep `intent_parser.py` untouched, and remove the three allowlist
entries that exist only because of the deleted file.

## Why the order matters

The three allowlist entries in `scripts/check_agent_single_writer.py` must be
removed **in the same commit** as the deletion. Removing them while
`command_router.py` still exists would make the guardrail fire on every commit
touching that file — for *every* lane, including the one doing the migration.

## Applying it

The patch is stored **base64-encoded** (`.patch.b64`) on purpose: the repo's
pre-commit `trailing-whitespace` and `end-of-file-fixer` hooks rewrite a raw
`.patch` file, and that rewrite **corrupts it** — verified: the rewritten patch
silently fails to delete the two files, so it applies "successfully" and leaves
the dead code in place. Base64 has no trailing whitespace to strip, so it
survives the hooks byte-for-byte.

```sh
cd /mnt/archie_brain
base64 -d docs/plans/2026-10-21-task-7386-dead-staging-module.patch.b64 > /tmp/7386.patch
git apply --check /tmp/7386.patch    # verify first
git apply /tmp/7386.patch
```

The patch is against `origin/main` and was dry-run verified to apply cleanly
(`git apply --check`), and was verified to produce the intended result: the two
dead files gone, `intent_parser.py` untouched.

## What was verified (all of it, before handing over)

- **The guardrail still WORKS.** With the entries removed, the guard was run
  against three deliberate violations and fired on every one, with the
  single-writer guidance intact:
  - `cur.execute("UPDATE agents SET department = %s WHERE id = %s", ...)` →
    *"K.I.N. single-writer guardrail: raw agents-table mutation detected"*
  - `from ai_bridge.bridge_dispatcher import get_dispatcher` → fired
  - `f"{base}/api/chat"` → fired
- **The guardrail is CLEAN** on the tree with the deletions applied
  (exit 0).
- **The live importer still works.** `from archie_engine_staging.intent_parser
  import IntentParser` imports and constructs fine after the deletions — that
  file is untouched by the patch.
- **The deleted modules are genuinely unreachable.** Both now raise
  `ModuleNotFoundError`, and nothing in the repository referenced them.
- The patch removes 1,613 lines and adds none.

## The three entries this removes

| Allow-list | What it allowed, and why it is no longer needed |
|---|---|
| `ALLOWED_AGENTS_PATHS` | a raw `UPDATE agents SET department` in the deleted file |
| `ALLOWED_DISPATCHER_PATHS` | `from ai_bridge.bridge_dispatcher import ...` in the deleted file |
| `_API_GENERATE_ALLOWLIST` | `f"{self.ollama_url}/api/chat"` — a direct Ollama call used as a dispatcher fallback — in the deleted file |

Each entry's comment already said "remove this entry when that migration
lands" and carried task **#7386**. This is that step.

## One thing this patch does NOT fix — and should not

`archie_engine_staging/intent_parser.py` — the **live** file — has the *same*
stale dispatcher import, on its line 21:

```python
from ai_bridge.bridge_dispatcher import get_dispatcher as _get_dispatcher
```

It is **not** in any allow-list, so the guard already reports it today
("K.I.N. architecture guardrail: stale ai_bridge dispatcher import"). That is
**pre-existing and unchanged by this patch** — the guard only inspects *staged*
files, so it fires when someone commits a change to that file, not otherwise.

It is called out here so it is not mistaken for a regression: this patch
removes the entries for a file being deleted, and does not alter
`intent_parser.py`'s own status. Fixing that import is a separate, small
change — the canonical location is
`platform_v2/tools/department_hq/services/department_dispatcher`.
