"""Prove the existing account cannot use delegated keys to sign UserOperations."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from eth_account import Account
from web3 import Web3


def test_userop_requires_owner_signature_and_prefund_comes_from_account():
    rpc = os.environ.get('MINTLY_TEST_RPC')
    if not rpc:
        pytest.skip('MINTLY_TEST_RPC is required for isolated contract testing')
    assert urlparse(rpc).hostname in ('localhost', '127.0.0.1')
    w3 = Web3(Web3.HTTPProvider(rpc))
    assert w3.eth.chain_id == 31337
    entry_point = w3.eth.accounts[0]  # Controlled EntryPoint caller for validation only.
    spec = json.loads((Path(__file__).parent / 'fixtures/metamask-delegation-contracts.json').read_text())['contracts']['EIP7702StatelessDeleGator']
    factory = w3.eth.contract(abi=spec['abi'], bytecode=spec['bytecode'])
    receipt = w3.eth.wait_for_transaction_receipt(factory.constructor(w3.eth.accounts[1], entry_point).transact({'from': entry_point}))
    owner, delegate = Account.create(), Account.create()
    authorization = Account.sign_authorization({'chainId': 31337, 'address': receipt.contractAddress, 'nonce': 0}, owner.key)
    auth = {key: getattr(authorization, attr) for key, attr in [('chainId','chain_id'),('address','address'),('nonce','nonce'),('yParity','y_parity'),('r','r'),('s','s')]}
    w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction({'from': entry_point, 'to': owner.address, 'value': 10**16, 'type': 4, 'authorizationList': [auth]}))
    account = w3.eth.contract(address=owner.address, abi=spec['abi'])
    operation = [owner.address, 0, b'', b'', bytes(32), 100000, bytes(32), b'', b'']
    digest = account.functions.getPackedUserOperationTypedDataHash(tuple(operation)).call()
    owner_signature = Account.unsafe_sign_hash(digest, owner.key).signature
    delegate_signature = Account.unsafe_sign_hash(digest, delegate.key).signature
    operation[-1] = owner_signature
    assert account.functions.validateUserOp(tuple(operation), bytes(32), 0).call({'from': entry_point}) == 0
    operation[-1] = delegate_signature
    assert account.functions.validateUserOp(tuple(operation), bytes(32), 0).call({'from': entry_point}) == 1
    operation[-1] = owner_signature
    operation[5] += 1
    assert account.functions.validateUserOp(tuple(operation), bytes(32), 0).call({'from': entry_point}) == 1
    operation[5] -= 1
    before = w3.eth.get_balance(owner.address)
    prefund = 123456
    result = w3.eth.wait_for_transaction_receipt(account.functions.validateUserOp(tuple(operation), bytes(32), prefund).transact({'from': entry_point}))
    assert result.status == 1
    assert before - w3.eth.get_balance(owner.address) == prefund
    # This exercises account validation/prefund, not real EntryPoint handleOps,
    # bundler acceptance, NFT execution, or a live wallet signature.
