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
    this._glowBridge = document.createElement("div");
    this._glowBridge.className = "pc-glow-bridge";
    containerEl.appendChild(this._glowBridge);
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
    CharacterManager.draw(this.ctx);
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
    if (this._glowBridge && this._glowBridge.parentNode) {
      this._glowBridge.parentNode.removeChild(this._glowBridge);
    }
    this._glowBridge = null;
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

/* ── Character State Machine & Pathfinding ────────── */

var ANIM_SPEEDS = {
  idle:      0.25,   // seconds per frame
  walk:      0.12,
  working:   0.30,
  beamIn:    0.15,
  beamOut:   0.15,
  celebrate: 0.20
};
var WALK_SPEED = 3; // tiles per second

/* Frame counts per animation (from sprite.frames) */
var ANIM_FRAME_COUNTS = {
  idle:      4,
  walk:      6,
  working:   4,
  beamIn:    4,
  beamOut:   4,
  celebrate: 3
};

/* One-shot animations that don't loop */
var ONE_SHOT_ANIMS = { beamIn: true, beamOut: true, celebrate: true };

/* Station-to-console mapping */
var STATION_CONSOLE_MAP = {
  COMMAND:        "vault",
  SECURITY:       "vault",
  ANALYTICS:      "conversations",
  OPERATIONS:     "conversations",
  CREATIVE:       "sessions",
  COMMUNICATIONS: "sessions",
  ENGINEERING:    "code",
  RESEARCH:       "learned",
  LOGISTICS:      "repos",
  DIPLOMATIC:     "conversations"
};

/**
 * Build a walkability grid. Returns a GRID_ROWS x GRID_COLS boolean array
 * where true = walkable.
 */
function _buildWalkGrid() {
  var grid = [];
  var r, c, i, con;
  for (r = 0; r < GRID_ROWS; r++) {
    grid[r] = [];
    for (c = 0; c < GRID_COLS; c++) {
      grid[r][c] = true;
    }
  }
  // Mark console tiles (2x2 each) as not walkable
  for (i = 0; i < CONSOLE_LAYOUT.length; i++) {
    con = CONSOLE_LAYOUT[i];
    // Each console occupies 2x2 tiles at (col, row)
    if (con.row < GRID_ROWS && con.col < GRID_COLS)
      grid[con.row][con.col] = false;
    if (con.row < GRID_ROWS && con.col + 1 < GRID_COLS)
      grid[con.row][con.col + 1] = false;
    if (con.row + 1 < GRID_ROWS && con.col < GRID_COLS)
      grid[con.row + 1][con.col] = false;
    if (con.row + 1 < GRID_ROWS && con.col + 1 < GRID_COLS)
      grid[con.row + 1][con.col + 1] = false;
  }
  return grid;
}

/**
 * BFS pathfinding on the tile grid.
 * Returns array of {col, row} from start to end (exclusive of start, inclusive of end).
 * occupiedTiles: Set of "col,row" strings to avoid (optional collision).
 */
function _bfs(startCol, startRow, endCol, endRow, occupiedTiles) {
  // Clamp to grid bounds
  startCol = Math.max(0, Math.min(GRID_COLS - 1, startCol));
  startRow = Math.max(0, Math.min(GRID_ROWS - 1, startRow));
  endCol   = Math.max(0, Math.min(GRID_COLS - 1, endCol));
  endRow   = Math.max(0, Math.min(GRID_ROWS - 1, endRow));

  if (startCol === endCol && startRow === endRow) return [];

  var grid = _buildWalkGrid();
  var dirs = [[0, -1], [0, 1], [-1, 0], [1, 0]]; // up, down, left, right
  var visited = {};
  var parent = {};
  var queue = [];
  var startKey = startCol + "," + startRow;
  var endKey = endCol + "," + endRow;

  visited[startKey] = true;
  queue.push({ col: startCol, row: startRow });

  var found = false;
  var useOccupied = occupiedTiles && occupiedTiles.size > 0;

  while (queue.length > 0) {
    var curr = queue.shift();
    var currKey = curr.col + "," + curr.row;

    if (currKey === endKey) {
      found = true;
      break;
    }

    for (var d = 0; d < dirs.length; d++) {
      var nc = curr.col + dirs[d][0];
      var nr = curr.row + dirs[d][1];
      if (nc < 0 || nc >= GRID_COLS || nr < 0 || nr >= GRID_ROWS) continue;
      var nk = nc + "," + nr;
      if (visited[nk]) continue;
      if (!grid[nr][nc]) continue;
      // Allow the destination tile even if occupied
      if (useOccupied && nk !== endKey && occupiedTiles.has(nk)) continue;

      visited[nk] = true;
      parent[nk] = currKey;
      queue.push({ col: nc, row: nr });
    }
  }

  if (!found) {
    // Retry without occupied tiles if collision avoidance blocked the path
    if (useOccupied) {
      return _bfs(startCol, startRow, endCol, endRow, null);
    }
    return [];
  }

  // Reconstruct path (end -> start), then reverse, excluding start
  var path = [];
  var traceKey = endKey;
  while (traceKey && traceKey !== startKey) {
    var parts = traceKey.split(",");
    path.push({ col: parseInt(parts[0], 10), row: parseInt(parts[1], 10) });
    traceKey = parent[traceKey];
  }
  path.reverse();
  return path;
}

