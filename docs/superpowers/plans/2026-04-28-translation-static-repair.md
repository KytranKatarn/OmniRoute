# Translation Static Sites Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve 0 Mock values and 0 missing keys on kytranempowerment.com and creed-ai.org across all 9 languages by running the P.R.O.B.E. DOM audit, routing gaps to R.O.S.E.T.T.A., and redeploying full site zips to Hostinger.

**Architecture:** P.R.O.B.E. audit (Plan 1) runs first to produce a complete gap list. R.O.S.E.T.T.A. fills all gaps via Department HQ dispatch. Full site zips deployed via Hostinger API. P.R.O.B.E. re-audits to confirm 0 gaps.

**Tech Stack:** Python, existing `translations.json` files, Hostinger deployStaticWebsite API, `delegate_task(capability='translate')`.

**Prerequisite:** Plan 1 (P.R.O.B.E. Translation Audit System) must be deployed first.

---

### Task 1: Identify All Missing Keys via P.R.O.B.E. Audit

**Files:**
- Read: `platform_v2/tools/consciousness/translation_scanners/domain_registry.py`
- Read: `website/kytranempowerment.com/data/translations.json`
- Read: `standalone/websites/creed-ai.org/data/translations.json` (or `/mnt/standalone/websites/creed-ai.org/data/translations.json`)

- [ ] **Step 1: Trigger a manual audit run for the two static sites.**

```bash
docker exec archie_platform python -c "
from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner
from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

# Run audit for kytranempowerment_com and creed_ai_org only
target_names = {'kytranempowerment_com', 'creed_ai_org'}
scanner = DomainAuditScanner()

total = 0
by_site = {}
for domain in EXTERNAL_DOMAINS:
    if domain['name'] not in target_names:
        continue
    results = list(scanner._scan_domain(domain))
    by_site[domain['name']] = results
    total += len(results)
    missing = [r for r in results if r.gap_type == 'missing']
    quality = [r for r in results if r.gap_type == 'quality_suspect']
    print(f\"{domain['name']}: {len(missing)} missing, {len(quality)} quality_suspect\")

print(f'Total gaps: {total}')
"
```

- [ ] **Step 2: Export gap list to a review file.**

```bash
docker exec archie_platform python -c "
import json
from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner
from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

target_names = {'kytranempowerment_com', 'creed_ai_org'}
scanner = DomainAuditScanner()
gaps = []
for domain in EXTERNAL_DOMAINS:
    if domain['name'] not in target_names:
        continue
    for r in scanner._scan_domain(domain):
        gaps.append({'site': domain['name'], 'gap_type': r.gap_type,
                     'language': r.language, 'key': r.key, 'snippet': r.snippet})

with open('/tmp/static_site_gaps.json', 'w') as f:
    json.dump(gaps, f, indent=2)
print(f'Wrote {len(gaps)} gaps to /tmp/static_site_gaps.json')
" && cat /tmp/static_site_gaps.json | python3 -m json.tool | head -60
```

---

### Task 2: Fix kytranempowerment.com translations.json

**Files:**
- Modify: `website/kytranempowerment.com/data/translations.json`

- [ ] **Step 1: Find the local translations.json path.**

```bash
ls -la /mnt/archie_brain/website/kytranempowerment.com/data/translations.json
```

- [ ] **Step 2: Route all missing keys to R.O.S.E.T.T.A. via dispatch.**

