# ARCHIE Chat UI CSS Fix — Design

**Date**: 2026-03-02
**Status**: Approved

---

## Problem

ARCHIE Chat module doesn't match the LCARS theme used by all other gold-standard modules. Content overflows/clips at Fold5 sizes (374px closed, 717px open). Missing LCARS frame wrapper, wrong fonts, wrong accent colors, non-standard breakpoints.

## Approach: CSS-Only Fix

Keep existing layout structure (sidebar + chat area) and all functionality. Fix via CSS changes in the inline `{% block styles %}` plus adding the LCARS frame wrapper divs.

## Changes

### 1. LCARS Frame Wrapper
Add standard `lcars-frame` + `lcars-sidebar` + `lcars-content` wrapper divs around chat content. Same pattern as Bridge/Consciousness/Autonomy.

### 2. Responsive Breakpoints
Replace 900px/600px with platform-standard breakpoints:
- 768px: sidebar → drawer, chat full-width
- 500px: compact mode for Fold5 closed (374px)

### 3. Overflow Fixes
- Suggestion chips: flex-wrap: wrap
- Capability buttons: flex-wrap: wrap, max-width: 100%
- Mode tabs: overflow-x: auto with touch scrolling
- Welcome text: proper padding at mobile
- Input: full-width, shorter placeholder at small screens

### 4. Theme Alignment
- Headings: Orbitron font
- Section labels: Antonio font
- Accent: --archie-accent (gold #FFAA00) instead of hardcoded purple gradient
- Status badges: lcars-btn patterns

## Files Changed
- `templates/tools/archie_chat.html` — LCARS frame wrapper + inline CSS fixes
