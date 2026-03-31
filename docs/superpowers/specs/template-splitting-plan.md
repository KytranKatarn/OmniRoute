# Template Splitting Plan — 3 Largest HTML Templates

**Date**: 2026-03-31
**Scope**: account_center.html (8,228 lines), media_hub.html (5,824 lines), archie_chat.html (5,355 lines)
**Goal**: Extract inline CSS/JS to separate files, split tab/modal HTML into `{% include %}` partials

---

## 1. account_center.html (8,228 lines)

### Current Structure

| Section | Lines | Type |
|---------|-------|------|
| Inline CSS (`<style>`) | 12-2343 (2,331 lines) | Styles |
| HTML content | 2346-3645 (1,299 lines) | Markup |
| Inline JS (`<script>`) | 3646-8227 (4,581 lines) | JavaScript |

### Existing External Files
- **None** — all CSS and JS is inline

### 10 Tabs (HTML partials)

| Tab | ID | Lines (approx) | Proposed Include |
|-----|----|-----------------|------------------|
| Users (list) | `tab-list` | 2436-2509 (73) | `includes/ac/tab_users.html` |
| Pending | `tab-pending` | 2510-2545 (35) | `includes/ac/tab_pending.html` |
| Permissions | `tab-permissions` | 2546-2588 (42) | `includes/ac/tab_permissions.html` |
| Subscriptions | `tab-subscriptions` | 2589-2654 (65) | `includes/ac/tab_subscriptions.html` |
| Security | `tab-security` | 2655-2821 (166) | `includes/ac/tab_security.html` |
| Sessions | `tab-sessions` | 2822-2890 (68) | `includes/ac/tab_sessions.html` |
| API Keys | `tab-api-keys` | 2891-2958 (67) | `includes/ac/tab_api_keys.html` |
| Bulk Ops | `tab-bulk` | 2959-3077 (118) | `includes/ac/tab_bulk.html` |
| Activity | `tab-activity` | 3078-3157 (79) | `includes/ac/tab_activity.html` |
| Organizations (SaaS) | `tab-organizations` | 3158-3337 (179) | `includes/ac/tab_organizations.html` |

### 7 Modals (HTML partials)

| Modal | ID | Lines (approx) | Proposed Include |
|-------|----|-----------------|------------------|
| SaaS Detail Panel | `saas-detail-panel` | 3339-3408 (69) | `includes/ac/modal_saas_detail.html` |
| SaaS New Org | `saas-new-org-modal` | 3409-3446 (37) | `includes/ac/modal_saas_new_org.html` |
| SaaS Add Domain | `saas-add-domain-modal` | 3447-3486 (39) | `includes/ac/modal_saas_add_domain.html` |
| Add/Edit User | `user-modal` | 3487-3535 (48) | `includes/ac/modal_user.html` |
| User Profile | `details-modal` | 3536-3550 (14) | `includes/ac/modal_profile.html` |
| Create API Key | `create-api-key-modal` | 3551-3609 (58) | `includes/ac/modal_api_key.html` |
| API Key Created | `api-key-created-modal` | 3610-3634 (24) | `includes/ac/modal_api_key_created.html` |
| Subscription Mgmt | `sub-mgmt-modal` | 3635-3645 (10) | `includes/ac/modal_subscription.html` |

### JS Function Groups (for splitting into separate .js files)

| Group | Functions | Lines | Proposed File |
|-------|-----------|-------|---------------|
| Core (tabs, toast, init) | debounce, showToast, tab switching, DOMContentLoaded | 3646-3750 | `account-center-core.js` |
| Users CRUD | loadUsers, renderUsersTable, pagination, showAddUserModal, editUser, saveUser, deleteUser | 3752-4830 | `account-center-users.js` |
| User Profile | viewUser, buildProfileHeader, buildOverviewTab, buildSubscriptionTab, buildSecurityTab, buildActivityTab, createInlineField, saveProfileField | 4109-4810 | `account-center-profile.js` |
| Permissions | loadPermissions, renderRoleCards, renderPermissionMatrix, toggleCategory, filterPermissions | 4839-5130 | `account-center-permissions.js` |
| Subscriptions | loadSubMgmtUsers, loadTiers, renderTierCards, renderTierComparison, openSubMgmtModal, renderSubscriptionManagement, previewTierChange, applyTierChange | 5131-5915 | `account-center-subscriptions.js` |
| Security | loadSecurity, loadLockoutPolicy, loadRecentFailedLogins, load2FAManagement | ~5916-6145 | `account-center-security.js` |
| Sessions | startSessionsAutoRefresh, stopSessionsAutoRefresh, loadSessions | ~6146-6339 | `account-center-sessions.js` |
| API Keys | loadApiKeys, showCreateApiKeyModal, createApiKey | ~6340-6635 | `account-center-apikeys.js` |
| Bulk Ops | loadBulkOps, executeBulkAction | ~6636-6754 | `account-center-bulk.js` |
| Activity | loadActivity, renderActivityChart, startActivityAutoRefresh | ~6755-7128 | `account-center-activity.js` |
| Organizations (SaaS) | saasRenderOrgGrid, saasUpdateStats, saasLoadAllDomains, saasLoadNetworkInfo, etc. | ~7129-8227 | `account-center-orgs.js` |