/* ── CharacterManager ─────────────────────────────── */

var CharacterManager = {
  characters: [],

  /**
   * Create and add a character.
   * config: { name, displayName, station, status }
   */
  addCharacter: function(config) {
    var name = (config.name || "unknown").toLowerCase();
    var station = (config.station || "COMMAND").toUpperCase();

    // Generate sprite
    var sprite = PixelSpriteFactory.generate({
      name: config.name || name,
      station: station
    });

    var homeConsole = this._assignHomeConsole(station);

    var character = {
      name: name,
      displayName: config.displayName || config.name || name,
      station: station,
      sprite: sprite,
      state: "beamIn",
      tileCol: CORE_PAD.col,
      tileRow: CORE_PAD.row,
      targetCol: null,
      targetRow: null,
      path: [],
      pathIndex: 0,
      moveProgress: 0,
      frame: 0,
      frameTimer: 0,
      facing: 1,
      homeConsole: homeConsole,
      opacity: 1.0,
      _pendingState: "idle",   // state to transition to after beam_in
      _pendingRemove: false,
      _celebrateReturn: false
    };

    this.characters.push(character);
    return character;
  },

  /**
   * Start beam-out, then remove.
   */
  removeCharacter: function(name) {
    var ch = this.getCharacter(name);
    if (!ch) return;

    // If not at core pad, walk there first
    if (ch.tileCol !== CORE_PAD.col || ch.tileRow !== CORE_PAD.row) {
      ch.targetCol = CORE_PAD.col;
      ch.targetRow = CORE_PAD.row;
      ch.path = _bfs(ch.tileCol, ch.tileRow, CORE_PAD.col, CORE_PAD.row, this._getOccupiedTiles());
      ch.pathIndex = 0;
      ch.moveProgress = 0;
      ch.state = "walk";
      ch.frame = 0;
      ch.frameTimer = 0;
      ch._pendingState = "beamOut";
      ch._pendingRemove = true;
    } else {
      ch.state = "beamOut";
      ch.frame = 0;
      ch.frameTimer = 0;
      ch._pendingRemove = true;
    }
  },

  /**
   * Send character to work at a console.
   */
  setWorking: function(name, consoleId) {
    var ch = this.getCharacter(name);
    if (!ch) return;

    var targetConsole = consoleId || ch.homeConsole;
    if (!targetConsole) return;

    var seat = this._getConsoleSeat(targetConsole);
    if (!seat) return;

    // Already at the seat
    if (ch.tileCol === seat.col && ch.tileRow === seat.row) {
      ch.state = "working";
      ch.frame = 0;
      ch.frameTimer = 0;
      return;
    }

    // Pathfind to seat
    ch.targetCol = seat.col;
    ch.targetRow = seat.row;
    ch.path = _bfs(ch.tileCol, ch.tileRow, seat.col, seat.row, this._getOccupiedTiles());
    ch.pathIndex = 0;
    ch.moveProgress = 0;
    ch.state = "walk";
    ch.frame = 0;
    ch.frameTimer = 0;
    ch._pendingState = "working";
  },

  /**
   * Stop working, walk back to home console seat.
   */
  setIdle: function(name) {
    var ch = this.getCharacter(name);
    if (!ch) return;

    var seat = this._getConsoleSeat(ch.homeConsole);
    if (!seat) {
      ch.state = "idle";
      ch.frame = 0;
      ch.frameTimer = 0;
      return;
    }

    if (ch.tileCol === seat.col && ch.tileRow === seat.row) {
      ch.state = "idle";
      ch.frame = 0;
      ch.frameTimer = 0;
      return;
    }

    ch.targetCol = seat.col;
    ch.targetRow = seat.row;
    ch.path = _bfs(ch.tileCol, ch.tileRow, seat.col, seat.row, this._getOccupiedTiles());
    ch.pathIndex = 0;
    ch.moveProgress = 0;
    ch.state = "walk";
    ch.frame = 0;
    ch.frameTimer = 0;
    ch._pendingState = "idle";
  },

  /**
   * Play celebrate animation, then return to idle.
   */
  celebrate: function(name) {
    var ch = this.getCharacter(name);
    if (!ch) return;

    ch.state = "celebrate";
    ch.frame = 0;
    ch.frameTimer = 0;
    ch._celebrateReturn = true;
  },

  /**
   * Advance all character animations and movement.
   * dt: delta time in seconds.
   */
  update: function(dt) {
    var i, ch, speed, maxFrames;

    for (i = this.characters.length - 1; i >= 0; i--) {
      ch = this.characters[i];
      speed = ANIM_SPEEDS[ch.state] || 0.25;
      maxFrames = ANIM_FRAME_COUNTS[ch.state] || 4;

      // Advance frame timer
      ch.frameTimer += dt;
      if (ch.frameTimer >= speed) {
        ch.frameTimer -= speed;
        ch.frame++;

        if (ONE_SHOT_ANIMS[ch.state]) {
          // One-shot: stop at last frame
          if (ch.frame >= maxFrames) {
            ch.frame = maxFrames - 1;
            this._onAnimComplete(ch, i);
            continue;
          }
        } else {
          // Looping: wrap
          ch.frame = ch.frame % maxFrames;
        }
      }

      // Walking movement
      if (ch.state === "walk" && ch.path.length > 0) {
        ch.moveProgress += dt * WALK_SPEED;

        if (ch.moveProgress >= 1) {
          // Snap to next tile
          var nextTile = ch.path[ch.pathIndex];
          if (nextTile) {
            // Update facing
            if (nextTile.col > ch.tileCol) ch.facing = 1;
            else if (nextTile.col < ch.tileCol) ch.facing = -1;

            ch.tileCol = nextTile.col;
            ch.tileRow = nextTile.row;
          }
          ch.pathIndex++;
          ch.moveProgress = 0;

          // Path complete?
          if (ch.pathIndex >= ch.path.length) {
            ch.path = [];
            ch.pathIndex = 0;
            ch.moveProgress = 0;
            ch.targetCol = null;
            ch.targetRow = null;
            // Transition to pending state
            var next = ch._pendingState || "idle";
            ch._pendingState = null;
            ch.state = next;
            ch.frame = 0;
            ch.frameTimer = 0;

            // If beam_out after walking, mark pending remove
            if (next === "beamOut") {
              ch._pendingRemove = true;
            }
          }
        }
      }

      // Beam opacity effects
      if (ch.state === "beamIn") {
        ch.opacity = Math.min(1.0, (ch.frame + 1) / ANIM_FRAME_COUNTS.beamIn);
      } else if (ch.state === "beamOut") {
        ch.opacity = Math.max(0, 1.0 - (ch.frame + 1) / ANIM_FRAME_COUNTS.beamOut);
      } else {
        ch.opacity = 1.0;
      }
    }
  },

  /**
   * Handle end of one-shot animations.
   */
  _onAnimComplete: function(ch, index) {
    if (ch.state === "beamIn") {
      // Beam-in complete: walk to home console seat
      var seat = this._getConsoleSeat(ch.homeConsole);
      if (seat) {
        ch.targetCol = seat.col;
        ch.targetRow = seat.row;
        ch.path = _bfs(ch.tileCol, ch.tileRow, seat.col, seat.row, this._getOccupiedTiles());
        ch.pathIndex = 0;
        ch.moveProgress = 0;
        ch.state = "walk";
        ch.frame = 0;
        ch.frameTimer = 0;
        ch._pendingState = "idle";
      } else {
        ch.state = "idle";
        ch.frame = 0;
        ch.frameTimer = 0;
      }
      ch.opacity = 1.0;
    } else if (ch.state === "beamOut") {
      // Beam-out complete: remove
      if (ch._pendingRemove) {
        ch.sprite = null;
        this.characters.splice(index, 1);
      }
    } else if (ch.state === "celebrate") {
      // Celebrate complete: return to idle
      ch.state = "idle";
      ch.frame = 0;
      ch.frameTimer = 0;
      ch._celebrateReturn = false;
    }
  },

  /**
   * Draw all characters onto the given context.
   * Characters sorted by tileRow for proper overlap.
   */
  draw: function(ctx) {
    if (this.characters.length === 0) return;

    // Sort by row for painter's algorithm
    var sorted = this.characters.slice().sort(function(a, b) {
      return a.tileRow - b.tileRow;
    });

    var i, ch, sprite, frameIndices, frameIdx, srcX;
    var px, py, interpX, interpY;

    for (i = 0; i < sorted.length; i++) {
      ch = sorted[i];
      if (!ch.sprite) continue;

      sprite = ch.sprite;
      frameIndices = sprite.frames[ch.state];
      if (!frameIndices || frameIndices.length === 0) continue;

      var clampedFrame = Math.min(ch.frame, frameIndices.length - 1);
      frameIdx = frameIndices[clampedFrame];
      srcX = frameIdx * sprite.frameWidth;

      // Calculate pixel position with interpolation
      px = ch.tileCol * TILE_SIZE;
      py = ch.tileRow * TILE_SIZE;

      // Interpolate position during walking
      if (ch.state === "walk" && ch.path.length > 0 && ch.pathIndex < ch.path.length) {
        var nextTile = ch.path[ch.pathIndex];
        if (nextTile) {
          interpX = (nextTile.col * TILE_SIZE - px) * ch.moveProgress;
          interpY = (nextTile.row * TILE_SIZE - py) * ch.moveProgress;
          px += interpX;
          py += interpY;
        }
      }

      // Apply opacity
      ctx.globalAlpha = ch.opacity;

      // Draw sprite (handle facing)
      if (ch.facing === -1) {
        ctx.save();
        ctx.translate(px + TILE_SIZE, py);
        ctx.scale(-1, 1);
        ctx.drawImage(
          sprite.canvas,
          srcX, 0, sprite.frameWidth, sprite.frameHeight,
          0, 0, TILE_SIZE, TILE_SIZE
        );
        ctx.restore();
      } else {
        ctx.drawImage(
          sprite.canvas,
          srcX, 0, sprite.frameWidth, sprite.frameHeight,
          px, py, TILE_SIZE, TILE_SIZE
        );
      }

      ctx.globalAlpha = 1.0;

      // Draw name label above character
      var labelX = px + TILE_SIZE / 2;
      var labelY = py - 4;
      var stationColor = STATION_COLORS[ch.station] || "#ffffff";
      var labelText = ch.displayName;

      ctx.font = "8px Antonio, sans-serif";
      ctx.textAlign = "center";
      var textW = ctx.measureText(labelText).width;

      // Semi-transparent background pill
      ctx.fillStyle = "rgba(0, 0, 0, 0.5)";
      ctx.fillRect(labelX - textW / 2 - 2, labelY - 8, textW + 4, 10);

      // Name text in station color
      ctx.fillStyle = stationColor;
      ctx.fillText(labelText, labelX, labelY);
    }
    ctx.textAlign = "start"; // reset
  },

  /**
   * Find a character by name (case-insensitive).
   */
  getCharacter: function(name) {
    if (!name) return null;
    var lower = name.toLowerCase();
    for (var i = 0; i < this.characters.length; i++) {
      if (this.characters[i].name === lower) return this.characters[i];
    }
    return null;
  },

  /**
   * Assign a home console based on station.
   */
  _assignHomeConsole: function(station) {
    var preferred = STATION_CONSOLE_MAP[station] || "conversations";

    // Count how many characters already assigned to each console
    var counts = {};
    var i;
    for (i = 0; i < CONSOLE_LAYOUT.length; i++) {
      counts[CONSOLE_LAYOUT[i].id] = 0;
    }
    for (i = 0; i < this.characters.length; i++) {
      var hc = this.characters[i].homeConsole;
      if (hc && counts[hc] !== undefined) counts[hc]++;
    }

    // Use preferred if it has fewer than 2 characters
    if (counts[preferred] !== undefined && counts[preferred] < 2) {
      return preferred;
    }

    // Otherwise pick the console with fewest characters
    var best = null;
    var bestCount = Infinity;
    for (i = 0; i < CONSOLE_LAYOUT.length; i++) {
      var cid = CONSOLE_LAYOUT[i].id;
      if (counts[cid] < bestCount) {
        bestCount = counts[cid];
        best = cid;
      }
    }
    return best || preferred;
  },

  /**
   * Get the seat position for a console (tile below console center).
   */
  _getConsoleSeat: function(consoleId) {
    if (!consoleId) return null;
    for (var i = 0; i < CONSOLE_LAYOUT.length; i++) {
      var c = CONSOLE_LAYOUT[i];
      if (c.id === consoleId) {
        return { col: c.col, row: c.row + 2 };
      }
    }
    return null;
  },

  /**
   * Get occupied tile positions (non-walking characters).
   */
  _getOccupiedTiles: function() {
    var tiles = new Set();
    for (var i = 0; i < this.characters.length; i++) {
      var ch = this.characters[i];
      if (ch.state !== "walk") {
        tiles.add(ch.tileCol + "," + ch.tileRow);
      }
    }
    return tiles;
  },

  /**
   * Remove all characters and null sprite references.
   */
  clear: function() {
    for (var i = 0; i < this.characters.length; i++) {
      this.characters[i].sprite = null;
    }
    this.characters = [];
  }
};

