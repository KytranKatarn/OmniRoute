/**
 * Dev HQ Visual QA — Screenshot all 6 tabs at 3 breakpoints
 * Breakpoints: 374px (Fold closed), 717px (Fold open), 1280px (Desktop)
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

const TABS = ['overview', 'projects', 'ideas', 'knowledge', 'decisions', 'system'];

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
  console.log('Browser launched');

  for (const vp of VIEWPORTS) {
    console.log(`\n=== Viewport: ${vp.name}px ===`);
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      ignoreHTTPSErrors: true,
    });
    const page = await context.newPage();

    // Login
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
    await page.fill('#username', CREDS.username);
    await page.fill('#password', CREDS.password);
    await page.click('#loginBtn');
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 10000 });
    console.log('  Logged in');

    // Navigate to Dev HQ
    await page.goto(`${BASE}/dev-hq`, { waitUntil: 'networkidle', timeout: 15000 });
    await dismissBoot(page);
    await page.waitForTimeout(1000);

    // Screenshot each tab
    for (const tab of TABS) {
      await page.evaluate((t) => {
        if (typeof window.switchDevHQTab === 'function') {
          window.switchDevHQTab(t);
        }
      }, tab);
      await page.waitForTimeout(1500);

      const fname = `devhq-${tab}-${vp.name}.png`;
      await page.screenshot({ path: `${OUT}/${fname}`, fullPage: true });
      console.log(`  ${fname}`);
    }

    // Bonus: Open a project detail view if projects exist
    const hasProjects = await page.evaluate(() => {
      const cards = document.querySelectorAll('[onclick*="openProjectDetail"]');
      if (cards.length > 0) {
        cards[0].click();
        return true;
      }
      return false;
    });

    if (hasProjects) {
      await page.waitForTimeout(1500);
      await page.screenshot({
        path: `${OUT}/devhq-project-detail-${vp.name}.png`,
        fullPage: true,
      });
      console.log(`  devhq-project-detail-${vp.name}.png`);

      // Screenshot each sub-tab
      for (const sub of ['tasks', 'decisions', 'docs', 'activity']) {
        await page.evaluate((s) => {
          if (typeof window.switchProjectSubTab === 'function') {
            window.switchProjectSubTab(s);
          }
        }, sub);
        await page.waitForTimeout(1200);
        const sfname = `devhq-project-${sub}-${vp.name}.png`;
        await page.screenshot({ path: `${OUT}/${sfname}`, fullPage: true });
        console.log(`  ${sfname}`);
      }

      // Go back
      await page.evaluate(() => {
        if (typeof window.closeProjectDetail === 'function') {
          window.closeProjectDetail();
        }
      });
      await page.waitForTimeout(500);
    }

    await context.close();
  }

  await browser.close();
  console.log('\nDone — screenshots saved to /mnt/archie_brain/screenshots/');
}

run().catch((e) => {
  console.error('FATAL:', e.message);
  process.exit(1);
});
