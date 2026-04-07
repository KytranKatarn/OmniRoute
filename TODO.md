# Consciousness UX Overhaul — Remaining Work

## Project #222 | Task #1647 (Phase 6 — Visual QA)

### IMMEDIATE: Fix Strip Layout with Playwright

**Step 1: Get Playwright working**
- Fresh session → Playwright MCP will auto-connect
- Login: admin / Kyt$13ran2025
- Navigate: http://192.168.1.200:3000/tools/consciousness

**Step 2: Fix status strip buttons at 717px (Fold 5 unfolded)**
- The EN / THEME / ALERTS buttons in the status strip don't fit well at 717px
- User said: "border of button doesn't fit inside frame of bar"
- Resize Playwright to 717px, screenshot, fix CSS, verify
- File: `platform_v2/static/css/lcars-header.css`
- Current strip CSS:
  ```
  .lcars-header-strip { height: 26px; }
  .lcars-strip-btn { height: 18px; padding: 0 12px; border-radius: 4px; }
  @717px: icons-only, height: 14px, padding: 0 6px
  ```

**Step 3: Check tab row at 717px**
- 6 tabs (Dashboard, Intelligence, Knowledge, GitHub, Languages, Code Health)
- May crowd or overflow at 717px with full labels
- Consider: horizontal scroll, or short labels at this breakpoint

**Step 4: Verify all 6 breakpoints**
Screenshot at each width:
- [ ] 1440px (desktop)
- [ ] 1024px (laptop)
- [ ] 768px (tablet)
- [ ] 717px (Fold 5 unfolded) ← PRIORITY
- [ ] 480px (phone)
- [ ] 360px (Fold 5 folded)

Check at each:
- Header elbow alignment with panel frames below (both 56px)
- Strip buttons fit inside strip frame
- Tabs readable and not overlapping
- Neural Core frame visible
- Toast notifications styled properly

### THEN: Complete Phase 6 QA

Screenshot every TAB at every breakpoint:
- Dashboard tab: Neural Core + HUD + System Health frame
- Intelligence tab: 5 LCARS panels + ApexCharts + 3D graph
- Knowledge tab
- GitHub tab
- Languages tab
- Code Health tab

### Key Files

| File | Purpose |
|------|---------|
| `platform_v2/static/css/lcars-header.css` | Header + strip + tabs + toasts + bm- modals + responsive |
| `platform_v2/templates/includes/lcars-header.html` | Header template (elbow, title bar, strip, tabs, footer) |
| `platform_v2/static/js/lcars-header.js` | Tab switching, alerts, toasts, ops polling |
| `platform_v2/static/css/neural-core.css` | Neural Core hero (teal, glassmorphism, scanline) |
| `platform_v2/static/js/consciousness-dashboard-v2.js` | ApexCharts, 3D graph, expertise panels |
| `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | Main template |

### What's Already Done (Phases 1-5)

- [x] Phase 1: Platform breakpoints (archie-breakpoints.css)
- [x] Phase 2: LCARS header HTML template (shared include)
- [x] Phase 3: LCARS header CSS (responsive + alert states + toasts)
- [x] Phase 4: Light/dark mode + i18n
- [x] Phase 5: Sci-fi visuals (ApexCharts, 3D graph, scanlines, count-up)
- [x] Ops bar integration (hidden legacy bars, elbow alert state, LCARS toasts)
- [x] Neural Core LCARS frame + visual upgrade
- [x] Status strip (stardate | EN | THEME | ALERTS)
- [x] Left column alignment (56px header + 56px panels)
- [x] Footer bar for scroll blending
- [x] Toast dismiss persistence (sessionStorage)
- [x] bm- modal styles added to lcars-header.css
- [ ] Phase 6: Visual QA ← IN PROGRESS

### Architecture Notes

- Elbow = clickable alert indicator (red/yellow pulse, opens notification modal)
- Status strip sits between title bar and tabs
- Ops summary polls /tools/autonomy/api/ops-summary every 30s
- First poll silent (no toast on page load), toast only on state change
- Dismissed toasts tracked in sessionStorage
- All purple (#8b5cf6) converted to var(--cat-accent) (#00ffff teal)
- Shared LCARS header: any module uses one `{% include 'includes/lcars-header.html' %}`
