#!/usr/bin/env node
/**
 * A.R.C.H.I.E. Visual Baseline Capture
 *
 * Captures screenshots of every platform module at 3 device breakpoints
 * for visual regression testing during the Platform UI Overhaul (Project #94).
 *
 * Usage:
 *   node visual_baseline.mjs --username Kytran --password <pass>
 *   node visual_baseline.mjs --compare screenshots/run1 screenshots/run2
 */

import { chromium } from 'playwright';
import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync } from 'fs';
import { join, resolve } from 'path';

// ---------------------------------------------------------------------------
// 1. CLI & Configuration
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);

function getArg(name, fallback) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : fallback;
}

const hasFlag = (name) => args.includes(`--${name}`);

// Comparison mode — handle early
if (hasFlag('compare')) {
  const idx = args.indexOf('--compare');
  const dir1 = args[idx + 1];
  const dir2 = args[idx + 2];
  if (!dir1 || !dir2) {
    console.error('Usage: --compare <dir1> <dir2>');
    process.exit(1);
  }
  runComparison(dir1, dir2);
  process.exit(0);
}

const CONFIG = {
  url:      getArg('url', process.env.ARCHIE_URL || 'http://192.168.1.200:3000'),
  username: getArg('username', process.env.ARCHIE_USERNAME),
  password: getArg('password', process.env.ARCHIE_PASSWORD),
  outputDir: getArg('output-dir', join(resolve('.'), 'screenshots')),
  timeout:  parseInt(getArg('timeout', '10000'), 10),
};

if (!CONFIG.username || !CONFIG.password) {
  console.error('Error: --username and --password required (or ARCHIE_USERNAME / ARCHIE_PASSWORD env vars)');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 2. Route Registry
// ---------------------------------------------------------------------------

const ROUTES = [
  // Public (no auth)
  { name: 'login',             route: '/login',                   auth: false },
  { name: 'iaae',              route: '/iaae',                    auth: false },
  // Core
  { name: 'dashboard',         route: '/dashboard',               auth: true },
  { name: 'dev-hq',            route: '/dev-hq',                  auth: true },
  // Admin Operations
  { name: 'backup-manager',    route: '/tools/backup-manager',    auth: true },
  { name: 'security-network',  route: '/tools/security-network',  auth: true },
  { name: 'account-center',    route: '/tools/account-center',    auth: true },
  { name: 'system-operations', route: '/tools/system-operations', auth: true },
  { name: 'saas-manager',      route: '/tools/saas-manager',      auth: true },
  // AI Command
  { name: 'bridge',            route: '/tools/bridge',            auth: true },
  { name: 'team-management',   route: '/tools/team-management',   auth: true },
  { name: 'consciousness',     route: '/tools/consciousness',     auth: true },
  { name: 'autonomy',          route: '/tools/autonomy',          auth: true },
  // SaaS Services
  { name: 'archie-chat',       route: '/tools/archie-chat',       auth: true },
  { name: 'crm',               route: '/tools/crm',               auth: true },
  { name: 'website-studio',    route: '/tools/website-studio',    auth: true },
  { name: 'store-builder',     route: '/tools/store-builder',     auth: true },
  { name: 'call-center',       route: '/tools/call-center',       auth: true },
  { name: 'email-manager',     route: '/tools/email-manager',     auth: true },
  { name: 'automations',       route: '/tools/automations',       auth: true },
  { name: 'invoicing',         route: '/tools/invoicing',         auth: true },
  { name: 'scheduler',         route: '/tools/scheduler',         auth: true },
  { name: 'social-media',      route: '/tools/social-media',      auth: true },
  { name: 'media-hub',         route: '/tools/media-hub',         auth: true },
  // Dev Tools
  { name: 'code-sentinel',     route: '/tools/code_sentinel',     auth: true },
  { name: 'sandbox-manager',   route: '/tools/sandbox-manager',   auth: true },
  { name: 'improvements-lab',  route: '/tools/improvements-lab',  auth: true },
  // Project & Knowledge
  { name: 'project-manager',   route: '/tools/project-manager',   auth: true },
  // Placeholders
  { name: 'fitness',           route: '/tools/fitness',           auth: true },
  { name: 'therapy',           route: '/tools/therapy',           auth: true },
  { name: 'doc',               route: '/tools/doc',               auth: true },
  { name: 'stockbot',          route: '/tools/stockbot',          auth: true },
  { name: 'game-studio',       route: '/tools/game-studio',       auth: true },
  { name: 'archie-pool',       route: '/tools/archie-pool',       auth: true },
  { name: 'pool-management',   route: '/tools/pool-management',   auth: true },
  { name: 'task-planner',      route: '/tools/task-planner',      auth: true },
  { name: 'google-workspace',  route: '/tools/google-workspace',  auth: true },
  { name: 'content-studio',    route: '/tools/content-studio',    auth: true },
  { name: 'media-studio',      route: '/tools/media-studio',      auth: true },
];

// ---------------------------------------------------------------------------
// 3. Viewports
// ---------------------------------------------------------------------------

const VIEWPORTS = [
  { name: 'fold5_closed', width: 374,  height: 812 },
  { name: 'fold5_open',   width: 717,  height: 812 },
  { name: 'desktop',      width: 1280, height: 900 },
];

// ---------------------------------------------------------------------------
// 4. Login Helper
// ---------------------------------------------------------------------------

async function login(page, baseUrl, username, password) {
  console.log('  Logging in...');
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle', timeout: CONFIG.timeout });

  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('#loginBtn');

  // Wait for navigation away from /login
  try {
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: CONFIG.timeout });
  } catch {
    const currentUrl = page.url();
    if (currentUrl.includes('/login')) {
      throw new Error('Login failed — still on /login page. Check credentials.');
    }
  }

  const currentUrl = new URL(page.url());
  if (currentUrl.pathname.startsWith('/verify_2fa') || currentUrl.pathname.startsWith('/verify-2fa')) {
    throw new Error('2FA redirect detected. Use a non-2FA account or disable 2FA for testing.');
  }

  console.log('  Login successful.');
}

