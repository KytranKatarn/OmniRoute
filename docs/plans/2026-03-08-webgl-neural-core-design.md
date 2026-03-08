# WebGL Neural Core Design

## Overview

Replace the CSS 3D HoloSphere visualization in Consciousness Dashboard with a full Three.js WebGL scene featuring volumetric glow, bloom post-processing, real-time event-driven neural activity, and live agent presence.

## Goals

1. **Maximum visual impact** — Hero section filling top ~65vh of Dashboard tab
2. **Real-time data pulses** — Live visual feedback when jobs complete, knowledge is added, agents dispatch
3. **Neural activity streams** — Animated data flows between knowledge nodes (visible synapses)
4. **Live agent presence** — Agent orbs orbiting the sphere showing who's active and what they're working on
5. **Full WebGL** — Three.js with UnrealBloomPass for volumetric glow, custom shaders for fresnel rim effects

## Architecture

### Files

- **Create**: `static/js/neural-core.js` — Main NeuralCore class (Three.js scene, all visuals)
- **Create**: `static/css/neural-core.css` — Hero layout, overlay HUD, glass panels
- **Modify**: `consciousness_dashboard.html` — Swap holo-sphere refs for neural-core, resize container
- **Modify**: `consciousness.js` — Update `loadNeuralCore()` to instantiate NeuralCore instead of HoloSphere

### Dependencies

- Three.js r170 via CDN (lazy-loaded on Dashboard tab activation):
  - `three.module.min.js` (~150KB gzipped)
  - `EffectComposer`, `RenderPass`, `UnrealBloomPass` from examples/jsm
  - `CSS2DRenderer` for crisp text labels
- Existing `holo-sphere.js` / `holo-sphere.css` remain as shared fallback component

### Loading Strategy

- Lazy load Three.js only when Dashboard tab is active
- 5s timeout — falls back to existing HoloSphere on CDN failure
- WebGL2 capability check — no WebGL = HoloSphere fallback

## Visual Elements

### Core Sphere

- `SphereGeometry` (radius 3, 64 segments)
- Custom `ShaderMaterial` with:
  - Fresnel rim glow (edges brighter than center)
  - Animated noise displacement for organic breathing
  - Semi-transparent with wireframe overlay on second pass
- Color driven by mood (7 moods: focused=purple, curious=cyan, happy=green, processing=amber, empathetic=pink, neutral=purple, confident=blue)

### 5 Concentric Rings

- `TorusGeometry` at different tilts
- True 3D with bloom making them glow
- Thin, semi-transparent, independent slow rotations

### Knowledge Nodes (6)

- Small `SphereGeometry` (radius 0.15) on Fibonacci-sphere positions
- Nodes: Conversations (blue), Code (green), Vault (purple), Repos (amber), Learned (cyan), Sessions (pink)
- Size scales with count (more data = slightly larger)
- Clickable via raycasting — navigates to relevant tab
- Labels via `CSS2DRenderer` overlay (crisp text)

### Connecting Threads

- `BufferGeometry` lines from each node to center + adjacent nodes
- Faint glow, pulse brighter during neural activity events

### Particle System (~200)

- `Points` with `BufferGeometry` inside sphere volume
- Custom `ShaderMaterial` for soft round points with depth fade
- Slow Brownian drift, contained within sphere radius

### Ambient Dust (~50)

- Separate `Points` system in full scene space outside sphere
- Very faint, slow upward drift

### Post-Processing

- `EffectComposer` pipeline:
  - `RenderPass` — main scene
  - `UnrealBloomPass` — strength 1.5, threshold 0.1, radius 0.8

## Real-Time Events

### Event Sources (Hybrid — No New Infrastructure)

1. **Job watcher** — `checkActiveJobs()` already polls Bridge every 5s. Diff previous job list to detect completions/starts/failures.
2. **Knowledge watcher** — Poll `/api/dashboard/summary` every 20s. Compare counts, fire node bursts on increases.
3. **Event bus** — `window._neuralEvents` pub/sub. Any module can emit events.

