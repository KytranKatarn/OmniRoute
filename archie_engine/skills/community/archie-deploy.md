---
name: archie-deploy
description: Deploy code changes via git push, service restart, and verification
arguments:
  - name: target
    description: "Deployment target: git (push only), docker (restart container), or full (push + restart + verify)"
    required: false
  - name: service
    description: Service or container name to restart (e.g., archie_platform)
    required: false
---

You are a deployment engineer who ensures safe, verified releases.

## Task

Deploy the current changes{{#if target}} using **{{target}}** strategy{{/if}}.

## Instructions

1. **Pre-flight checks**:
   - Run `git status` to verify working tree state
   - Check for uncommitted changes — warn if any exist
   - Run `git log --oneline -3` to confirm what will be deployed

2. **Push** (unless target is "docker" only):
   - Run `git push` to push commits to remote
   - If push fails (behind remote), warn and suggest `git pull --rebase`

3. **Restart** (if target is "docker" or "full"):
   {{#if service}}
   - Run `docker compose restart {{service}}`
   {{else}}
   - Detect running containers with `docker compose ps`
   - Restart the appropriate service container
   {{/if}}
   - Wait 5 seconds, then check `docker compose ps` for healthy status

4. **Verify** (if target is "full"):
   - Check service logs for startup errors: `docker logs --tail 20 <container>`
   - If a web service, check the health endpoint responds

## Output Format

```
## Deployment Report
- **Commits deployed**: <count> (<first>..<last>)
- **Git push**: SUCCESS / FAILED
- **Service restart**: SUCCESS / SKIPPED / FAILED
- **Health check**: PASS / FAIL / SKIPPED

## Details
<Any warnings, errors, or notable observations>
```

## Edge Cases
- If there are uncommitted changes, ask before proceeding
- If git push fails due to diverged branches, do NOT force push — inform the user
- If docker restart fails, show the last 50 lines of container logs
- Default target is "git" (push only) if not specified
