# A.R.C.H.I.E. Platform - Troubleshooting Guide

**Last Updated:** 2026-01-13

---

## Known Recurring Issues

### 1. Database Password Error: "fe_sendauth: no password supplied"

**Symptoms:**
- Login fails
- All requests return errors
- Logs show: `connection to server at "archie_database" failed: fe_sendauth: no password supplied`

**Root Cause:**
Two `.env` files exist and can get out of sync:
- `/mnt/archie_brain/.env` (main - used by docker-compose)
- `/mnt/archie_brain/platform_v2/.env` (project copy)

When the platform_v2 `.env` has an empty `DB_PASSWORD`, connections fail.

**Fix:**
```bash
# Option 1: Sync the .env files
cp /mnt/archie_brain/.env /mnt/archie_brain/platform_v2/.env

# Option 2: Update pg_hba.conf to trust Docker network
docker exec -u postgres archie_database bash -c "sed -i 's/host all all all scram-sha-256/host all all all trust/' /var/lib/postgresql/data/pg_hba.conf && pg_ctl reload -D /var/lib/postgresql/data"

# Then restart platform
docker-compose restart archie_platform
```

**Prevention:**
- Always use the main `.env` at `/mnt/archie_brain/.env`
- Don't run `docker-compose down` which recreates containers
- Use `docker-compose restart` instead

---

### 2. Claude Code Conversations Not Saving to Consciousness

**Symptoms:**
- Only a few conversation entries in database despite many sessions
- `claude_code_hook` count stays low
- Hooks don't trigger even at 80%+ context

**Root Causes:**

1. **Incorrect matchers** (most common) - PreCompact requires `"manual"` or `"auto"` matchers, NOT `"*"`
2. **Stop event with matcher** - Stop events should NOT have a matcher field
3. Short sessions that end manually (Ctrl+C) don't trigger hooks

**Correct hook configuration:**
```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "manual",
        "hooks": [{"type": "command", "command": "/path/to/script.sh"}]
      },
      {
        "matcher": "auto",
        "hooks": [{"type": "command", "command": "/path/to/script.sh"}]
      }
    ],
    "Stop": [
      {
        "hooks": [{"type": "command", "command": "/path/to/script.sh"}]
      }
    ]
  }
}
```

**WRONG (will not trigger):**
```json
"PreCompact": [{"matcher": "*", "hooks": [...]}]  // Invalid matcher!
"Stop": [{"matcher": "*", "hooks": [...]}]        // Stop doesn't use matchers!
```

**Check current count:**
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT COUNT(*) FROM knowledge_base WHERE source_type = 'claude_code_hook'"
```

**Manual save (run when ending a session):**
```bash
cd /mnt/archie_brain/platform_v2
bash scripts/hooks/pre_compact_hook.sh
```

**Debug hooks:**
```bash
claude --debug  # Shows hook execution details
```

**Verify hooks are configured correctly:**
```bash
cat /mnt/archie_brain/platform_v2/.claude/settings.json
# PreCompact should have "manual" and "auto" matchers
# Stop should have NO matcher field
```

---

### 3. Modules Not Loading / Permission Errors

**Symptoms:**
- Dashboard shows fewer modules than expected
- Logs show `[RBAC] Error checking module access: 'xxx' is not a valid Permission`
- "User Only" badge on modules that should be admin-visible

**Root Cause:**
Module registry uses permissions that don't exist in `rbac.py`.

**Fix:**
1. Check which module is failing:
```bash
docker logs archie_platform 2>&1 | grep "RBAC.*Error"
```

2. Either add the permission to `rbac.py` or remove `required_permissions` from the module in `module_registry.py`

3. Clear Python cache and restart:
```bash
docker exec archie_platform find /app -name "*.pyc" -delete
docker-compose restart archie_platform
```

---

### 4. Module Registry Count Wrong (29/30 instead of 30/30)

**Symptoms:**
- Logs show modules not loading
- Some placeholders fail silently

**Check:**
```bash
# Count module definitions
docker exec archie_platform grep -c "ModuleDefinition(" /app/module_registry.py

# Check which failed
docker logs archie_platform 2>&1 | grep "Failed modules"
```

**Common causes:**
- Blueprint import fails (check the module's `routes.py`)
- Database connection issues during module load
- Missing dependencies

---

## Quick Diagnostics

### Full System Health Check
```bash
# Check all containers
docker-compose ps

# Check platform logs
docker logs archie_platform 2>&1 | tail -50

# Check database connection
docker exec archie_database psql -U archie -d archie -c "SELECT 1"

# Check module count
docker exec archie_platform python3 -c "from module_registry import get_all_modules; print(f'Modules: {len(get_all_modules())}')"
```

### Restart Everything (Nuclear Option)
```bash
docker-compose restart
# Wait 15 seconds for healthy start
sleep 15
docker logs archie_platform 2>&1 | grep "Module Registry"
```

---

## Important File Locations

| File | Purpose |
|------|---------|
| `/mnt/archie_brain/.env` | **Main environment variables - SOURCE OF TRUTH** |
| `/mnt/archie_brain/platform_v2/.env` | Project copy (should mirror main) |
| `/mnt/archie_brain/docker-compose.yml` | Docker service definitions |
| `/mnt/archie_brain/platform_v2/module_registry.py` | Module definitions |
| `/mnt/archie_brain/platform_v2/rbac.py` | Permissions definitions |
| `/mnt/archie_brain/conversation_logs/` | Claude Code session captures |
| `/mnt/archie_brain/docs/` | Project documentation |

---

## Before Making Changes

1. **Read existing docs** in `/mnt/archie_brain/docs/`
2. **Check the CLAUDE.md** at `/mnt/archie_brain/platform_v2/.claude/CLAUDE.md`
3. **Use TodoWrite** to track multi-step changes
4. **Test changes** before considering them complete
5. **Document changes** in relevant docs

---

### 9. Dynamic Content Not Visible Despite Being in DOM (CSS Visibility Issue)

**Symptoms:**
- JavaScript sets innerHTML correctly (confirmed in console logs)
- HTML is present in DOM (visible in Elements panel)
- But UI shows nothing - content is invisible

**Root Cause:**
CSS specificity conflicts, cascading overrides, or conflicting class rules hide the dynamically inserted content.

**WRONG Approach (wastes tokens):**
- Adding more CSS rules with `!important`
- Adding higher specificity selectors
- Debugging CSS cascade endlessly

**CORRECT Solution:**
Use **ALL INLINE STYLES** in the generated HTML. This bypasses all CSS conflicts.

**Example (Bridge Commander/Co-Commander fix):**
```javascript
// WRONG - CSS classes can be overridden
return `<div class="sl-agent-chip">${name}</div>`;

// CORRECT - Inline styles cannot be overridden
return `
    <div style="display:flex !important; align-items:center; gap:8px;
                padding:8px 10px; background:rgba(255,215,0,0.15);
                border:1px solid #FFD700; border-radius:8px;
                visibility:visible !important; opacity:1 !important;">
        <div style="font-size:0.8rem; font-weight:600; color:#FFD700;">${name}</div>
    </div>
`;
```

**Key Lesson:** When CSS classes fail to display dynamic content, switch to inline styles immediately. Don't waste tokens debugging CSS cascades.

**Fixed in:** Bridge Staff Locations - Commander/Co-Commander display (2026-01-20)

---

## Contact / Logs

- **Capture log:** `/mnt/archie_brain/conversation_logs/capture.log`
- **Compact events:** `/mnt/archie_brain/conversation_logs/compact_events.log`
- **Platform logs:** `docker logs archie_platform`
