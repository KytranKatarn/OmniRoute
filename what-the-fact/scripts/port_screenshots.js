#!/usr/bin/env node
/**
 * Claude Design port review: every design page, LIVE vs DESIGN, same viewport(s), full page, PLUS objective layout
 * measurements, written to a manifest and a REPORT.md.  Pixel-diffing is deliberately NOT the verdict: the live pages
 * carry real, changing data and the mockups carry sample data, so only STRUCTURE is comparable (header alignment, fonts,
 * container width, horizontal overflow, headings present, broken images, failed requests).
 *
 *   cd what-the-fact && node scripts/port_screenshots.js --check                       # is the rig configured and capturing correctly?
 *   cd what-the-fact && node scripts/port_screenshots.js [--base https://what-the-fact.com] [--out design-handoff/shots]
 *                                                        [--widths 1280,390] [--only mps,elections  (re-checks just those and MERGES into the existing manifest)] [--report-only] [--cookie "name=value"]
 *
 * Needs `playwright` + chromium, python3 (static server over design-handoff/), an EMOJI FONT (fonts-noto-color-emoji; without one
 * every emoji is a tofu box in every shot), and internet (the design files load fonts, d3 and map data from CDNs; live needs the site).
 * Output: <out>/<tab>/<slug>-live[-<w>].png, <slug>-design[-<w>].png, <out>/manifest.json, <out>/REPORT.md.
 * Public pages only; pass --cookie to capture a signed-in/subscriber state.
 */
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('child_process');
const http = require('http');
const fs = require('fs'), path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > -1 ? process.argv[i + 1] : d; };
const flag = (k) => process.argv.includes('--' + k);
const BASE = arg('base', 'https://what-the-fact.com').replace(/\/$/, '');
const OUT = arg('out', 'design-handoff/shots');
const WIDTHS = (arg('widths', '1280') || '1280').split(',').map(Number).filter(Boolean);
const ONLY = (arg('only', '') || '').split(',').filter(Boolean);
const COOKIE = arg('cookie', '');
const PORT = 8799;
const DESIGN_DIR = path.join(__dirname, '..', 'design-handoff');
const STATIC_DIR = path.join(__dirname, '..', 'consumer', 'static');

// tab -> [slug, live path, design file]  (mirrors the nav in consumer/templates/base.html)
const PAGES = {
  news: [['home', '/', 'wtf-home'], ['news', '/news', 'wtf-news'], ['archive', '/archive', 'wtf-archive'], ['activity', '/activity', 'wtf-activity'],
         ['weather', '/weather', 'wtf-weather'], ['blindspot', '/blindspot', 'wtf-blindspot'],
         ['divergence', '/divergence', 'wtf-divergence'], ['clusters', '/clusters', 'wtf-clusters']],
  politics: [['parties', '/parties', 'wtf-parties'], ['platforms', '/platforms', 'wtf-platforms'], ['mps', '/mps', 'wtf-mps'],
             ['municipal', '/municipal', 'wtf-municipal'], ['lobbying', '/lobbying', 'wtf-lobbying'], ['gic', '/gic', 'wtf-gic'],
             ['ethics', '/ethics', 'wtf-ethics'], ['officers', '/parliament/officers', 'wtf-officers']],
  elections: [['elections', '/elections', 'wtf-elections'], ['races', '/races', 'wtf-races'], ['ridings', '/ridings', 'wtf-ridings']],
  money: [['economy', '/economy', 'wtf-economy'], ['rates', '/rates', 'wtf-rates'], ['cost', '/cost', 'wtf-cost'],
          ['global', '/global', 'wtf-global'], ['debt', '/debt', 'wtf-debt'], ['markets', '/markets', 'wtf-markets']],
  media: [['sources', '/sources', 'wtf-sources'], ['owners', '/owners', 'wtf-owners'], ['journalists', '/journalists', 'wtf-journalists'],
          ['crtc', '/crtc', 'wtf-crtc'], ['echo', '/echo', 'wtf-echo']],
  data: [['map', '/map', 'wtf-map'], ['chain', '/chain', 'wtf-chain'], ['cross-watch', '/cross-watch', 'wtf-cross-watch'],
         ['claims', '/claims', 'wtf-claims'], ['api', '/api/docs', 'wtf-api'], ['edu', '/edu', 'wtf-edu'], ['search', '/search', 'wtf-search'],
         ['accuracy', '/weather/accuracy', 'wtf-accuracy']],
  about: [['methodology', '/methodology', 'wtf-methodology'], ['team', '/team', 'wtf-team'], ['governance', '/governance', 'wtf-governance'],
          ['creed', '/creed', 'wtf-creed'], ['literacy', '/literacy', 'wtf-literacy'], ['score', '/score', 'wtf-score']],
  // Pages whose live URL has an id/slug: resolved by taking the first matching link off a list page.  [slug, list page, link prefix, design file]
  dynamic: [['article', '/news', '/article/', 'wtf-article'], ['outlet', '/sources', '/source/', 'wtf-outlet'],
            ['mp', '/mps', '/mp/', 'wtf-mp'], ['senator', '/mps', '/senator/', 'wtf-senator'],
            ['city', '/weather', '/weather/city/', 'wtf-city']],
  // The 404 design is compared with a URL that must NOT exist (status 404 is the EXPECTED result).
  errors: [['404', '/this-page-does-not-exist-port-check', 'wtf-404']],
};

