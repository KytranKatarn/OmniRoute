# A.R.C.H.I.E. Notification System

## Overview

The A.R.C.H.I.E. Notification System is a centralized, feature-rich notification management platform that provides real-time alerts, comprehensive filtering, and intelligent priority handling across the dashboard.

**Version:** 2.0 (Enhanced)
**Last Updated:** December 31, 2025

---

## ⚠️ MANDATORY STANDARD FOR ALL ADMIN FEATURES

**IMPORTANT:** This notification system is the **required standard** for ALL dashboard features, tools, and applications.

### Compliance Requirements

**✅ ALL admin features MUST:**
- Use the centralized notification system for user feedback
- Call `showSuccess()`, `showError()`, `showWarning()`, or `showInfo()` for all operations
- Never use browser `alert()`, `confirm()`, or `console.log()` for user-facing messages
- Follow the priority guidelines (Critical, High, Normal, Low)
- Include appropriate source icons for visual identification

**❌ DO NOT:**
- Create custom notification/alert systems
- Use popup dialogs for operation feedback
- Display messages only in browser console
- Bypass the centralized notification API

### Why This Matters

1. **Consistency:** Users always know where to find notifications
2. **Auditability:** All actions are logged and searchable
3. **Never Miss Critical Alerts:** Unread counter forces awareness
4. **Centralized Management:** Filter, search, export all admin activity
5. **Future-Proof:** New features integrate seamlessly

### For New Features/Tools

When creating new admin features:
```javascript
// ✅ CORRECT: Use centralized notification system
async function myNewAdminFeature() {
    const result = await performOperation();

    if (result.success) {
        showSuccess('Operation completed successfully');
    } else {
        showError('Operation failed: ' + result.error);
    }
}

// ❌ INCORRECT: Don't use alerts
async function myNewAdminFeature() {
    alert('Operation completed');  // DON'T DO THIS
}
```

---

## Features

### Core Features
- ✅ **Centralized Notification Center** - All admin messages appear in one location
- ✅ **Priority-Based System** - Critical, High, Normal, and Low priority levels
- ✅ **Intelligent Grouping** - Duplicate notifications are automatically grouped
- ✅ **Deduplication** - Prevents notification spam within 5-minute windows
- ✅ **Advanced Filtering** - Filter by type, priority, date range, and status
- ✅ **Full-Text Search** - Search notifications by message content
- ✅ **Pagination** - Efficient handling of thousands of notifications
- ✅ **Auto-Refresh** - Counter updates every 30 seconds automatically
- ✅ **Export** - Download notifications as CSV or JSON
- ✅ **Archive System** - Auto-archive old read notifications
- ✅ **Keyboard Shortcuts** - Fast navigation and actions
- ✅ **Click-to-Dismiss** - Single click to mark notifications as read
- ✅ **Visual Priority Indicators** - Color-coded borders and pulsing animations
- ✅ **Relative Timestamps** - Human-readable time display ("5m ago", "2h ago")

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    ADMIN PANEL UI                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Filters    │  │    Search    │  │  Pagination  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌────────────────────────────────────────────────────┐     │
│  │         Notification Feed Display                  │     │
│  │  (Priority indicators, grouping, click-to-dismiss) │     │
│  └────────────────────────────────────────────────────┘     │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  API Endpoints  │
                    │  (Flask Routes) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   PostgreSQL    │
                    │   Database      │
                    │system_notifications│
                    └─────────────────┘