/* ── Event Bus Helpers ────────────────────────────── */

function _subscribeEvents() {
  if (!window._neuralEvents) return;
  var bus = window._neuralEvents;

  var handlers = [
    { event: "job:started", fn: function(data) {
      if (data && data.agent) {
        PixelCrew.setAgentWorking(data.agent, data.nodeId || null);
      }
    }},
    { event: "job:completed", fn: function(data) {
      if (data && data.agent) {
        PixelCrew.celebrateAgent(data.agent);
      }
    }},
    { event: "job:failed", fn: function(data) {
      if (data && data.agent) {
        // Flash character at reduced opacity briefly
        var ch = CharacterManager.getCharacter(data.agent);
        if (ch) {
          var origOpacity = ch.opacity;
          ch.opacity = 0.4;
          setTimeout(function() { if (ch) ch.opacity = origOpacity; }, 300);
        }
        PixelCrew.setAgentIdle(data.agent);
      }
    }},
    { event: "knowledge:added", fn: function() {
      // Find nearest idle character, do a brief frame jump (head tilt effect)
      var idle = null;
      for (var i = 0; i < CharacterManager.characters.length; i++) {
        if (CharacterManager.characters[i].state === "idle") {
          idle = CharacterManager.characters[i];
          break;
        }
      }
      if (idle) {
        // Brief look-up effect: temporarily shift to frame 1 (breathing) for 0.5s
        var origFrame = idle.frame;
        idle.frame = 1;
        setTimeout(function() { if (idle.state === "idle") idle.frame = origFrame; }, 500);
      }
    }},
    { event: "agent:dispatched", fn: function(data) {
      if (data && data.agent) {
        PixelCrew.addAgent({
          name: data.agent.name || data.agent,
          display_name: data.agent.display_name || data.agent.name || data.agent,
          station: data.agent.station || "COMMAND",
          status: "active"
        });
      }
    }}
  ];

  handlers.forEach(function(h) {
    bus.on(h.event, h.fn);
  });

  PixelCrew._eventHandlers = handlers;
}

