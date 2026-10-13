"""Validated chain reads without enabling transaction execution in discovery."""
from urllib.parse import urlparse
from web3 import AsyncWeb3
from app.config import settings
from app.services.networks import NETWORKS

async def provider_for(chain_id):
    network=NETWORKS.get(chain_id)
    if not network or (network.opt_in and not getattr(settings,network.opt_in)):
        raise ValueError('This network is not advertised.')
    from app.services.automatic import rpc_for
    url=rpc_for(chain_id);parsed=urlparse(url)
    if chain_id==31337:
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','evm'):
            raise ValueError('Local display reads require an isolated RPC.')
    elif parsed.scheme!='https':raise ValueError('Display reads require HTTPS RPC.')
    web3=AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url,request_kwargs={'timeout':8}))
    try:
        if await web3.eth.chain_id!=chain_id:raise ValueError('Display RPC chain mismatch.')
        return web3
    except BaseException:
        await web3.provider.disconnect();raise
