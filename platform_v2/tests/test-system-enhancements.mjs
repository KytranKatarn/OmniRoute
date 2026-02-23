/**
 * System Tab Enhancements — Visual QA + Integration Tests
 * Screenshots at 3 breakpoints + endpoint validation
 */
import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_URL || 'http://192.168.1.200:3000';
const CREDS = { username: 'admin', password: 'Kyt$13ran2025' };
const OUT = '/mnt/archie_brain/screenshots';

const VIEWPORTS = [
  { name: '374', width: 374, height: 812 },
  { name: '717', width: 717, height: 812 },
  { name: '1280', width: 1280, height: 900 },
];

async function dismissBoot(pg) {
  try {
    const skipBtn = pg.locator('#bootSkipBtn');
    await skipBtn.waitFor({ state: 'visible', timeout: 6000 });
    await skipBtn.click();
    await pg.waitForTimeout(1500);
  } catch (e) {
    await pg.waitForTimeout(6000);
  }
  await pg.evaluate(() => {
    const o = document.getElementById('bootOverlay');
    if (o) o.remove();
  });
  await pg.waitForTimeout(500);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  let passed = 0, failed = 0;

  // --- Integration Tests (1280px) ---
  console.log('=== Integration Tests ===');
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });

  await page.goto(`${BASE}/dev-hq`, { waitUntil: 'networkidle', timeout: 15000 });
  await dismissBoot(page);
  await page.waitForTimeout(1000);

  // Switch to System tab
  await page.evaluate(() => window.switchDevHQTab && window.switchDevHQTab('system'));
  await page.waitForTimeout(3000);

  // Test 1: Health sparklines
  const sparklines = await page.locator('#healthHistoryRow').isVisible();
  console.log(`${sparklines ? 'PASS' : 'FAIL'}: Health sparklines visible`);
  sparklines ? passed++ : failed++;

  // Test 2: MCP usage panel
  const usagePanel = await page.locator('#mcpUsagePanel').isVisible();
  console.log(`${usagePanel ? 'PASS' : 'FAIL'}: MCP usage panel visible`);
  usagePanel ? passed++ : failed++;

  // Test 3: Quick actions
  const quickActions = await page.locator('#quickActionsGrid').isVisible();
  console.log(`${quickActions ? 'PASS' : 'FAIL'}: Quick actions visible`);
  quickActions ? passed++ : failed++;

  // Test 4: Health check quick action
  await page.click('button:has-text("Run Health Check")');
  await page.waitForTimeout(4000);
  const resultText = await page.locator('#quickActionResult').textContent();
  const healthOk = resultText.includes('Health check complete') || resultText.includes('Done');
  console.log(`${healthOk ? 'PASS' : 'FAIL'}: Health check action (got: ${resultText.trim()})`);
  healthOk ? passed++ : failed++;

  // Test 5-7: API endpoints
  const endpoints = [
    { url: '/dev-hq/api/integrations/mcp/usage', method: 'GET', name: 'MCP Usage' },
    { url: '/dev-hq/api/integrations/health/history', method: 'GET', name: 'Health History' },
    { url: '/dev-hq/api/system/actions/reindex-embeddings', method: 'POST', name: 'Reindex' },
  ];

  for (const ep of endpoints) {
    const status = await page.evaluate(async ({ url, method }) => {
      const r = await fetch(url, { method, credentials: 'include' });
      return r.status;
    }, ep);
    const ok = status === 200;
    console.log(`${ok ? 'PASS' : 'FAIL'}: ${ep.name} API (${status})`);
    ok ? passed++ : failed++;
  }

  await ctx.close();

  // --- Visual QA at all breakpoints ---
  console.log('\n=== Visual QA ===');
  for (const vp of VIEWPORTS) {
    console.log(`\n--- ${vp.name}px ---`);
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      ignoreHTTPSErrors: true,
    });
    const pg = await context.newPage();

    await pg.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
    await pg.fill('#username', CREDS.username);
    await pg.fill('#password', CREDS.password);
    await pg.click('#loginBtn');
    await pg.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });

    await pg.goto(`${BASE}/dev-hq`, { waitUntil: 'networkidle', timeout: 15000 });
    await dismissBoot(pg);
    await pg.waitForTimeout(1000);

    await pg.evaluate(() => window.switchDevHQTab && window.switchDevHQTab('system'));
    await pg.waitForTimeout(3000);

    const fname = `devhq-system-enhanced-${vp.name}.png`;
    await pg.screenshot({ path: `${OUT}/${fname}`, fullPage: true });
    console.log(`  ${fname}`);
    passed++;

    await context.close();
  }

  console.log(`\nResults: ${passed} passed, ${failed} failed`);
  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