### CSS Extraction

- **Target file**: `static/css/account-center.css` (2,331 lines)
- Single `<style>` block, clean extraction
- Contains responsive breakpoints for 480px, 768px, 1024px, Galaxy Fold
- Has modal styles, tab styles, profile tab styles, SaaS sub-tab styles

### Work Items

1. **[CSS]** Extract lines 12-2343 to `static/css/account-center.css`, replace with `<link>` tag
2. **[JS]** Extract lines 3646-8227 to `static/js/account-center.js` (monolith first, split later)
3. **[HTML]** Create `templates/includes/ac/` directory
4. **[HTML]** Extract each of the 10 tab content divs into `{% include %}` partials
5. **[HTML]** Extract each of the 7+1 modals into `{% include %}` partials
6. **[JS-SPLIT]** (Phase 2) Split monolith JS into 11 domain-specific files
7. **[VERIFY]** Screenshot all 10 tabs + all modals before and after

**Expected result**: 8,228 lines reduced to ~150-line skeleton (block defs, includes, link/script tags)

---

## 2. media_hub.html (5,824 lines)

### Current Structure

| Section | Lines | Type |
|---------|-------|------|
| PWA meta/manifest | 1-93 (93 lines) | Head markup |
| Inline CSS (small) | 9-66 (57 lines) | PWA styles |
| HTML content | 94-728 (634 lines) | Markup |
| Inline CSS (massive) | 730-5791 (5,061 lines) | Styles |
| Inline JS (small) | 5794-5823 (29 lines) | Init + service workers |

### Existing External Files
- `static/js/media-hub.js` (4,369 lines) — already extracted, contains all major functions
- `static/js/media-hub-sw.js` — service worker
- **No external CSS file** — 5,061 lines of CSS still inline

### 7 Tabs (HTML partials)

| Tab | ID | Lines (approx) | Proposed Include |
|-----|----|-----------------|------------------|
| Dashboard | `tab-dashboard` | 221-348 (127) | `includes/mh/tab_dashboard.html` |
| Movies | `tab-movies` | 350-379 (29) | `includes/mh/tab_movies.html` |
| TV Shows | `tab-shows` | 381-410 (29) | `includes/mh/tab_shows.html` |
| Requests | `tab-requests` | 412-437 (25) | `includes/mh/tab_requests.html` |
| Calendar | `tab-calendar` | 439-486 (47) | `includes/mh/tab_calendar.html` |
| Stats | `tab-stats` | 488-580 (92) | `includes/mh/tab_stats.html` |
| Settings | `tab-settings` | 582-625 (43) | `includes/mh/tab_settings.html` |

### 3 Modals (HTML partials)

| Modal | ID | Lines (approx) | Proposed Include |
|-------|----|-----------------|------------------|
| Media Details | `mediaPanel` | 630-641 | `includes/mh/modal_media_details.html` |
| Video Player | `videoPlayerModal` | 643-668 | `includes/mh/modal_video_player.html` |
| Add/Edit Service | `serviceModal` | 669-727 | `includes/mh/modal_service.html` |

### CSS Extraction

- **Target file**: `static/css/media-hub.css` (5,061 lines)
- Lines 730-5791: massive inline `<style>` block with 30+ named sections:
  - Header, Navigation Tabs, Main Content, Stats Grid, Content Sections
  - Media Details Modal, Video Player Modal, Quality Badges, Continue Watching
  - Trending, Collections, Statistics Tab, Lazy Loading, Download Controls
  - Episode Browser, Episode Tiles, PWA Install Banner, TV/D-Pad Navigation
  - Responsive enhancements
- Lines 9-66: small PWA-specific styles (can merge into same file or keep inline)

### CSS Split Candidates (Phase 2)

| Section | Lines (approx) | Proposed File |
|---------|-----------------|---------------|
| Core layout + header + tabs + grid | 730-1227 (~500) | `media-hub-core.css` |
| Content sections + posters | 1228-2765 (~1,500) | `media-hub-content.css` |
| Media details modal | 2766-3411 (~650) | `media-hub-modal.css` |
| Episodes + calendar | 3412-5170 (~1,750) | `media-hub-episodes.css` |
| PWA + TV + responsive | 5171-5791 (~620) | `media-hub-responsive.css` |

### Work Items

