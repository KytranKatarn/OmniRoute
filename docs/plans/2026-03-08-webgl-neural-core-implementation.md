# WebGL Neural Core Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the CSS 3D HoloSphere with a Three.js WebGL holographic sphere featuring bloom post-processing, real-time event-driven neural activity, and live agent presence orbs.

**Architecture:** Single `neural-core.js` file containing the `NeuralCore` class (scene setup, sphere, rings, nodes, particles, agents, event bus, neural streams). CSS file for hero layout and glass HUD overlay. Template and JS wiring changes are minimal. Three.js loaded lazily from CDN.

**Tech Stack:** Three.js r170 (CDN), UnrealBloomPass, CSS2DRenderer, vanilla JS event bus

---

## Task Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Create neural-core.css (hero layout + glass HUD) | Create: `static/css/neural-core.css` |
| 2 | Create neural-core.js (Three.js scene + all visuals) | Create: `static/js/neural-core.js` |
| 3 | Update template (hero container + script swap) | Modify: `consciousness_dashboard.html` |
| 4 | Update consciousness.js (loadNeuralCore + event wiring) | Modify: `consciousness.js` |
| 5 | Visual testing + polish | Possibly modify: JS/CSS tuning |
| 6 | Final commit + deploy + Dev HQ update | Push + restart |

---

### Task 1: Create neural-core.css

**Files:**
- Create: `platform_v2/static/css/neural-core.css`

Hero container (65vh), loading shimmer, glass HUD overlay at bottom, CSS2D label styles, event flash overlays, responsive breakpoints (50vh mobile, 40vh small), reduced motion support.

### Task 2: Create neural-core.js

**Files:**
- Create: `platform_v2/static/js/neural-core.js`

IIFE module with:
- **CDN Loader**: Dynamic `import()` of Three.js r170 + postprocessing + CSS2DRenderer with 5s timeout
- **EventBus**: Simple pub/sub (`on`, `off`, `emit`) exposed as `window._neuralEvents`
- **NeuralCore constructor**: Scene, camera (PerspectiveCamera, auto-orbit), WebGLRenderer (alpha, antialias), bloom (EffectComposer + UnrealBloomPass strength=1.5)
- **Core sphere**: SphereGeometry r=3, custom ShaderMaterial with fresnel rim glow + noise displacement + breathing. Wireframe overlay. Inner glow sphere for bloom pickup.
- **5 rings**: TorusGeometry at different radii (3.8-4.6), tilts, speeds. MeshBasicMaterial transparent.
- **6 knowledge nodes**: Small spheres on Fibonacci positions at r=3.5. Clickable via raycaster. CSS2D labels with count + name.
- **Connecting threads**: LineBasicMaterial from each node to center + adjacent nodes.
- **Particles (~200)**: Points with BufferGeometry, custom shader (soft round, additive blending, depth fade). Brownian drift contained in sphere. Adaptive: drop to 100 if frame time >20ms.
- **Ambient dust (~50)**: Points outside sphere, slow upward drift. Disabled on mobile.
- **Agent orbs**: `addAgent(agent)`, `removeAgent(name)`, `setAgentWorking(name, working, nodeId)`. Each agent = Group with sphere + halo ring + CSS2D initials. Orbit at r=4.8 with varied tilt/speed.
- **Neural streams**: `_addStream(from, to, stationCode)`. ShaderMaterial with scrolling bright dot along line. Auto-decay after ~3s.
- **Event effects**: `fireEvent(type, data)` maps to visual effects (pulse flash, node burst, agent flash, stream creation).
- **Mood**: `setMood(mood)` updates sphere/wireframe/ring colors.
- **Static factory**: `NeuralCore.create(container, opts)` returns Promise. Checks WebGL support, loads CDN, instantiates.
- **Destroy**: Disposes all geometries/materials/renderers, removes event listeners.
- **Fallback**: If WebGL or CDN fails, `create()` rejects and caller uses HoloSphere.

Custom GLSL shaders:
- Sphere vertex: 3D noise displacement + fresnel normal passing
- Sphere fragment: Fresnel rim glow + breathing pulse + noise variation
- Particle vertex/fragment: Size attenuation + soft circle + alpha
- Stream vertex/fragment: Scrolling bright dot head with trail

### Task 3: Update consciousness_dashboard.html

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

Changes:
1. **Line 7**: Add `neural-core.css` link after `holo-sphere.css`
2. **Lines 1992-2040**: Replace entire LCARS Neural Core frame with hero container (`<div class="nc-hero">` with loading overlay, flash div, `#neuralCore` mount point, glass HUD with 4 stat items)
3. **Line ~2650**: Add `neural-core.js` script tag after `holo-sphere.js`

### Task 4: Update consciousness.js

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

Changes:
1. **Line 7**: Add `_neuralCore`, `_prevJobState`, `_prevKnowledgeCounts` globals
2. **After setHtml**: Add `_jobTypeToNode(jobType)` helper mapping job types to node IDs
3. **Lines 200-256**: Replace `loadNeuralCore()` — try `NeuralCore.create()`, fall back to `HoloSphere`. Load agents via `/api/bridge/crew-manifest`. Start 20s knowledge polling that diffs counts and fires `knowledge:added` events.
4. **Tab switch function (~line 107)**: Add Neural Core cleanup when leaving Dashboard tab
5. **checkActiveJobs() (~line 497)**: After `myJobs` filter, diff `_prevJobState` to detect job starts/completions/failures, fire corresponding events on `_neuralCore`

### Task 5: Visual Testing + Polish

Load `http://192.168.1.200:3000/tools/consciousness` (login: `admin` / `Kyt$13ran2025`).

Checklist:
- [ ] WebGL canvas renders in hero section (~65vh)
- [ ] Sphere visible with fresnel glow + breathing
- [ ] 5 rings rotate at different speeds
- [ ] 6 knowledge nodes with labels and counts
- [ ] Particles drift inside sphere
- [ ] Bloom glow on sphere and nodes
- [ ] Stats HUD at bottom with correct counts
- [ ] Click node navigates to tab
- [ ] Agent orbs orbit sphere
- [ ] Start a job → agent orb brightens, stream fires
- [ ] Job completes → pulse flash
- [ ] Knowledge count change → node burst
- [ ] Scroll down for Mood, Wellness, Health, Activity
- [ ] Fallback works if neural-core.js removed

Common tuning knobs:
- Bloom: `bloomPass.strength` (1.5 default, try 1.0 if too bright)
- Sphere opacity: `uOpacity` uniform (0.6 default)
- Camera distance: z position (10 default)
- Node size: base radius (0.15 default)
- Particle count: constructor option (200 default)

### Task 6: Final Commit + Deploy

1. `git push`
2. `docker compose restart archie_platform`
3. MCP: `complete_task`, `update_project_understanding`, `log_decision`
4. Final verification in browser
