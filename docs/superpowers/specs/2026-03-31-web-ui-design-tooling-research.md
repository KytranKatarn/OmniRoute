# Web UI/CSS Design Tooling Research for Claude Code

**Date**: 2026-03-31
**Goal**: Find the best tools, MCP servers, skills, and approaches for high-quality UI/CSS work in Claude Code on an LCARS-themed platform.

---

## 1. MCP Servers for Web Design

### Tier 1 — Install Immediately

| MCP Server | What It Does | Install Command |
|------------|-------------|-----------------|
| **Playwright MCP** (Microsoft) | Browser control, screenshots, DOM snapshots, form filling, visual QA | `claude mcp add playwright -- npx @playwright/mcp@latest` |
| **Chrome DevTools MCP** (Google) | Live CSS inspection, DOM analysis, network monitoring, console, performance | `claude mcp add chrome-devtools -- npx @anthropic/chrome-devtools-mcp@latest` |
| **Context7** | Up-to-date library docs (Tailwind, Bootstrap, etc.) injected into context | Already installed |

### Tier 2 — Install When Needed

| MCP Server | What It Does | Install Command |
|------------|-------------|-----------------|
| **Figma MCP** (Official) | Read Figma designs, generate code from layers, push code back to Figma | `claude mcp add figma -- npx @anthropic/figma-mcp@latest` |
| **Screenshot MCP** (upnorthmedia) | Capture full-page, element, and device-specific screenshots | `claude mcp add screenshot -- npx @anthropic/screenshot-mcp@latest` |
| **Magic UI MCP** | React + Tailwind component library exposed over MCP | See github.com/magicuidesign/mcp |
| **BrowserMCP** | Chrome extension controlling your actual logged-in browser | Chrome Web Store + MCP config |

### Token Budget Warning

MCP servers consume tokens at session start. Keep 3-5 active max. Disable servers when not in use. Prefer skills over MCP servers for static knowledge.

---

## 2. Claude Code Skills for UI Work

### Already Installed (Check Your Plugin List)

| Skill | What It Does |
|-------|-------------|
| **frontend-design** (Anthropic official) | Picks an aesthetic direction before writing code. 240+ styles, 127 font pairings, 99 UX guidelines. Avoids "generic AI look." |
| **ui-ux-pro-max** (nextlevelbuilder) | 50+ styles, 161 color palettes, 57 font pairings, 25 chart types across 10 stacks. Design System Generator. |

### Recommended Additional Skills

| Skill | Source | What It Does |
|-------|--------|-------------|
| **baseline-ui** | Part of "polish pipeline" | Fixes spacing, typography, and states after generation |
| **fixing-accessibility** | Part of "polish pipeline" | Keyboard nav, labels, focus, semantics |
| **sc:sc-analyze** | SuperClaude | Code quality analysis including CSS |
| **sc:sc-improve** | SuperClaude | Systematic code improvements |

### Polish Pipeline (3-Step Sequential)

1. **frontend-design** — Generate the page with real aesthetic choices
2. **baseline-ui** — Fix spacing, typography, interactive states
3. **fixing-accessibility** — Keyboard, labels, focus, semantics

