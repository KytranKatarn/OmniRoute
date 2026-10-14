const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/consciousness.js'), 'utf8');
const match = source.match(/function _codeHealthYellowLabel\(moduleKey\) \{[\s\S]*?\n\}/);
assert.ok(match);
const context = {window: {_chModuleHealthDetails: {}}};
vm.createContext(context);
vm.runInContext(match[0], context);
const label = (details) => {
  context.window._chModuleHealthDetails.website_what_the_fact = details;
  return context._codeHealthYellowLabel('website_what_the_fact');
};
assert.equal(label({stale:false, last_audit_status:'findings_open'}), 'FINDINGS OPEN');
assert.equal(label({stale:true, last_audit_status:'findings_open'}), 'STALE');
assert.equal(label({}), 'ATTENTION');
for (const name of ['_renderModuleTable', '_renderStandaloneTable', '_renderWebsiteTable']) {
  const start = source.indexOf('function '+name+'(');
  const end = source.indexOf('\nfunction ', start+1);
  const body = source.slice(start, end === -1 ? undefined : end);
  assert.ok(body.includes('_codeHealthYellowLabel('), name+' must use the truthful label');
}
console.log('Code Health labels: fresh findings, stale audit, unknown status and all three tables PASS');
