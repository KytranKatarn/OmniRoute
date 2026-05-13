# DHQ API Access Tab Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser-native `confirm()`/`prompt()` dialogs in the API Access tab with LCARS modals, and purge the dead test device.

**Architecture:** Three targeted edits: (1) one SQL DELETE, (2) three `bm-overlay` modal blocks added to `panel-devices` HTML, (3) three JS functions rewritten + button render updated in `department-hq.js`. No new files, no backend changes.

**Tech Stack:** Vanilla JS (inline in `department-hq.js`), Jinja2 template (`department_hq.html`), PostgreSQL (one-time DELETE).

---

## File Map

| File | Action |
|------|--------|
| `platform_v2/tools/department_hq/templates/department_hq.html` | Add 3 bm-overlay modals inside `panel-devices` |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Rewrite `approveDevice`, `denyDevice`, `revokeDevice`; update button render in `loadDevices`; add `confirmDenyDevice`, `confirmRevokeDevice`, `copyDeviceKey` |

---

## Task 1: Delete Dead Test Device

- [ ] **Step 1: Verify the device exists**

```bash
docker exec archie_database psql -U archie -d archie -t -c \
  "SELECT id, device_name, status, request_count FROM registered_devices;"
```

Expected: one row — id=1, test-cli-device, revoked, 0 requests.

- [ ] **Step 2: Delete it**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "DELETE FROM registered_devices WHERE id = 1 AND status = 'revoked';"
```

Expected: `DELETE 1`

- [ ] **Step 3: Verify empty**

```bash
docker exec archie_database psql -U archie -d archie -t -c \
  "SELECT COUNT(*) FROM registered_devices;"
```

Expected: `0`

No commit needed — DB change only, no code modified.

---

## Task 2: Add LCARS Modals to panel-devices

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Find the insertion point**

```bash
grep -n "devicesContent\|END.*devices\|panel-dispatch" \
  platform_v2/tools/department_hq/templates/department_hq.html | head -10
```

Note the line of `<div id="devicesContent" class="dhq-loading">Loading devices...</div>`. Insert the three modals immediately AFTER this line, still inside `<div class="dhq-panel" id="panel-devices">`.

- [ ] **Step 2: Insert the three modals**

Add this block immediately after `<div id="devicesContent" class="dhq-loading">Loading devices...</div>`:

```html
      <!-- Device Deny Confirm Modal -->
      <div class="bm-overlay" id="deviceDenyModal" style="display:none" onclick="if(event.target===this)this.style.display='none'">
        <div class="bm-shell" style="--bm-accent:#ef4444;">
          <div class="bm-frame"></div>
          <div class="bm-content">
            <div class="bm-header"><span class="bm-header-title">DENY DEVICE</span></div>
            <div class="bm-body">
              <p id="deviceDenyName" style="font-family:'IBM Plex Mono',monospace;font-size:0.9rem;margin-bottom:8px;"></p>
              <p style="color:var(--dhq-text-dim);font-size:0.85rem;">This device will be denied access and cannot be re-approved.</p>
            </div>
            <div class="bm-footer">
              <button onclick="confirmDenyDevice()" style="background:#ef4444;color:#fff;border:none;padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;">CONFIRM</button>
              <button onclick="document.getElementById('deviceDenyModal').style.display='none'" style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.2);color:var(--dhq-text);padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;">CANCEL</button>
            </div>
          </div>
        </div>
      </div>
      <!-- Device Revoke Confirm Modal -->
      <div class="bm-overlay" id="deviceRevokeModal" style="display:none" onclick="if(event.target===this)this.style.display='none'">
        <div class="bm-shell" style="--bm-accent:#ef4444;">
          <div class="bm-frame"></div>
          <div class="bm-content">
            <div class="bm-header"><span class="bm-header-title">REVOKE ACCESS</span></div>
            <div class="bm-body">
              <p id="deviceRevokeName" style="font-family:'IBM Plex Mono',monospace;font-size:0.9rem;margin-bottom:8px;"></p>
              <p style="color:var(--dhq-text-dim);font-size:0.85rem;">This device will lose all access immediately.</p>
            </div>
            <div class="bm-footer">
              <button onclick="confirmRevokeDevice()" style="background:#ef4444;color:#fff;border:none;padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;">CONFIRM</button>
              <button onclick="document.getElementById('deviceRevokeModal').style.display='none'" style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.2);color:var(--dhq-text);padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;">CANCEL</button>
            </div>
          </div>
        </div>
      </div>
      <!-- Device API Key Display Modal -->
      <div class="bm-overlay" id="deviceKeyModal" style="display:none" onclick="if(event.target===this)this.style.display='none'">
        <div class="bm-shell" style="--bm-accent:#00e5ff;">
          <div class="bm-frame"></div>
          <div class="bm-content">
            <div class="bm-header"><span class="bm-header-title">API KEY ISSUED</span></div>
            <div class="bm-body">
              <p style="color:#f59e0b;font-size:0.8rem;margin-bottom:12px;">&#9888; This key will not be shown again. Copy it now.</p>
              <pre id="deviceKeyValue" style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;background:rgba(0,0,0,0.4);border:1px solid rgba(0,229,255,0.3);border-radius:4px;padding:10px;word-break:break-all;white-space:pre-wrap;color:#00e5ff;margin:0;"></pre>
            </div>
            <div class="bm-footer">
              <button id="deviceKeyCopyBtn" onclick="copyDeviceKey()" style="background:#00e5ff;color:#010409;border:none;padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;font-weight:600;">COPY KEY</button>
              <button onclick="document.getElementById('deviceKeyModal').style.display='none'" style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.2);color:var(--dhq-text);padding:6px 18px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;font-size:0.8rem;">CLOSE</button>
            </div>
          </div>
        </div>
      </div>
