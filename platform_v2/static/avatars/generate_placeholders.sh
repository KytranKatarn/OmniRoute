#!/bin/bash
# Generate placeholder SVG avatars with initials + station colors
DIR="/mnt/archie_brain/platform_v2/static/avatars"

gen() {
  local name="$1" initials="$2" color="$3" bg="$4"
  cat > "$DIR/$name.svg" << EOF
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
  <defs>
    <radialGradient id="bg" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="$bg"/>
      <stop offset="100%" stop-color="#0a0e14"/>
    </radialGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <circle cx="100" cy="100" r="98" fill="url(#bg)" stroke="$color" stroke-width="2" opacity="0.9"/>
  <circle cx="100" cy="100" r="88" fill="none" stroke="$color" stroke-width="1" opacity="0.15" stroke-dasharray="4,4"/>
  <text x="100" y="108" text-anchor="middle" font-family="'Courier New',monospace" font-size="56" font-weight="bold" fill="$color" filter="url(#glow)" letter-spacing="2">$initials</text>
  <text x="100" y="170" text-anchor="middle" font-family="'Courier New',monospace" font-size="14" fill="$color" opacity="0.4" letter-spacing="3" text-transform="uppercase">PLACEHOLDER</text>
</svg>
EOF
}

# Agent: name, initials, station color, dark bg tint
gen "archie"  "AR" "#FFD700" "#2a2200"
gen "vigil"   "VI" "#FFD700" "#2a2200"
gen "dante"   "DA" "#FF69B4" "#2a0020"
gen "marcus"  "MA" "#32CD32" "#002a00"
gen "aria"    "AI" "#32CD32" "#002a00"
gen "nia"     "NI" "#FF8C00" "#2a1500"
gen "liam"    "LI" "#FF8C00" "#2a1500"
gen "amara"   "AM" "#00CED1" "#001a2a"
gen "jin"     "JI" "#00CED1" "#001a2a"
gen "sofia"   "SO" "#6495ED" "#000a2a"

echo "Generated $(ls $DIR/*.svg | wc -l) placeholder SVGs"
ls -la $DIR/*.svg
