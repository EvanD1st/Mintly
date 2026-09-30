const form = document.getElementById('pair-form');
const button = document.getElementById('connect');
const status = document.getElementById('status');
const discovered = [];

window.addEventListener('eip6963:announceProvider', (event) => {
  const detail = event.detail;
  if (detail?.info?.rdns === 'io.metamask' && detail.provider?.request) {
    discovered.push(detail.provider);
  }
});
window.dispatchEvent(new Event('eip6963:requestProvider'));

async function metaMaskProvider() {
  window.dispatchEvent(new Event('eip6963:requestProvider'));
  await new Promise(resolve => setTimeout(resolve, 300));
  if (discovered.length) return discovered[0];
  const legacy = window.ethereum?.providers?.find(provider => provider.isMetaMask)
    || (window.ethereum?.isMetaMask ? window.ethereum : null);
  if (!legacy?.request) throw new Error('MetaMask was not found in this Chrome tab. Enable the extension for this site, unlock it, and reload.');
  return legacy;
}

async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body), cache: 'no-store', credentials: 'omit'
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || `Request failed (${response.status})`);
  return result;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = 'Waiting for MetaMask…';
  try {
    const code = document.getElementById('code').value.trim();
    if (!/^[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}$/i.test(code)) {
      throw new Error('Enter the current one-time code shown in the Mintly app.');
    }
    const provider = await metaMaskProvider();
    const accounts = await provider.request({method: 'eth_requestAccounts'});
    const address = accounts[0];
    if (!address) throw new Error('Select an account in MetaMask.');
    const challenge = await post('/api/wallet-link/challenge', {code, address});
    const messageHex = '0x' + [...new TextEncoder().encode(challenge.message)]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    status.textContent = 'Review the message in MetaMask. It does not authorize a transaction.';
    const signature = await provider.request({method: 'personal_sign', params: [messageHex, address]});
    const result = await post('/api/wallet-link/complete', {code, address, signature});
    status.textContent = `Connected ${result.address}. Return to the Mintly app.`;
    form.reset();
  } catch (error) {
    const message = String(error?.message || 'Wallet connection failed.');
    if (/broadcast channel unavailable/i.test(message)) {
      status.textContent = 'MetaMask did not respond in this Chrome tab. Unlock MetaMask, ensure this site can access the extension, then reload this page and try a fresh code. If another wallet extension is active, select MetaMask for this site.';
    } else if (error?.code === 4001) {
      status.textContent = 'The MetaMask request was declined. No wallet was linked.';
    } else {
      status.textContent = message;
    }
  } finally {
    button.disabled = false;
  }
});
