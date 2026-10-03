const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

test('capability probe sends explicit empty params and never requests spending authority', async () => {
  const requests = [];
  const elements = Object.fromEntries(['wallet', 'platform', 'version', 'check', 'status', 'report'].map(id => [id, {
    value: id === 'platform' ? 'extension' : '', handlers: {}, selectedOptions: [],
    addEventListener(event, callback) { this.handlers[event] = callback; },
    appendChild(option) { this.value = option.value; this.selectedOptions = [option]; },
  }]));
  const provider = { async request(request) {
    requests.push(request);
    if (request.method === 'eth_requestAccounts') return ['0x' + '1'.repeat(40)];
    if (request.method === 'eth_chainId') return '0xaa36a7';
    assert.ok(Array.isArray(request.params));
    if (request.method === 'wallet_getSupportedExecutionPermissions') return { 'native-token-allowance': { chainIds: [11155111] } };
    return {};
  }};
  vm.runInNewContext(readFileSync(join(__dirname, '../app/web/wallet-capabilities.js'), 'utf8'), {
    document: { getElementById: id => elements[id], createElement: () => ({}) },
    window: { ethereum: provider, addEventListener() {}, dispatchEvent() {} }, Event: class {},
  });
  await elements.check.handlers.click();
  assert.deepEqual(requests.map(r => r.method), ['eth_requestAccounts', 'eth_chainId',
    'wallet_getSupportedExecutionPermissions', 'wallet_getCapabilities', 'web3_clientVersion']);
  assert.equal(requests[2].params.length, 0);
  const report = JSON.parse(elements.report.textContent);
  assert.equal(report.automatic_minting, 'unproven');
  assert.equal(report.permission_requested, false);
});
