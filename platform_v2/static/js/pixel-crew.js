/* ═══════════════════════════════════════════════════════
   PixelCrew — 32x32 Pixel Art Crew Sprite System
   Generates sprite sheets for LCARS station agents
   using Canvas 2D at native pixel resolution.

   Usage:
     var sprite = PixelSpriteFactory.generate({
       name: "Nexus",
       station: "COMMAND",
       skinTone: "#f5d0a9",   // optional
       hairStyle: 2,          // optional (0-7)
       hairColor: "#2c1810"   // optional
     });
     // sprite.canvas  — 800x32 offscreen canvas (25 frames)
     // sprite.frames  — { idle: [0..3], walk: [4..9], ... }
   ═══════════════════════════════════════════════════════ */

(function() {
"use strict";

/* ── Constants ──────────────────────────────────────── */

var STATION_COLORS = {
  COMMAND:        "#8b5cf6",
  ANALYTICS:      "#06b6d4",
  CREATIVE:       "#ec4899",
  ENGINEERING:    "#f59e0b",
  COMMUNICATIONS: "#3b82f6",
  RESEARCH:       "#22c55e",
  SECURITY:       "#ef4444",
  LOGISTICS:      "#f97316",
  DIPLOMATIC:     "#a78bfa",
  OPERATIONS:     "#14b8a6"
};

var SKIN_TONES = [
  "#f5d0a9", "#e8b88a", "#d4956b", "#b8764e", "#8d5c3a", "#5c3a21"
];

var HAIR_COLORS = [
  "#2c1810", "#5c3317", "#8b6914", "#c4a35a", "#d4d4d4", "#4a90d9"
];

/* Hair style definitions — each is an array of [dx, dy] offsets
   relative to head top-left (col 12, row 4). These pixels get
   drawn ON TOP of the head shape. */
var HAIR_STYLES = [
  // 0: Flat top
  [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],
   [0,1],[1,1],[2,1],[3,1],[4,1],[5,1],[6,1],[7,1]],
  // 1: Parted left — swept right
  [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],
   [0,1],[1,1],[2,1],[5,1],[6,1],[7,1],[8,1]],
  // 2: Spiky
  [[1,0],[3,0],[5,0],[7,0],
   [0,1],[1,1],[2,1],[3,1],[4,1],[5,1],[6,1],[7,1]],
  // 3: Buzz cut (minimal)
  [[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],
   [0,1],[7,1]],
  // 4: Long — extends down sides
  [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],
   [0,1],[1,1],[2,1],[3,1],[4,1],[5,1],[6,1],[7,1],
   [-1,2],[-1,3],[-1,4],[8,2],[8,3],[8,4]],
  // 5: Mohawk center ridge
  [[3,0],[4,0],
   [2,-1],[3,-1],[4,-1],[5,-1],
   [3,1],[4,1]],
  // 6: Side-swept fringe
  [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],
   [0,1],[1,1],[2,1],[3,1]],
  // 7: Curly / puffy
  [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],
   [-1,0],[8,0],
   [-1,1],[0,1],[1,1],[2,1],[3,1],[4,1],[5,1],[6,1],[7,1],[8,1],
   [-1,2],[8,2]]
];

var JUMPSUIT_COLOR = "#1a1a2e";
var BOOT_COLOR     = "#111122";
var BADGE_COLOR    = "#e0e0ff";
var EYE_WHITE      = "#ffffff";
var EYE_PUPIL      = "#1a1a2e";

var FRAME_W = 32;
var FRAME_H = 32;
var TOTAL_FRAMES = 25;

/* ── Helpers ────────────────────────────────────────── */

function _hashName(name) {
  var hash = 0;
  var i;
  for (i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i);
    hash = hash & hash; // Convert to 32-bit int
  }
  return Math.abs(hash);
}

function _hexToRgb(hex) {
  var result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return { r: 0, g: 0, b: 0 };
  return {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16)
  };
}