1. **[CSS]** Extract lines 730-5791 to `static/css/media-hub.css`, replace with `<link>` tag
2. **[HTML]** Create `templates/includes/mh/` directory
3. **[HTML]** Extract each of the 7 tab sections into `{% include %}` partials
4. **[HTML]** Extract each of the 3 modals into `{% include %}` partials
5. **[CSS-SPLIT]** (Phase 2) Split 5,061-line CSS monolith into 5 domain files
6. **[VERIFY]** Screenshot all 7 tabs + modals before and after

**Expected result**: 5,824 lines reduced to ~200-line skeleton (PWA head, includes, link/script tags)

---

## 3. archie_chat.html (5,355 lines)

### Current Structure

| Section | Lines | Type |
|---------|-------|------|
| Inline CSS | 6-2968 (~2,962 lines) | Styles |
| HTML content | 2969-3537 (568 lines) | Markup |
| Inline JS | 3539-5355 (1,816 lines) | JavaScript |

### Existing External Files
- `static/css/archie-chat.css` (983 lines) — partial extraction already done
- `static/js/archie-chat.js` (701 lines) — partial extraction already done
- `static/js/archie-chat-overlay.js` — overlay functionality

**Note**: External files exist but contain only a fraction of the code. The template still has ~2,962 lines of inline CSS and ~1,816 lines of inline JS.

### CSS Sections (inline, lines 6-2968)

| Section | Lines (approx) | Description |
|---------|-----------------|-------------|
| Core layout | 41-307 | Container, grid, header |
| Chat bubbles/messages | 308-790 | Message styling, avatars, code blocks |
| Multi-agent mode | 791-901 | Discussion threads, agent panels |
| Side-by-side mode | 902-1005 | Dual chat panes |
| Mode tabs | 1006-1052 | Tab switching UI |
| Collaboration mode | 1053-1193 | Collab-specific styles |
| Work products panel | 1194-1407 | Work output display |
| Input area | 1408-1695 | Chat input, send button, attachments |
| Sidebar | 1696-1910 | Left sidebar, quick commands |
| Work products (extended) | 1911-2094 | Additional work product styles |
| Interjection modal | 2095-2194 | Modal for interjections |
| Keyboard shortcuts modal | 2195-2277 | Shortcuts help overlay |
| Voice features | 2278-2484 | TTS controls, voice sidebar |
| Responsive | 2485-2536 | Mobile breakpoints |
| Conversation threads | 2537-2583 | Thread navigation |
| Activity badge | 2584-2698 | Notification badges |
| Phase 7-8 features | 2699-2968 | Analytics, memory, export, settings, search panels |

### HTML Sections (lines 2969-3537)

| Section | Lines (approx) | Proposed Include |
|---------|-----------------|------------------|
| Toast container | 2971-2982 | (keep inline, tiny) |
| Left sidebar | 2983-3047 | `includes/chat/sidebar.html` |
| Search panel | 3048-3062 | `includes/chat/panel_search.html` |
| Analytics panel | 3063-3079 | `includes/chat/panel_analytics.html` |
| Memory panel | 3080-3091 | `includes/chat/panel_memory.html` |
| Settings panel | 3092-3130 | `includes/chat/panel_settings.html` |
| Conversation threads | 3123-3130 | `includes/chat/panel_threads.html` |
| Settings modal | 3131-3194 | `includes/chat/modal_settings.html` |
| Main chat area | 3195-3301 | `includes/chat/main_chat.html` |
| Side-by-side mode | 3302-3338 | `includes/chat/mode_sidebyside.html` |
| Collaboration mode | 3339-3449 | `includes/chat/mode_collaboration.html` |
| Interjection modal | 3450-3461 | `includes/chat/modal_interjection.html` |
| Voice sidebar | 3462-3522 | `includes/chat/panel_voice.html` |
| Shortcuts modal | 3523-3535 | `includes/chat/modal_shortcuts.html` |

### JS Function Groups (lines 3539-5355)

