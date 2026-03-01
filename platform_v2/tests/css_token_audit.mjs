#!/usr/bin/env node
/**
 * A.R.C.H.I.E. CSS Token Audit
 *
 * Validates --archie-* CSS custom property usage across all modules.
 * Reports unused tokens, undefined references, and per-module coverage.
 *
 * Usage:
 *   node platform_v2/tests/css_token_audit.mjs
 *   node platform_v2/tests/css_token_audit.mjs --verbose
 *   node platform_v2/tests/css_token_audit.mjs --json
 */

import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative, extname } from 'path';

// ---------------------------------------------------------------------------
// 1. CLI & Configuration
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const hasFlag = (name) => args.includes(`--${name}`);

const VERBOSE = hasFlag('verbose');
const JSON_OUTPUT = hasFlag('json');

// Resolve paths relative to the repo root (two levels up from tests/)
const SCRIPT_DIR = new URL('.', import.meta.url).pathname;
const PLATFORM_DIR = join(SCRIPT_DIR, '..');
const ROOT_DIR = join(PLATFORM_DIR, '..');

const CSS_DIRS = [
  join(PLATFORM_DIR, 'static', 'css'),
];

const TEMPLATE_DIRS = [
  join(PLATFORM_DIR, 'templates'),
  join(PLATFORM_DIR, 'tools'),
];

const JS_DIRS = [
  join(PLATFORM_DIR, 'static', 'js'),
];

// ---------------------------------------------------------------------------
// 2. ANSI Color Helpers
// ---------------------------------------------------------------------------

const C = {
  reset:   '\x1b[0m',
  bold:    '\x1b[1m',
  dim:     '\x1b[2m',
  red:     '\x1b[31m',
  green:   '\x1b[32m',
  yellow:  '\x1b[33m',
  cyan:    '\x1b[36m',
  white:   '\x1b[37m',
  gray:    '\x1b[90m',
};

function colorize(color, text) {
  if (JSON_OUTPUT) return text;
  return `${color}${text}${C.reset}`;
}

// ---------------------------------------------------------------------------
// 3. File Discovery
// ---------------------------------------------------------------------------

/**
 * Recursively collect files matching given extensions.
 */
