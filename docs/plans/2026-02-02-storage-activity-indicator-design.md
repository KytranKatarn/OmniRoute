# Storage Tab Activity Indicator & Notification System

**Date:** 2026-02-02
**Status:** Approved
**Module:** System Operations - Storage Tab

---

## Overview

Improve the user experience for storage operations (extend, shrink, resize, mount/unmount) by adding:

1. A persistent activity status bar showing ongoing operations
2. Completion notifications that require manual dismissal
3. Live elapsed timer with operation stage information
4. Pre-flight checks to detect issues before operations start

## Problem Statement

Current issues with storage operations UX:

- No indication that an operation is still processing after the modal closes
- Completion toasts auto-dismiss before user can read them (6 seconds)
- Timer shows elapsed time but no detail about what stage the operation is in
- Operations can fail due to stale mounts or busy devices with no pre-warning

## Design

### 1. Activity Status Bar

**Location:** Below the header controls (near auto-refresh toggle)

**Structure:**
```html
<div class="activity-status-bar" id="activityStatusBar">
    <div class="activity-indicator">
        <span class="pulse-dot"></span>
        <span class="activity-text">Extending volume media-drive...</span>
        <span class="activity-timer">45s</span>
        <span class="activity-stage">(Running resize2fs)</span>
    </div>
</div>
```

**Styling:**
- Background: subtle gradient matching header style
- Height: ~32px, same border treatment as header
- Pulse dot: animated green glow (matches existing live indicator)
- Text: operation name in white, timer in cyan, stage in muted text

**Behavior:**
- Only visible when operations are active (hidden when idle)
- Slides down smoothly when operation starts
- Updates every second with elapsed time
- Stage text updates as operation progresses
- Slides up when all operations complete
- Supports multiple concurrent operations

---

### 2. Persistent Completion Notifications

**Changes to `showCompletionMessage()`:**

Current behavior: Auto-dismisses after 6 seconds
New behavior: Stays until manually dismissed

**New Toast Structure:**
```html
<div class="toast success persistent">
    <div class="toast-header">
        <i data-lucide="check-circle"></i>
        <strong>Extend Volume Complete</strong>
        <button class="toast-close" onclick="this.parentElement.parentElement.remove()">×</button>
    </div>
    <div class="toast-body">
        <span>Extended media-drive by 800 GB</span>
        <span class="toast-meta">Duration: 24s • Containers restarted: 1</span>
    </div>
</div>
```

**Toast Types:**
| Type | Color | Icon | Use Case |
|------|-------|------|----------|
| Success | Green | check-circle | Operation completed successfully |
| Error | Red | x-circle | Operation failed |
| Warning | Orange | alert-triangle | Partial success (e.g., extended but resize failed) |

**Features:**
- Close button (X) in top-right corner
- Shows duration and affected containers
- Multiple toasts stack vertically
- Wider toast (~350px) for more detail

---

### 3. Live Timer & Stage Tracking

**Operation Tracker System:**

```javascript
// Global operation tracker
const activeOperations = new Map();

function trackOperation(commandId, label) {
    activeOperations.set(commandId, {
        label: label,
        startTime: Date.now(),
        stage: 'Submitting...',
        commandId: commandId
    });
    updateActivityStatusBar();
    startActivityTimer();
}

function updateOperationStage(commandId, stage) {
    const op = activeOperations.get(commandId);
    if (op) {
        op.stage = stage;
        updateActivityStatusBar();
    }
}

function completeOperation(commandId) {
    activeOperations.delete(commandId);
    updateActivityStatusBar();
    if (activeOperations.size === 0) {
        stopActivityTimer();
    }
}
```

**Stage Detection from Backend Responses:**

| Backend Signal | Display Stage |
|----------------|---------------|
| Command submitted | "Queued..." |
| 202 status (pending) | "Executing..." |
| Result has `containers_stopped` | "Stopping containers..." |
| Result mentions resize2fs | "Resizing filesystem..." |
| Result has `containers_restarted` | "Restarting containers..." |
| Refreshing data | "Verifying changes..." |

**Timer Format:**
- Under 2 minutes: `45s`
- 2+ minutes: `2m 15s`

---

### 4. Pre-flight Checks

**New API Endpoint:**

```python
@system_operations_bp.route("/api/storage/preflight", methods=["POST"])
@login_required
@admin_required
def api_storage_preflight():
    """Check for issues before a storage operation."""
    device = request.json.get('device')
    mountpoint = request.json.get('mountpoint')
    operation = request.json.get('operation')  # extend, shrink, resize, unmount

    warnings = []

    # Check 1: Containers using the mount
    containers = get_containers_using_mount(mountpoint)
    if containers:
        warnings.append({
            'type': 'containers',
            'message': f'{len(containers)} containers will be stopped',
            'details': containers
        })

    # Check 2: Stale mount detection
    if is_stale_mount(device, mountpoint):
        warnings.append({
            'type': 'stale_mount',
            'message': 'Stale mount detected - device path may have changed',
            'severity': 'high'
        })

    # Check 3: Device busy
    if is_device_busy(device):
        warnings.append({
            'type': 'busy',
            'message': 'Device is currently in use'
        })

    return jsonify({
        'success': True,
        'warnings': warnings,
        'can_proceed': len([w for w in warnings if w.get('severity') == 'high']) == 0
    })
```

**Frontend Pre-flight Flow:**

1. User clicks Extend/Shrink/Resize button
2. Call `/api/storage/preflight` with device and operation
3. If warnings exist, show confirmation modal:
   ```
   ⚠️ Pre-flight Check

   The following conditions were detected:
   • 3 containers will be stopped: plex, radarr, sonarr
   • Device is currently in use

   [Cancel]  [Proceed Anyway]
   ```
4. User clicks "Proceed Anyway" → continue with operation
5. No warnings → proceed immediately

---

## Files to Modify

| File | Changes |
|------|---------|
| `platform_v2/templates/tools/system_operations.html` | Add status bar HTML/CSS, modify JS for tracker and notifications |
| `platform_v2/tools/system_operations/routes.py` | Add `/api/storage/preflight` endpoint |
| `scripts/host_monitor.py` | Already has container detection from earlier work |

## Implementation Order

1. **Activity Status Bar** - HTML structure, CSS styling, basic show/hide
2. **Persistent Notifications** - Modify `showCompletionMessage()`, add close button
3. **Operation Tracker** - Create `activeOperations` Map, timer interval, stage updates
4. **Wire to submitHostCommand()** - Integrate tracker with existing command flow
5. **Pre-flight API** - Add endpoint in routes.py
6. **Pre-flight UI** - Add confirmation modal flow before operations

## Success Criteria

- [ ] Activity bar appears when storage operation starts
- [ ] Timer counts up in real-time
- [ ] Stage text updates as operation progresses
- [ ] Activity bar hides when operation completes
- [ ] Completion toast stays until user dismisses it
- [ ] Toast shows duration and affected containers
- [ ] Pre-flight check warns about containers that will be stopped
- [ ] Pre-flight detects stale mounts before operation fails
