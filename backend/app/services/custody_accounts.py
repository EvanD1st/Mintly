"""Direct owner-key transactions, including explicitly pinned EIP-7702 EOAs.

This adapter never creates a delegation or invokes a delegate's execute method.
Code pins detect changes; they are not an audit of delegated wallet storage/code.
"""
from eth_utils import keccak, to_checksum_address


async def inspect_account(web3, address, mode='eoa'):
    code = bytes(await web3.eth.get_code(to_checksum_address(address), 'pending'))
    if mode == 'eoa':
        if code:
            raise ValueError('Account code requires explicit EIP-7702 provisioning')
        return {'mode': 'eoa'}
    if mode != 'eip7702-direct' or len(code) != 23 or code[:3] != b'\xef\x01\x00':
        raise ValueError('Account is not a valid EIP-7702 delegated EOA')
    delegate = to_checksum_address(code[3:])
    implementation = bytes(await web3.eth.get_code(delegate, 'pending'))
    if not implementation or implementation.startswith(b'\xef\x01\x00'):
        raise ValueError('Empty or chained delegation is unsupported')
    return {'mode': mode, 'delegation': '0x' + code.hex(),
            'delegate_code_hash': '0x' + keccak(implementation).hex()}


async def verify_account(web3, policy):
    expected = policy.get('account_adapter', {'mode': 'eoa'})
    observed = await inspect_account(web3, policy['account'], expected.get('mode'))
    if observed != expected:
        raise ValueError('Account delegation or implementation changed; provision a new policy')