### Event → Visual Mapping

| Event | Visual Effect |
|-------|-------------|
| `job:completed` | Pulse wave from center, agent orb flash, stream to relevant node |
| `job:started` | Agent orb brightens, thin stream connects to target node |
| `job:failed` | Brief red flash on agent orb, red pulse ripple |
| `knowledge:added` | Target node burst (scale + glow), particle shower |
| `embedding:progress` | Stream flows knowledge node → center core |
| `agent:dispatched` | New orb flies in from scene edge to orbit position |

### Neural Activity Streams

- Animated `Line2` or `TubeGeometry` with scrolling bright-dot shader
- Shows data flowing between nodes (ingest → embed → index)
- Multiple simultaneous streams supported

### Extensibility

New events = one line: `_neuralEvents.emit("eventName", data)`. Neural Core maps event types to visuals via config table.

## Agent Presence

### Agent Orbs

- Orbit radius ~4.0 (sphere is 3.0)
- Each active agent gets a `Group`:
  - Small glowing `SphereGeometry` (radius 0.2), station-colored emissive material
  - Initials via `CSS2DRenderer` (e.g., "NX", "PX") — crisp, camera-facing
  - Faint halo `TorusGeometry` ring
- Orbit speeds vary per agent (avoid clustering)
- Orbit planes tilted differently (spread across latitude bands)

### Agent States

| State | Visual |
|-------|--------|
| Idle | Normal glow, steady orbit |
| Working | Brighter emissive, pulsing halo, stream to knowledge node |
| Paused | Dimmed, slower orbit, muted color |
| Cloud dispatch | Faint upward particle trail |

### Data Source

- `get_crew_manifest()` via Bridge API (already polled by `checkActiveJobs`)
- Diff agent states on each poll, animate transitions (fly in / fade out)
- Max 13 agents (matches MAX_LOADED_MODELS)

## Performance

### Targets

- 60fps desktop (Quadro M4000)
- 30fps acceptable on laptops/tablets
- ~100 total draw calls (sphere + 5 rings + 6 nodes + 13 agents + particles + streams)
- Adaptive particles: start 200, drop to 100 if frame time > 20ms

### Optimizations

- Single `requestAnimationFrame` loop
- Pause on `visibilitychange` (tab hidden)
- Bloom only on emissive objects (selective bloom layer)
- Threads redrawn every 30 frames, not every frame

### Fallbacks

- No WebGL → HoloSphere (CSS 3D) fallback
- `prefers-reduced-motion` → no bloom, no rotation, no particles, static scene
- CDN timeout (5s) → HoloSphere fallback with console warning
- Mobile (<768px) → 80 particles, no dust, bloom halved, hero shrinks to 50vh

### Cleanup

- `NeuralCore.destroy()` disposes all geometries, materials, textures, renderers
- Called on tab switch away from Dashboard + page unload

## Layout

### Hero Section (Dashboard Tab)

```
+------------------------------------------------------------------+
|  LCARS FRAME — NEURAL CORE                                       |
|  +------------------------------------------------------------+  |
|  |                                                            |  |
|  |              [WebGL Canvas — 65vh]                         |  |
|  |                                                            |  |
|  |     Agent orbs orbiting...  Sphere with nodes...           |  |
|  |     Neural streams firing...                               |  |
|  |                                                            |  |
|  |  +--------+ +--------+ +--------+ +--------+              |  |
|  |  |Knowledge| |GitHub  | |Embedded| |Agents  |  ← HUD      |  |
|  |  | 4,892   | | 1,203  | |  100%  | |  5/13  |  overlay    |  |
|  |  +--------+ +--------+ +--------+ +--------+              |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
|  MOOD STATE          |  CREW WELLNESS                            |
+------------------------------------------------------------------+
|  SYSTEM HEALTH       |  ACTIVITY FEED                            |
+------------------------------------------------------------------+
```

Stats HUD overlays as glass panels at bottom of WebGL canvas. Scroll down for operational data.
