const status = document.getElementById('status');
const approve = document.getElementById('approve');
let reviewed = null;
const discovered = [];
window.addEventListener('eip6963:announceProvider', event => {
  if (event.detail?.info?.rdns === 'io.metamask' && event.detail.provider?.request) discovered.push(event.detail.provider);
});
window.dispatchEvent(new Event('eip6963:requestProvider'));
async function provider() {
  window.dispatchEvent(new Event('eip6963:requestProvider'));
  await new Promise(resolve => setTimeout(resolve, 300));
  const result = discovered[0] || window.ethereum?.providers?.find(p => p.isMetaMask) || (window.ethereum?.isMetaMask ? window.ethereum : null);
  if (!result?.request) throw new Error('Enable and unlock MetaMask in this browser.');
  return result;
}
async function post(path,body) {
  const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store',credentials:'omit'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Permission request failed.');
  return data;
}
document.getElementById('review-form').addEventListener('submit', async event => {
  event.preventDefault(); approve.disabled=true; reviewed=null;
  try {
    const code=document.getElementById('code').value.trim();
    if (!/^[0-9a-f]{32}$/.test(code)) throw new Error('Enter the current 32-character permission code.');
    const data=await post('/api/mint-permission-link/challenge',{code});
    if (data.mode==='revoke') {
      document.getElementById('review').textContent=`Revoke the signed permission for ${data.collection}.\nWallet: ${data.wallet_address}\nNetwork ID: ${data.chain_id}\nThis sends a revocation transaction; your wallet pays network gas. It does not mint or transfer an NFT.`;
      reviewed={code,data}; approve.disabled=false; approve.textContent='Revoke permission in MetaMask'; return;
    }
    document.getElementById('review').textContent='Scheduled signing is unavailable with the current MetaMask integration. Return to Mint plans and use Open on OpenSea when your eligible stage opens. Confirm the mint and network fee in MetaMask.';
    status.textContent='No automatic mint was armed.';
  } catch(error) {status.textContent=error.message;}
});
approve.addEventListener('click',async () => {
  if (!reviewed) return;
  approve.disabled=true;
  try {
    const {code,data}=reviewed;
    if (data.mode!=='revoke') throw new Error('Scheduled signing is unavailable with the current MetaMask integration. No automatic mint was armed.');
    const wallet=await provider();
    const accounts=await wallet.request({method:'eth_requestAccounts'});
    if (!accounts.some(address => address.toLowerCase()===data.wallet_address.toLowerCase())) throw new Error('Select the exact wallet shown in the permission.');
    await wallet.request({method:'wallet_switchEthereumChain',params:[{chainId:'0x'+data.chain_id.toString(16)}]});
    if (data.mode==='revoke') {
      const hash=await wallet.request({method:'eth_sendTransaction',params:[{...data.transaction,from:data.wallet_address}]});
      reviewed=null;status.textContent=`Revocation submitted: ${hash}. Check confirmation in MetaMask. Mintly cancellation remains in effect.`;return;
    }
  } catch(error) {reviewed=null;status.textContent=error.message || 'Permission was not approved.';}
});
