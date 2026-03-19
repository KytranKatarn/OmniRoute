#!/usr/bin/env node
/**
 * A.R.C.H.I.E. WCAG Accessibility Audit
 *
 * Runs axe-core WCAG 2.1 AA scans against key platform pages and produces
 * a colour-coded terminal report plus per-page JSON result files.
 *
 * Usage:
 *   node platform_v2/tests/test_accessibility.mjs
 *   node platform_v2/tests/test_accessibility.mjs --username admin --password 'Kyt$13ran2025'
 *   node platform_v2/tests/test_accessibility.mjs --url http://localhost:3000
 *   node platform_v2/tests/test_accessibility.mjs --pages dashboard,login
 *
 * Exit code is always 0 (audit tool, not a gate).
 */

import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'fs';
import { join, resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// ---------------------------------------------------------------------------
// 1. CLI Arguments
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);

function getArg(name, fallback) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : fallback;
}

const CONFIG = {
  url:       getArg('url', process.env.ARCHIE_URL || 'http://192.168.1.200:3000'),
  username:  getArg('username', process.env.ARCHIE_USERNAME || 'admin'),
  password:  getArg('password', process.env.ARCHIE_PASSWORD || 'Kyt$13ran2025'),
  outputDir: getArg('output-dir', join(__dirname, 'a11y-results')),
  timeout:   parseInt(getArg('timeout', '15000'), 10),
  pages:     getArg('pages', ''),   // comma-separated filter, empty = all
};

// ---------------------------------------------------------------------------
// 2. Route Registry
// ---------------------------------------------------------------------------

const ALL_PAGES = [
  // Public
  { name: 'login',              route: '/login',                    auth: false },
  // Core
  { name: 'dashboard',          route: '/dashboard',                auth: true },
  { name: 'dev-hq',             route: '/dev-hq',                   auth: true },
  // Admin Operations
  { name: 'account-center',     route: '/tools/account-center',     auth: true },
  { name: 'system-operations',  route: '/tools/system-operations',  auth: true },
  { name: 'backup-manager',     route: '/tools/backup-manager',     auth: true },
  // AI Command
  { name: 'bridge',             route: '/tools/starbase',             auth: true },
  { name: 'consciousness',      route: '/tools/consciousness',      auth: true },
  // SaaS / Additional (bonus coverage)
  { name: 'crm',                route: '/tools/crm',                auth: true },
  { name: 'invoicing',          route: '/tools/invoicing',          auth: true },
  { name: 'email-manager',      route: '/tools/email-manager',      auth: true },
  { name: 'autonomy',           route: '/tools/autonomy',           auth: true },
  { name: 'saas-manager',       route: '/tools/saas-manager',       auth: true },
  { name: 'iaae',               route: '/iaae',                     auth: false },
];

// Filter pages if --pages flag was provided
const pageFilter = CONFIG.pages
  ? CONFIG.pages.split(',').map((p) => p.trim().toLowerCase())
  : null;

const PAGES = pageFilter
  ? ALL_PAGES.filter((p) => pageFilter.includes(p.name))
  : ALL_PAGES;