function _rgbToHex(r, g, b) {
  function _c(v) {
    var h = Math.max(0, Math.min(255, Math.round(v))).toString(16);
    return h.length === 1 ? "0" + h : h;
  }
  return "#" + _c(r) + _c(g) + _c(b);
}

function _darken(hex, amount) {
  var c = _hexToRgb(hex);
  var factor = 1 - amount;
  return _rgbToHex(c.r * factor, c.g * factor, c.b * factor);
}

function _lighten(hex, amount) {
  var c = _hexToRgb(hex);
  return _rgbToHex(
    c.r + (255 - c.r) * amount,
    c.g + (255 - c.g) * amount,
    c.b + (255 - c.b) * amount
  );
}

/* ── Character Drawing Primitives ───────────────────── */

/**
 * Draw the base character in a given frame slot.
 * ox = x offset (frame index * 32), oy = y offset within frame.
 * pose controls limb positions.
 *
 * pose: {
 *   armL: number (-2 to 2, vertical offset of left hand),
 *   armR: number (-2 to 2, vertical offset of right hand),
 *   legSpread: number (0 = together, 1 = apart left, -1 = apart right),
 *   bodyDy: number (vertical shift of whole body),
 *   eyesClosed: boolean,
 *   armsUp: boolean
 * }
 */
