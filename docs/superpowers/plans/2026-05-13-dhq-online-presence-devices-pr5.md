# DHQ Online Presence Coming Soon + API Access Rename — Implementation Plan (PR 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Online Presence stub with a polished Coming Soon placeholder, and rename the Devices tab and panel header to "API Access" to accurately describe its contents.

**Architecture:** Both changes are pure HTML edits inside a single Jinja2 template (`department_hq.html`). No routes, no Python, no DB migrations required. The tab list is a Jinja2 `{% set header_tabs %}` tuple at line 27; panel bodies are `<div class="dhq-panel">` blocks further down.

**Tech Stack:** Jinja2 HTML template, LCARS frame markup, Orbitron font, Docker compose restart.

---

## File Map

| File | Lines touched |
|---|---|
| `platform_v2/tools/department_hq/templates/department_hq.html` | 35, 189, 588–636 |

---

## Task 1: Replace Online Presence Stub with Coming Soon

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:588-636`

- [ ] **Step 1: Confirm the stub block boundaries**

Read lines 585–640 of `department_hq.html`. Confirm the inner stub block starts around line 588 (`<div style="padding:16px">`) and ends around line 636, with a wrapper div at 587 and closing wrapper at 637. The wrapper lines must NOT be touched.

- [ ] **Step 2: Replace lines 588–636 with Coming Soon placeholder**

Delete the entire stub content (agent selector, sessions panel, quick-task panel, task log panel) and replace with:

```html
              <div style="display:flex;align-items:center;justify-content:center;min-height:300px;flex-direction:column;gap:1rem;opacity:0.5">
                <div style="font-size:2.5rem">&#127760;</div>
                <div style="font-family:'Orbitron',sans-serif;letter-spacing:0.1em;font-size:1rem">COMING SOON</div>
                <div style="font-size:0.8rem;text-align:center;max-width:300px">Human agent social media visibility &#8212; Instagram, Facebook feed integration</div>
              </div>
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to `http://192.168.1.200:3000/tools/department-hq`, click the Online Presence tab. Confirm the globe emoji + "COMING SOON" + description renders. Confirm the agent selector and panels are gone.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): replace Online Presence stub with Coming Soon placeholder"
```

---

## Task 2: Rename Devices Tab Button to "API Access"

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:35`

- [ ] **Step 1: Find the tab definition**

Read lines 27–44. Locate the line that reads:

```
    ("devices", "Devices", "monitor"),
```

- [ ] **Step 2: Change the label**

Change `"Devices"` to `"API Access"`:

```
    ("devices", "API Access", "monitor"),
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Confirm the tab button in the nav bar reads "API Access" instead of "Devices".

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): rename Devices tab label to API Access"
```

---

## Task 3: Rename Devices Panel Header

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:189`

- [ ] **Step 1: Find the panel header line**

Read line 189. It contains a long inline-styled div with:

```
...>DEVICE REGISTRY</span>...<span ...>ACCESS</span>...
```

- [ ] **Step 2: Make two string replacements on line 189**

1. `DEVICE REGISTRY` → `API ACCESS`
2. The suffix span text `ACCESS` → `TOKENS`

Result contains:
```
...>API ACCESS</span>...<span ...>TOKENS</span>...
```

All other attributes on the line remain unchanged.

- [ ] **Step 3: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Click the "API Access" tab. Confirm the teal header bar reads "API ACCESS" with "TOKENS" as the right-side mono label.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): rename Devices panel header to API ACCESS / TOKENS"
```

---

## Task 4: Push and Open PR

- [ ] **Step 1: Push branch**

```bash
git push origin feat/dispatch-history
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "feat(dhq): Online Presence Coming Soon + API Access rename (PR 5/5)" \
  --body "$(cat <<'EOF'
## Summary
- Online Presence tab: replaces broken stub (empty agent selector, hidden panels) with Coming Soon placeholder. Feature (human agent Instagram/Facebook visibility) has a clear future purpose — tab stays visible.
- Devices tab: renamed to API Access in nav + panel header renamed DEVICE REGISTRY → API ACCESS. Accurately describes the content: API/CLI device authentication tokens.

## Files changed
- `platform_v2/tools/department_hq/templates/department_hq.html` — lines 35, 189, 588–636

## Test Plan
- [ ] Online Presence tab shows globe + COMING SOON + description
- [ ] Devices tab button reads "API Access" in nav bar
- [ ] Devices panel header reads "API ACCESS / TOKENS"
- [ ] No regressions on other tabs

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge via /merge-pr**

Use `/merge-pr <PR_NUMBER>` — never `gh pr merge` directly.

---

## Quick Reference

| Location | Change |
|---|---|
| Line 35 | `"Devices"` → `"API Access"` (tab nav label) |
| Line 189 | `DEVICE REGISTRY` → `API ACCESS`, `ACCESS` → `TOKENS` (panel header) |
| Lines 588–636 | Replace entire stub body with 5-line Coming Soon div |

**Restart:** `docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform`
**Verify:** `http://192.168.1.200:3000/tools/department-hq`