```

---

## Database Schema

### Table: `system_notifications`

```sql
CREATE TABLE system_notifications (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(50),                  -- 'success', 'error', 'warning', 'info'
    title           VARCHAR(255),                 -- Notification title
    message         TEXT,                         -- Notification message
    source          VARCHAR(100),                 -- Source of notification (e.g., 'admin-panel', 'github', 'system')
    priority        VARCHAR(20) DEFAULT 'normal', -- 'critical', 'high', 'normal', 'low'
    source_icon     VARCHAR(10) DEFAULT '📋',     -- Emoji icon for visual identification
    grouped_count   INTEGER DEFAULT 1,            -- Number of grouped duplicates
    related_action  VARCHAR(100),                 -- Optional quick action link
    is_read         BOOLEAN DEFAULT FALSE,        -- Read status
    is_archived     BOOLEAN DEFAULT FALSE,        -- Archive status
    created_at      TIMESTAMP DEFAULT NOW(),      -- Creation timestamp
    expires_at      TIMESTAMP                     -- Optional expiration
);

-- Indexes for performance
CREATE INDEX idx_notifications_priority ON system_notifications(priority, created_at DESC);
CREATE INDEX idx_notifications_archived ON system_notifications(is_archived, created_at DESC);
CREATE INDEX idx_notifications_source ON system_notifications(source);
CREATE INDEX idx_notifications_type ON system_notifications(type);
CREATE INDEX idx_notifications_unread ON system_notifications(is_read, created_at);
```

### Priority Levels

| Priority  | Use Case | Visual Indicator | Behavior |
|-----------|----------|-----------------|----------|
| **Critical** | System failures, security alerts | 🔴 Red border + pulsing animation | Shown first, never auto-archived |
| **High** | Errors, failed operations | 🟠 Orange border | Shown after critical |
| **Normal** | Successful operations, general info | 🟢 Green border | Standard display |
| **Low** | Minor updates, FYI messages | ⚪ Gray border | Shown last |

---

## API Endpoints

### 1. Create Notification
**Endpoint:** `POST /api/notifications`

**Description:** Create a new notification with automatic grouping and deduplication.

**Request Body:**
```json
{
    "type": "success",           // Required: success|error|warning|info
    "title": "Admin Action",     // Required
    "message": "Settings saved", // Required
    "source": "admin-panel",     // Optional, default: 'system'
    "priority": "normal",        // Optional: critical|high|normal|low
    "source_icon": "✅",         // Optional: emoji icon
    "related_action": "/settings" // Optional: quick action URL
}
```

**Response:**
```json
{
    "success": true,
    "id": 123,                    // Notification ID
    "grouped": false              // true if grouped with existing notification
}
```

**Deduplication Logic:**
- Checks for duplicate within last 5 minutes
- If duplicate found: increments `grouped_count` and updates timestamp
- If no duplicate: creates new notification

---

### 2. Get Notification Count
**Endpoint:** `GET /api/notifications/count`

**Description:** Get real-time notification counts for dashboard.

**Response:**
```json
{
    "success": true,
    "unread": 15,      // Total unread notifications
    "critical": 2,     // Unread critical notifications
    "errors": 5        // Unread error notifications
}
```

**Usage:** Called automatically every 30 seconds by frontend

---

### 3. Search & Filter Notifications
**Endpoint:** `GET /api/notifications/search`

**Description:** Advanced search with filtering and pagination.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filter` | string | 'all' | 'all', 'unread', 'read' |
| `type` | string | 'all' | 'success', 'error', 'warning', 'info', 'all' |
| `priority` | string | 'all' | 'critical', 'high', 'normal', 'low', 'all' |
| `source` | string | 'all' | Filter by source name |
| `q` | string | '' | Search query (searches title and message) |
| `date_range` | string | 'all' | '24h', '7d', '30d', 'all' |
| `page` | integer | 1 | Page number |
| `per_page` | integer | 20 | Items per page |

**Example Request:**
```
GET /api/notifications/search?filter=unread&type=error&priority=critical&page=1
```

**Response:**
```json
{
    "success": true,
    "notifications": [
        {
            "id": 123,
            "type": "error",
            "title": "GitHub Clone Failed",
            "message": "Failed to clone repository: authentication error",
            "source": "github",
            "source_icon": "🔴",
            "priority": "critical",
            "grouped_count": 3,
            "related_action": "/config/github",
            "is_read": false,
            "created_at": "2025-12-31T10:30:00"
        }
    ],
    "total": 25,
    "page": 1,
    "per_page": 20,
    "total_pages": 2
}
```