function _drawCharacter(ctx, ox, oy, config, pose) {
  var skin      = config.skinTone;
  var skinDark  = _darken(skin, 0.15);
  var station   = config.stationColor;
  var stationDk = _darken(station, 0.25);
  var hair      = config.hairColor;
  var hairDk    = _darken(hair, 0.2);
  var style     = HAIR_STYLES[config.hairStyle] || HAIR_STYLES[0];

  var dy = pose.bodyDy || 0;

  /* shorthand for fillRect */
  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(ox + x, oy + y + dy, w || 1, h || 1);
  }

  /* ── Head (rows 4-10) ── */
  // Head oval — 8px wide centered at x=12..19
  // Row 4-5: top of head (6px wide, x=13..18)
  px(13, 4, 6, 1, skin);
  px(12, 5, 8, 1, skin);
  // Row 6-9: full width head (8px, x=12..19)
  px(12, 6, 8, 1, skin);
  px(12, 7, 8, 1, skin);
  px(12, 8, 8, 1, skin);
  px(12, 9, 8, 1, skin);
  // Row 10: chin (6px, x=13..18)
  px(13, 10, 6, 1, skin);

  // Ear shadow pixels
  px(11, 7, 1, 2, skinDark);
  px(20, 7, 1, 2, skinDark);

  /* ── Eyes (row 7-8) ── */
  if (!pose.eyesClosed) {
    // Left eye
    px(14, 7, 2, 1, EYE_WHITE);
    px(15, 7, 1, 1, EYE_PUPIL);
    px(14, 8, 2, 1, EYE_WHITE);
    px(15, 8, 1, 1, EYE_PUPIL);
    // Right eye
    px(17, 7, 2, 1, EYE_WHITE);
    px(18, 7, 1, 1, EYE_PUPIL);
    px(17, 8, 2, 1, EYE_WHITE);
    px(18, 8, 1, 1, EYE_PUPIL);
  } else {
    // Closed eyes — horizontal lines
    px(14, 8, 2, 1, EYE_PUPIL);
    px(17, 8, 2, 1, EYE_PUPIL);
  }

  /* ── Hair ── */
  var hi;
  for (hi = 0; hi < style.length; hi++) {
    var hx = 12 + style[hi][0];
    var hy = 4 + style[hi][1];
    if (hx >= 0 && hx < 32 && (hy + dy) >= 0 && (hy + dy) < 32) {
      px(hx, hy, 1, 1, (style[hi][1] <= 0) ? hair : hairDk);
    }
  }

  /* ── Neck (row 11) ── */
  px(14, 11, 4, 1, skin);

  /* ── Torso (rows 12-20) ── */
  // Shoulder panels — station color (rows 12-14)
  px(10, 12, 12, 1, station);    // wide shoulders
  px(10, 13, 12, 1, station);
  px(11, 14, 10, 1, stationDk);  // slightly narrower

  // Comm badge at row 13
  px(14, 13, 1, 1, BADGE_COLOR);

  // Lower torso — jumpsuit (rows 15-20)
  px(12, 15, 8, 1, JUMPSUIT_COLOR);
  px(12, 16, 8, 1, JUMPSUIT_COLOR);
  px(12, 17, 8, 1, JUMPSUIT_COLOR);
  px(12, 18, 8, 1, JUMPSUIT_COLOR);
  px(13, 19, 6, 1, JUMPSUIT_COLOR);
  px(13, 20, 6, 1, JUMPSUIT_COLOR);

  /* ── Arms ── */
  if (pose.armsUp) {
    // Arms raised up (celebration)
    // Left arm going up
    px(10, 12, 2, 1, station);
    px(9, 11, 2, 1, JUMPSUIT_COLOR);
    px(8, 10, 2, 1, JUMPSUIT_COLOR);
    px(8, 9, 2, 1, skin);  // hand
    // Right arm going up
    px(20, 12, 2, 1, station);
    px(21, 11, 2, 1, JUMPSUIT_COLOR);
    px(22, 10, 2, 1, JUMPSUIT_COLOR);
    px(22, 9, 2, 1, skin);  // hand
  } else {
    // Normal arm positions
    var armLy = 15 + (pose.armL || 0);
    var armRy = 15 + (pose.armR || 0);

    // Left arm
    px(10, 13, 2, 1, JUMPSUIT_COLOR);
    px(9, 14, 2, 1, JUMPSUIT_COLOR);
    px(9, armLy, 2, 1, JUMPSUIT_COLOR);
    px(9, armLy + 1, 2, 1, skin);  // left hand

    // Right arm
    px(20, 13, 2, 1, JUMPSUIT_COLOR);
    px(21, 14, 2, 1, JUMPSUIT_COLOR);
    px(21, armRy, 2, 1, JUMPSUIT_COLOR);
    px(21, armRy + 1, 2, 1, skin);  // right hand
  }

  /* ── Legs (rows 21-28) ── */
  var legOffset = pose.legSpread || 0;
  var leftLegX, rightLegX;

  if (legOffset > 0) {
    // Left leg forward, right leg back
    leftLegX = 12;
    rightLegX = 18;
  } else if (legOffset < 0) {
    // Right leg forward, left leg back
    leftLegX = 13;
    rightLegX = 17;
  } else {
    // Neutral standing
    leftLegX = 13;
    rightLegX = 17;
  }

  // Left leg
  px(leftLegX, 21, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 22, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 23, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 24, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 25, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 26, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 27, 3, 1, JUMPSUIT_COLOR);
  px(leftLegX, 28, 3, 1, JUMPSUIT_COLOR);

  // Right leg
  px(rightLegX, 21, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 22, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 23, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 24, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 25, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 26, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 27, 3, 1, JUMPSUIT_COLOR);
  px(rightLegX, 28, 3, 1, JUMPSUIT_COLOR);

  /* ── Boots (rows 29-31) ── */
  px(leftLegX, 29, 3, 1, BOOT_COLOR);
  px(leftLegX, 30, 3, 1, BOOT_COLOR);
  px(leftLegX - 1, 31, 4, 1, BOOT_COLOR); // slight overhang for boot shape

  px(rightLegX, 29, 3, 1, BOOT_COLOR);
  px(rightLegX, 30, 3, 1, BOOT_COLOR);
  px(rightLegX, 31, 4, 1, BOOT_COLOR);
}

/**
 * Draw working/seated variant — body shifted down 2px, legs bent.
 */