function _unsubscribeEvents() {
  if (!window._neuralEvents) return;
  var bus = window._neuralEvents;
  PixelCrew._eventHandlers.forEach(function(h) {
    bus.off(h.event, h.fn);
  });
  PixelCrew._eventHandlers = [];
}

/* ── PixelCrew — Public API ──────────────────────── */

var PixelCrew = {
  _instance: null,
  _raf: null,
  _lastTime: 0,
  _frameSkip: 0,
  _eventHandlers: [],
  _destroyed: false,
  _visibilityHandler: null,

  /**
   * Initialise the pixel crew scene.
   * container: the .nc-hero DOM element to render into.
   * opts: { consoles: [...] } (optional)
   * Returns PixelCrew on success, null if Canvas 2D unsupported.
   */
  create: function(container, opts) {
    // Canvas 2D support check
    var testCanvas = document.createElement("canvas");
    if (!testCanvas.getContext || !testCanvas.getContext("2d")) {
      return null;
    }
    testCanvas = null;

    // If already created, tear down first
    if (this._instance) {
      this.destroy();
    }

    this._destroyed = false;
    this._instance = this;

    // 1. Init DeckRenderer
    DeckRenderer.init(container, opts || {});

    // 2. Subscribe to event bus
    _subscribeEvents();

    // 3. Start animation loop (targeting 30fps)
    var self = this;

    function _loop(timestamp) {
      if (self._destroyed) return;
      self._raf = requestAnimationFrame(_loop);

      var dt = (timestamp - self._lastTime) / 1000;
      self._lastTime = timestamp;

      // Cap dt to avoid huge jumps (e.g. after tab switch)
      if (dt > 0.1) dt = 0.016;

      // 30fps frame skip
      self._frameSkip += dt;
      if (self._frameSkip < 0.033) return;
      self._frameSkip -= 0.033;

      // Update and render
      CharacterManager.update(dt);
      DeckRenderer.render(CharacterManager.characters, dt);
    }

    self._lastTime = performance.now();
    self._raf = requestAnimationFrame(_loop);

    // 4. Visibility change handler — pause when tab hidden
    self._visibilityHandler = function() {
      if (document.hidden && self._raf) {
        cancelAnimationFrame(self._raf);
        self._raf = null;
      } else if (!document.hidden && !self._raf && !self._destroyed) {
        self._lastTime = performance.now();
        self._raf = requestAnimationFrame(_loop);
      }
    };
    document.addEventListener("visibilitychange", self._visibilityHandler);

    return this;
  },

  /**
   * Add an agent character to the scene.
   * agent: { name, display_name, station, status }
   */
  addAgent: function(agent) {
    if (!agent || !agent.name) return;
    // Don't add duplicates
    if (CharacterManager.getCharacter(agent.name)) return;

    var ch = CharacterManager.addCharacter({
      name: agent.name,
      displayName: agent.display_name || agent.name,
      station: agent.station || "COMMAND",
      status: agent.status || "active"
    });

    // If already working, go straight to working state after beam-in
    if (agent.status === "working" && ch) {
      ch._pendingState = "working";
    }
  },

  /**
   * Remove an agent from the scene (beam-out animation).
   */
  removeAgent: function(name) {
    CharacterManager.removeCharacter(name);
  },

  /**
   * Send an agent to work at a specific console node.
   * nodeId: console id (e.g. "conversations")
   */
  setAgentWorking: function(name, nodeId) {
    CharacterManager.setWorking(name, nodeId);
  },

  /**
   * Return an agent to idle state.
   */
  setAgentIdle: function(name) {
    CharacterManager.setIdle(name);
  },

  /**
   * Play celebrate animation, then return to idle after 0.8s.
   */
  celebrateAgent: function(name) {
    CharacterManager.celebrate(name);
    setTimeout(function() {
      CharacterManager.setIdle(name);
    }, 800);
  },

  /**
   * Tear down the scene and free resources.
   */
  destroy: function() {
    this._destroyed = true;

    // Cancel animation frame
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }

    // Unsubscribe event bus
    _unsubscribeEvents();

    // Remove visibility listener
    if (this._visibilityHandler) {
      document.removeEventListener("visibilitychange", this._visibilityHandler);
      this._visibilityHandler = null;
    }

    // Clean up subsystems
    CharacterManager.clear();
    DeckRenderer.destroy();

    // Null references
    this._instance = null;
    this._lastTime = 0;
    this._frameSkip = 0;
  }
};

/* ── Export ──────────────────────────────────────────── */

window.PixelCrew = PixelCrew;
window.PixelSpriteFactory = PixelSpriteFactory;
window._DeckRenderer = DeckRenderer;
window._CharacterManager = CharacterManager;

})();
