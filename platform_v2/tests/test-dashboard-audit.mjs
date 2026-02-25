import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

async function setLang(pg, lang) {
    await pg.evaluate((l) => {
        localStorage.setItem('archie-language', l);
        localStorage.removeItem('archie-translations');
    }, lang);
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

// Reset to English
await setLang(page, 'en');

// Desktop 1280 — full page
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-1280-top.png', fullPage: false });
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-1280-full.png', fullPage: true });
console.log('EN 1280 done');

// Fold5 closed 374
await page.setViewportSize({ width: 374, height: 800 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-374-top.png', fullPage: false });
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-374-full.png', fullPage: true });
console.log('EN 374 done');

// Fold5 open 717
await page.setViewportSize({ width: 717, height: 800 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-717-top.png', fullPage: false });
console.log('EN 717 done');

// Light mode desktop
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.evaluate(() => { if(typeof toggleTheme==='function') toggleTheme(); });
await page.waitForTimeout(500);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-en-light-1280.png', fullPage: false });
// Switch back to dark
await page.evaluate(() => { if(typeof toggleTheme==='function') toggleTheme(); });
console.log('EN light done');

// Hebrew RTL desktop
await setLang(page, 'he');
await page.goto('http://192.168.1.200:3000/dashboard');
await page.waitForLoadState('networkidle');
await dismissBoot(page);
await page.screenshot({ path: '/mnt/archie_brain/screenshots/audit-he-1280-top.png', fullPage: false });
console.log('HE 1280 done');

// Reset to English
await setLang(page, 'en');

await browser.close();
