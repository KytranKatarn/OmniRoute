# Phase 4: Collaboration Mode UI Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing collaboration backend + JS (1,895 lines) into visible UI in `archie_chat.html` so users can access Collaboration Mode, Side-by-Side Mode, session history, and work products.

**Architecture:** Add mode tab bar to `.top-status-bar`, wrap existing chat in `#solo-chat-container`, add `#dual-chat-container` (ttyd iframe) and `#collab-container` (start/active views), load `collaboration.js`, and add CSS for all new components. No backend changes needed — all API endpoints already exist.

**Tech Stack:** HTML/CSS (Jinja2 template), vanilla JS, existing `collaboration.js`

**Security note:** All dynamic content in `collaboration.js` uses DOM methods (createElement/textContent) or `renderMarkdownSafe()` which escapes HTML before applying markdown transforms. No raw innerHTML with user content.

---

### Task 1: Add Collaboration CSS to archie_chat.html

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (lines 5-1190, inside `{% block styles %}`)

**Step 1: Add mode tabs CSS**

Insert before the `/* RESPONSIVE */` section (before line 962). Add styles for:

```css
/* ============================================
   MODE TABS
   ============================================ */
.mode-tabs {
    display: flex;
    gap: 4px;
    padding: 4px;
    background: var(--archie-bg-tertiary);
    border-radius: 8px;
}

.chat-mode-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: var(--archie-text-muted);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    font-family: var(--archie-font-body);
}

.chat-mode-btn:hover {
    color: var(--archie-text-secondary);
    background: var(--archie-bg-elevated);
}

.chat-mode-btn.active {
    color: white;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}

.chat-mode-btn i {
    width: 14px;
    height: 14px;
}
```

**Step 2: Add Side-by-Side container CSS**

```css
/* ============================================
   SIDE-BY-SIDE MODE
   ============================================ */
#dual-chat-container {
    display: none;
    flex: 1;
    flex-direction: row;
    overflow: hidden;
}

.chat-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
}

.panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    background: var(--archie-bg-secondary);
    border-bottom: 1px solid var(--archie-border-default);
    font-size: 0.8rem;
    font-weight: 600;
}

.panel-header .panel-title {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--archie-text-secondary);
}

.panel-header .panel-title i {
    width: 16px;
    height: 16px;
    color: var(--archie-cyan);
}

.panel-header .panel-actions {
    display: flex;
    gap: 8px;
}

.panel-action-btn {
    padding: 4px 10px;
    background: var(--archie-bg-tertiary);
    border: 1px solid var(--archie-border-default);
    border-radius: 4px;
    color: var(--archie-text-tertiary);
    font-size: 0.7rem;
    cursor: pointer;
    transition: all 0.2s;
}

.panel-action-btn:hover {
    background: var(--archie-bg-elevated);
    color: var(--archie-text-secondary);
    border-color: var(--archie-purple);
}

.resize-handle {
    width: 4px;
    background: var(--archie-border-default);
    cursor: col-resize;
    transition: background 0.2s;
    flex-shrink: 0;
}

.resize-handle:hover {
    background: var(--archie-purple);
}

#claude-terminal-iframe {
    flex: 1;
    border: none;
    background: #1a1a2e;
}

.terminal-offline {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--archie-text-muted);
    font-size: 0.85rem;
    background: #1a1a2e;
}

.terminal-offline i {
    width: 32px;
    height: 32px;
    color: var(--archie-text-muted);
}
```

**Step 3: Add Collaboration container CSS**

