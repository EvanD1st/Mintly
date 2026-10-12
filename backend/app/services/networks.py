"""Network identity and native units; this registry never grants spending rights."""
from dataclasses import dataclass
from app.config import settings


@dataclass(frozen=True)
class Network:
    chain_id: int
    slug: str
    name: str
    symbol: str
    rpc_setting: str
    opt_in: str | None
    explorer: str
    fee_model: str = 'evm'
    log_span: int = 2000


NETWORKS = {
    1: Network(1, 'ethereum', 'Ethereum', 'ETH', 'RPC_ETHEREUM', 'ENABLE_ETHEREUM_AUTOMATIC', 'https://etherscan.io/tx/'),
    8453: Network(8453, 'base', 'Base', 'ETH', 'RPC_BASE', 'ENABLE_BASE_AUTOMATIC', 'https://basescan.org/tx/', 'op_stack'),
    4663: Network(4663, 'robinhood', 'Robinhood', 'ETH', 'RPC_ROBINHOOD', 'ENABLE_ROBINHOOD_AUTOMATIC', 'https://robinhoodchain.blockscout.com/tx/', 'nitro'),
    # Configured archive endpoint was verified with historical calls and 300-block
    # log ranges. Hyperliquid's restricted default endpoint is not used here.
    999: Network(999, 'hyperevm', 'HyperEVM', 'HYPE', 'RPC_HYPEREVM', 'ENABLE_HYPEREVM_AUTOMATIC', 'https://hyperevmscan.io/tx/', log_span=300),
    33139: Network(33139, 'ape_chain', 'ApeChain', 'APE', 'RPC_APECHAIN', 'ENABLE_APECHAIN_AUTOMATIC', 'https://apescan.io/tx/', 'nitro'),
    57073: Network(57073, 'ink', 'Ink', 'ETH', 'RPC_INK', 'ENABLE_INK_AUTOMATIC', 'https://explorer.inkonchain.com/tx/', 'op_stack'),
    11155111: Network(11155111, 'sepolia', 'Sepolia', 'ETH', 'RPC_SEPOLIA', None, 'https://sepolia.etherscan.io/tx/'),
    31337: Network(31337, 'local', 'Local test', 'ETH', 'AUTOMATIC_RPC', None, ''),
}


def symbol(chain_id):
    return NETWORKS[chain_id].symbol if chain_id in NETWORKS else 'ETH'


def name(chain_id):
    return NETWORKS[chain_id].name if chain_id in NETWORKS else f'Chain {chain_id}'


def fee_model(chain_id):
    return NETWORKS[chain_id].fee_model if chain_id in NETWORKS else 'evm'


def metadata(chain_id):
    return {'chain_id': chain_id, 'name': name(chain_id), 'native_symbol': symbol(chain_id), 'native_decimals': 18}


def require_currency(chain_id, confirmed):
    from fastapi import HTTPException
    expected = symbol(chain_id)
    if (confirmed is not None and confirmed != expected) or (expected != 'ETH' and confirmed != expected):
        raise HTTPException(422, f'Confirm {expected} as the native currency for these network limits.')


def advertised(*, native_currencies=False):
    return [metadata(n.chain_id) for n in NETWORKS.values() if n.opt_in and getattr(settings, n.opt_in)
            and (native_currencies or n.symbol == 'ETH')]
