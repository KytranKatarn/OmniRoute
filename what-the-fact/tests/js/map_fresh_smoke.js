// Extracts freshLabel from map.html and checks it. Run: node tests/js/map_fresh_smoke.js
const fs = require('fs'), path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../../consumer/templates/map.html'), 'utf8');
const m = src.match(/function freshLabel[\s\S]*?\n  }\n/);
if (!m) { console.error('freshLabel not found'); process.exit(1); }
const freshLabel = new Function(m[0] + '; return freshLabel;')();
const now = Date.parse('2026-10-02T12:00:00Z'), min = 60000;
const eq = (a, b) => { if (a !== b) { console.error('FAIL', a, '!=', b); process.exit(1); } };
eq(freshLabel(now - 14 * min, now), 'Newest story 14 min ago');
eq(freshLabel(now - 5 * 60 * min, now), 'Newest story 5 h ago');
eq(freshLabel(now - 72 * 60 * min, now), 'Newest story 3 d ago');
eq(freshLabel(now + 5 * min, now), 'Newest story 0 min ago');   // clock skew never goes negative
eq(freshLabel(-Infinity, now), '');                              // no timestamps -> no label
console.log('ok map_fresh_smoke');