```

- [ ] **Step 3: Verify insertion**

```bash
grep -n "deviceDenyModal\|deviceRevokeModal\|deviceKeyModal" \
  platform_v2/tools/department_hq/templates/department_hq.html
```

Expected: 3 lines — each modal id appears once.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): add LCARS confirm + API key modals to API Access tab"
```

---

## Task 3: Rewrite JS Functions

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

### Step 1: Find the three functions to replace

```bash
grep -n "async function approveDevice\|async function denyDevice\|async function revokeDevice" \
  platform_v2/tools/department_hq/static/js/department-hq.js
```

Note the line numbers.

### Step 2: Replace `approveDevice`

Find and replace the entire `approveDevice` function. Current:
```javascript
async function approveDevice(deviceId) {
    try {
        var resp = await fetch(DHQ_BASE + '/api/auth/approve/' + deviceId, {method: 'POST'});
        var data = await resp.json();
        if (data.api_key) {
            // Show in a prompt so user can copy — alert may truncate
            prompt('API Key (copy this — shown once only):', data.api_key);
        }
        loadDevices();
    } catch (err) {
        alert('Error approving device: ' + err.message);
    }
}
```

Replace with:
```javascript
async function approveDevice(deviceId) {
    try {
        var resp = await fetch(DHQ_BASE + '/api/auth/approve/' + deviceId, {method: 'POST'});
        var data = await resp.json();
        if (data.api_key) {
            document.getElementById('deviceKeyValue').textContent = data.api_key;
            var copyBtn = document.getElementById('deviceKeyCopyBtn');
            if (copyBtn) copyBtn.textContent = 'COPY KEY';
            document.getElementById('deviceKeyModal').style.display = 'flex';
        }
        loadDevices();
    } catch (err) {
        console.error('Error approving device:', err);
    }
}
```

### Step 3: Replace `denyDevice`

Current:
```javascript
async function denyDevice(deviceId) {
    if (!confirm('Deny this device registration?')) return;
    try {
        await fetch(DHQ_BASE + '/api/auth/deny/' + deviceId, {method: 'POST'});
        loadDevices();
    } catch (err) {
        alert('Error denying device: ' + err.message);
    }
}
```

Replace with:
```javascript
function denyDevice(deviceId, deviceName) {
    window._dhqPendingDenyId = deviceId;
    document.getElementById('deviceDenyName').textContent = deviceName;
    document.getElementById('deviceDenyModal').style.display = 'flex';
}

function confirmDenyDevice() {
    var id = window._dhqPendingDenyId;
    window._dhqPendingDenyId = null;
    document.getElementById('deviceDenyModal').style.display = 'none';
    fetch(DHQ_BASE + '/api/auth/deny/' + id, {method: 'POST'})
        .then(function() { loadDevices(); })
        .catch(function(err) { console.error('Error denying device:', err); });
}
```

