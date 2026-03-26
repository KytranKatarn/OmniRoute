# Modern Website Visual Effects & Techniques (2025-2026)
# Research compiled for AI company website — LCARS sci-fi aesthetic + Stripe-level polish

---

## 1. SCROLL-DRIVEN ANIMATIONS

### Horizontal Scroll Sections (GSAP ScrollTrigger)
```js
gsap.registerPlugin(ScrollTrigger);

let sections = gsap.utils.toArray(".panel");
gsap.to(sections, {
  xPercent: -100 * (sections.length - 1),
  ease: "none",
  scrollTrigger: {
    trigger: ".container",
    pin: true,
    scrub: 1,
    snap: 1 / (sections.length - 1),
    end: "+=" + (sections.length * 100) + "%"
  }
});
```

### Parallax Layers
```js
gsap.to(".bg-layer", { y: "-30%", scrollTrigger: { scrub: true } });
gsap.to(".mid-layer", { y: "-15%", scrollTrigger: { scrub: true } });
gsap.to(".fg-layer", { y: "0%", scrollTrigger: { scrub: true } });
```

### Scroll-Linked Progress Bar
```js
gsap.to(".progress-bar", {
  scaleX: 1,
  ease: "none",
  scrollTrigger: { scrub: 0.3 }
});
```

### Batch Stagger Reveal (Cards, Grid Items)
```js
ScrollTrigger.batch(".card", {
  onEnter: batch => gsap.to(batch, { opacity: 1, y: 0, stagger: 0.1 }),
  start: "top 85%"
});
```

### CSS-Only Scroll Animations (Native, Chrome 115+, Firefox 120+, Safari 18+)
```css
@keyframes reveal {
  from { opacity: 0; transform: translateY(50px); }
  to { opacity: 1; transform: translateY(0); }
}
.card {
  animation: reveal linear both;
  animation-timeline: view();
  animation-range: entry 0% entry 100%;
}
```
**Performance**: Zero JavaScript, fully compositor-driven. Best performance possible.

### Performance Notes
- Use `will-change: transform` on animated elements
- Use `gsap.set()` for initial states (avoids FOUC)
- Prefer transform/opacity only (compositor-friendly)
- Lazy-init ScrollTriggers below fold
- Kill ScrollTriggers on route change (SPA memory leaks)

---

## 2. 3D / WebGL EFFECTS

### Particle Systems / Star Fields (Three.js)
- `BufferGeometry` with thousands of points
- Custom shaders for glow/twinkle effects
- Mouse-reactive (particles follow/avoid cursor)
- **Performance**: Use `InstancedMesh` for >10K particles

### Animated Mesh Gradients (Shader-based) — Used by Stripe, Linear, Vercel
- Custom fragment shaders with Simplex/Perlin noise functions
- Time-uniform drives animation
- Looks like: liquid aurora, flowing colors
- **Libraries**: meshgradient.js, granim.js, or custom canvas

### 3D Card Tilt (Vanilla JS)
```js
card.addEventListener('mousemove', (e) => {
  const rect = card.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width - 0.5;
  const y = (e.clientY - rect.top) / rect.height - 0.5;
  card.style.transform = `perspective(1000px) rotateX(${y * -10}deg) rotateY(${x * 10}deg)`;
});
card.addEventListener('mouseleave', () => {
  card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0)';
});
```
- Add glare overlay that follows mouse angle
- CSS: `transform-style: preserve-3d` for depth layers

### Morphing Blob/Sphere — Used by Stripe Docs hero
- `IcosahedronGeometry` with vertex displacement
- Noise-based vertex shader animation
- Responds to audio or scroll position
- `MeshPhysicalMaterial` with iridescence

### Floating 3D Objects
- GLB/GLTF model loading
- Gentle rotation + bobbing animation
- Environment map reflections
- Post-processing: bloom, chromatic aberration
- Used by: Apple, Nothing, teenage engineering

### Grid/Matrix Effect (Perfect for LCARS)
- Instanced planes or lines
- Wave propagation from cursor position
- Fade by distance from camera
- Wireframe aesthetic matches sci-fi