if (PAGES.length === 0) {
  console.error(`No pages matched filter: ${CONFIG.pages}`);
  console.error(`Available: ${ALL_PAGES.map((p) => p.name).join(', ')}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 3. Terminal Colour Helpers
// ---------------------------------------------------------------------------

const C = {
  reset:    '\x1b[0m',
  bold:     '\x1b[1m',
  dim:      '\x1b[2m',
  red:      '\x1b[31m',
  green:    '\x1b[32m',
  yellow:   '\x1b[33m',
  orange:   '\x1b[38;5;208m',
  cyan:     '\x1b[36m',
  magenta:  '\x1b[35m',
  white:    '\x1b[37m',
  bgRed:    '\x1b[41m',
  bgGreen:  '\x1b[42m',
};

const SEVERITY_STYLE = {
  critical: { colour: C.red,    label: 'CRITICAL' },
  serious:  { colour: C.orange, label: 'SERIOUS'  },
  moderate: { colour: C.yellow, label: 'MODERATE' },
  minor:    { colour: C.dim,    label: 'MINOR'    },
};

function severityColour(impact) {
  return SEVERITY_STYLE[impact] || { colour: C.dim, label: impact?.toUpperCase() || 'UNKNOWN' };
}

function banner(text) {
  const line = '='.repeat(70);
  console.log(`\n${C.cyan}${line}${C.reset}`);
  console.log(`${C.cyan}  ${text}${C.reset}`);
  console.log(`${C.cyan}${line}${C.reset}\n`);
}

function sectionHeader(text) {
  console.log(`\n${C.bold}${C.white}--- ${text} ---${C.reset}`);
}

// ---------------------------------------------------------------------------
// 4. Login Helper (matches visual_baseline.mjs pattern)
// ---------------------------------------------------------------------------

async function login(page, baseUrl, username, password) {
  console.log(`  ${C.dim}Logging in as ${username}...${C.reset}`);
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle', timeout: CONFIG.timeout });

  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('#loginBtn');

  try {
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: CONFIG.timeout });
  } catch {
    const currentUrl = page.url();
    if (currentUrl.includes('/login')) {
      throw new Error('Login failed -- still on /login page. Check credentials.');
    }
  }

  const currentUrl = new URL(page.url());
  if (currentUrl.pathname.startsWith('/verify_2fa') || currentUrl.pathname.startsWith('/verify-2fa')) {
    throw new Error('2FA redirect detected. Use a non-2FA account or disable 2FA for testing.');
  }

  console.log(`  ${C.green}Login successful.${C.reset}`);
}

// ---------------------------------------------------------------------------
// 5. Axe Scan Helper
// ---------------------------------------------------------------------------

async function scanPage(page, pageConfig, baseUrl) {
  const { name, route } = pageConfig;
  const fullUrl = `${baseUrl}${route}`;

  process.stdout.write(`  ${C.bold}${name}${C.reset} (${route}) ... `);

  const startMs = Date.now();

  try {
    await page.goto(fullUrl, { waitUntil: 'networkidle', timeout: CONFIG.timeout });
  } catch (err) {
    if (err.message.includes('Timeout') || err.name === 'TimeoutError') {
      // Page may have loaded partially -- continue with scan
      await page.waitForTimeout(2000);
    } else {
      console.log(`${C.red}NAVIGATION ERROR: ${err.message}${C.reset}`);
      return {
        page: name,
        route,
        error: err.message,
        violations: [],
        passes: 0,
        incomplete: 0,
        inapplicable: 0,
        timestamp: new Date().toISOString(),
      };
    }
  }

  // Detect session loss on authenticated pages
  const currentUrl = new URL(page.url());
  if (pageConfig.auth && currentUrl.pathname.startsWith('/login')) {
    console.log(`${C.yellow}SESSION LOST -- re-authenticating${C.reset}`);
    await login(page, baseUrl, CONFIG.username, CONFIG.password);
    return scanPage(page, pageConfig, baseUrl);
  }

  // Run axe-core scan (WCAG 2.1 AA)
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();

  const elapsedMs = Date.now() - startMs;
  const violationCount = results.violations.length;
  const totalNodes = results.violations.reduce((sum, v) => sum + v.nodes.length, 0);

  // Count by severity
  const bySeverity = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  for (const v of results.violations) {
    const impact = v.impact || 'minor';
    bySeverity[impact] = (bySeverity[impact] || 0) + v.nodes.length;
  }

  // Status indicator
  if (violationCount === 0) {
    console.log(`${C.green}PASS${C.reset} ${C.dim}(${elapsedMs}ms)${C.reset}`);
  } else {
    const parts = [];
    if (bySeverity.critical > 0) parts.push(`${C.red}${bySeverity.critical} critical${C.reset}`);
    if (bySeverity.serious > 0)  parts.push(`${C.orange}${bySeverity.serious} serious${C.reset}`);
    if (bySeverity.moderate > 0) parts.push(`${C.yellow}${bySeverity.moderate} moderate${C.reset}`);
    if (bySeverity.minor > 0)    parts.push(`${C.dim}${bySeverity.minor} minor${C.reset}`);
    console.log(
      `${C.yellow}${violationCount} rules, ${totalNodes} nodes${C.reset} [${parts.join(', ')}] ${C.dim}(${elapsedMs}ms)${C.reset}`
    );
  }

  return {
    page: name,
    route,
    url: fullUrl,
    timestamp: new Date().toISOString(),
    scan_time_ms: elapsedMs,
    violations: results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      description: v.description,
      help: v.help,
      helpUrl: v.helpUrl,
      tags: v.tags,
      nodes: v.nodes.map((n) => ({
        html: n.html,
        target: n.target,
        failureSummary: n.failureSummary,
      })),
    })),
    violation_count: violationCount,
    node_count: totalNodes,
    by_severity: bySeverity,
    passes: results.passes.length,
    incomplete: results.incomplete.length,
    inapplicable: results.inapplicable.length,
  };
}

// ---------------------------------------------------------------------------
// 6. Main Flow
// ---------------------------------------------------------------------------

async function main() {
  const runId = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const runDir = join(CONFIG.outputDir, runId);
  mkdirSync(runDir, { recursive: true });

  banner('A.R.C.H.I.E. WCAG Accessibility Audit');

  console.log(`  Platform:  ${CONFIG.url}`);
  console.log(`  Pages:     ${PAGES.length}`);
  console.log(`  Standard:  WCAG 2.1 AA + best practices`);
  console.log(`  Output:    ${runDir}`);
  console.log(`  Run ID:    ${runId}`);
  console.log('');

  // Launch browser
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (err) {
    if (err.message.includes('Executable doesn\'t exist') || err.message.includes('browserType.launch')) {
      console.error(`${C.red}Chromium not found. Run setup:${C.reset}`);
      console.error('  cd platform_v2/tests && npm install && npx playwright install chromium');
      process.exit(1);
    }
    throw err;
  }

  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // Separate public and authenticated pages
  const publicPages = PAGES.filter((p) => !p.auth);
  const authPages = PAGES.filter((p) => p.auth);

  const allResults = [];

  // --- Public pages (no login) ---
  if (publicPages.length > 0) {
    sectionHeader('Public Pages');
    for (const pg of publicPages) {
      const result = await scanPage(page, pg, CONFIG.url);
      allResults.push(result);
      // Save individual result
      writeFileSync(
        join(runDir, `${pg.name}.json`),
        JSON.stringify(result, null, 2)
      );
    }
  }

  // --- Authenticated pages ---
  if (authPages.length > 0) {
    sectionHeader('Authenticated Pages');
    try {
      await login(page, CONFIG.url, CONFIG.username, CONFIG.password);
    } catch (err) {
      console.error(`${C.red}Login failed: ${err.message}${C.reset}`);
      await context.close();
      await browser.close();
      process.exit(1);
    }

    for (const pg of authPages) {
      const result = await scanPage(page, pg, CONFIG.url);
      allResults.push(result);
      writeFileSync(
        join(runDir, `${pg.name}.json`),
        JSON.stringify(result, null, 2)
      );
    }
  }

  await context.close();
  await browser.close();

  // ---------------------------------------------------------------------------
  // 7. Summary Report
  // ---------------------------------------------------------------------------

  banner('Audit Summary');

  // Aggregate totals
  const totals = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  let totalRules = 0;
  let totalNodes = 0;
  let totalPasses = 0;
  let pagesWithViolations = 0;
  let pagesClean = 0;
  let pagesErrored = 0;

  for (const r of allResults) {
    if (r.error) {
      pagesErrored++;
      continue;
    }
    totalRules += r.violation_count;
    totalNodes += r.node_count;
    totalPasses += r.passes;
    if (r.violation_count > 0) {
      pagesWithViolations++;
    } else {
      pagesClean++;
    }
    for (const sev of ['critical', 'serious', 'moderate', 'minor']) {
      totals[sev] += r.by_severity[sev] || 0;
    }
  }

  // Per-page table
  console.log(`  ${C.bold}Page Results:${C.reset}\n`);
  const nameWidth = Math.max(...allResults.map((r) => r.page.length), 4) + 2;

  for (const r of allResults) {
    const pad = r.page.padEnd(nameWidth);
    if (r.error) {
      console.log(`    ${C.red}ERROR${C.reset}  ${pad}  ${C.dim}${r.error}${C.reset}`);
    } else if (r.violation_count === 0) {
      console.log(`    ${C.green}PASS ${C.reset}  ${pad}  ${C.green}${r.passes} rules passed${C.reset}`);
    } else {
      const parts = [];
      if (r.by_severity.critical > 0) parts.push(`${C.red}${r.by_severity.critical}C${C.reset}`);
      if (r.by_severity.serious > 0)  parts.push(`${C.orange}${r.by_severity.serious}S${C.reset}`);
      if (r.by_severity.moderate > 0) parts.push(`${C.yellow}${r.by_severity.moderate}M${C.reset}`);
      if (r.by_severity.minor > 0)    parts.push(`${C.dim}${r.by_severity.minor}m${C.reset}`);
      console.log(
        `    ${C.yellow}WARN ${C.reset}  ${pad}  ${r.violation_count} rules, ${r.node_count} nodes [${parts.join(' ')}]`
      );
    }
  }

  // Totals by severity
  sectionHeader('Violations by Severity');
  console.log('');
  for (const sev of ['critical', 'serious', 'moderate', 'minor']) {
    const { colour, label } = severityColour(sev);
    const count = totals[sev];
    const bar = count > 0 ? ' '.repeat(Math.min(count, 50)) : '';
    const barColour = count > 0 ? `${colour}${'#'.repeat(Math.min(count, 50))}${C.reset}` : '';
    console.log(`    ${colour}${label.padEnd(10)}${C.reset} ${String(count).padStart(5)}  ${barColour}`);
  }
  console.log(`    ${'TOTAL'.padEnd(10)} ${String(totalNodes).padStart(5)}`);

  // Top violated rules across all pages
  const ruleMap = new Map();
  for (const r of allResults) {
    for (const v of r.violations) {
      const key = v.id;
      if (!ruleMap.has(key)) {
        ruleMap.set(key, {
          id: v.id,
          impact: v.impact,
          help: v.help,
          helpUrl: v.helpUrl,
          totalNodes: 0,
          pages: [],
        });
      }
      const entry = ruleMap.get(key);
      entry.totalNodes += v.nodes.length;
      entry.pages.push(r.page);
    }
  }

  if (ruleMap.size > 0) {
    sectionHeader('Top Violated Rules');
    console.log('');

    const sortedRules = [...ruleMap.values()].sort((a, b) => {
      const sevOrder = { critical: 0, serious: 1, moderate: 2, minor: 3 };
      const aSev = sevOrder[a.impact] ?? 4;
      const bSev = sevOrder[b.impact] ?? 4;
      if (aSev !== bSev) return aSev - bSev;
      return b.totalNodes - a.totalNodes;
    });

    // Show top 20
    const topRules = sortedRules.slice(0, 20);
    for (const rule of topRules) {
      const { colour, label } = severityColour(rule.impact);
      const pageList = [...new Set(rule.pages)].join(', ');
      console.log(
        `    ${colour}[${label}]${C.reset} ${rule.id} (${rule.totalNodes} nodes)`
      );
      console.log(
        `           ${C.dim}${rule.help}${C.reset}`
      );
      console.log(
        `           ${C.dim}Pages: ${pageList}${C.reset}`
      );
      console.log('');
    }
    if (sortedRules.length > 20) {
      console.log(`    ${C.dim}... and ${sortedRules.length - 20} more rules${C.reset}\n`);
    }
  }

  // Final summary line
  sectionHeader('Final Score');
  console.log('');
  console.log(`    Pages scanned:     ${allResults.length}`);
  console.log(`    ${C.green}Clean pages:       ${pagesClean}${C.reset}`);
  if (pagesWithViolations > 0) {
    console.log(`    ${C.yellow}Pages with issues:  ${pagesWithViolations}${C.reset}`);
  }
  if (pagesErrored > 0) {
    console.log(`    ${C.red}Pages errored:     ${pagesErrored}${C.reset}`);
  }
  console.log(`    Rules passed:      ${totalPasses} (across all pages)`);
  console.log(`    Rules violated:    ${totalRules}`);
  console.log(`    Affected nodes:    ${totalNodes}`);
  console.log('');

  // Save aggregate report
  const summaryReport = {
    run_id: runId,
    platform_url: CONFIG.url,
    standard: 'WCAG 2.1 AA + best-practice',
    timestamp: new Date().toISOString(),
    pages_scanned: allResults.length,
    pages_clean: pagesClean,
    pages_with_violations: pagesWithViolations,
    pages_errored: pagesErrored,
    totals,
    total_rules_violated: totalRules,
    total_nodes_affected: totalNodes,
    total_rules_passed: totalPasses,
    top_rules: [...ruleMap.values()].sort((a, b) => {
      const sevOrder = { critical: 0, serious: 1, moderate: 2, minor: 3 };
      return (sevOrder[a.impact] ?? 4) - (sevOrder[b.impact] ?? 4) || b.totalNodes - a.totalNodes;
    }),
    pages: allResults.map((r) => ({
      page: r.page,
      route: r.route,
      violation_count: r.violation_count,
      node_count: r.node_count,
      by_severity: r.by_severity,
      passes: r.passes,
      error: r.error || null,
    })),
  };

  const summaryPath = join(runDir, '_summary.json');
  writeFileSync(summaryPath, JSON.stringify(summaryReport, null, 2));

  // Also write a "latest" symlink-style copy at the output root
  const latestPath = join(CONFIG.outputDir, 'latest.json');
  writeFileSync(latestPath, JSON.stringify(summaryReport, null, 2));

  console.log(`  ${C.bold}Reports saved:${C.reset}`);
  console.log(`    Summary:    ${summaryPath}`);
  console.log(`    Latest:     ${latestPath}`);
  console.log(`    Per-page:   ${runDir}/<page>.json`);
  console.log('');

  if (totalNodes > 0) {
    console.log(
      `  ${C.yellow}WARNING: ${totalNodes} accessibility violations found across ${pagesWithViolations} page(s).${C.reset}`
    );
    console.log(
      `  ${C.dim}Review the JSON reports for details and remediation guidance.${C.reset}`
    );
  } else {
    console.log(`  ${C.green}All pages passed WCAG 2.1 AA checks. No violations found.${C.reset}`);
  }
  console.log('');
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

main().catch((err) => {
  console.error(`${C.red}Fatal error: ${err.message}${C.reset}`);
  console.error(err.stack);
  process.exit(1);
});