### Step 4: Replace `revokeDevice`

Current:
```javascript
async function revokeDevice(deviceId) {
    if (!confirm('Revoke this device? It will lose all access immediately.')) return;
    try {
        await fetch(DHQ_BASE + '/api/auth/revoke/' + deviceId, {method: 'POST'});
        loadDevices();
    } catch (err) {
        alert('Error revoking device: ' + err.message);
    }
}
```

Replace with:
```javascript
function revokeDevice(deviceId, deviceName) {
    window._dhqPendingRevokeId = deviceId;
    document.getElementById('deviceRevokeName').textContent = deviceName;
    document.getElementById('deviceRevokeModal').style.display = 'flex';
}

function confirmRevokeDevice() {
    var id = window._dhqPendingRevokeId;
    window._dhqPendingRevokeId = null;
    document.getElementById('deviceRevokeModal').style.display = 'none';
    fetch(DHQ_BASE + '/api/auth/revoke/' + id, {method: 'POST'})
        .then(function() { loadDevices(); })
        .catch(function(err) { console.error('Error revoking device:', err); });
}
```

### Step 5: Add `copyDeviceKey` function

Add this function immediately after `confirmRevokeDevice`:

```javascript
function copyDeviceKey() {
    var key = document.getElementById('deviceKeyValue').textContent;
    navigator.clipboard.writeText(key).then(function() {
        var btn = document.getElementById('deviceKeyCopyBtn');
        if (btn) {
            btn.textContent = 'COPIED ✓';
            setTimeout(function() { btn.textContent = 'COPY KEY'; }, 3000);
        }
    }).catch(function(err) { console.error('Clipboard write failed:', err); });
}
```

### Step 6: Update button render in `loadDevices`

Find the button render block inside `loadDevices`. It currently reads:

```javascript
            if (d.status === 'pending') {
                html += '<button class="dhq-btn dhq-btn-approve" onclick="approveDevice(' + d.id + ')">Approve</button>'
                    + '<button class="dhq-btn dhq-btn-deny" onclick="denyDevice(' + d.id + ')">Deny</button>';
            } else if (d.status === 'approved') {
                html += '<button class="dhq-btn dhq-btn-revoke" onclick="revokeDevice(' + d.id + ')">Revoke</button>';
            }
```

Replace with:

```javascript
            if (d.status === 'pending') {
                html += '<button class="dhq-btn dhq-btn-approve" onclick="approveDevice(' + d.id + ')">Approve</button>'
                    + '<button class="dhq-btn dhq-btn-deny" onclick="denyDevice(' + d.id + ', \'' + esc(d.device_name) + '\')">Deny</button>';
            } else if (d.status === 'approved') {
                html += '<button class="dhq-btn dhq-btn-revoke" onclick="revokeDevice(' + d.id + ', \'' + esc(d.device_name) + '\')">Revoke</button>';
            }
```

- [ ] **Step 7: Verify no confirm() or prompt() remain in device functions**

```bash
grep -n "confirm(\|prompt(" platform_v2/tools/department_hq/static/js/department-hq.js | grep -i device
```

Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq): replace confirm()/prompt() with LCARS modals in API Access tab"
```

---

## Task 4: Deploy, Verify, PR

- [ ] **Step 1: Deploy**

```bash
docker compose restart archie_platform
sleep 12
docker logs archie_platform 2>&1 | grep -iE "error|traceback" | grep -v "^$" | tail -5
```

Expected: no errors.

- [ ] **Step 2: Register a test device for verification**

Use Playwright to open `http://192.168.1.200:3000/tools/department-hq` (logged in as admin), navigate to API Access tab. The tab should show "No devices found" (test device was deleted).

Then register a test device via the API (use browser dev tools or curl from a terminal the user controls — this is a public endpoint):

