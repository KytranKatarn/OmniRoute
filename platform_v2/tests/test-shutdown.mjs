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

// Desktop — trigger shutdown
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);

// Intercept navigation so we can capture the animation
await page.route('**/logout', route => route.abort());

// Click logout button
await page.click('#cbLogoutBtn');

// Capture at different points in the animation
await page.waitForTimeout(2000);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/shutdown-2s.png', fullPage: false });
console.log('2s screenshot done');

await page.waitForTimeout(3000);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/shutdown-5s.png', fullPage: false });
console.log('5s screenshot done');

await page.waitForTimeout(3000);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/shutdown-8s.png', fullPage: false });
console.log('8s screenshot done');

await page.waitForTimeout(3000);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/shutdown-11s.png', fullPage: false });
console.log('11s screenshot done');

await browser.close();
