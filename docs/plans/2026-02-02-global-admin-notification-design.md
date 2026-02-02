# Global Admin Notification System

**Date:** 2026-02-02
**Status:** Approved
**Module:** Platform-wide (base.html)

---

## Overview

Create a platform-wide notification system that:
1. Shows critical alerts to admin users regardless of which module they're viewing
2. Broadcasts notifications across all open browser tabs
3. Slides in from the top with a dismissable notification bar
4. Persists until manually dismissed

## Problem Statement

Current issues:
- Storage operation status only visible on the Storage tab
- Admins navigating to other modules miss important operation updates
- No centralized system for cross-page admin alerts
- Health warnings, storage operations, and system events have no global visibility

## Design

### 1. Notification Bar Component

**Location:** Top of every page (in base.html, above flash messages)

**Structure:**
```html
<div id="adminNotificationBar" class="admin-notification-bar hidden">
    <div class="admin-notification-content">
        <div class="admin-notification-icon">
            <i data-lucide="bell-ring"></i>
        </div>
        <div class="admin-notification-message">
            <span class="notification-title">Storage Operation</span>
            <span class="notification-text">Extending media-drive... (45s)</span>
        </div>
        <button class="admin-notification-close" onclick="dismissAdminNotification()">
            <i data-lucide="x"></i>
        </button>
    </div>
</div>
```

**Styling:**
- Fixed position at top of viewport
- Full width, height ~48px
- Background: gradient with subtle glow (cyan/purple)
- Slide-down animation on show, slide-up on dismiss
- Z-index above everything (10001)
- Close button on right side

### 2. Cross-Tab Communication

**Using BroadcastChannel API:**
```javascript
const adminNotifyChannel = new BroadcastChannel('archie_admin_notifications');

// Send notification to all tabs
function broadcastAdminNotification(notification) {
    adminNotifyChannel.postMessage(notification);
}

// Receive notifications from other tabs
adminNotifyChannel.onmessage = (event) => {
    showAdminNotification(event.data);
};
```

### 3. Notification Types

| Type | Color | Icon | Use Case |
|------|-------|------|----------|
| operation | Cyan | activity | Storage operations in progress |
| success | Green | check-circle | Operation completed |
| warning | Orange | alert-triangle | System warnings |
| error | Red | x-circle | Operation failed |
| info | Purple | info | General admin info |

### 4. API Integration

**New Endpoint (optional for server-push):**
```python
@app.route("/api/admin/notifications")
@login_required
@admin_required
def get_admin_notifications():
    """Get pending admin notifications."""
    # Could poll this endpoint for server-side events
    return jsonify({"notifications": []})
```

**Primary method:** Client-side BroadcastChannel for instant cross-tab sync.

### 5. Integration Points

Modules that will broadcast admin notifications:
- **System Operations (Storage):** Operation start, progress, completion
- **Health Monitoring:** Critical health alerts
- **Docker Management:** Container issues
- **Backup System:** Backup status changes

---

## Files to Modify

| File | Changes |
|------|---------|
| `platform_v2/templates/base.html` | Add notification bar HTML, CSS, and JS |
| `platform_v2/templates/tools/system_operations.html` | Broadcast storage operations to global system |

## Implementation

### Phase 1: Base Infrastructure
1. Add notification bar HTML to base.html
2. Add CSS styling matching ARCHIE theme
3. Add JavaScript for show/hide/dismiss functionality
4. Add BroadcastChannel setup

### Phase 2: Storage Integration
1. Modify system_operations.html to broadcast operation events
2. Send notifications on: operation start, stage change, completion

## Success Criteria

- [ ] Admin notification bar visible on all pages when active
- [ ] Notifications appear in real-time across browser tabs
- [ ] Non-admin users never see the notification bar
- [ ] Notifications persist until manually dismissed
- [ ] Smooth slide-in/slide-out animations
- [ ] Storage operations broadcast their status globally
