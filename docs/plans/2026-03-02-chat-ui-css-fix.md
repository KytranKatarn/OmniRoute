# ARCHIE Chat UI CSS Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix ARCHIE Chat module to match LCARS theme and be responsive at Fold5 sizes (374px/717px).

**Architecture:** CSS-only changes in the inline `{% block styles %}` of `archie_chat.html`, plus adding an LCARS frame wrapper in `{% block content %}`. No JS changes, no new files.

**Tech Stack:** CSS, Jinja2 template, LCARS design tokens

---

### Task 1: Replace purple gradients with theme accent

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (inline CSS, lines 5-2829)

**Step 1: Replace all hardcoded purple gradient references**

There are 5 places where `#667eea` / `#764ba2` purple gradient is hardcoded. Replace with the admin ops gold accent.

| Line | Current | Replace With |
|------|---------|-------------|
| ~906 | `.welcome-icon` background gradient `#667eea → #764ba2` | `var(--archie-cyan, #00d4ff) → var(--archie-purple, #8b5cf6)` |
| ~921 | `.welcome-icon::after` gradient (glow) | Same as above |
| ~931 | `.welcome-message h2` gradient text | `var(--archie-cyan, #00d4ff) → var(--archie-purple, #8b5cf6)` |
| ~34 | `.command-interface::before` grid BG | `rgba(0, 212, 255, 0.03)` (cyan tint instead of purple) |
| ~2548 | `.toast` box-shadow | `rgba(0, 212, 255, 0.15)` |

Also replace all remaining `color: var(--archie-purple)` on capability-tag icons and suggestion-chip icons with `var(--archie-cyan)` to match the LCARS cyan accent used across the platform.

**Step 2: Replace font references**

Replace the Google Fonts import (line 6):
```css
/* OLD */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap');
```

Change to use platform fonts (Antonio/Orbitron already loaded via base.html):
```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');
```

Add heading font overrides:
```css
.welcome-message h2,
.sidebar h1,
.sidebar h3 {
    font-family: 'Orbitron', var(--archie-font-mono), monospace;
    letter-spacing: 1px;
    text-transform: uppercase;
}
```

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "fix(chat): replace purple gradients with theme accent colors"
```

---

### Task 2: Add LCARS frame wrapper

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (content block, line ~2834)

**Step 1: Wrap .command-interface in LCARS frame**

Replace the current structure (lines 2833-2834):
```html
<div class="toast-container" id="toastContainer"></div>
<div class="command-interface">
```

With:
```html
<div class="toast-container" id="toastContainer"></div>
<div class="lcars-frame chat-lcars-frame">
    <div class="lcars-sidebar">
        <div class="lcars-elbow-top"></div>
        <div class="lcars-segment" style="background: var(--archie-cyan); flex: 2;"></div>
        <div class="lcars-segment" style="background: var(--archie-orange); flex: 1;"></div>
        <div class="lcars-segment" style="background: var(--archie-purple); flex: 1.5;"></div>
        <div class="lcars-elbow-bottom"></div>
    </div>
    <div class="lcars-content">
<div class="command-interface">
```

And at the very end of `.command-interface` (before `{% endblock %}`), close the LCARS wrapper:
```html
</div><!-- .command-interface -->
    </div><!-- .lcars-content -->
</div><!-- .lcars-frame -->
```

**Step 2: Add LCARS frame CSS overrides**

Add to the inline CSS (after the existing styles, before the `@media` queries):

```css
/* LCARS Frame Integration */
.chat-lcars-frame {
    display: flex;
    height: calc(100vh - 52px);
    overflow: hidden;
}

.chat-lcars-frame .lcars-sidebar {
    width: 48px;
    min-width: 48px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px 0;
    background: var(--archie-bg-primary);
    flex-shrink: 0;
}

.chat-lcars-frame .lcars-elbow-top,
.chat-lcars-frame .lcars-elbow-bottom {
    width: 48px;
    height: 32px;
    background: var(--archie-cyan);
    border-radius: 0 0 24px 0;
    flex-shrink: 0;
}

.chat-lcars-frame .lcars-elbow-bottom {
    border-radius: 0 24px 0 0;
}

.chat-lcars-frame .lcars-segment {
    border-radius: 0 8px 8px 0;
}