---

### 4. Mark Notification as Read
**Endpoint:** `POST /api/notifications/mark-read/<id>`

**Description:** Mark a single notification as read.

**Response:**
```json
{
    "success": true
}
```

---

### 5. Mark All Notifications as Read
**Endpoint:** `POST /api/notifications/mark-all-read`

**Description:** Mark all unread notifications as read.

**Response:**
```json
{
    "success": true
}
```

---

### 6. Export Notifications
**Endpoint:** `GET /api/notifications/export?format=<csv|json>`

**Description:** Export up to 1000 notifications in CSV or JSON format.

**Query Parameters:**
- `format`: 'csv' or 'json' (default: 'csv')

**Response:** File download (notifications.csv or notifications.json)

---

### 7. Archive Old Notifications
**Endpoint:** `POST /api/notifications/archive-old`

**Description:** Archive read notifications older than specified days.

**Request Body:**
```json
{
    "days": 30  // Archive notifications older than 30 days
}
```

**Response:**
```json
{
    "success": true,
    "archived": 45  // Number of notifications archived
}
```

---

## Frontend Integration

### Creating Notifications

All admin actions automatically create notifications using the centralized system:

```javascript
// Success notification
showSuccess('GitHub settings saved successfully');

// Error notification
showError('Failed to clone repository');

// Warning notification
showWarning('API rate limit approaching');

// Info notification
showInfo('Background task started');
```

### Priority Auto-Detection

The system automatically assigns priorities based on:

1. **Message Type:**
   - `error` → High priority
   - `success` → Normal priority
   - `warning` → Normal priority
   - `info` → Low priority

2. **Critical Keywords:**
   - Messages containing "failed", "error", "critical", "urgent", "security" → Critical priority
   - Overrides type-based priority

3. **Custom Icons:**
   - `error` → ❌
   - `warning` → ⚠️
   - `success` → ✅
   - `info` → ℹ️
   - `critical` → 🚨

### Keyboard Shortcuts

When the Notifications section is active:

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + R` | Refresh notifications |
| `Ctrl/Cmd + A` | Mark all as read |
| `←` (Left Arrow) | Previous page |
| `→` (Right Arrow) | Next page |

---

## Usage Examples

### Example 1: Creating a Notification Programmatically

```python
# In any Flask route
from tools.admin.routes import create_notification

# Simple notification
create_notification(
    type='success',
    title='Backup Completed',
    message='Database backup completed successfully',
    source='backup-service'
)

# High-priority notification
create_notification(
    type='error',
    title='Security Alert',
    message='Multiple failed login attempts detected',
    source='security-monitor'
)
```

### Example 2: Using JavaScript in Dashboard

```javascript
// After saving settings
async function saveSettings() {
    const response = await fetch('/api/settings', {
        method: 'POST',
        body: JSON.stringify(settings)
    });

    if (response.ok) {
        showSuccess('Settings saved successfully');
    } else {
        showError('Failed to save settings');
    }
}
```

### Example 3: Bulk Operations with Grouping

```javascript
// Clone multiple repositories
async function cloneAllRepos() {
    for (const repo of repositories) {
        const response = await cloneRepo(repo);

        // These will be automatically grouped
        if (response.ok) {
            showSuccess(`Repository cloned: ${repo.name}`);
        }
    }

    // Result: "Repository cloned successfully ×11" instead of 11 separate notifications
}
```

---

## Best Practices

### 1. **Use Appropriate Priority Levels**
- Reserve `critical` for genuine emergencies (security, system failures)
- Use `high` for errors that require attention
- Use `normal` for successful operations
- Use `low` for informational messages

### 2. **Write Clear, Actionable Messages**
```javascript
// ❌ Bad: Vague message
showError('Error occurred');