function _drawSeatedCharacter(ctx, ox, oy, config, pose) {
  var skin      = config.skinTone;
  var skinDark  = _darken(skin, 0.15);
  var station   = config.stationColor;
  var stationDk = _darken(station, 0.25);
  var hair      = config.hairColor;
  var hairDk    = _darken(hair, 0.2);
  var style     = HAIR_STYLES[config.hairStyle] || HAIR_STYLES[0];

  var dy = 2; // shifted down for seated

  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(ox + x, oy + y + dy, w || 1, h || 1);
  }

  /* ── Head (rows 4-10 + dy) ── */
  px(13, 4, 6, 1, skin);
  px(12, 5, 8, 1, skin);
  px(12, 6, 8, 1, skin);
  px(12, 7, 8, 1, skin);
  px(12, 8, 8, 1, skin);
  px(12, 9, 8, 1, skin);
  px(13, 10, 6, 1, skin);
  px(11, 7, 1, 2, skinDark);
  px(20, 7, 1, 2, skinDark);

  /* Eyes */
  px(14, 7, 2, 1, EYE_WHITE);
  px(15, 7, 1, 1, EYE_PUPIL);
  px(14, 8, 2, 1, EYE_WHITE);
  px(15, 8, 1, 1, EYE_PUPIL);
  px(17, 7, 2, 1, EYE_WHITE);
  px(18, 7, 1, 1, EYE_PUPIL);
  px(17, 8, 2, 1, EYE_WHITE);
  px(18, 8, 1, 1, EYE_PUPIL);

  /* Hair */
  var hi;
  for (hi = 0; hi < style.length; hi++) {
    var hx = 12 + style[hi][0];
    var hy = 4 + style[hi][1];
    if (hx >= 0 && hx < 32 && (hy + dy) >= 0 && (hy + dy) < 32) {
      px(hx, hy, 1, 1, (style[hi][1] <= 0) ? hair : hairDk);
    }
  }

  /* Neck */
  px(14, 11, 4, 1, skin);

  /* Torso */
  px(10, 12, 12, 1, station);
  px(10, 13, 12, 1, station);
  px(11, 14, 10, 1, stationDk);
  px(14, 13, 1, 1, BADGE_COLOR);
  px(12, 15, 8, 1, JUMPSUIT_COLOR);
  px(12, 16, 8, 1, JUMPSUIT_COLOR);
  px(12, 17, 8, 1, JUMPSUIT_COLOR);
  px(12, 18, 8, 1, JUMPSUIT_COLOR);

  /* Arms forward — reaching toward console */
  var handY = 14 + (pose.armL || 0);
  // Left arm reaching forward
  px(9, 13, 2, 1, JUMPSUIT_COLOR);
  px(8, 14, 2, 1, JUMPSUIT_COLOR);
  px(7, handY, 2, 1, JUMPSUIT_COLOR);
  px(6, handY, 2, 1, skin);
  // Right arm reaching forward
  px(21, 13, 2, 1, JUMPSUIT_COLOR);
  px(22, 14, 2, 1, JUMPSUIT_COLOR);
  px(23, handY, 2, 1, JUMPSUIT_COLOR);
  px(24, handY, 2, 1, skin);

  /* Legs — bent (seated on chair) */
  // Upper legs go forward horizontally
  px(12, 19, 3, 1, JUMPSUIT_COLOR);
  px(17, 19, 3, 1, JUMPSUIT_COLOR);
  px(11, 20, 3, 1, JUMPSUIT_COLOR);
  px(18, 20, 3, 1, JUMPSUIT_COLOR);
  // Lower legs go down
  px(10, 21, 3, 1, JUMPSUIT_COLOR);
  px(18, 21, 3, 1, JUMPSUIT_COLOR);
  px(10, 22, 3, 1, JUMPSUIT_COLOR);
  px(18, 22, 3, 1, JUMPSUIT_COLOR);
  px(10, 23, 3, 1, JUMPSUIT_COLOR);
  px(18, 23, 3, 1, JUMPSUIT_COLOR);

  /* Boots */
  px(10, 24, 3, 1, BOOT_COLOR);
  px(18, 24, 3, 1, BOOT_COLOR);
  px(9, 25, 4, 1, BOOT_COLOR);
  px(18, 25, 4, 1, BOOT_COLOR);
}

/**
 * Draw beam sparkle effect at a frame position.
 * intensity: 0 (few sparkles) to 1 (many sparkles).
 */
