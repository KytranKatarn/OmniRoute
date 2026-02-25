# Neural Core v2 — Holographic Sphere Design

**Date:** 2026-02-25
**Status:** Approved
**Goal:** Replace the flat 2D orbital Neural Core with a cinematic holographic sphere visualization and frosted-glass nav bar. Build as shared reusable components.

---

## Architecture

Two new shared components, zero external dependencies:

| Component | Files | Purpose |
|-----------|-------|---------|
| **HoloSphere** | `static/js/holo-sphere.js` + `static/css/holo-sphere.css` | 3D holographic sphere with particles, nodes, effects |
| **GlassNav** | `static/js/glass-nav.js` + `static/css/glass-nav.css` | Frosted glass floating nav bar with sliding indicator |

### HoloSphere API

```js
var sphere = new HoloSphere(containerEl, {
    nodes: [
        { id: "conversations", label: "Conv", count: 4155, color: "#3b82f6", tab: "knowledge" },
        // ... N nodes, auto-distributed via Fibonacci sphere
    ],
    mood: "focused",
    particleCount: 120,
    ambientDust: true,
    ambientTarget: document.querySelector(".cs-body"),
    accentColor: "#8b5cf6",     // CSS custom prop --holo-accent
    onNodeClick: function(node) { /* handler */ }
});

sphere.updateNode("conversations", { count: 4200 }); // triggers glitch + burst
sphere.setMood("curious");                             // shifts core color
sphere.destroy();                                       // cleanup
sphere.resize();                                        // responsive
```

### GlassNav API

```js
var nav = new GlassNav(navEl, {
    onSwitch: function(tabName) { /* handler */ }
});

nav.setActive("dashboard"); // slides indicator to tab
```

### Scalability

Nodes use **Fibonacci sphere distribution** to auto-position evenly in 3D space:
```
phi = acos(1 - 2*(i+0.5)/N)
theta = pi * (1 + sqrt(5)) * i
x = r * sin(phi) * cos(theta)
y = r * sin(phi) * sin(theta)
z = r * cos(phi)
```
Works identically for 6 or 60 nodes. Adding a knowledge type = adding an entry to the nodes array.

---

## Visual Design

### Holographic Sphere

**Shell:** 5 concentric CSS 3D rings (`transform-style: preserve-3d`, `perspective: 800px`). Each ring is a `<div>` with `border-radius: 50%`, thin translucent purple border, rotating at different speeds (20s-80s) and angles. Together they create a wireframe sphere illusion.

**Holographic Glow:** Radial gradient behind the sphere, breathing (scale 1.0→1.06 over 4s). Color shifts with mood.

**Knowledge Nodes:** DOM elements inside the sphere, positioned via `transform: translate3d(x,y,z)`. Depth effect: nodes with positive z are brighter/larger, negative z are dimmer/smaller. Slowly orbit by incrementing theta each frame. 32-40px glowing circles with count + label.

**Energy burst on update:** When a node's count changes, a ring scales from 0→2x over 0.6s with fading opacity.

**Connecting Threads:** SVG lines between nearby nodes (`rgba(accent, 0.06)`). Random threads briefly pulse brighter when API data arrives — simulates neural activity.

**Center Core:** 50px bright glow at center. Shows mood state text. Pulses with breathing animation.

### Particle System (3 Layers, 1 Canvas)

| Layer | Count | Behavior |
|-------|-------|----------|
| **Inner Sphere** | 80-100 | Orbit inside sphere volume. Wobble via sin/cos combinations. Color matches nearest node. Size 2-4px + 8px glow. Z-depth fading. |
| **Energy Streams** | 20-30 | Travel along bezier curves between nodes. Leave 3-4 frame trails. Burst of 5-10 launches from center when API returns data. |
| **Ambient Dust** | 30-40 | Float across entire page background (separate canvas, `pointer-events: none`). Tiny (1-2px), slow, alpha 0.1-0.2. Atmospheric. |

**Total:** ~150 particles. Single `requestAnimationFrame` loop. Well within Quadro M4000 budget.