const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();

/** Runs in the page: structural measurements that stay comparable even though live and design carry different DATA. */
function measure() {
  const vw = window.innerWidth;
  const cs = (el) => getComputedStyle(el);
  const first = (sel) => document.querySelector(sel);
  const h1 = first('h1');
  let h1m = null;
  if (h1) {
    const r = h1.getBoundingClientRect(), c = cs(h1);
    // Where the TEXT sits, not the box: a full-width block's box is always page-centred, so a box check cannot see a left-aligned title (the
    // first version of this rig under-reported exactly that). lineOffset = first text line's centre minus the heading box's centre;
    // slack = how much narrower than the box that line is (a line that fills the box is aligned either way and cannot be told apart).
    const range = document.createRange(); range.selectNodeContents(h1);
    // The FIRST LINE is the union of every rect on the first text row: an inline icon/emoji at the start of the heading is its own rect, and
    // taking only rects[0] measured the icon instead of the line (municipal and economy read 250px off while visibly centred).
    const rects = [...range.getClientRects()].filter(x => x.width > 0);
    const top0 = rects.length ? rects[0].top : r.top;
    const row = rects.filter(x => Math.abs(x.top - top0) < Math.max(6, (rects[0] || r).height * 0.5));
    const lineL = row.length ? Math.min(...row.map(x => x.left)) : r.left, lineR = row.length ? Math.max(...row.map(x => x.right)) : r.right;
    const line = { left: lineL, width: lineR - lineL };
    h1m = { text: (h1.textContent || '').trim().slice(0, 90), font: (c.fontFamily || '').split(',')[0].replace(/["']/g, '').trim(),
            size: c.fontSize, align: c.textAlign, left: Math.round(r.left), centreOffset: Math.round(Math.abs(r.left + r.width / 2 - vw / 2)),
            lineOffset: Math.round(Math.abs(line.left + line.width / 2 - (r.left + r.width / 2))), slack: Math.round(r.width - line.width) };
  }
  const main = first('main') || first('[role=main]') || document.body;
  const mr = main.getBoundingClientRect();
  const imgs = [...document.images];
  const brokenImgs = imgs.filter(i => i.complete && i.naturalWidth === 0 && i.getAttribute('src'));
  const label = (e) => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}`;
  const clipped = (e) => { for (let a = e.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
    const o = getComputedStyle(a).overflowX; if (o !== 'visible' && a.getBoundingClientRect().right <= vw + 1) return true; } return false; };
  const overflow = document.documentElement.scrollWidth - vw;
  const overflowCulprits = overflow > 1 ? [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 && getComputedStyle(e).position !== 'fixed' && !clipped(e); })
    .sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right).slice(0, 3).map(e => `${label(e)} right=${Math.round(e.getBoundingClientRect().right)}`) : [];
  // Only RENDERED bars: elements in a hidden tab / collapsed panel always measure 0 (a first version counted them: 29 false "empty bars" on /mps).
  // An explicit inline width of 0 is data (a real 0%), not the inline-element bug that renders every fill empty.
  const bars = [...document.querySelectorAll('[class*="bar-fill"]')].filter(e => e.getClientRects().length > 0 && !/width:\s*0(\.0+)?(%|px)?\s*(;|$)/.test(e.getAttribute('style') || ''));
  const barsTotal = bars.length, emptyBars = bars.filter(e => e.getBoundingClientRect().width === 0).length;
  const text = document.body ? document.body.innerText : '';
  return {
    title: document.title.slice(0, 90),
    overflowX: overflow, overflowCulprits,
    bodyFont: (cs(document.body).fontFamily || '').split(',')[0].replace(/["']/g, '').trim(),
    h1: h1m,
    mainWidth: Math.round(mr.width), mainLeft: Math.round(mr.left),
    h2: [...document.querySelectorAll('h2')].map(e => (e.textContent || '').trim().slice(0, 70)).filter(Boolean).slice(0, 40),
    brokenImages: brokenImgs.length, brokenImageSrcs: brokenImgs.slice(0, 3).map(i => `${i.loading === 'lazy' ? '[lazy] ' : ''}${i.getAttribute('src').slice(0, 90)}`),
    emptyBars, barsTotal,
    emojiCount: (text.match(/\p{Extended_Pictographic}/gu) || []).length,
    textChars: text.length,
    fontsLoaded: [...document.fonts].filter(f => f.status === 'loaded').length,
    fontsFailed: [...document.fonts].filter(f => f.status === 'error').map(f => f.family).slice(0, 5),
  };
}


const isFile = (f) => { try { return fs.statSync(f).isFile(); } catch (_) { return false; } };
/**
 * The mockups reference assets the LIVE app serves from consumer/static (the province GeoJSON, the i18n table...) that do not sit in
 * design-handoff/.  Served as-is they 404, the mockup's map never renders, and "map missing on live" would be a false finding.  For
 * design-page requests only: if the file is not in design-handoff/, fall back to consumer/static (path as-is, or minus a /static prefix).
 */
function staticFallback(urlPath) {
  const p = decodeURIComponent(urlPath.split('?')[0]);
  const inDesign = path.join(DESIGN_DIR, p);
  if (inDesign.startsWith(DESIGN_DIR) && isFile(inDesign)) return null;
  for (const c of [path.join(STATIC_DIR, p), path.join(STATIC_DIR, p.replace(/^\/static\//, ''))]) {
    if (c.startsWith(STATIC_DIR) && isFile(c)) return c;
  }
  return null;
}

const HIDE_MOTION = '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}';

async function newCtx(browser, width, url) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, locale: 'en-CA', timezoneId: 'America/Toronto', reducedMotion: 'reduce', deviceScaleFactor: 1 });
  if (COOKIE && url.startsWith(BASE)) { const [n, ...v] = COOKIE.split('='); await ctx.addCookies([{ name: n, value: v.join('='), url: BASE }]); }
  return ctx;
}

async function shoot(browser, url, file, width, manifest, key, expectStatus = 200) {
  const ctx = await newCtx(browser, width, url);
  const served = [];
  if (url.startsWith(`http://127.0.0.1:${PORT}`)) {
    await ctx.route(new RegExp('^http://127\\.0\\.0\\.1:' + PORT + '/'), route => {
      const f = staticFallback(new URL(route.request().url()).pathname);
      if (!f) return route.continue();
      served.push(path.relative(STATIC_DIR, f));
      return route.fulfill({ path: f, contentType: /\.(geo)?json$/.test(f) ? 'application/json' : undefined });
    });
  }
  const page = await ctx.newPage();
  const errs = [], failed = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 140)); });
  page.on('pageerror', e => errs.push('PAGEERROR ' + String(e).slice(0, 140)));
  // failed requests WITH their URL: a bare "404" console line says nothing about which asset is missing.
  page.on('response', r => { if (r.status() >= 400 && r.url() !== url) failed.push(`${r.status()} ${r.url().slice(0, 110)}`); });
  page.on('requestfailed', r => failed.push(`FAIL ${(r.failure() || {}).errorText || ''} ${r.url().slice(0, 110)}`));
  let status = null;
  try {
    const r = await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
    status = r ? r.status() : null;
  } catch (e) { errs.push('GOTO ' + e.message.slice(0, 120)); try { status = status || 0; } catch (_) {} }
  await page.addStyleTag({ content: HIDE_MOTION }).catch(() => {});
  await page.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});   // wait for fonts, not a fixed guess
  await page.waitForTimeout(1500);                                                      // client-rendered feeds / maps
  await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 100)); } window.scrollTo(0, 0); }).catch(() => {});
  await page.waitForTimeout(600);
  let m = {};
  try { m = await page.evaluate(measure); } catch (e) { errs.push('MEASURE ' + e.message.slice(0, 80)); }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' }).catch(e => errs.push('SHOT ' + e.message.slice(0, 80)));
  const height = await page.evaluate(() => document.documentElement.scrollHeight).catch(() => 0);
  manifest[key] = { url, width, status, expectStatus, height, errors: [...new Set(errs)].slice(0, 8), failedRequests: [...new Set(failed)].slice(0, 10), servedFromLiveStatic: [...new Set(served)], ...m };
  console.log(`${status || '???'} ${key} w=${width} h=${height}${errs.length ? ' errors=' + errs.length : ''}${failed.length ? ' failed=' + failed.length : ''}`);
  await ctx.close();
}