```css
/* ============================================
   COLLABORATION MODE
   ============================================ */
#collab-container {
    display: none;
    flex: 1;
    flex-direction: row;
    overflow: hidden;
}

/* Start View */
#collab-start-view {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 24px;
    overflow-y: auto;
    gap: 24px;
    max-width: 800px;
    margin: 0 auto;
}

.collab-header {
    text-align: center;
}

.collab-header h2 {
    font-size: 1.4rem;
    font-weight: 600;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.collab-header p {
    color: var(--archie-text-tertiary);
    font-size: 0.9rem;
}

.collab-config {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.collab-config label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--archie-text-muted);
    margin-bottom: 4px;
    display: block;
}

.collab-config textarea,
.collab-config input,
.collab-config select {
    width: 100%;
    padding: 12px 16px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 10px;
    color: var(--archie-text-secondary);
    font-family: var(--archie-font-body);
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
}

.collab-config textarea:focus,
.collab-config input:focus {
    border-color: var(--archie-purple);
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.collab-config textarea {
    min-height: 80px;
    resize: vertical;
}

.collab-row {
    display: flex;
    gap: 16px;
    align-items: flex-end;
}

.collab-row > div {
    flex: 1;
}

.collab-mode-toggle {
    display: flex;
    gap: 4px;
    padding: 4px;
    background: var(--archie-bg-tertiary);
    border-radius: 8px;
}

.collab-mode-toggle button {
    flex: 1;
    padding: 8px 16px;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: var(--archie-text-muted);
    font-size: 0.8rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--archie-font-body);
}

.collab-mode-toggle button.active {
    background: var(--archie-bg-elevated);
    color: var(--archie-text-secondary);
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.collab-mode-toggle button:hover:not(.active) {
    color: var(--archie-text-tertiary);
}

/* Templates */
#collab-templates {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
    width: 100%;
}

.template-card {
    padding: 16px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: center;
}

.template-card:hover {
    border-color: var(--archie-purple);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

.template-card.selected {
    border-color: var(--archie-purple);
    background: rgba(102, 126, 234, 0.08);
}

.template-icon {
    font-size: 1.8rem;
    margin-bottom: 8px;
}

.template-name {
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--archie-text-secondary);
    margin-bottom: 4px;
}

.template-desc {
    font-size: 0.75rem;
    color: var(--archie-text-muted);
    line-height: 1.4;
}

#btn-start-collab {
    padding: 12px 32px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    border-radius: 12px;
    color: white;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
}

#btn-start-collab:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
}

/* Learning Stats */
.learning-stats {
    display: flex;
    gap: 24px;
    padding: 16px 24px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 12px;
    width: 100%;
    justify-content: center;
}

.learning-stat {
    text-align: center;
}

.learning-stat .value {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--archie-cyan);
    font-family: var(--archie-font-mono);
}

.learning-stat .label {
    font-size: 0.7rem;
    color: var(--archie-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Active View */
#collab-active-view {
    display: none;
    flex: 1;
    flex-direction: column;
    overflow: hidden;
}

.collab-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    background: var(--archie-bg-secondary);
    border-bottom: 1px solid var(--archie-border-default);
}

.collab-toolbar-left {
    display: flex;
    align-items: center;
    gap: 12px;
}

.collab-toolbar-left h3 {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--archie-text-secondary);
}

.collab-status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.75rem;
    color: var(--archie-text-tertiary);
}

.collab-status-bar .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--archie-cyan);
}

.collab-status-bar .status-dot.active {
    background: var(--archie-cyan);
    animation: pulse-glow 2s ease-in-out infinite;
}

.collab-status-bar .status-dot.paused {
    background: var(--archie-orange);
}

.collab-status-bar .status-dot.completed,
.collab-status-bar .status-dot.stopped {
    background: var(--archie-text-muted);
}

.collab-toolbar-right {
    display: flex;
    align-items: center;
    gap: 8px;
}

.collab-btn {
    padding: 5px 12px;
    background: var(--archie-bg-tertiary);
    border: 1px solid var(--archie-border-default);
    border-radius: 6px;
    color: var(--archie-text-tertiary);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--archie-font-body);
}

.collab-btn:hover {
    background: var(--archie-bg-elevated);
    color: var(--archie-text-secondary);
    border-color: var(--archie-purple);
}

.collab-btn.danger:hover {
    border-color: var(--archie-red);
    color: var(--archie-red);
}

/* Collaboration Messages */
#collab-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.collab-message {
    padding: 16px;
    border-radius: 12px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    animation: message-enter 0.3s ease;
}

.collab-message.archie {
    border-left: 3px solid var(--archie-cyan);
}

.collab-message.claude {
    border-left: 3px solid var(--archie-purple);
}

.collab-message.user {
    border-left: 3px solid var(--archie-orange);
}

.collab-message .role {
    font-size: 0.75rem;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--archie-text-tertiary);
}

.collab-message.archie .role { color: var(--archie-cyan); }
.collab-message.claude .role { color: var(--archie-purple); }
.collab-message.user .role { color: var(--archie-orange); }

.collab-message .content {
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--archie-text-secondary);
    white-space: pre-wrap;
    word-wrap: break-word;
}

.collab-message .timestamp {
    font-size: 0.7rem;
    color: var(--archie-text-muted);
    margin-top: 8px;
    font-family: var(--archie-font-mono);
}

/* Thinking Indicator */
.thinking-indicator {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    color: var(--archie-text-muted);
    font-size: 0.8rem;
}

.thinking-indicator .dots {
    display: flex;
    gap: 4px;
}

.thinking-indicator .dot {
    width: 6px;
    height: 6px;
    background: var(--archie-purple);
    border-radius: 50%;
    animation: typing-bounce 1.4s ease-in-out infinite;
}

.thinking-indicator .dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-indicator .dot:nth-child(3) { animation-delay: 0.4s; }

/* Read-only banner */
#collab-readonly-banner {
    display: none;
    padding: 8px 16px;
    background: rgba(255, 159, 67, 0.1);
    border-bottom: 1px solid rgba(255, 159, 67, 0.3);
    color: var(--archie-orange);
    font-size: 0.8rem;
    text-align: center;
}

/* Export buttons */
#collab-export-btns {
    display: none;
    gap: 8px;
    padding: 10px 16px;
    background: var(--archie-bg-secondary);
    border-top: 1px solid var(--archie-border-default);
}
```

