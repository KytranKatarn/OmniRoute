---
name: skill-pipeline-test
description: Test the Skill Import Pipeline — verify installer, tester, CLI sync, dependency audit, and fleet push are working correctly
---

# Skill Pipeline Verification

Run a comprehensive check of all skill pipeline components. This covers Phase 1 (install/test/adapt), Phase 2 (CLI sync), Phase 3 (fleet push), and dependency auditing.

## Steps

### 1. Check Pipeline State

Query the database for current funnel numbers:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT status, COUNT(*) FROM github_skills GROUP BY status ORDER BY count DESC;
"
```

Then check installations by target:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT target,
       COUNT(*) as installed,
       COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as pass,
       COUNT(*) FILTER (WHERE dry_run_passed = FALSE) as fail,
       COUNT(*) FILTER (WHERE struct_valid IS NULL OR (struct_valid = TRUE AND dry_run_passed IS NULL)) as untested,
       COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
FROM skill_installations GROUP BY target ORDER BY target;
"
```

### 2. Test Installer (Job #59)

Run the skill installer to process any pending registered skills:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain')
from app import app
with app.app_context():
    from tools.consciousness.jobs import install_skills_to_claude
    install_skills_to_claude()
" 2>&1 | grep SkillInstaller
```

Expected: Either "No registered skills to install" or "Done: N installed, 0 errors"

### 3. Test Skill Tester (Job #60)

Run one dry-run test cycle:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain')
from app import app
with app.app_context():
    from tools.consciousness.jobs import test_installed_skills
    test_installed_skills()
" 2>&1 | grep SkillTester
```

Expected: "Testing 1 installed skills" then PASS or FAIL with assertions

### 4. Test Dependency Audit

Run the dependency CVE audit:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
from services.scan_service import audit_dependencies, store_dependency_findings
findings = audit_dependencies()
print(f'Findings: {len(findings)}')
for f in findings[:5]:
    print(f'  {f[\"severity\"]}: {f[\"package\"]}=={f[\"version\"]} — {f[\"vuln_id\"]}')
scan_id = store_dependency_findings(findings)
print(f'Stored as scan #{scan_id}')
"
```

Expected: List of CVE findings stored in Repair Bay

### 5. Test CLI Sync (Phase 2)

Sync skills from hub to Archie CLI:

```bash
cd /mnt/archie_brain/archie-code && python3 -c "
import asyncio
from pathlib import Path
from archie_engine.hub.auth import HubAuth
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.sync import HubSync

async def test():
    auth = HubAuth(key_file=Path('/tmp/test_hub_key'))
    auth.store_key('dev-api-key-change-in-production')
    connector = HubConnector(hub_url='http://192.168.1.200:3000', auth=auth)
    sync = HubSync(connector=connector, cache_dir=Path('/tmp/cli_test'))
    count = await sync.sync_skills()
    print(f'Synced {count} skills')

asyncio.run(test())
" 2>&1 | grep -v WARNING
rm -rf /tmp/cli_test /tmp/test_hub_key
```

Expected: "Synced N skills" where N = number of tested+passing skills

### 6. Test Fleet Push (Phase 3)

Check fleet push state:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT COUNT(*) as total_pushes,
       COUNT(*) FILTER (WHERE fail_count = 0) as successful,
       COUNT(*) FILTER (WHERE fail_count > 0) as failed
FROM node_skill_pushes;
"
```

Note: Fleet push only works when starship nodes have heartbeats within 10 minutes. If no nodes are online, this will show 0 — that's correct.

### 7. Check Pipeline Stats API

```bash
curl -s http://192.168.1.200:3000/tools/consciousness/api/github/skills/pipeline-stats
```

Expected: JSON with discovered, registered, installed, passed, failed, adapted, cli_synced, cluster_pushed counts.

### 8. Verify All Jobs Registered

```bash
docker logs archie_platform 2>&1 | grep -E 'Skill Installer|Skill Tester|Skill Fleet|Skill Adaptation|Dependency.*Audit|Registered.*consciousness'
```

Expected: All 5 skill-related jobs + "Registered 19 consciousness jobs"
