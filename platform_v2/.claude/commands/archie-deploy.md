# Safe Deployment Protocol

Deploy changes to A.R.C.H.I.E. platform with safety checks.

## Instructions

Follow this deployment checklist:

1. **Pre-flight checks**:
   - Run `docker ps` to verify all containers are healthy
   - Run `git status` to see uncommitted changes
   - Check for any failing tests if applicable

2. **Backup** (if significant changes):
   - Create database backup: `docker exec archie_database pg_dump -U archie archie > /mnt/archie_brain/backups/pre_deploy_$(date +%Y%m%d_%H%M%S).sql`

3. **Deploy**:
   - Restart platform: `docker-compose restart archie_platform`
   - Wait 10 seconds for startup

4. **Verify**:
   - Check container health: `docker ps | grep archie_platform`
   - Test health endpoint: `curl -s http://localhost:3000/tools/blueprint/api/health/full`

5. **Report** success or any issues found

IMPORTANT: Always confirm with user before restarting containers.