**Step 4: Add History sidebar CSS**

```css
/* ============================================
   HISTORY SIDEBAR
   ============================================ */
#collab-history-sidebar {
    width: 280px;
    background: var(--archie-bg-secondary);
    border-right: 1px solid var(--archie-border-default);
    display: flex;
    flex-direction: column;
    transition: width 0.3s ease, opacity 0.3s ease;
    overflow: hidden;
}

#collab-history-sidebar.collapsed {
    width: 0;
    opacity: 0;
    border: none;
}

.history-header {
    padding: 16px;
    border-bottom: 1px solid var(--archie-border-default);
}

.history-header h3 {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--archie-text-secondary);
    margin-bottom: 12px;
}

.filter-pills {
    display: flex;
    gap: 4px;
    margin-bottom: 10px;
}

.filter-pill {
    padding: 4px 10px;
    background: var(--archie-bg-tertiary);
    border: none;
    border-radius: 12px;
    color: var(--archie-text-muted);
    font-size: 0.7rem;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--archie-font-body);
}

.filter-pill.active {
    background: var(--archie-purple);
    color: white;
}

.filter-pill:hover:not(.active) {
    background: var(--archie-bg-elevated);
    color: var(--archie-text-tertiary);
}

.history-search {
    width: 100%;
    padding: 8px 12px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 8px;
    color: var(--archie-text-secondary);
    font-size: 0.8rem;
    outline: none;
    font-family: var(--archie-font-body);
}

.history-search:focus {
    border-color: var(--archie-purple);
}

#history-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
}

.history-item {
    padding: 12px;
    background: var(--archie-bg-tertiary);
    border-radius: 8px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid transparent;
}

.history-item:hover {
    border-color: var(--archie-border-default);
    transform: translateX(2px);
}

.history-item.active {
    border-color: var(--archie-purple);
    background: rgba(102, 126, 234, 0.08);
}

.history-item-topic {
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--archie-text-secondary);
    margin-bottom: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.history-item-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.7rem;
    color: var(--archie-text-muted);
    font-family: var(--archie-font-mono);
}

.history-status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}

.history-status-dot.active { background: var(--archie-cyan); }
.history-status-dot.completed { background: var(--archie-text-muted); }
.history-status-dot.stopped { background: var(--archie-orange); }
.history-status-dot.paused { background: var(--archie-orange); }

.history-item-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
}

.history-item-actions button {
    padding: 3px 8px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 4px;
    color: var(--archie-text-muted);
    font-size: 0.65rem;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--archie-font-body);
}

.history-item-actions button:hover {
    color: var(--archie-text-secondary);
    border-color: var(--archie-purple);
}

.history-item-actions .btn-continue {
    color: var(--archie-cyan);
}
```

**Step 5: Add Work products panel CSS**

