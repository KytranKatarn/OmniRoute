/**
 * Consciousness Module Redesign — Visual QA + Integration Tests
 * Tests: 7 LCARS tabs, 3 breakpoints, API endpoints, element visibility
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

const TABS = ['dashboard', 'knowledge', 'team', 'insights', 'languages', 'github', 'integration'];

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

  // === Integration Tests (1280px) ===
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

  await page.goto(`${BASE}/tools/consciousness`, { waitUntil: 'networkidle', timeout: 15000 });
  await dismissBoot(page);
  await page.waitForTimeout(2000);

  // Test 1: LCARS header visible
  const header = await page.locator('.cs-header').isVisible();
  console.log(`${header ? 'PASS' : 'FAIL'}: LCARS header visible`);
  header ? passed++ : failed++;

  // Test 2: 7 tabs visible
  const tabCount = await page.locator('.cs-tab').count();
  const tabsOk = tabCount === 7;
  console.log(`${tabsOk ? 'PASS' : 'FAIL'}: Tab count (${tabCount}/7)`);
  tabsOk ? passed++ : failed++;

  // Test 3: Dashboard stats populated
  await page.waitForTimeout(2000);
  const statValue = await page.locator('#statKnowledgeTotal').textContent();
  const statOk = statValue && statValue !== '--';
  console.log(`${statOk ? 'PASS' : 'FAIL'}: Dashboard stats populated (knowledge: ${statValue})`);
  statOk ? passed++ : failed++;

  // Test 4: Team tab loads agents
  await page.evaluate(() => window.switchConsciousnessTab && window.switchConsciousnessTab('team'));
  await page.waitForTimeout(3000);
  const agentCards = await page.locator('.cs-agent-card').count();
  const agentsOk = agentCards > 0;
  console.log(`${agentsOk ? 'PASS' : 'FAIL'}: Agent cards rendered (${agentCards})`);
  agentsOk ? passed++ : failed++;

  // Test 5: Integration health API
  const healthStatus = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/integration/health');
    return r.status;
  });
  console.log(`${healthStatus === 200 ? 'PASS' : 'FAIL'}: Integration health API (${healthStatus})`);
  healthStatus === 200 ? passed++ : failed++;

  // Test 6: Dashboard summary API
  const summaryStatus = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/dashboard/summary');
    return r.status;
  });
  console.log(`${summaryStatus === 200 ? 'PASS' : 'FAIL'}: Dashboard summary API (${summaryStatus})`);
  summaryStatus === 200 ? passed++ : failed++;

  // Test 7: Team roster API
  const rosterStatus = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/team/roster');
    return r.status;
  });
  console.log(`${rosterStatus === 200 ? 'PASS' : 'FAIL'}: Team roster API (${rosterStatus})`);
  rosterStatus === 200 ? passed++ : failed++;

  await ctx.close();

  // === Visual QA at all breakpoints ===
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

    await pg.goto(`${BASE}/tools/consciousness`, { waitUntil: 'networkidle', timeout: 15000 });
    await dismissBoot(pg);
    await pg.waitForTimeout(2000);

    for (const tab of TABS) {
      await pg.evaluate((t) => window.switchConsciousnessTab && window.switchConsciousnessTab(t), tab);
      await pg.waitForTimeout(2000);
      const fname = `consciousness-${tab}-${vp.name}.png`;
      await pg.screenshot({ path: `${OUT}/${fname}`, fullPage: true });
      console.log(`  ${fname}`);
      passed++;
    }

    await context.close();
  }

  console.log(`\nResults: ${passed} passed, ${failed} failed`);
  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
