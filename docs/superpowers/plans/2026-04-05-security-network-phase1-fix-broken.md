# Security Network Module — Phase 1: Fix Broken Features

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all broken features in the Security Network module without restructuring code or changing architecture.

**Architecture:** Targeted fixes to existing files only. No new files created. No route moves. Every fix is backward-compatible. AdGuard is the LIVE DNS server — do NOT modify any AdGuard service code or endpoints.

**Tech Stack:** Python/Flask, PostgreSQL, JavaScript (inline in template), Jinja2

**CRITICAL SAFETY RULE:** AdGuard DNS serves all network devices. Do NOT modify `adguard_service.py`, `stack_integration.py` AdGuard methods, or any `/api/dns/adguard/*` routes. These are working and must remain untouched.

---

### Task 1: Fix Device Consumption 500 Error

**Root cause:** `device_routes.py` queries `bytes_sent`, `bytes_recv`, `recorded_at` but the actual table `network_traffic_stats` has columns `bytes_in`, `bytes_out`, `hour_bucket`.

**Files:**
- Modify: `platform_v2/tools/security_network/device_routes.py:129-166`

- [ ] **Step 1: Fix column names in `devices_consumption()` query**

In `device_routes.py`, replace the query at line 131-148:

```python
                cur.execute(
                    """
                    SELECT
                        nts.device_mac,
                        nts.device_ip,
                        ndu.user_name,
                        ndu.device_label,
                        ndu.device_type,
                        SUM(nts.bytes_sent) AS bytes_sent,
                        SUM(nts.bytes_recv) AS bytes_recv,
                        SUM(nts.bytes_sent + nts.bytes_recv) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.recorded_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY nts.device_mac, nts.device_ip, ndu.user_name, ndu.device_label, ndu.device_type
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
```

Replace with:

```python
                cur.execute(
                    """
                    SELECT
                        nts.device_mac,
                        nts.device_ip,
                        ndu.user_name,
                        ndu.device_label,
                        ndu.device_type,
                        SUM(nts.bytes_out) AS bytes_sent,
                        SUM(nts.bytes_in) AS bytes_recv,
                        SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                    GROUP BY nts.device_mac, nts.device_ip, ndu.user_name, ndu.device_label, ndu.device_type
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
```

Changes: `bytes_sent` -> `bytes_out`, `bytes_recv` -> `bytes_in`, `recorded_at` -> `hour_bucket`

- [ ] **Step 2: Fix column names in `devices_consumption_by_user()` query**

Same file, the query at line 176-190. Replace:

```python
                cur.execute(
                    """
                    SELECT
                        COALESCE(ndu.user_name, 'Unknown') AS user_name,
                        COUNT(DISTINCT nts.device_mac) AS device_count,
                        SUM(nts.bytes_sent) AS bytes_sent,
                        SUM(nts.bytes_recv) AS bytes_recv,
                        SUM(nts.bytes_sent + nts.bytes_recv) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.recorded_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY COALESCE(ndu.user_name, 'Unknown')
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
```

Replace with:

```python
                cur.execute(
                    """
                    SELECT
                        COALESCE(ndu.user_name, 'Unknown') AS user_name,
                        COUNT(DISTINCT nts.device_mac) AS device_count,
                        SUM(nts.bytes_out) AS bytes_sent,
                        SUM(nts.bytes_in) AS bytes_recv,
                        SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                    GROUP BY COALESCE(ndu.user_name, 'Unknown')
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
```

- [ ] **Step 3: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open http://192.168.1.200:3000/tools/security-network, go to Devices tab. "Device Consumption" should no longer show "Error loading consumption data". If the table has no data, it should show an empty table instead of a 500 error.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/device_routes.py
git commit -m "fix: correct column names in device consumption queries (bytes_in/out, hour_bucket)"
```

---

### Task 2: Fix UFW Firewall Loading Errors

**Root cause:** The JS function `loadFirewall()` calls `SYSOPS_API + '/firewall/status'` and `SYSOPS_API + '/firewall/rules'` which hit System Operations endpoints. These return 302 auth redirects because the request context doesn't carry SysOps auth. Security Network already has its own `/api/firewall/status` route at `routes.py:976` that works — the JS just isn't calling it.

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html:2843`
- Modify: `platform_v2/tools/security_network/routes.py` (add firewall proxy routes)

- [ ] **Step 1: Change `SYSOPS_API` to use Security Network's own API**

In `security_network.html`, find line 2843:

```javascript
var SYSOPS_API = '/tools/system-operations/api';
```

Replace with:

```javascript
var SYSOPS_API = '/tools/security-network/api';
```

This variable is ONLY used by firewall functions. It changes them to call Security Network endpoints instead.

