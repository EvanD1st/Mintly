const form = document.getElementById('pair-form');
const button = document.getElementById('connect');
const status = document.getElementById('status');

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
    const provider = window.ethereum;
    if (!provider || !provider.isMetaMask) throw new Error('Open this page in the browser with your MetaMask extension.');
    const code = document.getElementById('code').value.trim();
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
    status.textContent = error.message || 'Wallet connection failed.';
  } finally {
    button.disabled = false;
  }
});
