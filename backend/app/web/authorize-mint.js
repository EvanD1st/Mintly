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
function eth(wei) {const n=BigInt(wei);return `${n/10n**18n}.${(n%10n**18n).toString().padStart(18,'0')}`;}
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
    document.getElementById('review').textContent=`Collection: ${data.collection}\nCollection contract: ${data.nft_contract}\nStage: ${data.stage_name ?? data.stage_type ?? 'Verified mint'}\nNFTs: ${data.quantity}\nWallet: ${data.wallet_address}\nNetwork ID: ${data.chain_id}\nMaximum user debit: ${eth(data.total_value_wei)} ETH\nEstimated equivalent: ${data.user_debit_usdt ?? 'Unavailable'} USDT\n${data.gas_mode==='direct_wallet'?'Maximum network gas':'Fixed gas reimbursement'}: ${data.gas_fee_eth} ETH (included above)\nExecute after: ${new Date(data.execute_after).toLocaleString()}\nExpires: ${new Date(data.expires_at).toLocaleString()}\n${data.gas_mode==='direct_wallet'?'Your main wallet pays network gas. Two signatures are required now, with no further prompt at execution. A failed or prematurely submitted operation can consume gas up to the approved ceiling.':'One exact SeaDrop mint plus this exact reimbursement to the relayer. Both revert if the mint fails.'} No other mint is permitted.`;
    reviewed={code,data}; approve.disabled=false; status.textContent='Review the details before approving.';
  } catch(error) {status.textContent=error.message;}
});
approve.addEventListener('click',async () => {
  if (!reviewed) return;
  approve.disabled=true;
  try {
    const {code,data}=reviewed;
    const wallet=await provider();
    const accounts=await wallet.request({method:'eth_requestAccounts'});
    if (!accounts.some(address => address.toLowerCase()===data.wallet_address.toLowerCase())) throw new Error('Select the exact wallet shown in the permission.');
    await wallet.request({method:'wallet_switchEthereumChain',params:[{chainId:'0x'+data.chain_id.toString(16)}]});
    if (data.mode==='revoke') {
      const hash=await wallet.request({method:'eth_sendTransaction',params:[{...data.transaction,from:data.wallet_address}]});
      reviewed=null;status.textContent=`Revocation submitted: ${hash}. Check confirmation in MetaMask. Mintly cancellation remains in effect.`;return;
    }
    const typed=structuredClone(data.typed_data);
    typed.types.EIP712Domain=[{name:'name',type:'string'},{name:'version',type:'string'},{name:'chainId',type:'uint256'},{name:'verifyingContract',type:'address'}];
    status.textContent='Review the spending permission in MetaMask.';
    const signature=await wallet.request({method:'eth_signTypedData_v4',params:[data.wallet_address,JSON.stringify(typed)]});
    let userop_signature;
    if (data.gas_mode==='direct_wallet') {
      const prepared=await post('/api/mint-permission-link/prepare-userop',{code,signature});
      const operation=prepared.typed_data;
      operation.types.EIP712Domain=typed.types.EIP712Domain;
      status.textContent='Approve the exact gas-paying operation in MetaMask. This is the second and final signature for arming.';
      userop_signature=await wallet.request({method:'eth_signTypedData_v4',params:[data.wallet_address,JSON.stringify(operation)]});
    }
    await post('/api/mint-permission-link/complete',{code,signature,userop_signature});
    reviewed=null; status.textContent='Authorized. Return to Mintly to track execution or cancel before submission.';
  } catch(error) {reviewed=null;status.textContent=error.message || 'Permission was not approved.';}
});