- [ ] **Step 2: Add firewall proxy routes to Security Network**

The JS calls `/firewall/rules`, `/firewall/enable`, `/firewall/disable`, `/firewall/allow`, `/firewall/deny`, `/firewall/delete`. Security Network only has `/firewall/status`. Add the missing routes.

In `routes.py`, after the `api_firewall_status()` function (around line 992), add proxy routes that delegate to the host_command_client (same pattern as the existing `api_firewall_status`):

```python
@security_network_bp.route("/api/firewall/rules")
@login_required
@admin_required
def api_firewall_rules():
    """Get firewall rules via host_command_client."""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available
        if not is_queue_available():
            return jsonify({"success": True, "rules": []})
        result_data = submit_and_wait("firewall_rules", {}, timeout=10, submitted_by="security_network")
        cmd_result = result_data.get("result", {})
        if cmd_result.get("success"):
            return jsonify({"success": True, "rules": cmd_result.get("rules", [])})
        return jsonify({"success": True, "rules": []})
    except Exception as e:
        logger.exception("firewall rules error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/<action>", methods=["POST"])
@login_required
@admin_required
def api_firewall_action(action):
    """Proxy firewall actions (enable/disable/allow/deny) via host_command_client."""
    allowed_actions = {"enable", "disable", "allow", "deny"}
    if action not in allowed_actions:
        return jsonify({"success": False, "error": "Invalid action"}), 400
    data = request.get_json(silent=True) or {}
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available
        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait(f"firewall_{action}", data, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/delete", methods=["DELETE"])
@login_required
@admin_required
def api_firewall_delete():
    """Delete firewall rule via host_command_client."""
    data = request.get_json(silent=True) or {}
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available
        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_delete", data, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 3: Verify host_command_client supports firewall commands**

Before deploying, check that System Operations' host_command_client handles these command types:

```bash
grep -r "firewall" platform_v2/tools/system_operations/host_command_client.py | head -10
```

If unsupported, the endpoints return empty/error gracefully (no crash).

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open http://192.168.1.200:3000/tools/security-network, go to Defense tab. UFW Firewall section should show status instead of "Error loading firewall".

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/security_network.html platform_v2/tools/security_network/routes.py
git commit -m "fix: route firewall calls through Security Network API instead of System Operations"
```

---

### Task 3: Fix Scanner Subtab HTML Structure

**Root cause:** Lines 963-964 and 1046-1047 in `security_network.html` have stray `-->` comment-close markers that break the div wrappers for Vulnerability and Reconnaissance subtabs.

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html:964,1047`

- [ ] **Step 1: Remove stray comment markers**

In `security_network.html`, find line 964 which reads `-->` right after the Vulnerability subtab div opening:

```html
<div id="subtab-scanners-vuln" class="subtab-content">
-->
```

Remove the `-->` line. Then find line 1047 (line number will shift by 1 after first edit) which has the same pattern for Reconnaissance:

```html
<div id="subtab-scanners-recon" class="subtab-content">
-->
```

Remove that `-->` line too.

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open Scanners tab. Click between Surveillance, Vulnerability, and Reconnaissance subtabs. All three should show/hide correctly.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "fix: remove stray HTML comment markers breaking scanner subtabs"
```

---

### Task 4: Add Missing `import time` to routes.py

**Root cause:** `_check_fail2ban_health()` and `_check_ddns_health()` use `time.time()` but `time` is never imported.

**Files:**
- Modify: `platform_v2/tools/security_network/routes.py:10-12`

- [ ] **Step 1: Add time import**

In `routes.py`, find the imports section (around line 10-12):

```python
import os
import logging
from datetime import datetime
```

Add `import time` after `import os`:

```python
import os
import time
import logging
from datetime import datetime
```

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

Check logs for no import errors:

```bash
docker logs archie_platform 2>&1 | grep -i "time" | grep -i "error" | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/security_network/routes.py
git commit -m "fix: add missing time import for fail2ban/DDNS health checks"
```

---

### Task 5: Fix DNS Domains Sub-tab (Empty Content)

**Root cause:** The Domains sub-tab has HTML content (lines 470-660) and a JS function `loadDomainsOverview()` (line 3371), but the subtab may not trigger the load function. The `loadDomainsOverview()` function calls NPM and Hostinger APIs that may error silently.

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html`

- [ ] **Step 1: Check subtab click handler wiring**

Search the inline JS for the DNS subtab click handler. Find how `data-subtab="domains-overview"` triggers content loading. The other DNS subtabs (query log, filters, etc.) work because they're wired in a switch/case or if-chain. Verify that `domains-overview` is included.

Look for a pattern like:
```javascript
case 'domains-overview':
    loadDomainsOverview();
    break;