/** First link on `listPath` whose href starts with `prefix` (then +1 path segment). */
async function resolveLink(browser, listPath, prefix) {
  const ctx = await newCtx(browser, 1280, BASE);
  const page = await ctx.newPage();
  try {
    await page.goto(BASE + listPath, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);
    return await page.evaluate((p) => { const a = [...document.querySelectorAll('a[href]')].map(x => x.getAttribute('href')).find(h => h && h.startsWith(p) && h.length > p.length); return a || null; }, prefix);
  } catch (e) { return null; } finally { await ctx.close(); }
}

function startServer() {
  return new Promise((resolve, reject) => {
    const get = http.get({ host: '127.0.0.1', port: PORT, path: '/wtf-home.html', timeout: 1500 }, res => { res.resume();
      reject(new Error(`port ${PORT} is already serving something: refusing to screenshot an unknown directory (kill it and retry)`)); });
    get.on('error', () => {   // nothing listening: good, start ours
      const srv = spawn('python3', ['-m', 'http.server', String(PORT), '--bind', '127.0.0.1'], { cwd: DESIGN_DIR, stdio: 'ignore' });
      setTimeout(() => http.get({ host: '127.0.0.1', port: PORT, path: '/wtf-home.html' }, res => {
        let b = ''; res.on('data', d => b += d); res.on('end', () => (res.statusCode === 200 && /WTF|What The Fact/i.test(b))
          ? resolve(srv) : (srv.kill(), reject(new Error('design server did not serve wtf-home.html'))));
      }).on('error', e => (srv.kill(), reject(e))), 1200);
    });
    get.on('timeout', () => get.destroy());
  });
}