```css
/* ============================================
   WORK PRODUCTS PANEL
   ============================================ */
#work-products-panel {
    display: none;
    width: 320px;
    flex-direction: column;
    background: var(--archie-bg-secondary);
    border-left: 1px solid var(--archie-border-default);
}

.wp-header {
    padding: 16px;
    border-bottom: 1px solid var(--archie-border-default);
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.wp-header h3 {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--archie-text-secondary);
}

.wp-header .wp-badge {
    padding: 2px 8px;
    background: var(--archie-purple);
    border-radius: 10px;
    color: white;
    font-size: 0.7rem;
    font-weight: 600;
}

#work-products-list {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
}

.work-product-card {
    padding: 12px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 8px;
    margin-bottom: 8px;
    transition: all 0.2s;
}

.work-product-card:hover {
    border-color: var(--archie-purple);
}

.wp-type {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
}

.wp-type.code { background: rgba(102, 126, 234, 0.15); color: var(--archie-purple); }
.wp-type.plan { background: rgba(0, 212, 170, 0.1); color: var(--archie-cyan); }
.wp-type.design { background: rgba(255, 159, 67, 0.1); color: var(--archie-orange); }
.wp-type.analysis { background: var(--archie-bg-tertiary); color: var(--archie-text-tertiary); }

.wp-author {
    font-size: 0.7rem;
    color: var(--archie-text-muted);
}

.wp-title {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--archie-text-secondary);
    margin: 6px 0;
}

.wp-content-preview {
    font-size: 0.75rem;
    color: var(--archie-text-tertiary);
    line-height: 1.5;
    max-height: 60px;
    overflow: hidden;
    cursor: pointer;
    white-space: pre-wrap;
}

.work-product-card.expanded .wp-content-preview {
    max-height: none;
}

.wp-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--archie-border-default);
}

.wp-actions button {
    padding: 4px 10px;
    background: var(--archie-bg-tertiary);
    border: 1px solid var(--archie-border-default);
    border-radius: 4px;
    color: var(--archie-text-tertiary);
    font-size: 0.7rem;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--archie-font-body);
}

.wp-actions button:hover {
    background: var(--archie-bg-elevated);
    color: var(--archie-text-secondary);
    border-color: var(--archie-purple);
}

.wp-actions button.approved {
    color: var(--archie-cyan);
    border-color: var(--archie-cyan);
    cursor: default;
}

/* ============================================
   INTERJECTION MODAL
   ============================================ */
#interjection-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 1000;
    align-items: center;
    justify-content: center;
}

#interjection-modal.visible {
    display: flex;
}

.interjection-content {
    background: var(--archie-bg-secondary);
    border: 1px solid var(--archie-border-default);
    border-radius: 16px;
    padding: 24px;
    width: 90%;
    max-width: 500px;
}

.interjection-content h3 {
    font-size: 1rem;
    margin-bottom: 12px;
    color: var(--archie-text-secondary);
}

.interjection-content textarea {
    width: 100%;
    min-height: 80px;
    padding: 12px;
    background: var(--archie-bg-elevated);
    border: 1px solid var(--archie-border-default);
    border-radius: 10px;
    color: var(--archie-text-secondary);
    font-family: var(--archie-font-body);
    font-size: 0.9rem;
    outline: none;
    resize: vertical;
}

.interjection-content textarea:focus {
    border-color: var(--archie-purple);
}

.interjection-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 12px;
}

.interjection-actions button {
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    border: none;
    font-family: var(--archie-font-body);
}

.interjection-actions .cancel-btn {
    background: var(--archie-bg-tertiary);
    color: var(--archie-text-tertiary);
}

.interjection-actions .send-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}
```

**Step 6: Commit**

---

### Task 2: Add mode tab bar and wrap Solo container

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (lines 1284-1381, `<main class="chat-main">` section)

**Step 1: Add mode tabs to `.top-status-bar`**

In the `.status-left` div (after line 1292), add the mode tabs:

```html
<div class="mode-tabs">
    <button class="chat-mode-btn active" data-mode="solo" onclick="switchChatMode('solo')">
        <i data-lucide="message-square"></i>
        Solo
    </button>
    <button class="chat-mode-btn" data-mode="side-by-side" onclick="switchChatMode('side-by-side')">
        <i data-lucide="columns"></i>
        Side-by-Side
    </button>
    <button class="chat-mode-btn" data-mode="collab" onclick="switchChatMode('collab')">
        <i data-lucide="users"></i>
        Collaborate
    </button>
</div>
```

**Step 2: Wrap existing content in `#solo-chat-container`**

Wrap the `.messages-container` and `.input-area` divs (lines 1320-1380) inside:

```html
<div id="solo-chat-container" style="display: flex; flex: 1; flex-direction: column; overflow: hidden;">
    <!-- existing .messages-container here -->
    <!-- existing .input-area here -->
</div>
```

**Step 3: Commit**

---

### Task 3: Add Side-by-Side container HTML

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add `#dual-chat-container` after `#solo-chat-container`**