### WebGL Performance Rules
- Use `OffscreenCanvas` + Web Worker when possible
- Reduce draw calls: merge geometries, use instancing
- LOD (Level of Detail) for complex scenes
- Pause rendering when not in viewport (`IntersectionObserver`)
- Mobile: reduce particle count by 75%, lower resolution
- Always `dispose()` geometries/materials/textures on unmount
- Target 60fps, degrade gracefully to 30fps
- `pixelRatio: Math.min(window.devicePixelRatio, 2)`

### Alternatives to Three.js
| Library | Size | Best For |
|---------|------|----------|
| **OGL** | 15KB | Lightweight WebGL (vs 150KB Three.js) |
| **Curtains.js** | - | WebGL for DOM elements (image distortion) |
| **PixiJS** | - | 2D WebGL renderer (particles, filters) |
| **Spline** | Tool | No-code 3D (spline.design), exports to web |
| **React Three Fiber** | - | React wrapper for Three.js |

---

## 3. HERO SECTION WOW EFFECTS

### Animated Gradient Background (CSS-only)
```css
@keyframes gradient-shift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.hero {
  background: linear-gradient(-45deg, #0a0a2e, #1a0a3e, #0a2a4e, #0a0a2e);
  background-size: 400% 400%;
  animation: gradient-shift 8s ease infinite;
}
```

### Text Reveal — Clip-path Wipe
```css
.reveal { clip-path: inset(0 100% 0 0); }
.reveal.active {
  clip-path: inset(0 0 0 0);
  transition: clip-path 0.8s cubic-bezier(0.77, 0, 0.18, 1);
}
```

### Text Reveal — Character-by-Character (GSAP SplitText)
```js
const split = new SplitText(".hero-title", { type: "chars,words" });
gsap.from(split.chars, {
  opacity: 0, y: 80, rotateX: -90,
  stagger: 0.02, duration: 0.8,
  ease: "back.out(1.7)"
});
```
- **Free alternative**: splitting.js

### Typewriter with Cursor
- Typed.js or custom with CSS `border-right` blinking cursor
- Great for AI company: "Building the future of ^500 intelligence"

### Morphing SVG Shapes
- **flubber.js** — interpolates between SVG paths
- **GSAP MorphSVGPlugin** — smoother, more control
- Blob shapes: blobmaker.app for base shapes

### Video Backgrounds
- Required attrs: `autoplay muted loop playsinline`
- Overlay with gradient for text readability
- Lazy load: poster image first, video on interaction
- WebM for Chrome/Firefox, MP4 fallback
- Compress to 2-4MB, 720p max, 24fps
- Advanced: video as texture on Three.js plane for distortion effects

### Interactive Particle Text
- Canvas particles form text/logo shape
- Mouse proximity scatters particles
- Particles return with spring physics
- **Library**: tsParticles (successor to particles.js)

### Noise/Grain Overlay (Premium Feel)
```css
.noise-overlay {
  position: fixed;
  inset: 0;
  background-image: url('noise-200x200.png');
  opacity: 0.04;
  pointer-events: none;
  z-index: 9999;
}
```
- SVG filter `feTurbulence` for animated noise
- Static PNG is cheapest performance-wise

---

## 4. MICRO-INTERACTIONS

### Magnetic Buttons (Used by Apple, Awwwards Winners)
```js
const magneticButton = (el, strength = 0.3) => {
  el.addEventListener("mousemove", (e) => {
    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) * strength;
    const y = (e.clientY - rect.top - rect.height / 2) * strength;
    gsap.to(el, { x, y, duration: 0.3, ease: "power2.out" });
  });
  el.addEventListener("mouseleave", () => {
    gsap.to(el, { x: 0, y: 0, duration: 0.5, ease: "elastic.out(1, 0.3)" });
  });
};
```

### Custom Cursor / Cursor Follower
- Small dot (actual cursor hidden) + larger circle following with lerp
- Circle scales up on hoverable elements
- Changes color/shape based on context (link, image, CTA)
- `mix-blend-mode: difference` for contrast effect
- **Performance**: transform only, `pointer-events: none` on cursor element

### Button Hover Effects
| Effect | Technique |
|--------|-----------|
| Liquid fill | Pseudo-element scales from point of entry |
| Border draw | SVG `stroke-dashoffset` animation |
| Shine sweep | `linear-gradient` overlay translates across |
| Glow pulse | `box-shadow` animation on hover |
| Split text | Characters stagger up/down on hover |
| Underline grow | `scaleX(0)` to `scaleX(1)` from left |