/** The rig's own self-test: is it configured and capturing correctly?  Prints a PASS/FAIL checklist. */
async function selfCheck(browser) {
  const rows = [];
  const add = (name, ok, detail = '') => rows.push([ok ? 'PASS' : 'FAIL', name, detail]);
  let emojiFonts = 0;
  try { emojiFonts = execFileSync('fc-list', { encoding: 'utf8' }).split('\n').filter(l => /emoji/i.test(l)).length; } catch (_) {}
  add('emoji font installed (fc-list)', emojiFonts > 0, `${emojiFonts} found; without one every emoji is a tofu box`);
  const ctx = await browser.newContext({ viewport: { width: 400, height: 300 } });
  const page = await ctx.newPage();
  await page.setContent('<canvas id=c width=60 height=60></canvas>');
  const colour = await page.evaluate(() => {
    const c = document.getElementById('c').getContext('2d'); c.font = '40px sans-serif'; c.fillText('\u{1F600}', 4, 44);
    const d = c.getImageData(0, 0, 60, 60).data; let sat = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200 && Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]) > 60) sat++;
    return sat;
  });
  add('chromium actually RENDERS colour emoji', colour > 50, `${colour} saturated glyph pixels (a tofu box is monochrome)`);
  // The detector must catch the defect class it claims to: an inline <span> bar fill ignores its width (every bar renders empty, #3803),
  // while a bar in a hidden panel and an explicit 0% are NOT defects.
  await page.setContent(`<div style="width:300px"><div class=track style="height:10px"><span class="wtf-a-bar-fill" style="width:50%"></span></div>
    <div class=track style="height:10px"><div class="wtf-a-bar-fill ok" style="width:40%;height:10px"></div></div>
    <div style="display:none"><div class="wtf-a-bar-fill" style="width:30%"></div></div>
    <div class=track style="height:10px"><div class="wtf-a-bar-fill zero" style="width:0%;height:10px"></div></div></div>`);
  const probe = await page.evaluate(measure);
  add('bar detector: catches an inline-span fill, ignores a hidden bar and an explicit 0%', probe.barsTotal === 2 && probe.emptyBars === 1, `rendered=${probe.barsTotal} empty=${probe.emptyBars} (want 2 and 1)`);
  await ctx.close();
  let srv;
  try { srv = await startServer(); add('design server on :' + PORT + ' serves design-handoff/', true); } catch (e) { add('design server', false, e.message); }
  const m = {};
  if (srv) {
    try {
      await shoot(browser, BASE + '/', path.join(OUT, '_check', 'live.png'), 1280, m, 'live');
      await shoot(browser, `http://127.0.0.1:${PORT}/wtf-home.html`, path.join(OUT, '_check', 'design.png'), 1280, m, 'design');
    } finally { srv.kill(); }
    for (const k of ['live', 'design']) {
      const r = m[k] || {};
      add(`${k}: HTTP 200`, r.status === 200, String(r.status));
      add(`${k}: has a heading and real content`, !!((r.h1 && r.h1.text) || (r.h2 || []).length) && r.textChars > 500, `${r.h1 ? 'h1 "' + r.h1.text + '"' : 'no h1'}, ${(r.h2 || []).length} h2, ${r.textChars} chars`);
      add(`${k}: web fonts loaded, none failed`, (r.fontsLoaded || 0) > 0 && !(r.fontsFailed || []).length, `${r.fontsLoaded} loaded, failed=[${(r.fontsFailed || []).join(',')}]`);
      add(`${k}: no horizontal overflow at 1280`, (r.overflowX || 0) <= 1, `${r.overflowX}px`);
      add(`${k}: screenshot written`, fs.existsSync(path.join(OUT, '_check', k + '.png')) && fs.statSync(path.join(OUT, '_check', k + '.png')).size > 20000);
      add(`${k}: no failed requests`, !(r.failedRequests || []).length, (r.failedRequests || []).join(' | ') || `none${(r.servedFromLiveStatic || []).length ? ' (served from consumer/static: ' + r.servedFromLiveStatic.join(', ') + ')' : ''}`);
    }
  }
  console.log('\nRIG CHECK');
  for (const [s, n, d] of rows) console.log(`  ${s}  ${n}${d ? '  -  ' + d : ''}`);
  const bad = rows.filter(r => r[0] === 'FAIL').length;
  console.log(bad ? `\n${bad} FAILED: fix before trusting any screenshot` : '\nall checks passed');
  return bad;
}