```bash
docker exec archie_platform python -c "
import json
from services.delegation_service import delegate_task

with open('/tmp/static_site_gaps.json') as f:
    all_gaps = json.load(f)

ke_gaps = [g for g in all_gaps if g['site'] == 'kytranempowerment_com'
           and g['gap_type'] == 'missing']

# Group by language
by_lang = {}
for g in ke_gaps:
    by_lang.setdefault(g['language'], []).append(g['key'])

for lang, keys in by_lang.items():
    # Batch into 20-key chunks
    for i in range(0, len(keys), 20):
        batch = keys[i:i+20]
        result = delegate_task(
            capability='translate',
            reason=f'Fill {len(batch)} missing keys for kytranempowerment.com language={lang}. Keys: {batch[:3]}...',
            args={'language': lang, 'keys': batch,
                  'source_file': 'website/kytranempowerment.com/data/translations.json'},
            delegation_source='automation',
            requested_by='static_site_repair',
            priority=6,
        )
        print(f'lang={lang} batch={i//20+1} keys={len(batch)} → task_id={result.get(\"task_id\")}')
"
```

- [ ] **Step 3: Monitor R.O.S.E.T.T.A. progress in Dev HQ.**

Open http://192.168.1.200:3000/tools/consciousness/#devhq → Tasks tab → filter by "translate" capability. Wait for all tasks to reach `completed` status.

Alternatively, poll from terminal:

```bash
docker exec archie_platform python -c "
from database import get_db_cursor
with get_db_cursor() as (_conn, cur):
    cur.execute('''
        SELECT status, COUNT(*) as n FROM unified_tasks
        WHERE title LIKE '%kytranempowerment%' OR title LIKE '%translate%'
        GROUP BY status ORDER BY status
    ''')
    for row in cur.fetchall():
        print(dict(row))
"
```

- [ ] **Step 4: Manually patch any Mock or quality_suspect keys.**

For keys R.O.S.E.T.T.A. could not translate automatically (e.g. brand names, proper nouns), update `translations.json` directly:

```bash
# Open the file and review quality_suspect keys:
python3 -c "
import json
with open('/mnt/archie_brain/website/kytranempowerment.com/data/translations.json') as f:
    t = json.load(f)
fr = t.get('fr', {})
mocks = {k: v for k, v in fr.items() if 'Mock' in str(v)}
print(f'Remaining Mock values in FR: {len(mocks)}')
for k, v in list(mocks.items())[:10]:
    print(f'  {k}: {v!r}')
"
```

Fix any remaining Mock values by editing `translations.json` directly.

---

### Task 3: Fix creed-ai.org translations.json

**Files:**
- Modify: `/mnt/standalone/websites/creed-ai.org/data/translations.json`

- [ ] **Step 1: Route creed-ai.org gaps to R.O.S.E.T.T.A.**

```bash
docker exec archie_platform python -c "
import json
from services.delegation_service import delegate_task

with open('/tmp/static_site_gaps.json') as f:
    all_gaps = json.load(f)

creed_gaps = [g for g in all_gaps if g['site'] == 'creed_ai_org'
              and g['gap_type'] == 'missing']

by_lang = {}
for g in creed_gaps:
    by_lang.setdefault(g['language'], []).append(g['key'])

for lang, keys in by_lang.items():
    for i in range(0, len(keys), 20):
        batch = keys[i:i+20]
        result = delegate_task(
            capability='translate',
            reason=f'Fill {len(batch)} missing keys for creed-ai.org language={lang}',
            args={'language': lang, 'keys': batch,
                  'source_file': '/mnt/standalone/websites/creed-ai.org/data/translations.json'},
            delegation_source='automation',
            requested_by='static_site_repair',
            priority=6,
        )
        print(f'lang={lang} keys={len(batch)} → task_id={result.get(\"task_id\")}')
"
```

- [ ] **Step 2: Wait for R.O.S.E.T.T.A. completion, then verify 0 Mock values.**

```bash
python3 -c "
import json
with open('/mnt/standalone/websites/creed-ai.org/data/translations.json') as f:
    t = json.load(f)
for lang, data in t.items():
    mocks = [k for k, v in data.items() if 'Mock' in str(v)]
    if mocks:
        print(f'{lang}: {len(mocks)} Mock values — {mocks[:3]}')
    else:
        print(f'{lang}: clean')
"
```

---

### Task 4: Deploy Full Sites + Verify

**Files:** None — deployment only.