function _drawSparkles(ctx, ox, oy, stationColor, intensity) {
  var sparkleColor = _lighten(stationColor, 0.5);
  var sparkleCount = Math.floor(4 + intensity * 12);
  var hash = ox * 7 + Math.floor(intensity * 100);
  var i, sx, sy;

  ctx.fillStyle = sparkleColor;
  for (i = 0; i < sparkleCount; i++) {
    // Deterministic pseudo-random positions using hash
    hash = ((hash * 1103515245 + 12345) & 0x7fffffff);
    sx = ox + 8 + (hash % 16);
    hash = ((hash * 1103515245 + 12345) & 0x7fffffff);
    sy = oy + 2 + (hash % 28);
    ctx.fillRect(sx, sy, 1, 1);
  }

  // Vertical beam lines
  ctx.fillStyle = _lighten(stationColor, 0.3);
  var lineCount = Math.floor(2 + intensity * 4);
  hash = ox * 13 + 42;
  for (i = 0; i < lineCount; i++) {
    hash = ((hash * 1103515245 + 12345) & 0x7fffffff);
    sx = ox + 10 + (hash % 12);
    var lineH = 8 + (hash % 16);
    sy = oy + 4 + (hash % 8);
    ctx.globalAlpha = 0.3 + intensity * 0.5;
    ctx.fillRect(sx, sy, 1, lineH);
  }
  ctx.globalAlpha = 1.0;
}

/**
 * Draw a ghost/faded version of the character for beam transitions.
 */
function _drawGhostCharacter(ctx, ox, oy, config, alpha) {
  ctx.globalAlpha = alpha;
  _drawCharacter(ctx, ox, oy, config, { armL: 0, armR: 0, legSpread: 0 });
  ctx.globalAlpha = 1.0;
}

/* ── PixelSpriteFactory ─────────────────────────────── */

var PixelSpriteFactory = {};

/**
 * Generate a full sprite sheet for an agent.
 * @param {Object} agentConfig - { name, station, skinTone?, hairStyle?, hairColor? }
 * @returns {Object} { canvas, frameWidth, frameHeight, frames }
 */
