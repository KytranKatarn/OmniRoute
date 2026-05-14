---
name: scout
description: Dispatch S.C.O.U.T. browser intelligence jobs from the CLI — UX audits, procurement sync, SEO snapshots, login tests, and more.
---

# /scout — S.C.O.U.T. CLI Skill

Dispatch browser intelligence jobs to S.C.O.U.T. (agent #364) via the hub API and poll for results.

## Usage

```
/scout ux-audit <url>              UX audit (desktop + mobile screenshots, console errors)
/scout login-test <url>            Test login flow, capture all states
/scout seo-snapshot <url>          SEO metadata snapshot
/scout procurement-sync [url]      CanadaBuys tender sync (default URL if omitted)
/scout web-scrape <url>            Extract elements from page
/scout price-monitor <url>         Track product prices
/scout status                      Show 10 most recent jobs
/scout report <job_id>             Show full findings for a completed job
```

## How to dispatch a job

Read credentials once:
```bash
SCOUT_KEY=$(grep '^CLUSTER_PROXY_KEY=' /mnt/archie_brain/.env | cut -d= -f2)
HUB=http://192.168.1.200:3000
```

Submit job (replace JOB_TYPE and TARGET_URL):
```bash
python3 -c "
import urllib.request, json
key = '${SCOUT_KEY}'
job_type = 'JOB_TYPE'   # e.g. ux_audit, seo_snapshot, web_scrape
target_url = 'TARGET_URL'
url = '${HUB}/tools/department-hq/api/scout/cli-dispatch'
payload = json.dumps({'job_type': job_type, 'target_url': target_url, 'params': {}}).encode()
req = urllib.request.Request(url, data=payload)
req.add_header('Content-Type', 'application/json')
req.add_header('X-Scout-Key', key)
r = urllib.request.urlopen(req, timeout=10)
d = json.loads(r.read())
print('Job #' + str(d.get('job_id')) + ' submitted')
"
```

Poll until complete (replace JOB_ID):
```bash
python3 -c "
import urllib.request, json, time
key = '${SCOUT_KEY}'
hub = 'http://192.168.1.200:3000'
job_id = JOB_ID
for i in range(24):
    req = urllib.request.Request(f'{hub}/tools/department-hq/api/scout/cli-status/{job_id}')
    req.add_header('X-Scout-Key', key)
    d = json.loads(urllib.request.urlopen(req, timeout=5).read())
    status = d.get('status', '?')
    print(f'[{(i+1)*5}s] {status}')
    if status not in ('pending', 'running'):
        print()
        print(d.get('findings', 'No findings'))
        if d.get('screenshots'):
            print('Screenshots:', [s['path'] for s in d['screenshots']])
        break
    time.sleep(5)
"
```

## Notes
- auto_approve=True skills finish as 'approved' immediately
- auto_approve=False skills (ux_audit, login_test, etc.) finish as 'needs_review' — approve in DHQ Scout → Reports tab
- Screenshots at: /mnt/data2/scout/screenshots/{job_id}/{step}.png
- Hub must be running: http://192.168.1.200:3000
