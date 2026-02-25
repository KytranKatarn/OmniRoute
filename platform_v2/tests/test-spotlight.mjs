import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

async function dismissBoot(pg) {
    try {
        const skipBtn = pg.locator('#bootSkipBtn');
        await skipBtn.waitFor({ state: 'visible', timeout: 8000 });
        await skipBtn.click();
        await pg.waitForTimeout(2000);
    } catch(e) {
        await pg.waitForTimeout(8000);
    }
    await pg.evaluate(() => {
        const overlay = document.getElementById('bootOverlay');
        if (overlay) overlay.remove();
    });
    await pg.waitForTimeout(1000);
}

// Login
await page.goto('http://192.168.1.200:3000/login');
await page.fill('input[name="username"]', 'admin');
await page.fill('input[name="password"]', 'Kyt$13ran2025');
await page.click('button[type="submit"]');
await page.waitForLoadState('networkidle');
await dismissBoot(page);

// Desktop — search "bridge"
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.click('#cbSearchInput');
await page.type('#cbSearchInput', 'bridge', { delay: 80 });
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/spotlight-bridge-1280.png', fullPage: false });
console.log('bridge search done');

// Clear and search "email"
await page.fill('#cbSearchInput', '');
await page.waitForTimeout(200);
await page.type('#cbSearchInput', 'email', { delay: 80 });
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/spotlight-email-1280.png', fullPage: false });
console.log('email search done');

// Fold5 — search "system"
await page.setViewportSize({ width: 374, height: 800 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.click('#cbSearchInput');
await page.type('#cbSearchInput', 'sys', { delay: 80 });
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/spotlight-sys-374.png', fullPage: false });
console.log('fold5 search done');

// Empty search — "zzzzz" (no results)
await page.fill('#cbSearchInput', '');
await page.type('#cbSearchInput', 'zzzzz', { delay: 80 });
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/spotlight-noresults-374.png', fullPage: false });
console.log('no results done');

await browser.close();