// ✅ Good: Clear, actionable message
showError('Failed to connect to GitHub API. Check your authentication token in Settings.');
```

### 3. **Include Source Icons**
```javascript
// Helps users quickly identify the source
saveNotificationToDatabase('Deployment completed', 'success', {
    source: 'deployment',
    source_icon: '🚀'
});
```

### 4. **Leverage Grouping for Bulk Operations**
- The system automatically groups duplicate messages within 5 minutes
- Perfect for loops and batch operations
- Reduces notification clutter

### 5. **Use Related Actions**
```python
# Add quick action link for user convenience
create_notification(
    type='warning',
    title='GitHub Token Expiring',
    message='Your GitHub token expires in 7 days',
    related_action='/config/github'  # Quick link to fix
)
```

---

## Configuration

### Auto-Refresh Interval
Default: 30 seconds

To change, edit `modular templates`:
```javascript
// Change 30000 to desired milliseconds
setInterval(updateNotificationCounts, 30000);
```

### Deduplication Window
Default: 5 minutes

To change, edit `/tools/ (now split into standalone modules)`:
```python
# Line ~492
WHERE created_at > NOW() - INTERVAL '5 minutes'
# Change '5 minutes' to desired duration
```

### Pagination Size
Default: 20 notifications per page

To change, edit `modular templates`:
```javascript
// Line ~7010
per_page: 20  // Change to desired number
```

### Archive Threshold
Default: 30 days

Users can specify custom threshold when archiving. To change default, edit `modular templates`:
```javascript
// Line ~7123
const days = prompt('Archive notifications older than how many days?', '30');
// Change '30' to desired default
```

---

## Troubleshooting

### Issue: Notifications not appearing

**Solution:**
1. Check browser console for JavaScript errors
2. Verify API endpoint is accessible: `GET /api/notifications/count`
3. Check database connection
4. Verify `system_notifications` table exists

### Issue: Duplicate notifications not grouping

**Possible Causes:**
- Different message text (grouping requires exact match)
- More than 5 minutes between notifications
- Different notification types or sources

**Solution:**
Ensure messages are identical for grouping to work

### Issue: Auto-refresh not working

**Solution:**
1. Check browser console for errors
2. Verify setInterval is not blocked
3. Check if notifications section is active
4. Test API endpoint manually: `/api/notifications/count`

### Issue: Search not returning results

**Solution:**
1. Check database indexes are created
2. Verify search query syntax
3. Check if notifications are archived (`is_archived = TRUE`)
4. Test direct database query to isolate issue

### Issue: Priority colors not showing

**Solution:**
1. Clear browser cache
2. Check CSS is loaded (inspect element)
3. Verify `data-priority` attribute is set on notification div
4. Check for CSS conflicts with other styles

---

## Performance Optimization

### Database Indexes
All critical queries are indexed for fast performance:
- Priority + Created Date
- Archived Status + Created Date
- Source
- Type
- Read Status + Created Date

### Pagination
- Limits results to 20 per page by default
- Prevents loading thousands of notifications at once

### Auto-Archiving
- Regular archiving of old read notifications keeps database lean
- Recommended: Archive monthly via automation

### Deduplication
- Reduces database writes by up to 80% during bulk operations
- Prevents notification spam

---

## Migration Guide

### Migrating from Old Notification System

1. **Database Migration:**
```sql
-- Run this to add new columns to existing table
ALTER TABLE system_notifications
ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS source_icon VARCHAR(10) DEFAULT '📋',
ADD COLUMN IF NOT EXISTS grouped_count INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS related_action VARCHAR(100);

-- Create new indexes
CREATE INDEX idx_notifications_priority ON system_notifications(priority, created_at DESC);
CREATE INDEX idx_notifications_archived ON system_notifications(is_archived, created_at DESC);
CREATE INDEX idx_notifications_source ON system_notifications(source);
CREATE INDEX idx_notifications_type ON system_notifications(type);
```

2. **Update Frontend Calls:**
   - Replace `alert()` calls with `showSuccess()`, `showError()`, etc.
   - Replace direct DOM manipulation with API calls

3. **Test Migration:**
   - Verify existing notifications display correctly
   - Test creating new notifications
   - Test filtering and search

---

## API Rate Limiting

No rate limiting is currently implemented on notification endpoints. For production deployments, consider:

```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=get_remote_address)