function report(manifest, unresolved, uncovered) {
  const L = [];
  const pairs = {};
  for (const [k, v] of Object.entries(manifest)) { const m = k.match(/^(.*) (live|design) (\d+)$/); if (m) { (pairs[`${m[1]} ${m[3]}`] ||= {})[m[2]] = v; } }
  L.push('# Design port review: live vs mockup', '', `Generated by \`scripts/port_screenshots.js\` against ${BASE}. Structure is compared, not pixels: live carries real data, mockups carry sample data.`, '');
  const rows = [], issues = { overflow: 0, headerAlign: 0, font: 0, missingHeadings: 0, broken: 0, failed: 0, status: 0 };
  for (const [key, p] of Object.entries(pairs).sort()) {
    const lv = p.live || {}, dg = p.design || {};
    const notes = [];
    const exp = lv.expectStatus || 200;
    if (lv.status !== exp) { notes.push(`live HTTP ${lv.status} (expected ${exp})`); issues.status++; }
    if ((lv.overflowX || 0) > 1) { notes.push(`live overflows ${lv.overflowX}px${(lv.overflowCulprits || []).length ? ' (' + lv.overflowCulprits.join(', ') + ')' : ''}`); issues.overflow++; }
    if (lv.h1 && dg.h1) {
      // A title is "centred" when its text-align is center, or its first line sits at the box centre; a line that fills the box (slack <= 48px) is indistinguishable and is not flagged.
      const centred = (h) => h.align === 'center' || h.lineOffset <= 8;
      const dCentred = centred(dg.h1), lCentred = centred(lv.h1);
      if (dCentred !== lCentred && Math.min(dg.h1.slack, lv.h1.slack) > 48) { notes.push(`h1 ${dCentred ? 'centred in design, not live' : 'left in design, centred live'}`); issues.headerAlign++; }
      if (dg.h1.font && lv.h1.font && dg.h1.font !== lv.h1.font) { notes.push(`h1 font ${lv.h1.font} vs design ${dg.h1.font}`); issues.font++; }
    } else if (dg.h1 && !lv.h1) notes.push('live has no <h1>');
    const liveH = new Set((lv.h2 || []).map(norm));
    const missing = (dg.h2 || []).filter(h => { const n = norm(h); return n && ![...liveH].some(l => l.includes(n) || n.includes(l)); });
    if (missing.length) { notes.push(`${missing.length} design heading(s) not in live: ${missing.slice(0, 3).map(h => '"' + h + '"').join(', ')}${missing.length > 3 ? '…' : ''}`); issues.missingHeadings++; }
    if (lv.brokenImages) { notes.push(`${lv.brokenImages} broken image(s) live, e.g. ${(lv.brokenImageSrcs || []).slice(0, 2).join(' ; ')}`); issues.broken++; }
    if (lv.barsTotal >= 3 && lv.emptyBars === lv.barsTotal) { notes.push(`ALL ${lv.barsTotal} rendered bar fills are zero-width (the inline-element bug)`); issues.broken++; }
    else if (lv.emptyBars) notes.push(`${lv.emptyBars} of ${lv.barsTotal} rendered bars are zero-width (probably data; eyeball)`);
    // ERR_ABORTED = the page cancelled its own fetch (navigation, AbortController): a cancellation, not a failure (the creed score API it flagged answers 200).
    const lf = (lv.failedRequests || []).filter(x => !/favicon/i.test(x) && !/ERR_ABORTED/.test(x));
    if (lf.length) { notes.push(`live failed requests: ${lf.slice(0, 2).join(' ; ')}`); issues.failed++; }
    rows.push(`| ${key} | ${lv.status}/${dg.status} | ${lv.height}/${dg.height} | ${notes.join('; ') || 'ok'} |`);
  }
  L.push('## Summary', '', ...Object.entries(issues).map(([k, v]) => `- ${k}: ${v} page-width combination(s)`), '', `Pages compared: ${Object.keys(pairs).length} page/width pairs.`, '');
  L.push('## Per page', '', '| page width | HTTP live/design | height live/design | findings |', '|---|---|---|---|', ...rows, '');
  if (unresolved.length) L.push('## Dynamic pages that could not be resolved to a live URL', '', ...unresolved.map(u => `- ${u}`), '');
  if (uncovered.length) L.push('## Design files with NO page mapping', '', ...uncovered.map(u => `- ${u}`), '');
  const designFail = Object.entries(manifest).filter(([k, v]) => / design \d+$/.test(k) && ((v.failedRequests || []).length || (v.errors || []).length));
  if (designFail.length) {
    const by = {};
    for (const [, v] of designFail) for (const r of (v.failedRequests || [])) by[r] = (by[r] || 0) + 1;
    L.push('## Design-side failed requests (these distort the MOCKUP screenshots, not the live site)', '', ...Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([r, n]) => `- ${n}x ${r}`), '');
  }
  return L.join('\n');
}

