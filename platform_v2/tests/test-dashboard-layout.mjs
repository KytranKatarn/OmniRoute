import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();
await page.setViewportSize({ width: 1280, height: 900 });

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

const languages = ['en', 'fr', 'he', 'zh', 'ar', 'de'];

for (const lang of languages) {
    await setLang(page, lang);
    await page.goto('http://192.168.1.200:3000/dashboard');
    await page.waitForLoadState('networkidle');
    await dismissBoot(page);

    // Full page
    await page.screenshot({ path: `/mnt/archie_brain/screenshots/dash-layout-${lang}-full.png`, fullPage: true });

    // Top stats bar area
    const statsBar = page.locator('.hud-stats, .stats-bar, .system-stats').first();
    if (await statsBar.isVisible().catch(() => false)) {
        await statsBar.screenshot({ path: `/mnt/archie_brain/screenshots/dash-layout-${lang}-stats.png` });
    }

    // Priority stations / featured cards
    const featured = page.locator('#featured-modules, .featured-section, .priority-stations').first();
    if (await featured.isVisible().catch(() => false)) {
        await featured.screenshot({ path: `/mnt/archie_brain/screenshots/dash-layout-${lang}-stations.png` });
    }

    console.log(lang + ' done');
}

await browser.close();