```bash
# Run from a terminal on any machine:
curl -s -X POST http://192.168.1.200:3000/tools/department-hq/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"device_name":"test-modal-device","device_type":"cli","hostname":"localhost","purpose":"modal testing"}' \
  | python3 -m json.tool
```

Expected: `{"device_id": N, "status": "pending", "message": "..."}`

- [ ] **Step 3: Browser verify**

Using the archie-platform-login skill to get a session, then:

1. DHQ → API Access tab — "test-modal-device" appears with PENDING status
2. Click **Deny** → `deviceDenyModal` opens (red accent, device name shown, CONFIRM + CANCEL buttons)
3. Click CANCEL → modal closes, device still pending
4. Click **Approve** → `deviceKeyModal` opens (cyan accent, key in monospace box, warning shown)
5. Click COPY KEY → button changes to "COPIED ✓" for 3 seconds
6. Click CLOSE → modal closes, device reloads as approved
7. Click **Revoke** → `deviceRevokeModal` opens (red accent, device name shown)
8. Click CONFIRM → modal closes, device becomes revoked
9. Open browser console — confirm no `confirm()` or `prompt()` calls fired at any point

- [ ] **Step 4: Clean up test device after verification**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "DELETE FROM registered_devices WHERE device_name = 'test-modal-device';"
```

- [ ] **Step 5: Push and open PR**

```bash
git push origin HEAD
gh pr create \
  --title "feat(dhq): replace confirm()/prompt() with LCARS modals in API Access tab" \
  --body "$(cat <<'EOF'
## Summary
- Deleted dead revoked test device (id=1, 0 requests, from March 2026)
- Replaced \`confirm()\` in deny + revoke flows with red LCARS bm-overlay confirm modals
- Replaced \`prompt()\` in approve flow with cyan LCARS modal — monospace key box + COPY KEY button (3s feedback)
- Button render now passes device name to modal functions so modal body shows the device name
- No backend changes — all existing auth_routes.py endpoints unchanged

## Test plan
- [ ] API Access tab shows empty state (no devices)
- [ ] Register test device via POST /api/auth/register → appears as pending
- [ ] Approve → deviceKeyModal opens with key, COPY KEY button works
- [ ] Revoke → deviceRevokeModal opens, CANCEL works, CONFIRM revokes
- [ ] No native confirm() or prompt() dialogs fire at any point

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- DB cleanup: Task 1 ✅
- Modal A (deny confirm): Task 2 HTML + Task 3 `denyDevice`/`confirmDenyDevice` ✅
- Modal B (revoke confirm): Task 2 HTML + Task 3 `revokeDevice`/`confirmRevokeDevice` ✅
- Modal C (key display): Task 2 HTML + Task 3 `approveDevice`/`copyDeviceKey` ✅
- Pass device name to modals: Task 3 Step 6 button render ✅
- `navigator.clipboard.writeText()` for COPY KEY: Task 3 Step 5 ✅
- No `confirm()`/`prompt()` remaining: Task 3 Step 7 verification ✅

**Placeholder scan:** No TBD, no TODO, no incomplete steps. All code is complete.

**Type consistency:**
- `deviceDenyModal` — defined in Task 2 HTML, referenced in `denyDevice()` and `confirmDenyDevice()` Task 3 ✅
- `deviceRevokeModal` — defined in Task 2 HTML, referenced in `revokeDevice()` and `confirmRevokeDevice()` Task 3 ✅
- `deviceKeyModal` — defined in Task 2 HTML, referenced in `approveDevice()` Task 3 ✅
- `deviceDenyName` — defined in Task 2 HTML, set in `denyDevice()` Task 3 ✅
- `deviceRevokeName` — defined in Task 2 HTML, set in `revokeDevice()` Task 3 ✅
- `deviceKeyValue` — defined in Task 2 HTML, set in `approveDevice()` and read in `copyDeviceKey()` Task 3 ✅
- `deviceKeyCopyBtn` — defined in Task 2 HTML, referenced in `approveDevice()` and `copyDeviceKey()` Task 3 ✅
- `confirmDenyDevice` — defined in Task 3, called from Task 2 HTML button ✅
- `confirmRevokeDevice` — defined in Task 3, called from Task 2 HTML button ✅
- `copyDeviceKey` — defined in Task 3, called from Task 2 HTML button ✅