// ---------------------------------------------------------------------------
// 5. Capture Function
// ---------------------------------------------------------------------------

async function captureRoute(page, routeConfig, baseUrl, outputDir, viewportName, viewportWidth) {
  const { name, route } = routeConfig;
  const dir = join(outputDir, name);
  mkdirSync(dir, { recursive: true });

  const screenshotPath = join(dir, `${viewportWidth}.png`);
  const consoleErrors = [];
  let httpStatus = null;

  // Collect console errors
  const onConsole = (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  };
  page.on('console', onConsole);

  // Track main document HTTP status
  const onResponse = (response) => {
    const reqUrl = new URL(response.url());
    const targetUrl = new URL(`${baseUrl}${route}`);
    if (reqUrl.pathname === targetUrl.pathname && response.request().resourceType() === 'document') {
      httpStatus = response.status();
    }
  };
  page.on('response', onResponse);

  const start = Date.now();
  let timedOut = false;

  try {
    await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: CONFIG.timeout });
  } catch (err) {
    if (err.message.includes('Timeout') || err.name === 'TimeoutError') {
      timedOut = true;
      // Wait a bit then capture whatever is visible
      await page.waitForTimeout(2000);
    } else {
      throw err;
    }
  }

  const loadTimeMs = Date.now() - start;

  // Detect session loss — redirected back to /login
  const currentUrl = new URL(page.url());
  if (routeConfig.auth && currentUrl.pathname.startsWith('/login')) {
    // Re-authenticate and retry once
    console.log(`    Session lost on ${name}, re-authenticating...`);
    page.removeListener('console', onConsole);
    page.removeListener('response', onResponse);
    await login(page, baseUrl, CONFIG.username, CONFIG.password);
    return captureRoute(page, routeConfig, baseUrl, outputDir, viewportName, viewportWidth);
  }

  await page.screenshot({ path: screenshotPath, fullPage: false });

  page.removeListener('console', onConsole);
  page.removeListener('response', onResponse);

  return {
    status: httpStatus,
    title: await page.title(),
    load_time_ms: loadTimeMs,
    timed_out: timedOut,
    console_errors: consoleErrors,
    screenshot_path: `${name}/${viewportWidth}.png`,
  };
}

// ---------------------------------------------------------------------------
// 6. Main Flow
// ---------------------------------------------------------------------------

