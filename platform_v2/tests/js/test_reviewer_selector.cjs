// Exercise the real functions extracted from the template against a minimal DOM stub.
// Checks the Review-agent selector in the Repair Bay PR Review tab.
//
// The functions are EXTRACTED FROM THE TEMPLATE by name rather than reimplemented, so
// this tests the shipped source. A hand-copied duplicate would pass while the template
// regressed — which is the whole failure mode a UI test usually has.
//
// Requires node. Skipped by the pytest wrapper when node is absent.
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'templates', 'tools', 'repair_bay.html'), 'utf8');

// Pull out just the helpers we changed, so we test the shipped source, not a copy.
function grab(name) {
  const i = html.indexOf('function ' + name);
  if (i < 0) throw new Error('missing ' + name);
  let depth = 0, started = false;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') { depth++; started = true; }
    else if (html[j] === '}') { depth--; if (started && depth === 0) return html.slice(i, j+1); }
  }
}

let created = 0;
function mkEl(tag) {
  created++;
  const el = {
    tagName: tag, children: [], attrs: {}, style: {cssText:''}, _text: '', value: '',
    set textContent(v) { this._text = String(v); }, get textContent() { return this._text; },
    setAttribute(k,v){ this.attrs[k]=v; },
    appendChild(c){ this.children.push(c); return c; },
    querySelector(sel){
      const want = sel.replace(/^select\[|\]$/g,'');
      const walk = n => { for (const c of n.children||[]) {
        if (c.tagName === 'select' && (!want || c.attrs[want] !== undefined)) return c;
        const r = walk(c); if (r) return r; } return null; };
      return walk(this);
    },
  };
  return el;
}
global.document = { createElement: mkEl };

const PR_REVIEWERS = ['F.O.R.G.E.','P.R.O.B.E.'];
let sel = null;
const code = grab('_prReviewerSelect') + '\n' + grab('_prSelectedReviewer');
eval(code);

const fails = [];
function check(n, got, want){ const ok = got===want; console.log(`  ${ok?'ok  ':'FAIL'} ${n}: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`); if(!ok) fails.push(n); }

sel = _prReviewerSelect();
check('selector has both reviewers', sel.children.map(o=>o.value).join(','), 'F.O.R.G.E.,P.R.O.B.E.');
check('default value set on select', sel.value, 'F.O.R.G.E.');
check('no CODEX option', sel.children.some(o=>o.value.indexOf('CODEX')>=0), false);

const row = mkEl('div'); sel.setAttribute('data-pr-reviewer','1'); row.appendChild(sel);
check('reads selected reviewer', _prSelectedReviewer(row), 'F.O.R.G.E.');
sel.value = 'P.R.O.B.E.';
check('reads changed reviewer', _prSelectedReviewer(row), 'P.R.O.B.E.');

const other = mkEl('div'); const sel2 = _prReviewerSelect(); sel2.setAttribute('data-pr-reviewer','1'); other.appendChild(sel2);
sel2.value = 'F.O.R.G.E.';
check('row A choice not read for row B', _prSelectedReviewer(other), 'F.O.R.G.E.');

const empty = mkEl('div');
check('no selector -> empty (server default)', _prSelectedReviewer(empty), '');

console.log('  FAILURES:', fails.length ? fails.join(', ') : 'none');
process.exit(fails.length ? 1 : 0);