### Card Hover Effects
- 3D tilt with perspective (see above)
- Spotlight/glow that follows mouse position on card
- Rotating border gradient (`conic-gradient` animation)
- Content shift: image scales, text slides up
- `backdrop-filter: blur()` increase on hover

### Link/Nav Hover Effects
- Underline slide from left with `scaleX` transform
- Background highlight slides behind text
- Text color wipe with `clip-path`
- Dot/marker slides to active item

### Scroll-Triggered Micro-Interactions
- Elements draw themselves (SVG stroke animation)
- Numbers count up when visible
- Progress rings fill on scroll
- Icons animate (Lottie on scroll)

### Loading/Transition Effects
- Skeleton screens with shimmer gradient
- Blur-up image loading (LQIP)
- Content placeholder pulse animation

---

## 5. BACKGROUND EFFECTS

### Aurora / Northern Lights (CSS-only) — Perfect for LCARS Palette
```css
.aurora {
  position: fixed;
  inset: 0;
  z-index: -1;
  overflow: hidden;
}
.aurora::before,
.aurora::after {
  content: "";
  position: absolute;
  width: 60vw;
  height: 60vw;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.3;
  animation: aurora-drift 15s ease-in-out infinite alternate;
}
.aurora::before {
  background: radial-gradient(circle, #00e5ff 0%, transparent 70%);
  top: -20%;
  left: -10%;
}
.aurora::after {
  background: radial-gradient(circle, #8b5cf6 0%, transparent 70%);
  bottom: -20%;
  right: -10%;
  animation-delay: -7s;
}
@keyframes aurora-drift {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(10vw, 5vh) scale(1.2); }
}
```

### Animated Star Field (CSS-only)
- Multiple `box-shadow` on tiny element
- Three layers at different animation speeds
- Depth illusion through size/opacity variation
- Single element with box-shadow is very cheap

### Dot Grid Pattern
```css
.dot-grid {
  background: radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px);
  background-size: 30px 30px;
}
```
- Optional: animate opacity wave from cursor position

### Glassmorphism Panels
```css
.glass-panel {
  backdrop-filter: blur(20px) saturate(180%);
  background: rgba(10, 10, 30, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
}
```
- GPU-accelerated. Fallback: solid dark background.

### Spotlight / Radial Glow Following Cursor
```js
document.addEventListener("mousemove", (e) => {
  spotlight.style.background =
    `radial-gradient(600px at ${e.clientX}px ${e.clientY}px, rgba(0,229,255,0.1), transparent 80%)`;
});
```

### Animated Grid Lines (Tech/LCARS aesthetic)
- SVG or canvas grid with pulse animation
- Lines brighten near cursor (proximity detection)
- Intersection points glow on hover

### Gradient Mesh (Stripe-style)
- Canvas with 4-6 animated color blobs
- Each blob: large circle with radial gradient
- Perlin noise drives position/size changes
- Gaussian blur pass for smooth blending
- **Libraries**: meshgradient.js, or custom canvas

---

## 6. TYPOGRAPHY EFFECTS