**Reduced motion:** `prefers-reduced-motion` disables layers 1-2, halves layer 3 count.

### Cinematic Effects (All Pure CSS)

| Effect | Implementation | Trigger |
|--------|---------------|---------|
| **Holographic Scanlines** | `::after` overlay, 1px lines every 3px, scrolling downward 8s | Always on |
| **Data Pulse Wave** | Circular div, scales 0.5→2.0 over 0.8s, fading | On API data load |
| **Glitch on Update** | 150ms `clip-path` slicing + RGB shift | On node count change |
| **Surface Energy Sweep** | Gradient band translating top→bottom | Every 6-8s |
| **Ambient Page Glow** | Animated radial gradient behind sphere, 20s drift | Always on |

### Floating Glass Nav Bar

**Container:** Centered, `max-width: 680px`, `border-radius: 20px`, positioned at top of `.cs-body`.

**Glassmorphism:**
- `background: rgba(15, 15, 30, 0.6)`
- `backdrop-filter: blur(16px) saturate(1.4)`
- `border: 1px solid rgba(139, 92, 246, 0.15)`

**Tab Items:** Icons + labels, `justify-content: space-around`. Inactive = opacity only, no pill backgrounds.

**Sliding Indicator:** Single absolute-positioned pill element that transitions `left` and `width` (0.3s ease) when switching tabs. Glow shadow + 2px bottom accent.

**Responsive (<600px):** Labels hide, icons only, full-width bar, horizontal scroll with momentum.

---

## File Changes

### New Files
```
platform_v2/static/js/holo-sphere.js   — HoloSphere class
platform_v2/static/css/holo-sphere.css  — Sphere CSS, effects, responsive
platform_v2/static/js/glass-nav.js      — GlassNav class
platform_v2/static/css/glass-nav.css    — Glass nav CSS, responsive
```

### Modified Files
```
consciousness_dashboard.html  — New <link>/<script> tags,
                                replace .cs-tabs with GlassNav markup,
                                replace .nc-container with HoloSphere container,
                                remove old .nc-* CSS and .cs-tab CSS
consciousness.js              — HoloSphere/GlassNav instantiation in loadDashboard(),
                                remove _drawPathways(), _initParticles(), _ncMoodColors,
                                update switchConsciousnessTab() for GlassNav
```

### Deleted Code
- All `.nc-*` CSS from template (moved to `holo-sphere.css`)
- All `.cs-tab` CSS (replaced by `glass-nav.css`)
- `_drawPathways()`, `_initParticles()`, `_particles`, `_particleAnim`, `_ncMoodColors` from consciousness.js
- `@keyframes orbitalDrift/orbitalDriftReverse/particleFlow/coreBreath/nodeGlow/pathFlow`

---

## CSS Custom Properties (Themeable)

```css
:root {
    --holo-accent: #8b5cf6;
    --holo-accent-rgb: 139, 92, 246;
    --holo-bg: rgba(15, 15, 30, 0.6);
    --holo-glow-intensity: 1;
    --holo-particle-count: 120;   /* read by JS */
    --glass-blur: 16px;
    --glass-bg: rgba(15, 15, 30, 0.6);
    --glass-border: rgba(139, 92, 246, 0.15);
}
```

Modules override these to theme the components (e.g., Bridge uses `--holo-accent: #06b6d4`).

---

## Performance Budget

| Resource | Budget |
|----------|--------|
| Canvas particles | ≤150 at 60fps |
| CSS animated elements | ≤15 (rings, overlays, pseudo-elements) |
| DOM knowledge nodes | ≤30 (beyond that, cluster/group) |
| JS file size | ≤20KB combined (holo-sphere + glass-nav) |
| CSS file size | ≤8KB combined |
| GPU composited layers | ≤10 (`will-change`, `transform`, `opacity`) |

---

## Reuse Example (Future Bridge Module)

```js
var bridgeSphere = new HoloSphere(document.getElementById("bridgeViz"), {
    nodes: stationData,
    mood: "operational",
    particleCount: 60,
    ambientDust: false,
    accentColor: "#06b6d4"
});
```