function uncoveredDesignFiles() {
  const used = new Set(Object.values(PAGES).flat().map(p => p[p.length - 1]));
  return fs.readdirSync(DESIGN_DIR).filter(f => /^wtf-.*\.html$/.test(f)).map(f => f.replace('.html', '')).filter(f => !used.has(f));
}

(async () => {
  if (flag('report-only')) {   // regenerate REPORT.md from an existing manifest, no browser, no network
    const mf = path.join(OUT, 'manifest.json');
    fs.writeFileSync(path.join(OUT, 'REPORT.md'), report(JSON.parse(fs.readFileSync(mf, 'utf8')), [], uncoveredDesignFiles()));
    console.log('wrote', path.join(OUT, 'REPORT.md'));
    return;
  }
  const browser = await chromium.launch();
  if (flag('check')) { const bad = await selfCheck(browser); await browser.close(); process.exit(bad ? 1 : 0); }
  let srv;
  try { srv = await startServer(); } catch (e) { console.error('ABORT: ' + e.message); await browser.close(); process.exit(2); }
  const manifest = {}, unresolved = [];
  try {
    for (const [tab, pages] of Object.entries(PAGES)) {
      for (const p of pages) {
        const slug = p[0];
        if (ONLY.length && !ONLY.includes(slug) && !ONLY.includes(tab)) continue;
        let livePath, design, expect = 200;
        if (tab === 'dynamic') {
          const [, list, prefix, d] = p; design = d;
          const href = await resolveLink(browser, list, prefix);
          if (!href) { unresolved.push(`${slug}: no ${prefix}… link found on ${list}`); continue; }
          livePath = href;
        } else { livePath = p[1]; design = p[2]; if (tab === 'errors') expect = 404; }
        for (const w of WIDTHS) {
          const sfx = w === 1280 ? '' : '-' + w;
          await shoot(browser, BASE + livePath, path.join(OUT, tab, `${slug}-live${sfx}.png`), w, manifest, `${tab}/${slug} live ${w}`, expect);
          await shoot(browser, `http://127.0.0.1:${PORT}/${design}.html`, path.join(OUT, tab, `${slug}-design${sfx}.png`), w, manifest, `${tab}/${slug} design ${w}`);
        }
      }
    }
  } finally { await browser.close(); srv.kill(); }
  const uncovered = uncoveredDesignFiles();
  fs.mkdirSync(OUT, { recursive: true });
  const mf = path.join(OUT, 'manifest.json');
  const merged = ONLY.length && fs.existsSync(mf) ? Object.assign(JSON.parse(fs.readFileSync(mf, 'utf8')), manifest) : manifest;   // --only re-checks a subset without losing the rest
  fs.writeFileSync(mf, JSON.stringify(merged, null, 2));
  fs.writeFileSync(path.join(OUT, 'REPORT.md'), report(merged, unresolved, uncovered));
  console.log('done ->', OUT, '(manifest.json, REPORT.md)');
})();
