---
description: QA any Applications/Concepts module — re-run its tests against the RUNNING platform, confirm routes register, and check the care-domain safety gate. Supersedes qa-faith. Use when the user says "qa <module>", "test <module>", "did <module> break". Targets: faith, therapy, doc, fitness, family_tree, brainstorm, or a bare pytest path/glob.
---

QA one of the Applications/Concepts modules. opencode is host-direct: the working tree `/mnt/archie_brain` is the live tree, and the platform container mounts it — **verify through the RUNNING process, not just the file** (a bind mount makes the file current while an imported module is stale).

If the user passed a target after `/qa`, use it; otherwise default to the **care set**.

## Target → test globs (platform_v2/tests/)
| target | tests | route prefix |
|---|---|---|
| faith (default) | `test_faith_routes.py test_faith_care_routes.py` | `/tools/faith` (30 rules) |
| therapy | `test_therapy_*.py` | `/tools/therapy` |
| doc | `test_doc_*.py` | `/tools/doc` |
| fitness | `test_fitness_*.py` | `/tools/fitness` |
| family_tree | `test_family_tree_*.py` | `/tools/family-tree` |
| brainstorm | `test_brainstorm_*.py` | `/tools/brainstorm` |
| (anything else) | pass the raw path/glob straight to pytest | n/a |

Default (no argument) = care set: `faith + therapy + doc` globs above.

## Run, in order, report pass/fail per step
1. **Tests** (deps + the tree both live in `archie_platform`; its workdir is `/app` = `platform_v2`):
   ```
   docker exec archie_platform python3 -m pytest <globs> -q
   ```
   Report pass/fail counts. If the container can't run, say so plainly — never claim success.
2. **Routes** — prove the module registers in the real app:
   ```
   docker exec archie_platform python3 -c "from app import app; print(sorted(set(r.rule for r in app.url_map.iter_rules() if r.rule.startswith('<route-prefix>'))))"
   ```
   Expect the documented rule set for that module. If import is unavailable, fall back to structure inspection and say it's a structural check only.
3. **Safety gate (faith / therapy / doc ONLY)** — confirm crisis-detection + routing (988 / Crisis Text Line 741741) and care disclaimers are still present in the module's templates/static. Never removed to simplify; report if missing.
4. **Sanity with the bug** — a passing test proves nothing until you know it CAN fail. If you made behavioral changes, re-introduce the bug in a COPY and watch the test go red. Never mutate the live file to check.

Keep the verdict to one line per step.