function collectFiles(dir, extensions) {
  const results = [];
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return results;
  }
  for (const entry of entries) {
    if (entry === 'node_modules' || entry === '__pycache__' || entry === '.git') continue;
    const fullPath = join(dir, entry);
    let stat;
    try {
      stat = statSync(fullPath);
    } catch {
      continue;
    }
    if (stat.isDirectory()) {
      results.push(...collectFiles(fullPath, extensions));
    } else if (extensions.includes(extname(entry).toLowerCase())) {
      results.push(fullPath);
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// 4. Token Extraction
// ---------------------------------------------------------------------------

/**
 * Extract --archie-* variable DEFINITIONS from content.
 * A definition looks like: --archie-foo-bar: <value>;
 */
function extractDefinitions(content, filePath) {
  const defs = [];
  const re = /(--archie-[a-zA-Z0-9_-]+)\s*:/g;
  let match;
  while ((match = re.exec(content)) !== null) {
    defs.push({
      token: match[1],
      file: filePath,
      line: content.substring(0, match.index).split('\n').length,
    });
  }
  return defs;
}

/**
 * Extract var(--archie-*) USAGES from content.
 */
function extractUsages(content, filePath) {
  const usages = [];
  const re = /var\(\s*(--archie-[a-zA-Z0-9_-]+)/g;
  let match;
  while ((match = re.exec(content)) !== null) {
    usages.push({
      token: match[1],
      file: filePath,
      line: content.substring(0, match.index).split('\n').length,
    });
  }
  return usages;
}

/**
 * Detect hardcoded color values in style contexts.
 * Returns count of hardcoded colors found.
 */
function countHardcodedColors(content, isTemplate) {
  let styleContent = content;

  // For HTML templates, extract only style blocks and inline styles
  if (isTemplate) {
    const styleBlocks = [];
    const styleRe = /<style[^>]*>([\s\S]*?)<\/style>/gi;
    let m;
    while ((m = styleRe.exec(content)) !== null) {
      styleBlocks.push(m[1]);
    }
    const inlineRe = /style\s*=\s*"([^"]*)"/gi;
    while ((m = inlineRe.exec(content)) !== null) {
      styleBlocks.push(m[1]);
    }
    styleContent = styleBlocks.join('\n');
  }

  if (!styleContent.trim()) return 0;

  // Remove CSS comments
  styleContent = styleContent.replace(/\/\*[\s\S]*?\*\//g, '');

  // Remove lines that are variable definitions — these are not "hardcoded"
  styleContent = styleContent.replace(/--[a-zA-Z0-9_-]+\s*:\s*[^;]+;/g, '');

  let count = 0;

  // Hex colors: #abc, #abcdef, #abcdef00
  const hexRe = /#(?:[0-9a-fA-F]{3,4}){1,2}\b/g;
  const hexMatches = styleContent.match(hexRe);
  if (hexMatches) {
    for (const h of hexMatches) {
      if (h.length >= 4) count++;
    }
  }

  // rgb/rgba/hsl/hsla functions (but not inside var())
  const funcRe = /\b(rgba?|hsla?)\s*\(/gi;
  const funcMatches = styleContent.match(funcRe);
  if (funcMatches) count += funcMatches.length;

  return count;
}

// ---------------------------------------------------------------------------
// 5. Module Name Extraction
// ---------------------------------------------------------------------------

/**
 * Derive a human-readable module name from a file path.
 */
function getModuleName(filePath) {
  const rel = relative(PLATFORM_DIR, filePath);

  const toolsMatch = rel.match(/templates\/tools\/([^/.]+)/);
  if (toolsMatch) return toolsMatch[1].replace(/_/g, '-');

  const templateMatch = rel.match(/templates\/([^/.]+)\.html/);
  if (templateMatch) return templateMatch[1].replace(/_/g, '-');

  const consMatch = rel.match(/tools\/consciousness\/templates\/([^/.]+)/);
  if (consMatch) return 'consciousness/' + consMatch[1].replace(/_/g, '-');

  const layoutCssMatch = rel.match(/static\/css\/layouts\/([^/.]+)\.css/);
  if (layoutCssMatch) return 'css/layouts/' + layoutCssMatch[1];

  const themeCssMatch = rel.match(/static\/css\/themes\/([^/.]+)\.css/);
  if (themeCssMatch) return 'css/themes/' + themeCssMatch[1];

  const cssMatch = rel.match(/static\/css\/([^/.]+)\.css/);
  if (cssMatch) return 'css/' + cssMatch[1];

  const jsMatch = rel.match(/static\/js\/([^/.]+)\.js/);
  if (jsMatch) return 'js/' + jsMatch[1];

  const includeMatch = rel.match(/templates\/includes\/([^/.]+)\.html/);
  if (includeMatch) return 'includes/' + includeMatch[1].replace(/_/g, '-');

  const layoutTplMatch = rel.match(/templates\/layouts\/([^/.]+)\.html/);
  if (layoutTplMatch) return 'layouts/' + layoutTplMatch[1];

  return rel;
}

// ---------------------------------------------------------------------------
// 6. Main Audit Logic
// ---------------------------------------------------------------------------

function runAudit() {
  const cssFiles = [];
  for (const dir of CSS_DIRS) {
    cssFiles.push(...collectFiles(dir, ['.css']));
  }

  const templateFiles = [];
  for (const dir of TEMPLATE_DIRS) {
    templateFiles.push(...collectFiles(dir, ['.html']));
  }

  const jsFiles = [];
  for (const dir of JS_DIRS) {
    jsFiles.push(...collectFiles(dir, ['.js']));
  }

  const allFiles = [...cssFiles, ...templateFiles, ...jsFiles];

  const allDefinitions = [];
  const allUsages = [];
  const moduleStats = {};

  for (const filePath of allFiles) {
    let content;
    try {
      content = readFileSync(filePath, 'utf-8');
    } catch {
      continue;
    }

    const isTemplate = extname(filePath) === '.html';
    const isJS = extname(filePath) === '.js';
    const moduleName = getModuleName(filePath);

    const defs = extractDefinitions(content, filePath);
    const usages = extractUsages(content, filePath);
    const hardcoded = countHardcodedColors(content, isTemplate || isJS);

    allDefinitions.push(...defs);
    allUsages.push(...usages);

    if (!moduleStats[moduleName]) {
      moduleStats[moduleName] = {
        tokenUsages: 0,
        tokenDefinitions: 0,
        hardcodedColors: 0,
        files: [],
        usedTokens: new Set(),
        definedTokens: new Set(),
      };
    }

    moduleStats[moduleName].tokenUsages += usages.length;
    moduleStats[moduleName].tokenDefinitions += defs.length;
    moduleStats[moduleName].hardcodedColors += hardcoded;
    moduleStats[moduleName].files.push(filePath);
    for (const u of usages) moduleStats[moduleName].usedTokens.add(u.token);
    for (const d of defs) moduleStats[moduleName].definedTokens.add(d.token);
  }

  // Build token maps
  const definedTokens = new Map();
  for (const d of allDefinitions) {
    if (!definedTokens.has(d.token)) definedTokens.set(d.token, []);
    definedTokens.get(d.token).push({ file: d.file, line: d.line });
  }

  const usedTokens = new Map();
  for (const u of allUsages) {
    if (!usedTokens.has(u.token)) usedTokens.set(u.token, []);
    usedTokens.get(u.token).push({ file: u.file, line: u.line });
  }

  // Unused: defined but never var()-referenced
  const unusedTokens = [];
  for (const [token, locations] of definedTokens) {
    if (!usedTokens.has(token)) {
      unusedTokens.push({ token, definedIn: locations });
    }
  }

  // Undefined: var()-referenced but never defined
  const undefinedTokens = [];
  for (const [token, locations] of usedTokens) {
    if (!definedTokens.has(token)) {
      undefinedTokens.push({ token, usedIn: locations });
    }
  }

  return {
    cssFiles,
    templateFiles,
    jsFiles,
    allDefinitions,
    allUsages,
    definedTokens,
    usedTokens,
    unusedTokens,
    undefinedTokens,
    moduleStats,
  };
}

// ---------------------------------------------------------------------------
// 7. Report Rendering
// ---------------------------------------------------------------------------

function printReport(audit) {
  const {
    cssFiles, templateFiles, jsFiles,
    definedTokens, usedTokens,
    unusedTokens, undefinedTokens,
    moduleStats,
  } = audit;

  const totalDefined = definedTokens.size;
  const totalUsed = usedTokens.size;
  const totalDefinitions = audit.allDefinitions.length;
  const totalUsages = audit.allUsages.length;

  // -- Header --
  console.log('');
  console.log(colorize(C.cyan + C.bold, '  ============================================================'));
  console.log(colorize(C.cyan + C.bold, '    A.R.C.H.I.E. CSS Token Audit'));
  console.log(colorize(C.cyan + C.bold, '  ============================================================'));
  console.log('');

  // -- File Summary --
  console.log(colorize(C.bold, '  FILES SCANNED'));
  console.log(colorize(C.gray, '  ------------------------------------------------'));
  console.log('  CSS files:      ' + colorize(C.cyan, String(cssFiles.length)));
  console.log('  Templates:      ' + colorize(C.cyan, String(templateFiles.length)));
  console.log('  JS files:       ' + colorize(C.cyan, String(jsFiles.length)));
  console.log('  Total:          ' + colorize(C.bold, String(cssFiles.length + templateFiles.length + jsFiles.length)));
  console.log('');

  // -- Token Summary --
  console.log(colorize(C.bold, '  TOKEN SUMMARY'));
  console.log(colorize(C.gray, '  ------------------------------------------------'));
  console.log('  Unique tokens defined:    ' + colorize(C.green, String(totalDefined)));
  console.log('  Unique tokens referenced: ' + colorize(C.cyan, String(totalUsed)));
  console.log('  Total definitions:        ' + colorize(C.white, String(totalDefinitions)) + '  ' + colorize(C.dim, '(incl. theme overrides)'));
  console.log('  Total var() usages:       ' + colorize(C.white, String(totalUsages)));
  console.log('');

  // -- Unused Tokens --
  const unusedCount = unusedTokens.length;
  if (unusedCount > 0) {
    console.log(colorize(C.yellow + C.bold, '  UNUSED TOKENS (' + unusedCount + ')'));
    console.log(colorize(C.gray, '  ------------------------------------------------'));
    console.log(colorize(C.dim, '  Defined but never referenced via var()'));
    console.log('');

    // Group by category
    const groups = {};
    for (const { token, definedIn } of unusedTokens) {
      const parts = token.replace('--archie-', '').split('-');
      const category = parts[0] || 'other';
      if (!groups[category]) groups[category] = [];
      groups[category].push({ token, definedIn });
    }

    for (const [category, tokens] of Object.entries(groups).sort()) {
      console.log(colorize(C.yellow, '    [' + category + ']'));
      for (const { token, definedIn } of tokens.sort((a, b) => a.token.localeCompare(b.token))) {
        const loc = definedIn[0];
        const relPath = relative(ROOT_DIR, loc.file);
        console.log('      ' + colorize(C.yellow, token) + '  ' + colorize(C.dim, relPath + ':' + loc.line));
      }
    }
    console.log('');
  } else {
    console.log(colorize(C.green + C.bold, '  UNUSED TOKENS: None'));
    console.log(colorize(C.green, '  All defined tokens are referenced.'));
    console.log('');
  }

  // -- Undefined Tokens (Potential Bugs) --
  const undefinedCount = undefinedTokens.length;
  if (undefinedCount > 0) {
    console.log(colorize(C.red + C.bold, '  UNDEFINED TOKENS (' + undefinedCount + ')'));
    console.log(colorize(C.gray, '  ------------------------------------------------'));
    console.log(colorize(C.dim, '  Referenced via var() but never defined -- potential bugs'));
    console.log('');

    for (const { token, usedIn } of undefinedTokens.sort((a, b) => a.token.localeCompare(b.token))) {
      const uniqueFiles = [...new Set(usedIn.map(u => relative(ROOT_DIR, u.file)))];
      console.log('    ' + colorize(C.red, token));
      for (const f of uniqueFiles.slice(0, 5)) {
        const locs = usedIn.filter(u => relative(ROOT_DIR, u.file) === f);
        const lines = locs.map(l => l.line).join(', ');
        console.log('      ' + colorize(C.dim, f + ':' + lines));
      }
      if (uniqueFiles.length > 5) {
        console.log(colorize(C.dim, '      ...and ' + (uniqueFiles.length - 5) + ' more files'));
      }
    }
    console.log('');
  } else {
    console.log(colorize(C.green + C.bold, '  UNDEFINED TOKENS: None'));
    console.log(colorize(C.green, '  All referenced tokens have definitions.'));
    console.log('');
  }

  // -- Per-Module Coverage --
  console.log(colorize(C.bold, '  PER-MODULE TOKEN COVERAGE'));
  console.log(colorize(C.gray, '  ------------------------------------------------'));
  console.log(colorize(C.dim, '  Modules sorted by token adoption (usages vs hardcoded colors)'));
  console.log('');

  const moduleEntries = Object.entries(moduleStats)
    .filter(([, stats]) => stats.tokenUsages > 0 || stats.hardcodedColors > 0)
    .sort((a, b) => {
      const coverageA = a[1].tokenUsages / Math.max(1, a[1].tokenUsages + a[1].hardcodedColors);
      const coverageB = b[1].tokenUsages / Math.max(1, b[1].tokenUsages + b[1].hardcodedColors);
      return coverageB - coverageA;
    });

  const nameWidth = 38;
  const numWidth = 8;
  console.log(
    '    ' + colorize(C.bold, 'Module'.padEnd(nameWidth)) +
    colorize(C.bold, 'Usages'.padStart(numWidth)) +
    colorize(C.bold, 'Hardcoded'.padStart(numWidth + 2)) +
    colorize(C.bold, 'Coverage'.padStart(numWidth + 2))
  );
  console.log(colorize(C.gray, '    ' + '-'.repeat(nameWidth + numWidth * 3 + 4)));

  for (const [name, stats] of moduleEntries) {
    const total = stats.tokenUsages + stats.hardcodedColors;
    const pct = total > 0 ? Math.round((stats.tokenUsages / total) * 100) : 0;

    let pctColor = C.red;
    let statusIcon = 'X';
    if (pct >= 80) { pctColor = C.green; statusIcon = '+'; }
    else if (pct >= 50) { pctColor = C.yellow; statusIcon = '~'; }
    else if (pct >= 20) { pctColor = C.yellow; statusIcon = '~'; }

    const pctStr = pct + '%';

    console.log(
      '  ' + colorize(pctColor, statusIcon) + ' ' +
      name.padEnd(nameWidth) +
      colorize(C.cyan, String(stats.tokenUsages).padStart(numWidth)) +
      colorize(stats.hardcodedColors > 0 ? C.yellow : C.green, String(stats.hardcodedColors).padStart(numWidth + 2)) +
      colorize(pctColor, pctStr.padStart(numWidth + 2))
    );
  }

  // Modules with zero usage
  const zeroModules = Object.entries(moduleStats)
    .filter(([, stats]) => stats.tokenUsages === 0 && stats.hardcodedColors === 0);

  if (zeroModules.length > 0 && VERBOSE) {
    console.log('');
    console.log(colorize(C.dim, '    ' + zeroModules.length + ' modules with no CSS token usage or hardcoded colors (structural/empty)'));
    for (const [name] of zeroModules.sort()) {
      console.log(colorize(C.dim, '      ' + name));
    }
  }

  console.log('');

  // -- Overall Health --
  const totalTokenUsages = Object.values(moduleStats).reduce((s, m) => s + m.tokenUsages, 0);
  const totalHardcoded = Object.values(moduleStats).reduce((s, m) => s + m.hardcodedColors, 0);
  const overallTotal = totalTokenUsages + totalHardcoded;
  const overallPct = overallTotal > 0 ? Math.round((totalTokenUsages / overallTotal) * 100) : 0;

  let healthColor = C.red;
  let healthLabel = 'POOR';
  if (overallPct >= 80) { healthColor = C.green; healthLabel = 'EXCELLENT'; }
  else if (overallPct >= 60) { healthColor = C.green; healthLabel = 'GOOD'; }
  else if (overallPct >= 40) { healthColor = C.yellow; healthLabel = 'FAIR'; }
  else if (overallPct >= 20) { healthColor = C.yellow; healthLabel = 'NEEDS WORK'; }

  console.log(colorize(C.bold, '  OVERALL HEALTH'));
  console.log(colorize(C.gray, '  ------------------------------------------------'));

  // Progress bar
  const barWidth = 40;
  const filled = Math.round((overallPct / 100) * barWidth);
  const empty = barWidth - filled;
  const bar = colorize(healthColor, '\u2588'.repeat(filled)) + colorize(C.gray, '\u2591'.repeat(empty));

  console.log('  Token adoption: ' + bar + ' ' + colorize(healthColor + C.bold, overallPct + '% ' + healthLabel));
  console.log('  Token usages:       ' + colorize(C.green, String(totalTokenUsages)));
  console.log('  Hardcoded colors:   ' + colorize(totalHardcoded > 0 ? C.yellow : C.green, String(totalHardcoded)));
  console.log('  Unused definitions: ' + colorize(unusedCount > 0 ? C.yellow : C.green, String(unusedCount)));
  console.log('  Undefined refs:     ' + colorize(undefinedCount > 0 ? C.red : C.green, String(undefinedCount)));
  console.log('');

  // -- Recommendations --
  if (undefinedCount > 0 || unusedCount > 10) {
    console.log(colorize(C.bold, '  RECOMMENDATIONS'));
    console.log(colorize(C.gray, '  ------------------------------------------------'));
    if (undefinedCount > 0) {
      console.log(colorize(C.red, '  ! ' + undefinedCount + ' undefined token(s) -- add definitions or fix typos'));
    }
    if (unusedCount > 10) {
      console.log(colorize(C.yellow, '  ~ ' + unusedCount + ' unused tokens -- consider pruning or adopting them'));
    }

    // Low-coverage modules
    const lowCoverage = moduleEntries
      .filter(([name, stats]) => {
        const total = stats.tokenUsages + stats.hardcodedColors;
        const pct = total > 0 ? (stats.tokenUsages / total) * 100 : 100;
        return pct < 50 && stats.hardcodedColors > 20 && !name.startsWith('css/');
      })
      .slice(0, 5);

    if (lowCoverage.length > 0) {
      console.log(colorize(C.yellow, '  ~ Modules with low token adoption (migrate hardcoded colors):'));
      for (const [name, stats] of lowCoverage) {
        const total = stats.tokenUsages + stats.hardcodedColors;
        const pct = Math.round((stats.tokenUsages / total) * 100);
        console.log(colorize(C.yellow, '      ' + name + ': ' + pct + '% (' + stats.hardcodedColors + ' hardcoded)'));
      }
    }
    console.log('');
  }

  console.log(colorize(C.cyan + C.bold, '  ============================================================'));
  console.log('');

  return { undefinedCount, unusedCount };
}

function printJsonReport(audit) {
  const { definedTokens, usedTokens, unusedTokens, undefinedTokens, moduleStats } = audit;

  const report = {
    timestamp: new Date().toISOString(),
    summary: {
      unique_tokens_defined: definedTokens.size,
      unique_tokens_referenced: usedTokens.size,
      total_definitions: audit.allDefinitions.length,
      total_usages: audit.allUsages.length,
      unused_tokens: unusedTokens.length,
      undefined_tokens: undefinedTokens.length,
      files_scanned: {
        css: audit.cssFiles.length,
        templates: audit.templateFiles.length,
        js: audit.jsFiles.length,
      },
    },
    unused_tokens: unusedTokens.map(({ token, definedIn }) => ({
      token,
      defined_in: definedIn.map(d => ({
        file: relative(ROOT_DIR, d.file),
        line: d.line,
      })),
    })),
    undefined_tokens: undefinedTokens.map(({ token, usedIn }) => ({
      token,
      used_in: usedIn.map(u => ({
        file: relative(ROOT_DIR, u.file),
        line: u.line,
      })),
    })),
    module_coverage: Object.entries(moduleStats)
      .filter(([, s]) => s.tokenUsages > 0 || s.hardcodedColors > 0)
      .map(([name, stats]) => {
        const total = stats.tokenUsages + stats.hardcodedColors;
        return {
          module: name,
          token_usages: stats.tokenUsages,
          hardcoded_colors: stats.hardcodedColors,
          coverage_pct: total > 0 ? Math.round((stats.tokenUsages / total) * 100) : 100,
          unique_tokens_used: stats.usedTokens.size,
        };
      })
      .sort((a, b) => b.coverage_pct - a.coverage_pct),
  };

  console.log(JSON.stringify(report, null, 2));
}

// ---------------------------------------------------------------------------
// 8. Entry Point
// ---------------------------------------------------------------------------

const audit = runAudit();

if (JSON_OUTPUT) {
  printJsonReport(audit);
} else {
  const { undefinedCount } = printReport(audit);
  // Exit with error code if undefined tokens found (CI integration)
  if (undefinedCount > 0) {
    process.exit(1);
  }
}
