# Security Network Phase 3: JS Extraction & Consolidation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract ~3,300 lines of inline JavaScript from security_network.html into external JS files and consolidate duplicate utility functions.

**Architecture:** Extract inline `<script>` content to a new `security-network-app.js` file. Keep existing `security-network.js` (761 lines) as-is since it handles a different concern (NOC/traffic/defense helpers). Consolidate duplicate utilities into the existing file. Replace inline script with `<script src>` tag.

**Tech Stack:** JavaScript, Jinja2 templates

**CRITICAL:** AdGuard DNS is live. Do not break any JS functions that call `/api/dns/adguard/*` endpoints.

---

### Task 1: Extract Inline JS to External File

Extract ALL inline `<script>` content from the template into a new external JS file.

**Files:**
- Create: `platform_v2/static/js/security-network-app.js`
- Modify: `platform_v2/templates/tools/security_network.html`

### Task 2: Consolidate Duplicate Utility Functions

Remove duplicates between security-network.js and security-network-app.js:
- `formatNum` / `snFormatNum`
- `setBadge` / `snSetBadge`
- `esc` / `snEsc`
- `showLoading` / `snShowLoading`
- `showEmpty` / `snShowEmpty`
- `buildTable` / `snBuildTable`
- `createBadge` / `snCreateBadge`
- `switchToTab` (defined in both)
- `deleteReconScan` (defined TWICE in inline)

### Task 3: Unify API Base Variables

The inline JS uses `var API = '/tools/security-network'` while security-network.js uses `const SN_API`. Consolidate to one variable.