Source: [Claude-Code-Frontend-Design-Toolkit](https://github.com/wilwaldon/Claude-Code-Frontend-Design-Toolkit)

---

## 3. Best Practices for Large HTML/CSS/JS Refactoring

### The Visual Regression Safety Net

1. **Baseline screenshots** — Before touching anything, capture screenshots of every meaningful state (not just page routes — include open modals, dropdowns, hover states, mobile breakpoints)
2. **Enumerate states upfront** — A regression in the navigation drawer won't show if you never screenshotted the drawer open
3. **Compare after each phase** — Claude can read image files and compare baseline vs current screenshots, identifying specific differences

### Incremental Refactoring Protocol

1. **Audit first** — Have Claude analyze existing styles: find duplicated rules, outdated resets, copy-pasted styles, hard-coded values
2. **Lock behavior** — Generate characterization tests or screenshot baselines before changing anything
3. **Refactor in phases** — One component/section at a time, verify after each
4. **Review every diff** — Treat AI output like a junior developer's PR; review line by line

### Splitting Large Templates (5000+ Lines)

- Break into Jinja2 includes/macros by component section
- Extract CSS into separate files per component (already done for dashboard, login, signup)
- Extract JS into module files with clear API boundaries
- Use BEM or similar naming convention to avoid specificity wars
- Keep a "CSS map" comment at the top of each file listing what it styles

### CSS Specificity Management

- Use CSS custom properties (variables) for theming — already doing this with `--bm-accent`
- Prefer class selectors over tag/ID selectors
- Use a consistent naming prefix per module (e.g., `cs-` for Consciousness, `devhq-` for Dev HQ)
- Avoid `!important` — if needed, it signals a specificity problem to fix

---

## 4. Tailwind CSS Assessment

### Pros for Your Platform

- Utility classes enforce consistency across modules
- Design tokens (spacing, colors, fonts) built in
- Responsive breakpoints (480/768/1024) map cleanly
- Reduces CSS file size through deduplication

### Cons for Your Platform

- **Major migration effort** — 46 modules with existing LCARS CSS
- **LCARS custom components** (elbows, frame blocks, sweep arcs) need custom CSS regardless
- **Jinja2 templates** — Tailwind works best with component frameworks (React/Vue)
- **Runtime overhead** — Need build step (PostCSS/JIT) added to Docker pipeline

### Recommendation

**Do NOT switch to Tailwind.** Your LCARS design system is too custom. Instead:
- Formalize your existing CSS variables into a design token system
- Create a `lcars-tokens.css` with all colors, spacing, typography as CSS custom properties
- Use your existing prefix convention (`cs-`, `devhq-`, `bm-`, `sc-`) as your "utility system"

---

## 5. LCARS Design Resources

### Open Source LCARS Frameworks (GitHub)

| Repo | Stars | Notes |
|------|-------|-------|
| [joernweissenborn/lcars](https://github.com/joernweissenborn/lcars) | Highest | Stylus-based, client-side, most complete component set |
| [louh/lcars](https://github.com/louh/lcars) | High | Responsive, pure HTML/CSS/JS |
| [mttaggart/lcars-css](https://github.com/mttaggart/lcars-css) | Medium | Simple CSS library, easy to extract patterns from |
| [xiphoseer.de/htmlcars](https://xiphoseer.de/htmlcars/) | — | Modern web standards, no images/absolute positioning |
| [sumawav/LCARS](https://github.com/sumawav/LCARS) | Medium | Pure CSS framework |

### What to Extract from These

- **Color palettes** — Canonical LCARS colors (Federation standard: #FF9900, #CC99CC, #9999FF, #FF9966, #CC6699, #FFCC99, #99CCFF, #FF6633)
- **Typography patterns** — Swiss 911 Ultra Compressed (canonical) or Antonio/Orbitron (web alternatives)
- **Component patterns** — Elbow corners, sweep arcs, frame blocks, status bars
- **Animation patterns** — Data stream scrolling, alert pulses, scan lines

### Recommendation

Review `joernweissenborn/lcars` and `xiphoseer.de/htmlcars` for component patterns you may be missing. Your existing LCARS implementation is already custom and mature — these are reference material, not replacements.

---

## 6. Browser-in-the-Loop Workflow

### Recommended Setup: Playwright MCP

The optimal workflow for CSS editing with Claude Code:

```
1. Edit CSS/HTML in Claude Code
2. Claude navigates to http://192.168.1.200:3000/your-page via Playwright
3. Claude takes screenshot + DOM snapshot
4. Claude analyzes the result and identifies issues
5. Claude makes corrections
6. Repeat until visually correct
7. Commit
```

### Playwright MCP vs Chrome DevTools MCP

| Feature | Playwright MCP | Chrome DevTools MCP |
|---------|---------------|-------------------|
| **Best for** | Automated QA, screenshot comparison | Live CSS debugging, DOM inspection |
| **Browser** | Headless Chromium (new profile) | Your actual Chrome (logged-in sessions) |
| **CSS inspection** | Via accessibility tree snapshots | Full computed styles, box model |
| **Screenshots** | Built-in, multiple viewports | Built-in |
| **Setup** | Zero config | Requires Chrome debug port |
| **Token cost** | Lower (accessibility tree is compact) | Higher (full DOM + styles) |

### Recommendation

**Start with Playwright MCP** (already available in your MCP list). Use it for:
- Screenshot verification after every CSS change
- Responsive testing at 480/768/1024px breakpoints
- Visual regression detection

**Add Chrome DevTools MCP** when you need to debug specific CSS issues (computed styles, box model, specificity).

---

## 7. Actionable Next Steps

### Immediate (This Session)

1. Verify Playwright MCP is configured: `claude mcp list` should show it
2. Test the browser loop: have Claude navigate to your platform and screenshot a page
3. Install the `frontend-design` skill if not present (Anthropic official)

### Short Term (This Week)

4. Create `lcars-tokens.css` — formalize all CSS custom properties into one token file
5. Set up a screenshot baseline for critical pages (dashboard, bridge, department HQ)
6. Review `joernweissenborn/lcars` for any component patterns worth adopting

### Medium Term (This Month)

7. Evaluate Chrome DevTools MCP for complex CSS debugging sessions
8. Consider Figma MCP if you want design-to-code workflow for new modules
9. Build a "CSS audit" script that checks for duplicate rules, unused classes, `!important` abuse

---

## Sources

- [Playwright MCP Setup with Claude Code](https://www.builder.io/blog/playwright-mcp-server-claude-code)
- [Simon Willison: Playwright MCP with Claude Code](https://til.simonwillison.net/claude-code/playwright-mcp-claude-code)
- [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- [Chrome DevTools MCP Blog](https://developer.chrome.com/blog/chrome-devtools-mcp)
- [Figma MCP Server Guide](https://github.com/figma/mcp-server-guide)
- [Figma + Claude Code Blog](https://www.figma.com/blog/introducing-claude-code-to-figma/)
- [Claude-Code-Frontend-Design-Toolkit](https://github.com/wilwaldon/Claude-Code-Frontend-Design-Toolkit)
- [UI/UX Pro Max Skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
- [Best MCP Servers 2026](https://www.builder.io/blog/best-mcp-servers-2026)
- [10 MCP Servers for Frontend Devs](https://thenewstack.io/10-mcp-servers-for-frontend-developers/)
- [CSS Refactoring with AI Safety Net](https://danielabaron.me/blog/css-refactoring-with-an-ai-safety-net/)
- [joernweissenborn/lcars](https://github.com/joernweissenborn/lcars)
- [louh/lcars](https://github.com/louh/lcars)
- [xiphoseer.de/htmlcars](https://xiphoseer.de/htmlcars/)
- [Addy Osmani: Chrome DevTools MCP](https://addyosmani.com/blog/devtools-mcp/)