async function main() {
  const runId = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const runDir = join(CONFIG.outputDir, runId);
  mkdirSync(runDir, { recursive: true });

  console.log(`A.R.C.H.I.E. Visual Baseline Capture`);
  console.log(`Run ID:  ${runId}`);
  console.log(`URL:     ${CONFIG.url}`);
  console.log(`Output:  ${runDir}`);
  console.log(`Routes:  ${ROUTES.length} | Viewports: ${VIEWPORTS.length}`);
  console.log(`Total screenshots: ${ROUTES.length * VIEWPORTS.length}`);
  console.log('');

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (err) {
    if (err.message.includes('Executable doesn\'t exist') || err.message.includes('browserType.launch')) {
      console.error('Chromium not found. Run setup:');
      console.error('  cd platform_v2/tests && npm install && npx playwright install chromium');
      process.exit(1);
    }
    throw err;
  }

  const publicRoutes = ROUTES.filter((r) => !r.auth);
  const authRoutes = ROUTES.filter((r) => r.auth);
  const startedAt = new Date().toISOString();
  const pages = [];
  let totalErrors = 0;

  // Build a map: routeName -> { screenshots: {}, results: {} }
  const pageMap = {};
  for (const r of ROUTES) {
    pageMap[r.name] = {
      name: r.name,
      route: r.route,
      screenshots: {},
      results: {},
    };
  }

  for (const vp of VIEWPORTS) {
    console.log(`--- Viewport: ${vp.name} (${vp.width}x${vp.height}) ---`);

    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      ignoreHTTPSErrors: true,
    });
    const page = await context.newPage();

    // Capture public routes (no login needed)
    for (const r of publicRoutes) {
      process.stdout.write(`  ${r.name} ... `);
      try {
        const result = await captureRoute(page, r, CONFIG.url, runDir, vp.name, vp.width);
        pageMap[r.name].screenshots[vp.name] = result.screenshot_path;
        pageMap[r.name].results[vp.name] = result;
        const statusTag = result.timed_out ? 'TIMEOUT' : `${result.status || '???'}`;
        console.log(`${statusTag} (${result.load_time_ms}ms)`);
        if (result.console_errors.length > 0) totalErrors += result.console_errors.length;
      } catch (err) {
        console.log(`FAIL: ${err.message}`);
        pageMap[r.name].results[vp.name] = { status: null, error: err.message };
        totalErrors++;
      }
    }

    // Login for authenticated routes
    try {
      await login(page, CONFIG.url, CONFIG.username, CONFIG.password);
    } catch (err) {
      console.error(`Login failed: ${err.message}`);
      await context.close();
      await browser.close();
      process.exit(1);
    }

    // Capture authenticated routes
    for (const r of authRoutes) {
      process.stdout.write(`  ${r.name} ... `);
      try {
        const result = await captureRoute(page, r, CONFIG.url, runDir, vp.name, vp.width);
        pageMap[r.name].screenshots[vp.name] = result.screenshot_path;
        pageMap[r.name].results[vp.name] = result;
        const statusTag = result.timed_out ? 'TIMEOUT' : `${result.status || '???'}`;
        console.log(`${statusTag} (${result.load_time_ms}ms)`);
        if (result.console_errors.length > 0) totalErrors += result.console_errors.length;
      } catch (err) {
        console.log(`FAIL: ${err.message}`);
        pageMap[r.name].results[vp.name] = { status: null, error: err.message };
        totalErrors++;
      }
    }

    await context.close();
    console.log('');
  }

  await browser.close();

  // ---------------------------------------------------------------------------
  // 7. Report Generation
  // ---------------------------------------------------------------------------

  const completedAt = new Date().toISOString();
  const durationSeconds = Math.round((new Date(completedAt) - new Date(startedAt)) / 1000);

  // Count screenshots and errors
  let totalScreenshots = 0;
  const errorsByRoute = {};

  const pagesArray = ROUTES.map((r) => {
    const entry = pageMap[r.name];
    for (const vp of VIEWPORTS) {
      const res = entry.results[vp.name];
      if (res && res.screenshot_path) totalScreenshots++;
      if (res && ((res.console_errors && res.console_errors.length > 0) || res.error)) {
        if (!errorsByRoute[r.name]) errorsByRoute[r.name] = [];
        if (res.error) {
          errorsByRoute[r.name].push({ viewport: vp.name, error: res.error });
        }
        if (res.console_errors) {
          for (const e of res.console_errors) {
            errorsByRoute[r.name].push({ viewport: vp.name, console_error: e });
          }
        }
      }
    }
    return entry;
  });

  const report = {
    run_id: runId,
    platform_url: CONFIG.url,
    started_at: startedAt,
    completed_at: completedAt,
    duration_seconds: durationSeconds,
    viewports: Object.fromEntries(VIEWPORTS.map((v) => [v.name, { width: v.width, height: v.height }])),
    total_screenshots: totalScreenshots,
    total_errors: totalErrors,
    pages: pagesArray,
    summary: {
      passed: totalScreenshots,
      failed: ROUTES.length * VIEWPORTS.length - totalScreenshots,
      errors_by_route: errorsByRoute,
    },
  };

  const reportPath = join(runDir, 'report.json');
  writeFileSync(reportPath, JSON.stringify(report, null, 2));

  console.log('=== Summary ===');
  console.log(`Screenshots:  ${totalScreenshots} / ${ROUTES.length * VIEWPORTS.length}`);
  console.log(`Errors:       ${totalErrors}`);
  console.log(`Duration:     ${durationSeconds}s`);
  console.log(`Report:       ${reportPath}`);

  if (totalErrors > 0) {
    console.log('\nRoutes with errors:');
    for (const [route, errors] of Object.entries(errorsByRoute)) {
      console.log(`  ${route}: ${errors.length} error(s)`);
    }
  }
}