@admin_bp.route('/notifications', methods=['POST'])
@limiter.limit("100 per hour")  # Prevent notification spam
def create_notification_endpoint():
    # ...
```

---

## Security Considerations

1. **Authentication Required:** All notification endpoints require `@login_required`
2. **Admin-Only Actions:** Archive and export require `@admin_required`
3. **SQL Injection Prevention:** All queries use parameterized statements
4. **XSS Protection:** All user input is sanitized before display

---

## Developer Onboarding & Compliance

### Quick Start for New Admin Features

**Step 1:** Read this documentation
**Step 2:** Use the helper functions in your code
**Step 3:** Test notifications appear in 🔔 NOTIFICATIONS section
**Step 4:** Verify notifications are saved to database

### Integration Checklist

When building a new admin tool or feature, ensure:

- [ ] All user feedback uses `showSuccess()`, `showError()`, `showWarning()`, or `showInfo()`
- [ ] No `alert()`, `confirm()`, or `console.log()` for user-facing messages
- [ ] Error messages are clear and actionable
- [ ] Success messages confirm what was accomplished
- [ ] Critical errors use appropriate priority (automatic with keywords)
- [ ] Source icons are meaningful (optional but recommended)
- [ ] Tested that notifications appear in Notifications Center
- [ ] Tested that notifications are searchable and exportable

### Code Review Guidelines

During code reviews, verify:

1. **No Alert Usage:** Search for `alert(`, `confirm(`, `prompt(` in admin code
2. **Proper Function Calls:** All feedback uses `show*()` functions
3. **Clear Messages:** Notifications are user-friendly and actionable
4. **Error Handling:** Failures produce error notifications
5. **Success Confirmation:** Successful operations produce success notifications

### Admin Feature Compliance Matrix

| Feature | Compliant? | Uses Notifications? | Notes |
|---------|-----------|---------------------|-------|
| GitHub Integration | ✅ Yes | ✅ Yes | All actions create notifications |
| User Management | ✅ Yes | ✅ Yes | Uses centralized system |
| Billing System | ✅ Yes | ✅ Yes | Payment notifications stored |
| Security & Network | ✅ Yes | ✅ Yes | Security alerts prioritized |
| Agent Management | ✅ Yes | ✅ Yes | Agent operations tracked |
| **Future Features** | ⚠️ Required | ⚠️ Mandatory | Must follow this standard |

### Enforcement

**This is a platform-wide standard.** All pull requests adding admin features will be reviewed for compliance with this notification system. Non-compliant code will be rejected.

### Quick Reference Card

**Developer Quick Reference:**
```javascript
// ✅ DO THIS:
showSuccess('User created successfully');
showError('Failed to save settings: ' + error);
showWarning('API rate limit at 80%');
showInfo('Background task started');

// ❌ DON'T DO THIS:
alert('User created');
console.log('Settings saved');
// (silent operation with no user feedback)
```

---

## Future Enhancements

Planned features for v3.0:
- [ ] WebSocket real-time push notifications
- [ ] Email/SMS notification delivery
- [ ] User-specific notification preferences
- [ ] Notification templates system
- [ ] Advanced analytics dashboard
- [ ] Notification scheduling
- [ ] Multi-language support
- [ ] Desktop push notifications

---

## Support

For issues, questions, or feature requests:
- **Documentation:** `/docs/notification-system.md`
- **Source Code:** `/mnt/archie_brain/platform_v2/` (modular architecture)
- **Database Schema:** `/mnt/archie_brain/database/migrations/`

---

**Last Updated:** December 31, 2025
**Version:** 2.0
**Status:** Production Ready ✅
