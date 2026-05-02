---
name: archie-scan
description: Run P.R.O.B.E. QA for a specific module or file path. Use after editing a module, fixing a bug, or deploying a change to verify nothing regressed. Accepts module name or file path.
allowed-tools: Bash, mcp__archie__run_qa_suite
argument: Module name (e.g., "media_studio") or file path (e.g., "platform_v2/tools/media_studio/routes.py"). Omit for interactive picker.
---

# P.R.O.B.E. Module Scanner

## Parse Argument

`$ARGUMENTS` can be:
- Module name: `media_studio`, `account_center`, `repair_bay`, `consciousness`, etc.
- File path: `platform_v2/tools/media_studio/routes.py`
- Empty → show module list and prompt

## If empty

Show available modules from MODULE_SUITE_MAP:

```bash
docker exec archie_platform python3 -c "
from services.qa_service import MODULE_SUITE_MAP
for mod, ids in sorted(MODULE_SUITE_MAP.items()):
    print(f'  {mod:<30} → suite(s) {ids}')
"
```

Print:
```
P.R.O.B.E. Module Scanner — available modules:
  account_center              → suite(s) [16, 31]
  media_studio                → suite(s) [23, 50]
  ...

Usage: /archie-scan <module_name>
       /archie-scan platform_v2/tools/media_studio/routes.py
```

## Run the scan

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from services.qa_service import run_suite_for_module
results = run_suite_for_module('$ARGUMENTS', triggered_by='archie_scan_cli')
for r in results:
    status = '✅' if r.get('status') == 'completed' else '❌'
    print(f\"{status} Suite #{r.get('run_id','?')}: {r.get('passed',0)}/{r.get('total',0)} passed — {r.get('status','?')}\")
if not results:
    print('No suites mapped for this module. Check MODULE_SUITE_MAP in qa_service.py.')
"
```

Display results:
```
P.R.O.B.E. Scan: <module>
  ✅ Suite #644: 30/30 passed — completed
  ✅ Suite #670: 34/34 passed — completed

All suites green. No regressions detected.
```

If any suite failed:
```
  ❌ Suite #644: 28/30 passed — failed
     → 2 failures detected. Repair Bay proposals auto-filed.
     → Run /archie-qa <suite-id> for details.
```

## Notes

- Uses `MODULE_SUITE_MAP` in `platform_v2/services/qa_service.py`
- Add new modules: edit `MODULE_SUITE_MAP` with `{module_name: [suite_id, ...]}`
- Same function Repair Bay calls automatically after deploying a fix
- Playwright e2e tests included if the module has them (e.g., media_studio suite #23)
- Platform must be running at 192.168.1.200:3000
