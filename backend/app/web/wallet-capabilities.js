'use strict';
// Read-only ERC-7715 compatibility diagnostic. Reports never activate a grant.
const wallets = new Map();
const selector = document.getElementById('wallet');
function addWallet(id, name, provider) {
  if (wallets.has(id)) return;
  wallets.set(id, provider);
  const option = document.createElement('option');
  option.value = id; option.textContent = name; selector.appendChild(option);
}
window.addEventListener('eip6963:announceProvider', event => {
  const { info, provider } = event.detail || {};
  if (info?.uuid && provider?.request) addWallet(info.uuid, `${info.name} (${info.rdns})`, provider);
});
window.dispatchEvent(new Event('eip6963:requestProvider'));
if (window.ethereum?.request) addWallet('injected', 'Injected wallet (identity unverified)', window.ethereum);
async function readCapability(provider, method, params) {
  try { return { result: await provider.request({ method, params: params ?? [] }) }; }
  catch (error) { return { error_code: error.code ?? null, error: String(error.message || 'Unavailable').slice(0, 300) }; }
}
document.getElementById('check').addEventListener('click', async () => {
  const button = document.getElementById('check');
  if (button.disabled) return;
  button.disabled = true;
  const status = document.getElementById('status');
  try {
    const provider = wallets.get(selector.value);
    if (!provider) throw new Error('No injected wallet found. Open this page in the browser where MetaMask is installed.');
    const accounts = await provider.request({ method: 'eth_requestAccounts' });
    const chain = await provider.request({ method: 'eth_chainId' });
    const report = {
      checked_at: new Date().toISOString(),
      platform: document.getElementById('platform').value,
      wallet_label: selector.selectedOptions[0].textContent,
      wallet_version_user_reported: document.getElementById('version').value || null,
      account: accounts[0] || null, chain_id: chain,
      execution_permissions: await readCapability(provider, 'wallet_getSupportedExecutionPermissions'),
      account_capabilities: accounts[0] ? await readCapability(provider, 'wallet_getCapabilities', [accounts[0]]) : null,
      // Client version can describe the RPC node, so never call it wallet version.
      rpc_client_version: await readCapability(provider, 'web3_clientVersion'),
      automatic_minting: 'unproven', permission_requested: false,
      reason: 'Capability discovery alone does not prove NFT-call authorization or backend redemption.'
    };
    document.getElementById('report').textContent = JSON.stringify(report, null, 2);
    status.textContent = 'Check complete. Share this public report with the developer; no mint was armed.';
  } catch (error) { status.textContent = String(error.message || 'Capability check failed.'); }
  finally { button.disabled = false; }
});
