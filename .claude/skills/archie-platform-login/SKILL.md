---
name: archie-platform-login
description: Log in to the A.R.C.H.I.E. platform using Claude's agent account. NEVER use Kytran's credentials. Call this before any Playwright browser session on platform.kytranempowerment.com or 192.168.1.200:3000.
---

# A.R.C.H.I.E. Platform Login Skill

## Identity Rule (MANDATORY — read before anything else)

**Claude Code logs in as `claude` / `claude@kytranempowerment.com` ONLY.**

Never use `kytran`, never use `admin`, never guess a password. If `claude@` fails, stop and tell the user — do not try other accounts.

| Who | Username | Password env var | File |
|-----|----------|-----------------|------|
| **Claude Code** | `claude` | `ARCHIE_CLAUDE_PASSWORD` | `/mnt/archie_brain/.env` |
| **A.R.C.H.I.E.** | `archie` | `ARCHIE_ARCHIE_PASSWORD` | `/mnt/archie_brain/.env` |
| **Kytran (human)** | `kytran` | **NEVER TOUCH** | — |

## Step 1: Read credentials

```bash
CLAUDE_USER=$(grep '^ARCHIE_CLAUDE_USERNAME=' /mnt/archie_brain/.env | cut -d= -f2)
CLAUDE_PASS=$(grep '^ARCHIE_CLAUDE_PASSWORD=' /mnt/archie_brain/.env | cut -d= -f2)
```

## Step 2: Navigate to platform

Use `mcp__plugin_playwright_playwright__browser_navigate` with `http://192.168.1.200:3000`
(NOT `https://platform.kytranempowerment.com` — CDN caps at 60s).

Expected: redirects to `/login`.

## Step 3: Fill login form

```
username → $CLAUDE_USER  (= "claude")
password → $CLAUDE_PASS  (from ARCHIE_CLAUDE_PASSWORD in root .env)
```

Use `mcp__plugin_playwright_playwright__browser_fill_form`:
- target: `input[name='username']` or `#username`
- target: `input[type='password']` or `#password`

## Step 4: Submit + verify

Click `button[type='submit']`. Expected: redirect to `/dashboard`. Confirm header shows `claude`.

## Step 5: Dismiss chat overlay (always required)

```javascript
() => {
  document.querySelectorAll('.ac-overlay-messages, [class^="ac-"]')
    .forEach(el => el.style.display = 'none');
  return 'dismissed';
}
```

Use `mcp__plugin_playwright_playwright__browser_evaluate` with above function.

## If login fails

1. Check lockout: `docker exec archie_database psql -U archie -d archie -c "SELECT failed_login_count FROM users WHERE username='claude';"`
2. If count ≥ 5: `docker exec archie_database psql -U archie -d archie -c "UPDATE users SET failed_login_count=0 WHERE username='claude';"`
3. **Do NOT attempt `kytran` login.** Stop and tell the user.

## Why this rule exists

Claude Code locked Kytran out of his own platform on 2026-05-08 by making 5 failed attempts as `kytran`. The `claude` and `archie` accounts were created specifically by Kytran via Account Manager for agent use. Use them.