// ---------------------------------------------------------------------------
// 8. Comparison Mode
// ---------------------------------------------------------------------------

function runComparison(dir1, dir2) {
  const report1Path = join(resolve(dir1), 'report.json');
  const report2Path = join(resolve(dir2), 'report.json');

  if (!existsSync(report1Path)) {
    console.error(`report.json not found in ${dir1}`);
    process.exit(1);
  }
  if (!existsSync(report2Path)) {
    console.error(`report.json not found in ${dir2}`);
    process.exit(1);
  }

  const report1 = JSON.parse(readFileSync(report1Path, 'utf-8'));
  const report2 = JSON.parse(readFileSync(report2Path, 'utf-8'));

  const pages1 = new Map(report1.pages.map((p) => [p.name, p]));
  const pages2 = new Map(report2.pages.map((p) => [p.name, p]));

  const allNames = new Set([...pages1.keys(), ...pages2.keys()]);
  const newPages = [];
  const missingPages = [];
  const changed = [];
  const unchanged = [];

  for (const name of allNames) {
    const p1 = pages1.get(name);
    const p2 = pages2.get(name);

    if (!p1 && p2) {
      newPages.push(name);
      continue;
    }
    if (p1 && !p2) {
      missingPages.push(name);
      continue;
    }

    // Compare screenshot file sizes per viewport
    let hasChange = false;
    const diffs = {};

    for (const vp of Object.keys(report1.viewports)) {
      const path1 = p1.screenshots[vp] ? join(resolve(dir1), p1.screenshots[vp]) : null;
      const path2 = p2.screenshots[vp] ? join(resolve(dir2), p2.screenshots[vp]) : null;

      if (!path1 || !path2 || !existsSync(path1) || !existsSync(path2)) {
        if (path1 !== path2) {
          hasChange = true;
          diffs[vp] = { reason: 'missing_screenshot' };
        }
        continue;
      }

      const size1 = statSync(path1).size;
      const size2 = statSync(path2).size;
      const delta = size2 - size1;
      const pct = size1 > 0 ? Math.round((delta / size1) * 100) : (size2 > 0 ? 100 : 0);

      if (delta !== 0) {
        hasChange = true;
        diffs[vp] = { size_before: size1, size_after: size2, delta, percent: pct };
      }
    }

    if (hasChange) {
      changed.push({ name, diffs });
    } else {
      unchanged.push(name);
    }
  }

  // Print summary
  console.log('=== Visual Comparison ===');
  console.log(`Before: ${dir1} (${report1.run_id})`);
  console.log(`After:  ${dir2} (${report2.run_id})`);
  console.log('');

  if (newPages.length > 0) {
    console.log(`New pages (${newPages.length}):`);
    for (const n of newPages) console.log(`  + ${n}`);
    console.log('');
  }

  if (missingPages.length > 0) {
    console.log(`Missing pages (${missingPages.length}):`);
    for (const n of missingPages) console.log(`  - ${n}`);
    console.log('');
  }

  if (changed.length > 0) {
    console.log(`Changed (${changed.length}):`);
    for (const c of changed) {
      console.log(`  ~ ${c.name}`);
      for (const [vp, d] of Object.entries(c.diffs)) {
        if (d.reason) {
          console.log(`      ${vp}: ${d.reason}`);
        } else {
          const sign = d.delta > 0 ? '+' : '';
          console.log(`      ${vp}: ${sign}${d.delta} bytes (${sign}${d.percent}%)`);
        }
      }
    }
    console.log('');
  }

  console.log(`Unchanged: ${unchanged.length}`);
  console.log(`Total:     ${allNames.size} pages`);

  // Write comparison JSON
  const comparison = {
    before: { dir: dir1, run_id: report1.run_id },
    after: { dir: dir2, run_id: report2.run_id },
    new_pages: newPages,
    missing_pages: missingPages,
    changed,
    unchanged,
    summary: {
      total: allNames.size,
      new: newPages.length,
      missing: missingPages.length,
      changed: changed.length,
      unchanged: unchanged.length,
    },
  };

  const outPath = join(resolve(dir2), 'comparison.json');
  writeFileSync(outPath, JSON.stringify(comparison, null, 2));
  console.log(`\nComparison report: ${outPath}`);
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

main().catch((err) => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
