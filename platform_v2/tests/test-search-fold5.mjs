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

// Fold5 closed (374px)
await page.setViewportSize({ width: 374, height: 800 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/search-fold5-374.png', fullPage: false });
console.log('374px done');

// Fold5 open (717px)
await page.setViewportSize({ width: 717, height: 800 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/search-fold5-717.png', fullPage: false });
console.log('717px done');

// Desktop (1280px)
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);

// Test search actually works — type "bridge" and screenshot
await page.fill('#cbSearchInput', 'bridge');
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/search-result-bridge.png', fullPage: false });
console.log('search test done');

await browser.close();