| Group | Functions | Lines (approx) | Proposed File |
|-------|-----------|-----------------|---------------|
| Core messaging | scrollToBottom, addMessage, formatMessage, addMultiAgentMessage, showTyping, sendMessage, renderMarkdown, addCopyButtons | 3563-3973 (~410) | `archie-chat-messages.js` |
| Conversation mgmt | p10LoadThreads, p10LoadConversation, p10NewConversation, loadHistory, clearChat | 3974-4152 (~178) | `archie-chat-conversations.js` |
| Status & suggestions | loadStatus, loadSuggestions, sendQuickCommand, updateRecentCommand | 4047-4179 (~132) | `archie-chat-status.js` |
| Consciousness save | saveToConsciousness | 4180-4243 (~63) | (merge into conversations) |
| Voice/TTS | loadVoiceConfig, toggleVoice, playVoice, stopVoice, addVoiceButton, etc. | 4244-4634 (~390) | `archie-chat-voice.js` |
| Activity & analytics | updateActivityBadge, toggleAnalytics, loadAnalytics, exportAnalyticsCSV | 4675-4813 (~138) | `archie-chat-analytics.js` |
| Memory panel | toggleMemory, loadMemories, renderMemories, filterMemories, deleteMemory | 4814-4896 (~82) | `archie-chat-memory.js` |
| Export & KB | exportConversation, saveToKnowledgeBase, summarizeConversation | 4897-4958 (~61) | (merge into conversations) |
| Sidebar & keyboard | toggleSidebar, handleEscapeKey, _isInputFocused, keyboard shortcuts | 4959-5095 (~136) | `archie-chat-ui.js` |
| Settings | toggleSettings, openSettingsModal, closeSettingsModal, loadSettings, applySettings, updateSetting | 5097-5186 (~89) | `archie-chat-settings.js` |
| Search | onSearchInput, searchConversations, renderSearchResults, loadSearchResult, setSearchRange, clearSearch | 5187-5355 (~168) | `archie-chat-search.js` |

### CSS Extraction

- **Target file**: `static/css/archie-chat-inline.css` (2,962 lines) — merge with existing `archie-chat.css` (983 lines)
- Combined total: ~3,945 lines of CSS
- Alternatively, keep both and load sequentially (existing file first, inline extraction second)

### Work Items

1. **[CSS]** Extract lines 6-2968 to `static/css/archie-chat-inline.css`, replace with `<link>` tag
2. **[CSS-MERGE]** Audit overlap between existing `archie-chat.css` (983 lines) and inline CSS, merge/deduplicate
3. **[JS]** Extract lines 3539-5355 to `static/js/archie-chat-inline.js`
4. **[JS-MERGE]** Audit overlap between existing `archie-chat.js` (701 lines) and inline JS, merge/deduplicate
5. **[HTML]** Create `templates/includes/chat/` directory
6. **[HTML]** Extract 14 sidebar/panel/modal/mode sections into `{% include %}` partials
7. **[JS-SPLIT]** (Phase 2) Split merged JS into 8-10 domain-specific files
8. **[VERIFY]** Screenshot all modes (standard, side-by-side, collaboration) + modals before and after

**Expected result**: 5,355 lines reduced to ~120-line skeleton (block defs, includes, link/script tags)

---

## Execution Priority

### Phase 1 — CSS Extraction (Biggest Win, Lowest Risk)

| Priority | File | Action | Impact |
|----------|------|--------|--------|
| 1 | media_hub.html | Extract 5,061-line `<style>` to `media-hub.css` | -87% file size |
| 2 | archie_chat.html | Extract 2,962-line `<style>` to CSS file | -55% file size |
| 3 | account_center.html | Extract 2,331-line `<style>` to `account-center.css` | -28% file size |

### Phase 2 — JS Extraction

| Priority | File | Action | Impact |
|----------|------|--------|--------|
| 4 | account_center.html | Extract 4,581-line `<script>` to `account-center.js` | -56% remaining |
| 5 | archie_chat.html | Extract 1,816-line `<script>`, merge with existing | -34% remaining |
| 6 | media_hub.html | JS already mostly external (29 lines inline) | Minimal |

### Phase 3 — HTML `{% include %}` Splitting

| Priority | File | Action | Partials |
|----------|------|--------|----------|
| 7 | account_center.html | Split 10 tabs + 8 modals | 18 files |
| 8 | archie_chat.html | Split 14 sections | 14 files |
| 9 | media_hub.html | Split 7 tabs + 3 modals | 10 files |

### Phase 4 — JS Domain Splitting (Optional Refinement)

| Priority | File | Action | Result Files |
|----------|------|--------|--------------|
| 10 | account_center.js | Split into 11 domain files | 11 files |
| 11 | archie_chat JS | Split into 8-10 domain files | 10 files |
| 12 | media-hub.js | Already one file (4,369 lines) — consider splitting | 5 files |

---

## Summary

| Template | Total Lines | Inline CSS | Inline JS | Tabs | Modals | External Files Exist |
|----------|-------------|------------|-----------|------|--------|---------------------|
| account_center.html | 8,228 | 2,331 | 4,581 | 10 | 8 | None |
| media_hub.html | 5,824 | 5,061 | 29 | 7 | 3 | JS (4,369 lines) |
| archie_chat.html | 5,355 | 2,962 | 1,816 | 0* | 3 | CSS (983) + JS (701) |

*archie_chat uses mode panels instead of tabs (standard, side-by-side, collaboration)

**Total inline code to extract**: 10,354 lines CSS + 6,426 lines JS = **16,780 lines**
**Total `{% include %}` partials**: 42 files across all three templates
**Post-split skeleton sizes**: ~150 + ~200 + ~120 = **~470 lines total** (from 19,407)