```html
<!-- Side-by-Side Mode -->
<div id="dual-chat-container">
    <div class="chat-panel">
        <div class="panel-header">
            <div class="panel-title">
                <i data-lucide="bot"></i>
                <span>A.R.C.H.I.E. Chat</span>
            </div>
            <div class="panel-actions">
                <button class="panel-action-btn" onclick="syncContextToClaude()">Sync Context</button>
                <button class="panel-action-btn" onclick="clearSideChat()">Clear</button>
            </div>
        </div>
        <div class="messages-container" id="archie-side-messages"></div>
    </div>
    <div class="resize-handle"></div>
    <div class="chat-panel">
        <div class="panel-header">
            <div class="panel-title">
                <i data-lucide="terminal"></i>
                <span>Claude Terminal</span>
                <span id="claude-cli-status"></span>
            </div>
            <div class="panel-actions">
                <button class="panel-action-btn" onclick="reconnectClaudeTerminal()">Reconnect</button>
                <button class="panel-action-btn" onclick="openClaudeTerminal()">Pop Out</button>
            </div>
        </div>
        <iframe id="claude-terminal-iframe" title="Claude Terminal"></iframe>
        <div class="terminal-offline" id="claude-terminal-offline" style="display: none;">
            <i data-lucide="wifi-off"></i>
            <span>Terminal offline</span>
            <button class="panel-action-btn" onclick="reconnectClaudeTerminal()">Reconnect</button>
        </div>
    </div>
</div>
```

**Step 2: Add `clearSideChat()` JS glue** in the inline `<script>` block:

```javascript
function clearSideChat() {
    const container = document.getElementById('archie-side-messages');
    if (container) container.textContent = '';
}
```

**Step 3: Commit**

---

### Task 4: Add Collaboration container HTML

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add `#collab-container` after `#dual-chat-container`**

```html
<!-- Collaboration Mode -->
<div id="collab-container">
    <!-- History Sidebar -->
    <div id="collab-history-sidebar" class="collapsed">
        <div class="history-header">
            <h3>Session History</h3>
            <div class="filter-pills">
                <button class="filter-pill active" data-filter="all" onclick="setHistoryFilter('all')">All</button>
                <button class="filter-pill" data-filter="active" onclick="setHistoryFilter('active')">Active</button>
                <button class="filter-pill" data-filter="completed" onclick="setHistoryFilter('completed')">Completed</button>
            </div>
            <input type="text" class="history-search" id="history-search-input"
                   placeholder="Search sessions..." oninput="loadCollabHistory()">
        </div>
        <div id="history-list"></div>
    </div>

    <!-- Start View -->
    <div id="collab-start-view">
        <div class="collab-header">
            <h2>AI Collaboration</h2>
            <p>ARCHIE and Claude work together on your topic</p>
        </div>

        <div class="collab-config">
            <div>
                <label>Topic</label>
                <textarea id="collab-topic" placeholder="What should ARCHIE and Claude discuss or work on?"></textarea>
            </div>

            <div class="collab-row">
                <div>
                    <label>Max Turns</label>
                    <input type="number" id="collab-max-turns" value="10" min="2" max="30">
                </div>
                <div>
                    <label>Mode</label>
                    <div class="collab-mode-toggle">
                        <button id="collab-mode-discuss" class="active" onclick="setCollabMode('discuss')">Discussion</button>
                        <button id="collab-mode-joint" onclick="setCollabMode('joint')">Joint Work</button>
                    </div>
                </div>
            </div>
        </div>

        <div>
            <label style="font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--archie-text-muted); margin-bottom: 8px; display: block;">Templates</label>
            <div id="collab-templates"></div>
        </div>

        <button id="btn-start-collab" onclick="startCollaboration()">Start Collaboration</button>

        <div class="learning-stats">
            <div class="learning-stat">
                <div class="value" id="learning-total">0</div>
                <div class="label">Total Learnings</div>
            </div>
            <div class="learning-stat">
                <div class="value" id="learning-week">0</div>
                <div class="label">This Week</div>
            </div>
            <div class="learning-stat">
                <div class="value" id="learning-topics">None yet</div>
                <div class="label">Top Topics</div>
            </div>
        </div>
    </div>

    <!-- Active View -->
    <div id="collab-active-view">
        <div id="collab-readonly-banner">Viewing past session (read-only)</div>
        <div class="collab-toolbar">
            <div class="collab-toolbar-left">
                <button class="collab-btn" id="btn-history-toggle" onclick="toggleCollabHistory()">
                    <i data-lucide="clock" style="width:14px;height:14px;vertical-align:middle;"></i> History
                </button>
                <h3 id="collab-active-title">Collaboration in Progress</h3>
                <div class="collab-status-bar">
                    <span class="status-dot collab-status-dot active"></span>
                    <span class="collab-status-text">Active</span>
                    <span id="turn-counter">Turn 0/10</span>
                </div>
            </div>
            <div class="collab-toolbar-right">
                <button class="collab-btn" id="btn-pause" onclick="pauseCollaboration()">Pause</button>
                <button class="collab-btn" id="btn-resume" onclick="resumeCollaboration()" style="display:none;">Resume</button>
                <button class="collab-btn" id="btn-interject" onclick="showInterjectionModal()">Interject</button>
                <button class="collab-btn danger" id="btn-stop" onclick="stopCollaboration()">Stop</button>
                <button class="collab-btn" id="btn-toggle-products" onclick="toggleWorkProducts()" style="display:none;">Work Products</button>
                <button class="collab-btn" onclick="newCollaboration()">New</button>
            </div>
        </div>

        <div id="collab-messages"></div>

        <div id="collab-export-btns">
            <button class="collab-btn" onclick="exportCollabMarkdown()">Export Markdown</button>
            <button class="collab-btn" onclick="copyCollabToClipboard()">Copy to Clipboard</button>
        </div>
    </div>

    <!-- Work Products Panel -->
    <div id="work-products-panel">
        <div class="wp-header">
            <h3>Work Products</h3>
            <span class="wp-badge" id="wp-count">0</span>
        </div>
        <div id="work-products-list"></div>
    </div>
</div>

<!-- Interjection Modal -->
<div id="interjection-modal">
    <div class="interjection-content">
        <h3>Add to Conversation</h3>
        <textarea id="interjection-text" placeholder="Type your message to inject into the collaboration..."></textarea>
        <div class="interjection-actions">
            <button class="cancel-btn" onclick="hideInterjectionModal()">Cancel</button>
            <button class="send-btn" onclick="submitInterjection()">Send</button>
        </div>
    </div>
</div>
```

