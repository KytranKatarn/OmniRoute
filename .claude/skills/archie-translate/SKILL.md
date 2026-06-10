---
name: archie-translate
description: Operate the A.R.C.H.I.E. translation coverage system — trigger scans, inspect coverage by source/language, query open gaps, tail nightly cron output. Invoke when working on translation tasks (#2089-#2099, #2103), investigating the CODEX/ROSETTA pair, or when the user asks about translations, coverage, or missing languages.
---

# A.R.C.H.I.E. Translation Workflow

Operational runbook for the dual-lane translation system shipped 2026-04-18 (PR #130). Architecture reference: KB `vault_note` #256950.

## Pipeline in 30 seconds

```
 Scanner (3 passes)  →  Generator (CODEX GPU / ROSETTA CPU)  →  Translations
 translation_gaps       dispatcher → dispatch_json              translations
 (open rows)            capability="translate"                   (approved rows)
```

Nightly cron: `translation_coverage_scan` via `fleet_jobs._translation_coverage_scan_wrapper`.

## Quick scan status

```python
mcp__archie__search_knowledge(
    query="translation coverage architecture",
    types=["vault_note"],
    limit=3,
)
# Or directly:
```

```sql
-- Gaps per source + type
SELECT source, gap_type, status, COUNT(*)
FROM translation_gaps
GROUP BY source, gap_type, status
ORDER BY source, gap_type;

-- Coverage per (source, language)
SELECT source_label, language, COUNT(*) AS total,
       SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved
FROM translations
WHERE source_label IS NOT NULL
GROUP BY source_label, language
ORDER BY source_label, language;

-- Last nightly run
SELECT status, items_processed, duration_ms/1000 AS dur_s, details, created_at
FROM autonomy_loop_log
WHERE job_name = 'translation_coverage_scan'
ORDER BY created_at DESC LIMIT 5;
```

## Trigger a scan

### Via HTTP endpoint (admin-gated, single-flight)

```bash
curl -X POST http://192.168.1.200:3000/api/translations/full-scan \
     -b /tmp/cookies.txt
# Returns {"success": true, "message": "scan started"} or 409 if one already running
```

### Via Python (for debugging — bypasses HTTP auth)

```bash
docker exec -d archie_platform bash -c '
cd /app
PYTHONPATH=/app:/mnt/archie_brain:/mnt/archie_brain/ai_bridge \
TRANSLATION_NIGHTLY_CAP=100 \
python3 -c "
from tools.consciousness.translation_scanners.orchestrator import run_translation_coverage_scan
import json
r = run_translation_coverage_scan()
open(\"/tmp/scan.json\",\"w\").write(json.dumps(r, default=str))
" 2>/tmp/scan.err; echo done > /tmp/scan.done'
```

Override `TRANSLATION_NIGHTLY_CAP` to control how many missing gaps the generator processes (default 5000 — scan takes ~2min, generation adds ~1s per gap on mistral).

## Coverage Health UI

Consciousness → Languages tab → Coverage Health card. Shows per-(source, language) approved/total rows. Also `GET /api/translations/coverage-health`.

## Sources covered (12 external + platform)

| Source | Path | Type |
|---|---|---|
| `website_kytranempowerment` | `/mnt/archie_brain/website/kytranempowerment.com` | website |
| `website_creed` | `/mnt/archie_brain/website/creed-ai.org` | website |
| `website_kso` | `/mnt/archie_brain/kytran-server-manager` | product |
| `website_what_the_fact` | `/mnt/standalone/websites/what-the-fact.com` | website |
| `website_thenews` | `/mnt/standalone/websites/thenews.kytranempowerment.com` | website |
| `product_civic_watch` / `gov_watch` / `legal_watch` / `market_watch` | `/mnt/standalone/kytran-*-watch` | product |
| `product_kytran_news` | `/mnt/standalone/kytran-news` | product |
| `product_business_suite` | `/mnt/standalone/kytran-business-suite` | product |
| `product_creed_governance` | `/mnt/standalone/kytran-creed` | product |

Declared in `platform_v2/tools/consciousness/language_routes.py::EXTERNAL_SCAN_SOURCES`.

## Gap types

| Type | Means | Fix path |
|---|---|---|
| `untagged` | Bare text in HTML, no `data-i18n` attribute | Manual tagging (workstream #2069) |
| `missing` | Tagged key, no row for a target language | Generator picks up, dispatches to CODEX/ROSETTA |
| `quality_suspect` | Semantic check flagged likely-bad translation | Review in Languages tab |

## Translation agents (Documentation & Knowledge)

| Agent | Model | Tier | Role |
|---|---|---|---|
| **C.O.D.E.X.** | `mistral:7b` | GPU | Low-latency, department director |
| **R.O.S.E.T.T.A.** | `mistral-cpu` | CPU | Parallel overflow, RTL specialist, Amina Youssef persona |

Both at task_queue_limit=10. Dispatcher picks via welfare + budget scoring — no manual routing needed.

## Debug when translation fails

1. Check coverage — are gaps accumulating instead of resolving?
2. Check budget counters — `/archie-budget` to see if CODEX/ROSETTA are blocked
3. Check last scan log — did it succeed? Look at `autonomy_loop_log.details.auto_fixed`
4. Check system_notifications for scan failures or overcommit alerts
5. Live test dispatch:
   ```python
   from tools.department_hq.services.department_dispatcher import dispatch_json
   r = dispatch_json(capability="translate", prompt="Translate: Hello", module_id="debug")
   print(r)  # should be a dict with "translated" key, real French/etc.
   ```

If `r` is `None` or contains the literal string `"mock"` → the dispatcher is misrouting. Most likely cause: budget counter drift (see `/archie-budget`). Task #2099 for history.

## Known gaps (open tasks)

- **#2089** Bundle export RO mount — 4 websites can't receive updated `translations.json`
- **#2090** Model choice audit — mistral:7b works, specialty translation model may be better
- **#2091** arctic-embed-cpu deployment — semantic scanner fallback
- **#2092** P.R.O.B.E. coverage for all 12 sources
- **#2093** coverage_health should include untagged
- **#2097** langdetect container rebuild

## Related

- `/archie-agent` — CODEX/ROSETTA welfare + counter
- `/archie-budget` — counter drift check (primary cause of past "mock" bug)
- `/archie-status` — platform-wide view including translate pair status

## Rules

- **Nightly cron runs at its scheduled time** — don't trigger manual scans from inside another scan (409 guard exists, but still).
- **Don't mass-delete `translation_gaps`** — reconciliation assumes monotonic accumulation; truncating during debug is fine but reset counters too.
- **`generated_by='coverage_scan'` is your audit trail** — filter by it when cleaning up test data.
