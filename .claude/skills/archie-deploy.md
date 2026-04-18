---
name: archie-deploy
description: Safely deploy A.R.C.H.I.E. platform changes — restart container, wait for healthy, run smoke checks, roll back on failure. Invoke after editing platform_v2 Python files, migrations, or templates. Also use when the user says "deploy", "restart", "apply changes", or after shipping a PR.
---

# A.R.C.H.I.E. Deploy — Safe Restart + Verify

Golden path for applying code changes to `archie_platform`. Prevents the "restart-and-hope" anti-pattern.

## Pre-flight (run BEFORE restart)

1. **Syntax check any edited Python** — `python3 -c "import ast; ast.parse(open('FILE').read())"` for each modified `.py`. Catch 90% of startup crashes here.
2. **Confirm migration ran** — if a migration file is part of this change, apply it FIRST:
   - `cat <migration.sql> | docker exec -i archie_database psql -U archie -d archie`
   - Verify it committed (no ROLLBACK in output)
3. **Check container currently healthy** — `docker ps --filter name=archie_platform --format '{{.Status}}'` should show `(healthy)`. If it's already broken, don't compound.

## Restart

```bash
docker compose restart archie_platform
```

Run from `/mnt/archie_brain` (compose file location) — otherwise you get "no configuration file provided: not found".

## Wait for healthy (up to 30s)

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/)
  if [ "$code" = "200" ] || [ "$code" = "302" ]; then
    echo "up (HTTP $code) at attempt $i"
    break
  fi
  sleep 2
done
```

## Post-flight smoke checks

- `docker logs archie_platform 2>&1 | tail -20` — look for Traceback/ERROR/ImportError
- `curl -s http://192.168.1.200:3000/ -o /dev/null -w "%{http_code}"` → 200 or 302
- If the change touched the scheduler: `docker logs archie_platform 2>&1 | grep "Added job"` should show the expected jobs

## Rollback (if healthcheck fails twice)

1. `git stash` (if uncommitted) OR `git revert <sha>` (if committed)
2. `docker compose restart archie_platform`
3. Re-run healthcheck

**Rule #3**: 2 failures → STOP. Don't spiral with 10 restart attempts. Surface to user with:
- What changed
- What the logs show
- What you've already tried

## When to use compose build vs restart

- **`docker compose restart`** — Python/template changes (`/app` is a bind-mount, new code is live after restart)
- **`docker compose build archie_platform && docker compose up -d archie_platform`** — requirements.txt changes, Dockerfile changes, base image upgrades. Takes 2-5 min. WARN user before running.
- **Never** `docker compose up -d` with other services mentioned — stops everything else

## Related skills

- `/archie-status` — verify post-deploy health comprehensively
- `/archie-qa` — run P.R.O.B.E. suites to catch regressions

## Rules

- Per `feedback_docker-compose-danger.md`: never modify `docker-compose.yml` without explicit user approval.
- Per `feedback_verify-everything.md`: show the HTTP status code + sample log output before claiming deployed.
- Don't run this on its own — only after verified code changes exist. `/archie-status` covers the bare "is it running" case.