- [ ] **Step 1: Deploy full kytranempowerment.com.**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com && \
zip -r /tmp/ke_deploy_$(date +%Y%m%d_%H%M%S).zip . \
  -x ".git/*" ".github/*" "*.bak*" "CONTRIBUTING.md" "SECURITY.md" \
     "CODE_OF_CONDUCT.md" "CHANGELOG.md" "LICENSE" "README.md" ".gitignore"
```

Then deploy via MCP (use `mcp__hostinger-api__hosting_deployStaticWebsite` with `domain='kytranempowerment.com'` and the zip path above).

- [ ] **Step 2: Verify kytranempowerment.com returns HTTP 200 and 0 Mock values.**

```bash
python3 -c "
import urllib.request, json, time
time.sleep(8)
resp = urllib.request.urlopen('https://kytranempowerment.com/data/translations.json', timeout=15)
t = json.loads(resp.read())
for lang in ['fr','es','pt','de','zh','ar','he']:
    data = t.get(lang, {})
    mocks = [k for k,v in data.items() if 'Mock' in str(v)]
    print(f'{lang}: {len(data)} keys, {len(mocks)} Mock')
"
```

Expected: all languages show `0 Mock`.

- [ ] **Step 3: Deploy full creed-ai.org.**

```bash
cd /mnt/standalone/websites/creed-ai.org && \
zip -r /tmp/creed_deploy_$(date +%Y%m%d_%H%M%S).zip . \
  -x ".git/*" ".github/*" "CONTRIBUTING.md" "SECURITY.md" \
     "CODE_OF_CONDUCT.md" "CHANGELOG.md" "LICENSE" "README.md" ".gitignore"
```

Deploy via `mcp__hostinger-api__hosting_deployStaticWebsite` with `domain='creed-ai.org'`.

- [ ] **Step 4: Verify creed-ai.org.**

```bash
python3 -c "
import urllib.request, json, time
time.sleep(8)
resp = urllib.request.urlopen('https://creed-ai.org/data/translations.json', timeout=15)
t = json.loads(resp.read())
for lang in ['fr','es','pt','de','zh','ar','he']:
    data = t.get(lang, {})
    mocks = [k for k,v in data.items() if 'Mock' in str(v)]
    print(f'{lang}: {len(data)} keys, {len(mocks)} Mock')
"
```

- [ ] **Step 5: Commit updated translations.json files.**

```bash
cd /mnt/archie_brain
git checkout -b fix/static-sites-translation-repair
git add website/kytranempowerment.com/data/translations.json
git commit -m "fix(i18n): fill missing/Mock translation keys on kytranempowerment.com"

# creed-ai.org is in /mnt/standalone — commit there separately if it has its own repo
# Otherwise commit the file to archie_brain if tracked here
git add -f standalone/websites/creed-ai.org/data/translations.json 2>/dev/null || true
git commit -m "fix(i18n): fill missing/Mock translation keys on creed-ai.org" 2>/dev/null || true
```

- [ ] **Step 6: Push and open PR.**

```bash
git push origin fix/static-sites-translation-repair
gh pr create \
  --title "fix(i18n): repair static site translations — 0 Mock values on KE.com + creed-ai.org" \
  --body "## What changed
- kytranempowerment.com/data/translations.json — all 8 languages filled, 0 Mock values
- creed-ai.org/data/translations.json — all 8 languages filled, 0 Mock values

## Verified
- HTTP 200 on both sites post-deploy
- 0 Mock values confirmed via translations.json fetch

All translation work dispatched through R.O.S.E.T.T.A. via Department HQ." \
  --base main
```

---

## Success Criteria

- `kytranempowerment.com/data/translations.json` — 0 Mock values in all 8 languages
- `creed-ai.org/data/translations.json` — 0 Mock values in all 8 languages
- Both sites return HTTP 200
- P.R.O.B.E. DOM audit re-run shows 0 open gaps for both domains