**Step 2: Commit**

---

### Task 5: Load collaboration.js and add glue code

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (inline `<script>` block)

**Step 1: Add `<script>` tag to load collaboration.js**

At the very end of `{% block content %}`, after the existing `</script>` tag (after line 2253), add:

```html
<script src="/static/js/collaboration.js"></script>
```

**Step 2: Add glue functions inside the existing inline `<script>` block**

Before the initialization section at the bottom (before line 2248), add:

```javascript
// ============================================
// Collaboration Glue Code
// ============================================

// Bridge: collaboration.js calls showFlashMessage via showNotification()
function showFlashMessage(message, type) {
    showToast(message, type);
}

// Bridge: collaboration.js voice functions reference voiceEnabled
var voiceEnabled = true;

// Bridge: collaboration.js voice calls sendArchieMessage (STT auto-send)
function sendArchieMessage() {
    var input = document.getElementById('messageInput');
    if (input && input.value.trim()) {
        sendMessage(input.value.trim());
        input.value = '';
    }
}

// Override switchChatMode to update sidebar for collab mode
var _originalSwitchChatMode = null;
document.addEventListener('DOMContentLoaded', function() {
    if (typeof switchChatMode === 'function') {
        _originalSwitchChatMode = switchChatMode;
    }
});
```

**Step 3: Verify voice toggle sync**

The existing `toggleVoice()` function sets `voiceConfig.enabled`. Update the `voiceEnabled` bridge var to stay in sync. Add to the `toggleVoice()` function body (after line 2010):

```javascript
voiceEnabled = voiceConfig.enabled;
```

**Step 4: Commit**

---

### Task 6: Deploy & Verify

**Step 1:** Restart the platform:
```bash
docker compose restart archie_platform
```

**Step 2:** Check logs for errors:
```bash
docker logs --tail 50 archie_platform
```

Expected: no template errors, no 500s.

**Step 3:** Open http://192.168.1.200:3000/tools/archie-chat in browser and verify:
- Mode tab bar shows Solo / Side-by-Side / Collaborate
- Solo mode works exactly as before (default)
- Click Side-by-Side: shows split with ARCHIE chat left + ttyd iframe right
- Click Collaborate: shows start view with topic input, mode toggle, templates, learnings stats
- Templates render (6 cards: Code Review, Brainstorm, Debug, Architecture, Knowledge Synthesis, Freeform)
- Click a template: fills topic, sets mode, highlights card
- Start a collaboration: switches to active view with messages streaming
- History toggle: opens sidebar with session list
- Work Products: panel shows during Joint Work mode

**Step 4:** Final commit with all changes.
