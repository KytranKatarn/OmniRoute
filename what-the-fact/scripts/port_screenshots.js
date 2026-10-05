#!/usr/bin/env node
/**
 * Side-by-side screenshots for the Claude Design port review: every nav page, LIVE vs DESIGN,
 * full page, same viewport.  Run on a machine with INTERNET (the design files load d3, fonts and
 * map data from CDNs, and the live pages need the real site + database) — the authoring sandbox
 * has neither, which is why this script exists.
 *
 *   cd what-the-fact && node scripts/port_screenshots.js [--base https://what-the-fact.com] [--out design-handoff/shots] [--width 1280] [--only mps,elections]
 *
 * Needs `playwright` (npm i -D playwright && npx playwright install chromium) and python3 (for a local
 * static server over design-handoff/). Writes <out>/<tab>/<slug>-live.png and <slug>-design.png plus
 * <out>/manifest.json (status code, console errors, page height per shot).
 * Public pages only: signed-in/subscriber states are NOT captured (use --cookie "name=value" to pass a session).
 */
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs'), path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'https://what-the-fact.com').replace(/\/$/, '');
const OUT = arg('out', 'design-handoff/shots');
const WIDTH = +arg('width', 1280);
const ONLY = (arg('only', '') || '').split(',').filter(Boolean);
const COOKIE = arg('cookie', '');
const PORT = 8799;

// tab -> [slug, live path, design file]  (mirrors the nav in consumer/templates/base.html)
const PAGES = {
  news: [['home', '/', 'wtf-home'], ['archive', '/archive', 'wtf-archive'], ['activity', '/activity', 'wtf-activity'],
         ['weather', '/weather', 'wtf-weather'], ['blindspot', '/blindspot', 'wtf-blindspot'],
         ['divergence', '/divergence', 'wtf-divergence'], ['clusters', '/clusters', 'wtf-clusters']],
  politics: [['parties', '/parties', 'wtf-parties'], ['mps', '/mps', 'wtf-mps'], ['municipal', '/municipal', 'wtf-municipal'],
             ['lobbying', '/lobbying', 'wtf-lobbying'], ['gic', '/gic', 'wtf-gic'], ['ethics', '/ethics', 'wtf-ethics'],
             ['officers', '/parliament/officers', 'wtf-officers']],
  elections: [['elections', '/elections', 'wtf-elections'], ['races', '/races', 'wtf-races'],
              ['ridings', '/ridings', 'wtf-ridings']],            // /candidates has no design file
  money: [['economy', '/economy', 'wtf-economy'], ['rates', '/rates', 'wtf-rates'], ['cost', '/cost', 'wtf-cost'],
          ['global', '/global', 'wtf-global'], ['debt', '/debt', 'wtf-debt'], ['markets', '/markets', 'wtf-markets']],
  media: [['sources', '/sources', 'wtf-sources'], ['owners', '/owners', 'wtf-owners'], ['journalists', '/journalists', 'wtf-journalists'],
          ['crtc', '/crtc', 'wtf-crtc'], ['echo', '/echo', 'wtf-echo']],
  data: [['map', '/map', 'wtf-map'], ['chain', '/chain', 'wtf-chain'], ['cross-watch', '/cross-watch', 'wtf-cross-watch'],
         ['claims', '/claims', 'wtf-claims'], ['api', '/api/docs', 'wtf-api'], ['edu', '/edu', 'wtf-edu'], ['search', '/search', 'wtf-search']],
  about: [['methodology', '/methodology', 'wtf-methodology'], ['team', '/team', 'wtf-team'], ['governance', '/governance', 'wtf-governance'],
          ['creed', '/creed', 'wtf-creed'], ['literacy', '/literacy', 'wtf-literacy'], ['score', '/score', 'wtf-score']],
};

async function shoot(browser, url, file, manifest, key) {
  const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 } });
  if (COOKIE && url.startsWith(BASE)) { const [n, ...v] = COOKIE.split('='); await ctx.addCookies([{ name: n, value: v.join('='), url: BASE }]); }
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 140)); });
  page.on('pageerror', e => errs.push('PAGEERROR ' + String(e).slice(0, 140)));
  let status = null;
  try {
    const r = await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
    status = r ? r.status() : null;
  } catch (e) { errs.push('GOTO ' + e.message.slice(0, 120)); }
  await page.waitForTimeout(2500);                       // client-rendered feeds / maps
  // scroll through once so lazy content loads, then back to the top
  await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } window.scrollTo(0, 0); });
  await page.waitForTimeout(800);
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage: true });
  manifest[key] = { url, status, height, errors: [...new Set(errs)].slice(0, 8) };
  console.log((status || '???') + ' ' + key + ' h=' + height + (errs.length ? '  errors=' + errs.length : ''));
  await ctx.close();
}

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT), '--bind', '127.0.0.1'], { cwd: path.join(__dirname, '..', 'design-handoff'), stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1200));
  const browser = await chromium.launch();
  const manifest = {};
  try {
    for (const [tab, pages] of Object.entries(PAGES)) {
      for (const [slug, live, design] of pages) {
        if (ONLY.length && !ONLY.includes(slug) && !ONLY.includes(tab)) continue;
        await shoot(browser, BASE + live, path.join(OUT, tab, slug + '-live.png'), manifest, tab + '/' + slug + ' live');
        await shoot(browser, `http://127.0.0.1:${PORT}/${design}.html`, path.join(OUT, tab, slug + '-design.png'), manifest, tab + '/' + slug + ' design');
      }
    }
  } finally { await browser.close(); srv.kill(); }
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log('done ->', OUT);
})();
