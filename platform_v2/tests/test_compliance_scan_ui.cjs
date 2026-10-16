// node tests/test_compliance_scan_ui.cjs -- isolated production-function contract.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/security-network-app.js'), 'utf8');
const start = source.indexOf('async function runComplianceScan()');
const end = source.indexOf('function _buildRingSvg', start);
assert(start >= 0 && end > start);
const elements = {'compliance-scan-status': {style: {}}, 'comp-scan-btn': {}};
const context = vm.createContext({
    document: {getElementById: id => elements[id]},
    renderScoreCards() {}, renderFrameworks() {}, loadEvidenceStatus() {}, loadHardeningContent() {},
    _compScoreColor: () => 'green'
});
vm.runInContext('let _lastScanId="old"; let loads=[];' +
    'function loadComplianceResults(){loads.push("results")};' +
    'function loadComplianceScanHistory(){loads.push("history")};' + source.slice(start, end), context);
(async () => {
    for (const [ok, data, success] of [
        [true, {scan_id:'partial', status:'persistence_error', error:'Unsaved'}, false],
        [true, {status:'error', error:'No rule packs loaded'}, false],
        [false, {scan_id:'bad-http', status:'completed'}, false],
        [true, {scan_id:'saved', status:'completed', score:100, passed:1, failed:0}, true]
    ]) {
        context.fetch = async () => ({ok, json: async () => data});
        vm.runInContext('loads=[]', context);
        await context.runComplianceScan();
        assert.equal(vm.runInContext('_lastScanId', context), success ? 'saved' : null);
        assert.equal(vm.runInContext('loads.includes("results")', context), success);
        assert.equal(elements['comp-scan-btn'].disabled, false);
    }
    console.log('PASS: platform UI rejects partial/error/HTTP-failed scans and accepts persisted completion.');
})().catch(error => { console.error(error); process.exitCode = 1; });
