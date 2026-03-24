/**
 * Compliance Scanning Engine — Integration Test
 * ================================================
 * Tests: pack loading, scan trigger, score retrieval, DB persistence.
 * Run: cd platform_v2/tests && node test-compliance-scan.mjs
 */

import { chromium } from 'playwright';

const BASE = 'http://192.168.1.200:3000';
const API = `${BASE}/tools/security-network/api/compliance`;

let browser, page;
let passed = 0, failed = 0;

function assert(label, condition, detail = '') {
  if (condition) {
    console.log(`  ✓ ${label}`);
    passed++;
  } else {
    console.log(`  ✗ ${label} ${detail}`);
    failed++;
  }
}

async function setup() {
  browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  page = await ctx.newPage();

  // Login
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('#username', 'admin');
  await page.fill('#password', 'Kyt$13ran2025');
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });
  console.log('Logged in as admin\n');
}

async function testPacks() {
  console.log('=== Test 1: List Rule Packs ===');
  const resp = await page.request.get(`${API}/packs`);
  assert('GET /packs returns 200', resp.status() === 200);

  const body = await resp.json();
  assert('Response has packs array', Array.isArray(body.packs), JSON.stringify(Object.keys(body)));
  assert('3 packs loaded', body.packs?.length === 3, `got ${body.packs?.length}`);

  if (body.packs?.length) {
    const ids = body.packs.map(p => p.pack_id).sort();
    assert('Docker STIG present', ids.includes('docker-stig'));
    assert('Network STIG present', ids.includes('network-stig'));
    assert('Ubuntu STIG present', ids.includes('ubuntu-22.04-stig'));

    const totalRules = body.packs.reduce((s, p) => s + (p.total_rules || 0), 0);
    assert('108 total rules', totalRules === 108, `got ${totalRules}`);
  }
  console.log('');
}

async function testScan() {
  console.log('=== Test 2: Trigger Compliance Scan ===');
  const resp = await page.request.post(`${API}/scan`, {
    data: {},
    headers: { 'Content-Type': 'application/json' },
    timeout: 120000,  // scans may take a while
  });
  assert('POST /scan returns 200', resp.status() === 200, `got ${resp.status()}`);

  const body = await resp.json();
  console.log(`  Scan ID: ${body.scan_id || 'N/A'}`);
  console.log(`  Total: ${body.total_rules}, Pass: ${body.passed}, Fail: ${body.failed}, Error: ${body.errors}, N/A: ${body.not_applicable}, Manual: ${body.manual}`);
  console.log(`  Score: ${body.score}%`);

  assert('Has scan_id', !!body.scan_id);
  assert('total_rules > 0', (body.total_rules || 0) > 0, `got ${body.total_rules}`);
  assert('Score is a number', typeof body.score === 'number');
  assert('passed + failed + errors + n/a + manual = total',
    (body.passed || 0) + (body.failed || 0) + (body.errors || 0) + (body.not_applicable || 0) + (body.manual || 0) === (body.total_rules || 0),
    `${body.passed}+${body.failed}+${body.errors}+${body.not_applicable}+${body.manual} != ${body.total_rules}`
  );

  return body.scan_id;
}

async function testScores() {
  console.log('\n=== Test 3: Get Compliance Scores ===');
  const resp = await page.request.get(`${API}/scores`);
  assert('GET /scores returns 200', resp.status() === 200);

  const body = await resp.json();
  assert('Has overall_score', typeof body.overall_score === 'number', JSON.stringify(body).slice(0, 200));
  assert('Has pack_scores', body.pack_scores !== undefined);
  console.log(`  Overall score: ${body.overall_score}%`);
  if (body.pack_scores) {
    for (const [k, v] of Object.entries(body.pack_scores)) {
      console.log(`  ${k}: ${v}%`);
    }
  }
  console.log('');
}

async function testResults(scanId) {
  if (!scanId) {
    console.log('\n=== Test 4: Skipped (no scan_id) ===\n');
    return;
  }
  console.log('=== Test 4: Get Scan Results ===');
  const resp = await page.request.get(`${API}/results/${scanId}`);
  assert('GET /results/:id returns 200', resp.status() === 200, `got ${resp.status()}`);

  const body = await resp.json();
  assert('Has results array', Array.isArray(body.results), JSON.stringify(Object.keys(body)));
  if (body.results?.length) {
    assert('Results have rule_id', !!body.results[0].rule_id);
    assert('Results have status', !!body.results[0].status);
    assert('Results have severity', !!body.results[0].severity);

    // Count by status
    const counts = {};
    body.results.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
    console.log(`  Result breakdown: ${JSON.stringify(counts)}`);
  }
  console.log('');
}

async function testReload() {
  console.log('=== Test 5: Reload Packs ===');
  const resp = await page.request.post(`${API}/packs/reload`, {
    headers: { 'Content-Type': 'application/json' },
  });
  assert('POST /packs/reload returns 200', resp.status() === 200, `got ${resp.status()}`);

  const body = await resp.json();
  assert('Reload returned results', Array.isArray(body.results), JSON.stringify(Object.keys(body)));
  console.log('');
}

// Main
try {
  await setup();
  await testPacks();
  const scanId = await testScan();
  await testScores();
  await testResults(scanId);
  await testReload();
} catch (err) {
  console.error('FATAL:', err.message);
  failed++;
} finally {
  if (browser) await browser.close();
}

console.log(`\n${'='.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(40)}`);
process.exit(failed > 0 ? 1 : 0);
