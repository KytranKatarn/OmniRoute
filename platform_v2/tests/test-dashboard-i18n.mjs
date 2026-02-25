import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();
await page.setViewportSize({ width: 1280, height: 900 });

async function setLang(pg, lang) {
    // Set both localStorage AND server-side preference
    await pg.evaluate((l) => {
        localStorage.setItem('archie-language', l);
        localStorage.removeItem('archie-translations');
    }, lang);
    // Update server preference
    await pg.evaluate(async (l) => {
        await fetch('/api/user/language', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: l })
        });
    }, lang);
}

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

// French
await setLang(page, 'fr');
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/dashboard-fr-1280.png', fullPage: false });
console.log('FR saved');

// Hebrew
await setLang(page, 'he');
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/dashboard-he-1280.png', fullPage: false });
console.log('HE saved');

// English (reset to default)
await setLang(page, 'en');
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/dashboard-en-1280.png', fullPage: false });
console.log('EN saved');

await browser.close();
