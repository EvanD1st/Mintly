const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../app/web/authorize-mint.js'), 'utf8');
const address = '0x1111111111111111111111111111111111111111';
const code = 'a'.repeat(32);

function page(payload, responseOk = true) {
  const elements = {};
  for (const id of ['status', 'approve', 'review', 'review-form', 'code']) {
    elements[id] = {
      value: code, disabled: id === 'approve', textContent: '', handlers: {},
      addEventListener(event, callback) { this.handlers[event] = callback; },
    };
  }
  const requests = [];
  const posts = [];
  vm.runInNewContext(source, {
    document: { getElementById: id => elements[id] },
    window: {
      addEventListener() {}, dispatchEvent() {},
      ethereum: {
        isMetaMask: true,
        async request(request) {
          requests.push(request);
          if (request.method === 'eth_requestAccounts') return [address];
          if (request.method === 'wallet_switchEthereumChain') return null;
          if (request.method === 'eth_sendTransaction') return '0x' + 'f'.repeat(64);
          throw new Error('External signature requests cannot sign delegations for internal accounts.');
        },
      },
    },
    Event: class Event {}, setTimeout,
    async fetch(path, options) {
      posts.push({ path, body: JSON.parse(options.body) });
      return { ok: responseOk, async json() { return payload; } };
    },
  });
  return {
    elements, requests, posts,
    review: () => elements['review-form'].handlers.submit({ preventDefault() {} }),
    approve: () => elements.approve.handlers.click(),
  };
}

test('a mint challenge cannot request a blocked delegation or user-operation signature', async () => {
  const ui = page({
    chain_id: 4663, wallet_address: address, gas_mode: 'direct_wallet',
    typed_data: { primaryType: 'Delegation' },
  });
  await ui.review();
  await ui.approve();
  assert.equal(ui.elements.approve.disabled, true);
  assert.match(ui.elements.review.textContent, /Scheduled signing is unavailable/);
  assert.match(ui.elements.status.textContent, /No automatic mint was armed/);
  assert.equal(ui.requests.length, 0);
  assert.deepEqual(ui.posts, [{ path: '/api/mint-permission-link/challenge', body: { code } }]);
});

test('a production rejection stays disabled and explains the limitation', async () => {
  const ui = page({ detail: 'Scheduled mint approval is unavailable with the current MetaMask integration.' }, false);
  await ui.review();
  await ui.approve();
  assert.equal(ui.elements.approve.disabled, true);
  assert.match(ui.elements.status.textContent, /Scheduled mint approval is unavailable/);
  assert.equal(ui.requests.length, 0);
});

test('existing revocation still asks for the exact transaction, never a raw signature', async () => {
  const transaction = { to: '0x2222222222222222222222222222222222222222', data: '0x1234', value: '0x0' };
  const ui = page({ mode: 'revoke', chain_id: 4663, wallet_address: address, collection: 'Existing plan', transaction });
  await ui.review();
  assert.equal(ui.elements.approve.disabled, false);
  await ui.approve();
  assert.deepEqual(ui.requests.map(r => r.method), ['eth_requestAccounts', 'wallet_switchEthereumChain', 'eth_sendTransaction']);
  assert.equal(ui.requests[2].params[0].from, address);
  assert.equal(ui.requests[2].params[0].to, transaction.to);
  assert.equal(ui.requests[2].params[0].data, transaction.data);
  assert.equal(ui.requests[2].params[0].value, '0x0');
  assert.match(ui.elements.status.textContent, /Revocation submitted/);
  assert.equal(ui.posts.length, 1);
});