### Gradient Text
```css
.gradient-text {
  background: linear-gradient(135deg, #00e5ff, #8b5cf6, #f472b6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

### Text Splitting Animations (splitting.js or GSAP SplitText)
| Pattern | Effect |
|---------|--------|
| Fade up per word | Most common, clean |
| 3D rotate per character | Dramatic |
| Scale from 0 per character | Playful |
| Blur in per word | Elegant |
| Slide up with overflow hidden per line | Clean, professional |

### Scramble/Decode Effect (Perfect for Sci-Fi/LCARS)
```js
function scrambleText(el, finalText, duration = 1000) {
  const chars = "!@#$%^&*()_+{}|:<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  let step = 0;
  const interval = setInterval(() => {
    el.textContent = finalText.split("").map((char, i) => {
      if (i < step) return finalText[i];
      return chars[Math.floor(Math.random() * chars.length)];
    }).join("");
    step++;
    if (step > finalText.length) clearInterval(interval);
  }, duration / finalText.length);
}
```

### Text Stroke / Outline Effect
```css
.outline-text {
  -webkit-text-stroke: 2px #00e5ff;
  -webkit-text-fill-color: transparent;
}
.outline-text:hover {
  -webkit-text-fill-color: #00e5ff;
  transition: -webkit-text-fill-color 0.3s;
}
```

### Glitch Text Effect (Sci-Fi)
```css
.glitch { position: relative; }
.glitch::before, .glitch::after {
  content: attr(data-text);
  position: absolute;
  left: 0;
  top: 0;
}
.glitch::before {
  color: #00e5ff;
  clip-path: inset(0 0 65% 0);
  transform: translate(-2px, 2px);
}
.glitch::after {
  color: #f472b6;
  clip-path: inset(35% 0 0 0);
  transform: translate(2px, -2px);
}
```
- Animate `clip-path` for glitch movement

### Variable Font Animations
- Animate `font-weight`, `font-width`, `font-slant`
- Responsive to cursor position or scroll
- Requires variable font (Inter, Manrope, etc.)

### Kinetic Typography
- Text that moves, rotates, scales in response to scroll
- Pinned sections where text transforms as you scroll
- Words flying in from edges
- Used by: Apple product pages, Stripe

---

## 7. PAGE TRANSITIONS

### Barba.js (Most Popular)
- Intercepts link clicks, fetches new page via AJAX
- Runs leave/enter animations between pages
- Persistent elements (nav, footer) don't reload
- Integrates with GSAP for complex transitions
- Patterns: fade, slide, wipe, morph, scale
- Prefetch on hover for instant feel

### View Transitions API (Native, 2025+)
```js
document.startViewTransition(() => {
  // Update the DOM
  updateDOM();
});
```
```css
::view-transition-old(hero) {
  animation: fade-out 0.3s ease-out;
}
::view-transition-new(hero) {
  animation: fade-in 0.3s ease-in;
}
```
- Most performant option when browser supports it
- Chrome/Edge full support, Safari partial, Firefox in progress

### Swup.js
- Lighter alternative to Barba.js
- Plugin architecture (scroll, preload, progress)
- Simpler API for basic transitions

### GSAP FLIP Plugin
```js
const state = Flip.getState(".items");
container.classList.toggle("reorder");
Flip.from(state, { duration: 0.6, ease: "power2.inOut", stagger: 0.05 });
```

---

## 8. LIBRARY ECOSYSTEM (2025-2026)

### Animation Libraries
| Library | Size (gzip) | Use Case | License |
|---------|-------------|----------|---------|
| **GSAP 3.12+** | 28KB core | Everything (scroll, text, SVG, FLIP) | Free + Business |
| **Framer Motion** | 45KB | React-specific motion | MIT |
| **Motion One** | 3.8KB | Lightweight, Web Animations API | MIT |
| **anime.js** | 17KB | Timeline animations | MIT |
| **Lottie** | 65KB | After Effects JSON animations | MIT |
| **AutoAnimate** | 2KB | Automatic layout transitions | MIT |

### Scroll Libraries
| Library | Size | Use Case |
|---------|------|----------|
| **GSAP ScrollTrigger** | 12KB | Scroll-linked animations |
| **Lenis** | 5KB | Smooth scroll (successor to LocomotiveScroll) |
| ScrollMagic | 15KB | Legacy, being replaced by ScrollTrigger |

### 3D/WebGL
| Library | Size | Use Case |
|---------|------|----------|
| **Three.js** | 150KB | Full 3D scenes |
| **React Three Fiber** | - | React Three.js |
| **OGL** | 15KB | Lightweight WebGL |
| **Spline** | Tool | No-code 3D design |
| **Theatre.js** | 50KB | Visual animation editor |

### Particles
| Library | Use Case |
|---------|----------|
| **tsParticles** | Configurable particle systems (particles.js successor) |
| **Canvas-confetti** | Celebration effects |

### Utilities
| Library | Use Case |
|---------|----------|
| **splitting.js** | Text splitting (free SplitText alternative) |
| **Intersection Observer** | Native API, no library needed |
| **Web Animations API** | Native animation, no library needed |
| **CSS scroll-timeline** | Native scroll-linked animations |

### Performance Budget
- Total JS animation bundle: **< 100KB gzipped**
- First Contentful Paint: **< 1.5s**
- Largest Contentful Paint: **< 2.5s**
- Cumulative Layout Shift: **< 0.1**
- First Input Delay: **< 100ms**
- Lighthouse Performance: **90+ target**
- **Always respect** `prefers-reduced-motion`
- Mobile: disable heavy effects via `IntersectionObserver` + `matchMedia`

---

## 9. AWARD-WINNING SITE ANALYSIS

### What Awwwards Winners Share
1. **Branded preloader** with progress (not a spinner)
2. **Custom cursor** — dot + circle, context-aware
3. **Smooth scroll** — Lenis (never native jerky)
4. **Hero impact** — full viewport, bold typography, motion within 1 second
5. **Scroll storytelling** — content reveals tied to scroll position
6. **Performance** — fast despite effects (lazy loading, code splitting)
7. **Sound design** — subtle audio on interactions (emerging trend, toggle on/off)
8. **Dark mode default** — dark backgrounds with accent glows

### Standout Agencies
| Agency | What Makes Them Stand Out |
|--------|--------------------------|
| **Locomotive** (locomotive.ca) | Custom smooth scroll, horizontal scroll case studies, magnetic nav, WebGL image distortion on hover |
| **Resn** (resn.co.nz) | Full Three.js experiences, audio-reactive visuals, custom physics |
| **Active Theory** (activetheory.net) | WebGL backgrounds, particle system transitions, custom shaders |
| **Aristide Benoist** | Minimal but flawless, image distortion shaders, perfect typography |

### Top Tech Companies
| Company | Key Effects |
|---------|-------------|
| **Stripe** | Animated gradient mesh hero, code syntax animations, globe (Three.js), progressive disclosure |
| **Linear** | Dark theme, precise accents, scroll-triggered screenshots, CSS-driven where possible |
| **Vercel** | Triangulated gradients, code deployment animations, terminal aesthetic |
| **Apple** | Pinned scroll sections, video storytelling, scroll-linked 360 rotation |
| **Nothing** | Dot-matrix aesthetic, glyph animations, monospace typography as design |

### The "OH MY GOD" Factor — 10 Requirements
1. **First 3 seconds** — hero must move/change/react immediately
2. **Cohesive motion language** — all animations feel related
3. **Purposeful, not gratuitous** — every effect serves the message
4. **Performance** — smooth 60fps or it kills the impression
5. **Details** — cursor effects, hover states, loading states, transitions
6. **Sound** — optional but differentiating (toggle on/off)
7. **Dark + glow** — dark backgrounds with strategic luminance
8. **Custom everything** — no stock templates, no generic layouts
9. **Scroll rewards** — each scroll reveals something delightful
10. **Speed** — paradoxically, the most animated sites feel FAST

---

## 10. LCARS + AI COMPANY FUSION CONCEPT

### Recommended Stack
- **GSAP + ScrollTrigger + SplitText** — core animation engine
- **Lenis** — smooth scroll
- **Three.js or OGL** — hero 3D background (particles/mesh)
- **splitting.js** — free text splitting
- **Barba.js** — page transitions (or View Transitions API with fallback)
- **tsParticles** — configurable particle effects

### Color Palette
- Base: `#0a0a1a` (near-black)
- Primary: `#00e5ff` (teal/cyan — LCARS)
- Secondary: `#8b5cf6` (purple)
- Accent: `#f472b6` (pink)
- Text: `#e0e0e0` (light gray)
- Subtle: `rgba(255,255,255,0.1)` (borders, grids)

### Feature Priorities
1. Aurora/gradient background with cursor-following spotlight
2. Scramble/decode text effect for hero headlines
3. Magnetic navigation with custom cursor
4. Scroll-triggered section reveals (batch stagger)
5. Dot grid pattern with proximity glow
6. 3D card tilt for service/feature cards
7. Glassmorphism panels for content sections
8. LCARS sweep page transitions
9. Noise texture overlay for premium feel
10. AI agent roster with personality-driven micro-interactions
11. Globe/network Three.js visualization for distributed AI
12. Animated compliance badges (SVG)
13. Terminal-like code sections with live-typing effects

### Implementation Order
1. **Foundation**: Dark theme, fonts, dot grid, noise overlay, aurora background
2. **Hero**: Gradient text, scramble effect, particle system or morphing blob
3. **Navigation**: Magnetic buttons, custom cursor, LCARS-style nav
4. **Scroll**: Lenis smooth scroll, ScrollTrigger reveals, parallax layers
5. **Content**: Glassmorphism panels, 3D card tilt, text splitting animations
6. **Polish**: Page transitions, sound design, preloader, reduced-motion fallbacks
7. **3D**: Three.js hero scene (particles or network visualization)