.chat-lcars-frame .lcars-content {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.chat-lcars-frame .command-interface {
    height: 100%;
}
```

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "fix(chat): add LCARS frame wrapper matching platform style"
```

---

### Task 3: Fix responsive breakpoints and overflow

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (inline CSS, lines ~2451-2528)

**Step 1: Replace the existing media queries**

Replace the existing `@media (max-width: 900px)` and `@media (max-width: 600px)` blocks (lines 2451-2528) with platform-standard breakpoints plus Fold5-specific fixes:

```css
/* ============================================
   RESPONSIVE: Tablet (Fold5 open @ 717px)
   ============================================ */
@media (max-width: 768px) {
    .chat-lcars-frame .lcars-sidebar {
        width: 32px;
        min-width: 32px;
    }
    .chat-lcars-frame .lcars-elbow-top,
    .chat-lcars-frame .lcars-elbow-bottom {
        width: 32px;
        height: 24px;
        border-radius: 0 0 16px 0;
    }
    .chat-lcars-frame .lcars-elbow-bottom {
        border-radius: 0 16px 0 0;
    }

    .sidebar-hamburger { display: inline-flex; align-items: center; }
    .sidebar-close { display: block; }
    .sidebar {
        position: fixed; top: 0; left: 0; bottom: 0;
        width: 280px; z-index: 999;
        transform: translateX(-100%);
        transition: transform .3s ease;
        overflow-y: auto;
    }
    .sidebar.drawer-open { transform: translateX(0); }

    #voice-sidebar { width: 100%; right: -100%; }
    #collab-history-sidebar { display: none; }
    #work-products-panel { display: none; }
    #dual-chat-container { flex-direction: column; }
    .chat-panel:first-child { border-right: none; border-bottom: 1px solid var(--archie-border-default); }
    .resize-handle { width: auto; height: 6px; cursor: row-resize; border-left: none; border-right: none; border-top: 1px solid var(--archie-border-default); border-bottom: 1px solid var(--archie-border-default); }
    .collab-message { max-width: 95%; }

    .welcome-message { padding: 24px 16px; }
    .welcome-message h2 { font-size: 1.25rem; }
    .welcome-message p { font-size: 0.85rem; }
    .welcome-capabilities { gap: 6px; }
    .capability-tag { padding: 6px 10px; font-size: 0.75rem; }

    .suggestions-row { gap: 6px; }
    .suggestion-chip { padding: 6px 10px; font-size: 0.75rem; white-space: nowrap; }

    .mode-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
    .mode-tabs::-webkit-scrollbar { display: none; }
    .chat-mode-btn { padding: 6px 12px; font-size: 0.75rem; white-space: nowrap; }

    .top-status-bar { flex-wrap: wrap; gap: 6px; }
    .status-right { gap: 4px; }
    .status-right button, .status-right a { padding: 6px; }
}

/* ============================================
   RESPONSIVE: Mobile (Fold5 closed @ 374px)
   ============================================ */
@media (max-width: 500px) {
    .chat-lcars-frame .lcars-sidebar {
        width: 20px;
        min-width: 20px;
    }
    .chat-lcars-frame .lcars-elbow-top,
    .chat-lcars-frame .lcars-elbow-bottom {
        width: 20px;
        height: 16px;
        border-radius: 0 0 10px 0;
    }
    .chat-lcars-frame .lcars-elbow-bottom {
        border-radius: 0 10px 0 0;
    }

    .messages-container { padding: 12px; }
    .message { max-width: 95%; }
    .input-area { padding: 8px 12px 12px; }

    .welcome-message { padding: 16px 8px; }
    .welcome-icon { width: 56px; height: 56px; font-size: 24px; border-radius: 16px; }
    .welcome-icon::after { border-radius: 20px; }
    .welcome-message h2 { font-size: 1.1rem; }
    .welcome-message p { font-size: 0.8rem; line-height: 1.5; }
    .welcome-capabilities { gap: 4px; }
    .capability-tag { padding: 5px 8px; font-size: 0.7rem; }

    .suggestions-row { gap: 4px; overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; padding-bottom: 4px; scrollbar-width: none; }
    .suggestions-row::-webkit-scrollbar { display: none; }
    .suggestion-chip { flex-shrink: 0; padding: 5px 10px; font-size: 0.7rem; }

    .mode-tabs { padding: 6px 8px; gap: 2px; }
    .chat-mode-btn { padding: 5px 8px; font-size: 0.7rem; }
    .chat-mode-btn i { display: none; }

    .top-status-bar { padding: 4px 8px; }
    .status-left { gap: 4px; }
    .workflow-indicator { font-size: 0.7rem; padding: 4px 6px; }
    .status-right button, .status-right a { padding: 4px; }
    .status-right button i, .status-right a i { width: 16px; height: 16px; }

    .chat-input { font-size: 0.85rem; }

    #collab-templates { grid-template-columns: 1fr; }
    .collab-toolbar { padding: 6px 8px; }
    .collab-btn { padding: 4px 8px; font-size: 0.65rem; }
}
```

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "fix(chat): responsive breakpoints for Fold5 (374px/717px)"
```

---

### Task 4: Visual verification

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
sleep 15
```

**Step 2: Screenshot at all 3 breakpoints**

Using Playwright, take screenshots at:
- 1280x800 (desktop)
- 717x900 (Fold5 open)
- 374x800 (Fold5 closed)

Verify:
- LCARS frame visible with colored segments on left
- No content clipping or overflow at 374px
- Capability tags wrap properly
- Suggestion chips scrollable or wrap
- Mode tabs fit or scroll
- Input field full-width
- Welcome text fully visible

**Step 3: Final commit and push**

```bash
git push
```