PixelSpriteFactory.generate = function(agentConfig) {
  var name    = agentConfig.name || "Unknown";
  var station = (agentConfig.station || "COMMAND").toUpperCase();
  var hash    = _hashName(name);

  var skinTone  = agentConfig.skinTone  || SKIN_TONES[hash % SKIN_TONES.length];
  var hairStyle = (agentConfig.hairStyle != null) ? agentConfig.hairStyle : (hash >> 4) % HAIR_STYLES.length;
  var hairColor = agentConfig.hairColor || HAIR_COLORS[(hash >> 8) % HAIR_COLORS.length];
  var stationColor = STATION_COLORS[station] || STATION_COLORS.COMMAND;

  var config = {
    skinTone: skinTone,
    hairStyle: hairStyle,
    hairColor: hairColor,
    stationColor: stationColor
  };

  var canvas = document.createElement("canvas");
  canvas.width  = FRAME_W * TOTAL_FRAMES; // 800
  canvas.height = FRAME_H;                // 32
  var ctx = canvas.getContext("2d");

  // Disable image smoothing for crisp pixels
  ctx.imageSmoothingEnabled = false;

  /* ── Idle: frames 0-3 ── */
  // Frame 0: Standing neutral
  _drawCharacter(ctx, 0 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  // Frame 1: Slight arm shift (breathing)
  _drawCharacter(ctx, 1 * FRAME_W, 0, config,
    { armL: 1, armR: 1, legSpread: 0 });

  // Frame 2: Standing neutral (same as 0)
  _drawCharacter(ctx, 2 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  // Frame 3: Blink
  _drawCharacter(ctx, 3 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0, eyesClosed: true });

  /* ── Walk: frames 4-9 ── */
  // Left step cycle (frames 4-6)
  _drawCharacter(ctx, 4 * FRAME_W, 0, config,
    { armL: -1, armR: 1, legSpread: 1 });

  _drawCharacter(ctx, 5 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  _drawCharacter(ctx, 6 * FRAME_W, 0, config,
    { armL: 1, armR: -1, legSpread: -1 });

  // Right step cycle (frames 7-9)
  _drawCharacter(ctx, 7 * FRAME_W, 0, config,
    { armL: 1, armR: -1, legSpread: -1 });

  _drawCharacter(ctx, 8 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  _drawCharacter(ctx, 9 * FRAME_W, 0, config,
    { armL: -1, armR: 1, legSpread: 1 });

  /* ── Working: frames 10-13 ── */
  _drawSeatedCharacter(ctx, 10 * FRAME_W, 0, config,
    { armL: 0 });

  _drawSeatedCharacter(ctx, 11 * FRAME_W, 0, config,
    { armL: 1 });

  _drawSeatedCharacter(ctx, 12 * FRAME_W, 0, config,
    { armL: -1 });

  _drawSeatedCharacter(ctx, 13 * FRAME_W, 0, config,
    { armL: 0 });

  /* ── Beam-in: frames 14-17 ── */
  // Frame 14: Just sparkles, no body
  _drawSparkles(ctx, 14 * FRAME_W, 0, stationColor, 1.0);

  // Frame 15: Faint body + sparkles
  _drawGhostCharacter(ctx, 15 * FRAME_W, 0, config, 0.3);
  _drawSparkles(ctx, 15 * FRAME_W, 0, stationColor, 0.7);

  // Frame 16: Mostly solid + few sparkles
  _drawGhostCharacter(ctx, 16 * FRAME_W, 0, config, 0.7);
  _drawSparkles(ctx, 16 * FRAME_W, 0, stationColor, 0.3);

  // Frame 17: Fully solid (same as idle 0)
  _drawCharacter(ctx, 17 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  /* ── Beam-out: frames 18-21 ── */
  // Frame 18: Fully solid
  _drawCharacter(ctx, 18 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0 });

  // Frame 19: Fading + sparkles
  _drawGhostCharacter(ctx, 19 * FRAME_W, 0, config, 0.7);
  _drawSparkles(ctx, 19 * FRAME_W, 0, stationColor, 0.3);

  // Frame 20: Faint + more sparkles
  _drawGhostCharacter(ctx, 20 * FRAME_W, 0, config, 0.3);
  _drawSparkles(ctx, 20 * FRAME_W, 0, stationColor, 0.7);

  // Frame 21: Just sparkles
  _drawSparkles(ctx, 21 * FRAME_W, 0, stationColor, 1.0);

  /* ── Celebrate: frames 22-24 ── */
  // Frame 22: Arms starting to raise
  _drawCharacter(ctx, 22 * FRAME_W, 0, config,
    { armL: -2, armR: -2, legSpread: 0 });

  // Frame 23: Arms fully up
  _drawCharacter(ctx, 23 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0, armsUp: true });

  // Frame 24: Jump — body shifted up 2px, arms up
  _drawCharacter(ctx, 24 * FRAME_W, 0, config,
    { armL: 0, armR: 0, legSpread: 0, armsUp: true, bodyDy: -2 });

  return {
    canvas: canvas,
    frameWidth: FRAME_W,
    frameHeight: FRAME_H,
    frames: {
      idle:      [0, 1, 2, 3],
      walk:      [4, 5, 6, 7, 8, 9],
      working:   [10, 11, 12, 13],
      beamIn:    [14, 15, 16, 17],
      beamOut:   [18, 19, 20, 21],
      celebrate: [22, 23, 24]
    }
  };
};

/* ── Deck Renderer ─────────────────────────────────── */

var TILE_SIZE  = 32;
var GRID_COLS  = 20;
var GRID_ROWS  = 8;

var CONSOLE_LAYOUT = [
  { id: "conversations", label: "CONV",     col: 5,  row: 2, color: "#3b82f6" },
  { id: "code",          label: "CODE",     col: 14, row: 2, color: "#22c55e" },
  { id: "vault",         label: "VAULT",    col: 2,  row: 4, color: "#8b5cf6" },
  { id: "repos",         label: "REPOS",    col: 17, row: 4, color: "#f59e0b" },
  { id: "learned",       label: "LEARN",    col: 5,  row: 6, color: "#06b6d4" },
  { id: "sessions",      label: "SESSIONS", col: 14, row: 6, color: "#ec4899" }
];

var CORE_PAD = { col: 10, row: 1 };

var DeckRenderer = {
  canvas: null,
  ctx: null,
  scale: 1,
  animTime: 0,
  _container: null,
  _resizeHandler: null,
  _offsetX: 0,

  init: function(containerEl) {
    var self = this;
    this._container = containerEl;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "pc-deck";
    this.canvas.style.display = "block";
    containerEl.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.ctx.imageSmoothingEnabled = false;
    this.resize();
    this._resizeHandler = function() { self.resize(); };
    window.addEventListener("resize", this._resizeHandler);
    return this.canvas;
  },

  resize: function() {
    if (!this._container) return;
    var cw = this._container.clientWidth;
    var ch = this._container.clientHeight;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var gridW = GRID_COLS * TILE_SIZE;
    var gridH = GRID_ROWS * TILE_SIZE;
    this.scale = Math.min(cw / gridW, ch / gridH);
    var displayW = Math.floor(gridW * this.scale);
    var displayH = Math.floor(gridH * this.scale);
    this.canvas.width = displayW * dpr;
    this.canvas.height = displayH * dpr;
    this.canvas.style.width = displayW + "px";
    this.canvas.style.height = displayH + "px";
    this._offsetX = Math.floor((cw - displayW) / 2);
    this.canvas.style.marginLeft = this._offsetX + "px";
    this.ctx = this.canvas.getContext("2d");
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  },

  render: function(characters, dt) {
    this.animTime += dt;
    var w = this.canvas.width;
    var h = this.canvas.height;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.ctx.clearRect(0, 0, w / dpr, h / dpr);
    this.ctx.save();
    this.ctx.scale(this.scale, this.scale);
    this._drawFloor();
    this._drawCorePad();
    this._drawConsoles();
    // Characters drawn later by Task 4
    this.ctx.restore();
  },

  _drawFloor: function() {
    var ctx = this.ctx;
    var totalW = GRID_COLS * TILE_SIZE;
    var totalH = GRID_ROWS * TILE_SIZE;

    // Dark background
    ctx.fillStyle = "rgba(10, 10, 30, 0.7)";
    ctx.fillRect(0, 0, totalW, totalH);

    // Hex grid pattern — faint hexagonal outlines every 2 tiles
    var hexR = TILE_SIZE; // radius = 1 tile = 32px (hex spans ~2 tiles)
    var hexW = hexR * 2;
    var hexH = Math.floor(hexR * Math.sqrt(3));
    var row, col, cx, cy, a, angle;

    ctx.strokeStyle = "rgba(10, 42, 58, 0.4)";
    ctx.lineWidth = 1;

    for (row = -1; row < Math.ceil(totalH / hexH) + 1; row++) {
      for (col = -1; col < Math.ceil(totalW / (hexW * 0.75)) + 1; col++) {
        cx = col * hexW * 0.75;
        cy = row * hexH + ((col % 2) ? hexH * 0.5 : 0);
        ctx.beginPath();
        for (a = 0; a < 6; a++) {
          angle = (Math.PI / 3) * a - Math.PI / 6;
          var px = cx + hexR * Math.cos(angle);
          var py = cy + hexR * Math.sin(angle);
          if (a === 0) {
            ctx.moveTo(px, py);
          } else {
            ctx.lineTo(px, py);
          }
        }
        ctx.closePath();
        ctx.stroke();
      }
    }

    // Radial glow from top-center
    var gCx = (GRID_COLS / 2) * TILE_SIZE;
    var gRadius = GRID_COLS * TILE_SIZE * 0.6;
    var grad = ctx.createRadialGradient(gCx, 0, 0, gCx, 0, gRadius);
    grad.addColorStop(0, "rgba(139, 92, 246, 0.12)");
    grad.addColorStop(1, "rgba(139, 92, 246, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, totalW, totalH);
  },

  _drawCorePad: function() {
    var ctx = this.ctx;
    var cx = CORE_PAD.col * TILE_SIZE + TILE_SIZE / 2;
    var cy = CORE_PAD.row * TILE_SIZE + TILE_SIZE / 2;
    var pulse = 0.3 + 0.2 * Math.sin(this.animTime * 2);

    // Outer circle
    ctx.beginPath();
    ctx.arc(cx, cy, 14, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(139, 92, 246, " + pulse + ")";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Inner circle — brighter
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(139, 92, 246, " + (pulse + 0.2) + ")";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Small cross/plus pattern in center
    ctx.strokeStyle = "rgba(139, 92, 246, " + (pulse + 0.15) + ")";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx - 4, cy);
    ctx.lineTo(cx + 4, cy);
    ctx.moveTo(cx, cy - 4);
    ctx.lineTo(cx, cy + 4);
    ctx.stroke();
  },

  _drawConsoles: function() {
    var ctx = this.ctx;
    var i, c, x, y;

    for (i = 0; i < CONSOLE_LAYOUT.length; i++) {
      c = CONSOLE_LAYOUT[i];
      x = c.col * TILE_SIZE;
      y = c.row * TILE_SIZE;

      // Desk body — dark base (2x2 tiles = 64x64 area, desk is lower portion)
      ctx.fillStyle = "#0a0a1e";
      ctx.fillRect(x + 7, y + 20, 50, 24);

      // Screen panel — lighter, on top half of desk area
      ctx.fillStyle = "#1a1a3e";
      ctx.fillRect(x + 12, y + 4, 40, 16);

      // Station-colored glow border around screen
      ctx.strokeStyle = _hexToRgba(c.color, 0.6);
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x + 12, y + 4, 40, 16);

      // Small station-colored dots on screen (data readouts)
      ctx.fillStyle = c.color;
      ctx.fillRect(x + 16, y + 8, 2, 2);
      ctx.fillRect(x + 22, y + 10, 3, 2);
      ctx.fillRect(x + 30, y + 8, 2, 2);
      ctx.fillRect(x + 36, y + 11, 4, 2);
      ctx.fillRect(x + 28, y + 14, 3, 2);

      // Faint glow dot on desk surface
      ctx.fillStyle = _hexToRgba(c.color, 0.2);
      ctx.fillRect(x + 24, y + 28, 16, 2);

      // Label below console
      ctx.fillStyle = c.color;
      ctx.font = "9px Antonio, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(c.label, x + 32, y + 56);
    }
    ctx.textAlign = "start"; // reset
  },

  getConsolePosition: function(consoleId) {
    var i, c;
    for (i = 0; i < CONSOLE_LAYOUT.length; i++) {
      c = CONSOLE_LAYOUT[i];
      if (c.id === consoleId) {
        // Chair position is the tile directly below the console center
        return {
          x: c.col * TILE_SIZE + TILE_SIZE,
          y: (c.row + 2) * TILE_SIZE
        };
      }
    }
    return null;
  },

  getCorePadPosition: function() {
    return { col: CORE_PAD.col, row: CORE_PAD.row };
  },

  destroy: function() {
    if (this._resizeHandler) {
      window.removeEventListener("resize", this._resizeHandler);
      this._resizeHandler = null;
    }
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas);
    }
    this.canvas = null;
    this.ctx = null;
    this._container = null;
  }
};

/* Helper: hex color to rgba string */
function _hexToRgba(hex, alpha) {
  var c = _hexToRgb(hex);
  return "rgba(" + c.r + ", " + c.g + ", " + c.b + ", " + alpha + ")";
}

/* ── Placeholder for Tasks 4-5 ─────────────────────── */
/* PixelCrew class (animation loop, agent lifecycle)
   will be added here. */

/* ── Export ──────────────────────────────────────────── */

window.PixelSpriteFactory = PixelSpriteFactory;
window._DeckRenderer = DeckRenderer;

})();
