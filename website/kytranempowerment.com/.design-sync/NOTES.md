# design-sync notes — kytranempowerment.com

- Shape styles-only: static Hostinger site, no JS component build.
- Closure mirrors the HOMEPAGE head order (base, components, pages/home, pages/hero-animations, responsive, reduced-motion — reduced-motion LAST). Other css/pages/*.css staged un-imported (page-specific, possible selector overlap).
- Fonts: Antonio + Orbitron + IBM Plex Mono from Google Fonts (no local font files).
- This site dir lives INSIDE the archie-platform repo; config is per-site under this directory, not repo-root.