```

If it's missing, add it to the switch/case that handles DNS subtab clicks.

- [ ] **Step 2: Add error display to loadDomainsOverview**

Find `loadDomainsOverview()` at line 3371. Ensure the catch block uses `textContent` (safe against XSS) to show an error message instead of rendering blank:

```javascript
} catch(e) {
    console.error('loadDomainsOverview error:', e);
    var el = document.getElementById('subtab-domains-overview');
    if (el) {
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'padding:20px;text-align:center;color:var(--archie-text-secondary)';
        errDiv.textContent = 'Error loading domains: ' + e.message;
        el.textContent = '';
        el.appendChild(errDiv);
    }
}
```

- [ ] **Step 3: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open DNS tab, click Domains. Should show content or a clear error message.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "fix: wire DNS Domains subtab loading and add error display"
```

---

### Task 6: Load Font Awesome for Compliance Tab Icons

**Root cause:** The Compliance tab uses `fas fa-*` icons (Font Awesome Solid) but no Font Awesome CSS is loaded.

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html` (extra_css block)

- [ ] **Step 1: Add Font Awesome CDN to the template's extra CSS**

Find the `{% block extra_css %}` section near the top of `security_network.html`. Add the Font Awesome CDN link before the module CSS:

```html
{% block extra_css %}
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" crossorigin="anonymous">
<link rel="stylesheet" href="{{ url_for('static', filename='css/security-network.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/security-network-theme-vars.css') }}">
{% endblock %}
```

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open Compliance tab. The PDF, Export, Evidence, Run Scan buttons should now show their icons.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "fix: add Font Awesome CSS for compliance tab icons"
```

---

### Task 7: Fix Duplicate Report History Section

**Root cause:** The Reports tab has two "Report History" sections. The first one at line 1227 is populated by `/api/reports/list` and works. The second one at line 1276 is a legacy duplicate showing "No reports generated yet".

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html:1275-1290`

- [ ] **Step 1: Remove the duplicate legacy Report History**

Find the second "Report History" section starting around line 1275:

```html
        <!-- Report History -->
        <div id="sn-report-list" class="sn-card" style="margin-top: 20px;">
            <h3 style="margin:0;color:var(--archie-text-primary)">Report History</h3>
```

Remove this entire card div (from the comment to its closing `</div>`). Keep the first Report History at line 1227.

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open Reports tab. Should show only ONE "Report History" section.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "fix: remove duplicate Report History section in Reports tab"
```

---

### Task 8: Fix System Alert Banner (Global Issue)

**Root cause:** The "System Alert - Loading..." banner is from `base.html` line 80. It's a global admin notification banner that starts visible with "Loading..." text. If no notifications are found by the polling JS, it stays visible forever.

**Note:** This affects ALL admin pages, not just Security Network. Be careful.

**Files:**
- Modify: `platform_v2/templates/base.html:80` area

- [ ] **Step 1: Read the notification banner and polling code**

Read `base.html` around lines 75-90 (HTML) and 220-250 (JS polling). Understand the full flow: banner HTML -> JS polls `/api/notifications` -> populates or hides.

- [ ] **Step 2: Set initial state to hidden**

Find the banner div (around line 80) and add `style="display:none"`:

```html
<div id="adminNotifyBanner" class="admin-notification-bar" style="display:none">
```

This ensures the banner only appears when a real notification arrives.

- [ ] **Step 3: Show banner only when notification exists**

In the polling JS (around line 236), ensure the banner is shown when a notification is received:

```javascript
if (notification && notification.message) {
    document.getElementById('adminNotifyBanner').style.display = '';
    titleEl.textContent = notification.title || 'System Alert';
    messageEl.textContent = notification.message;
} else {
    document.getElementById('adminNotifyBanner').style.display = 'none';
}
```

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open any admin page. The "System Alert - Loading..." banner should no longer appear unless there's an actual notification.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/base.html
git commit -m "fix: hide admin notification banner when no notifications available"
```

---

## Verification Checklist

After all 8 tasks are complete, do a full pass through every tab:

- [ ] **Overview**: Hero stats display, service health works, no stale "System Alert" banner
- [ ] **Traffic**: Client activity and bandwidth data displays
- [ ] **DNS > all 7 subtabs**: All functional (Domains shows content or clear error)
- [ ] **Devices**: Device consumption loads (empty table OK, no 500 error)
- [ ] **Defense**: UFW firewall shows status and rules, fail2ban works, DDNS works
- [ ] **Scanners**: All 3 subtabs switch correctly, no content bleeding
- [ ] **Compliance**: Icons display correctly (Font Awesome loaded)
- [ ] **Reports**: Single Report History section, no duplicate

Take screenshots of each tab as evidence. No console errors except expected warnings.
