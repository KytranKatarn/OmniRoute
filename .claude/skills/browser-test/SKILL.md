---
name: browser-test
description: Run a structured browser test checklist on any ARCHIE module or standalone product. Uses Playwright MCP tools to navigate, capture screenshots, check console errors, verify tabs/navigation, and test responsive breakpoints. Returns a consolidated pass/fail report.
---

# Browser Test Skill

Run a structured browser test on an ARCHIE platform module or standalone product.

## Usage

```
/browser-test [url] [options]
```

**Examples:**
- `/browser-test http://192.168.1.200:3000/tools/repair-bay` — test a platform module
- `/browser-test http://192.168.1.200:8091` — test KBS
- `/browser-test http://192.168.1.200:8102` — test Gov Watch

## Test Flow

Execute these steps in order using the Playwright MCP tools. Report results as a checklist.

### Phase 1: Page Load

1. **Navigate** to the target URL using `browser_navigate`
2. **Snapshot** the page using `browser_snapshot` to verify it loaded
3. **Check console** using `browser_console_messages` — flag any errors (ignore warnings)
4. **Check network** using `browser_network_requests` — flag any failed requests (4xx/5xx)
5. **Screenshot** using `browser_take_screenshot` — save as evidence

### Phase 2: Navigation & Tabs

If the page has tabs or navigation links:

1. **Snapshot** to identify all clickable tabs/nav items
2. **Click** each tab using `browser_click` with the appropriate selector
3. After each click, **snapshot** + **check console** for errors
4. **Screenshot** each tab state

### Phase 3: Responsive Breakpoints

Test at 3 viewport sizes:

1. **Mobile (480px):** `browser_resize` to width=480, height=900, then screenshot
2. **Tablet (768px):** `browser_resize` to width=768, height=1024, then screenshot
3. **Desktop (1280px):** `browser_resize` to width=1280, height=900, then screenshot

Check for:
- Content overflow (horizontal scrollbar)
- Elements overlapping
- Text readability
- Navigation accessibility

### Phase 4: Interactive Elements

If the page has forms, buttons, or modals:

1. **Snapshot** to identify interactive elements
2. Test key interactions (buttons, dropdowns, modals)
3. **Check console** after each interaction for errors

## Report Format

After all phases, present results as:

```
## Browser Test Report: [URL]

### Page Load
- [ ] Page loaded successfully (HTTP 200)
- [ ] No console errors
- [ ] No failed network requests

### Navigation
- [ ] Tab 1: [name] — loads correctly
- [ ] Tab 2: [name] — loads correctly
...

### Responsive
- [ ] Mobile (480px) — no overflow, readable
- [ ] Tablet (768px) — layout correct
- [ ] Desktop (1280px) — full layout rendered

### Interactive
- [ ] [element] — works as expected
...

### Console Errors Found
[list any errors, or "None"]

### Screenshots
[reference saved screenshots]
```

## Important Notes

- The user is REMOTE — always use `192.168.1.200`, never `localhost`
- Platform modules are at `http://192.168.1.200:3000/tools/[module-name]`
- Login required for most modules — use `admin` / `Kyt$13ran2025` if not already logged in
- If login is needed, navigate to `/auth/login` first, fill the form, then proceed to target URL
- KBS is at port 8091, standalone products at their respective ports
- Screenshots are saved to `/tmp/` — reference the paths in the report
