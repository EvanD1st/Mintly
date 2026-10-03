"""Operator-side masked key provisioning. Never send private keys through an API.

Run on the isolated signer host as its service user. Existing linked address only.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from getpass import getpass, GetPassWarning
import json
import os
import sys
from pathlib import Path
import uuid
import warnings

from eth_account import Account
from eth_utils import to_checksum_address
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AutomaticGrant, Wallet, User
from app.services import automatic
from app.services.custody import private_read, private_write
from app.services.custody_accounts import inspect_account


def source_root(source=None):
    source = Path(source or __file__).resolve()
    # In the image this file is /app/app/provision_custody.py, not
    # <checkout>/backend/app/... . Never mistake / for the entire checkout.
    return next((p for p in source.parents if (p / '.git').exists()), source.parents[1])


async def provision(args):
    automatic.enabled()
    if not sys.stdin.isatty():
        raise ValueError('Provisioning requires an interactive terminal with hidden key input.')
    if os.name == 'nt' and settings.APP_ENV == 'production':
        raise ValueError('Use the isolated Linux signer host for production key provisioning.')
    async with AsyncSessionLocal() as db:
        wallet = await db.get(Wallet, args.wallet_id)
        user = await db.get(User, args.user_id)
        if not wallet or not user or not user.is_active or wallet.user_id != user.id:
            raise ValueError('Link and verify this wallet under the specified user first.')
        expiry = datetime.fromisoformat(args.expires.replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError('An explicit future expiry with timezone is required.')
        budget, max_task = automatic.wei(args.budget_eth), automatic.wei(args.max_task_eth)
        if not 0 < max_task <= budget:
            raise ValueError('Task ceiling must fit a finite positive total budget.')
        contracts = [to_checksum_address(a) for a in args.contract]
        web3 = await automatic.provider()
        try:
            account_adapter = await inspect_account(web3, wallet.address, args.account_mode)
        finally:
            await web3.provider.disconnect()
        vault = Path(settings.CUSTODY_VAULT_DIR).resolve()
        if not settings.CUSTODY_VAULT_DIR:
            raise ValueError('Set CUSTODY_VAULT_DIR outside the checkout.')
        repo = source_root()
        if vault == repo or repo in vault.parents:
            raise ValueError('Vault must be outside the Git checkout.')
        vault.mkdir(mode=0o700, parents=True, exist_ok=True)
        password = private_read(settings.CUSTODY_PASSWORD_FILE)
        if len(password) < 32:
            raise ValueError('Provide a randomly generated secret of at least 32 characters through a separate secret mount.')
        print(f'Custody for linked address {wallet.address}; chain {settings.AUTOMATIC_CHAIN_ID}.')
        print('Account adapter: ' + json.dumps(account_adapter, sort_keys=True))
        print(f'Total budget {args.budget_eth} ETH, per-task cap {args.max_task_eth} ETH, expiry {expiry.isoformat()}.')
        print('The server will possess full signing authority; signer limits are software-enforced, not on-chain.')
        if input('Type the full wallet address to acknowledge custody: ').strip().lower() != wallet.address.lower():
            raise ValueError('Custody acknowledgment did not match.')
        with warnings.catch_warnings():
            # Refuse getpass's echoed-input fallback if terminal protection fails.
            warnings.simplefilter('error', GetPassWarning)
            secret = getpass('Private key (hidden; existing linked wallet only): ')
        account = Account.from_key(secret)
        del secret
        if account.address.lower() != wallet.address.lower():
            raise ValueError('Private key does not match the linked address. Nothing was stored.')
        encrypted = Account.encrypt(account.key, password, kdf='scrypt', iterations=262144)
        del account, password
        key_id, grant_id = str(uuid.uuid4()), str(uuid.uuid4())
        policy = {'grant_id': grant_id, 'key_id': key_id, 'user_id': user.id, 'wallet_id': wallet.id,
            'account': to_checksum_address(wallet.address), 'chain_id': settings.AUTOMATIC_CHAIN_ID,
            'contracts': contracts, 'mint_kinds': args.mint_kind, 'account_adapter': account_adapter,
            'budget_wei': budget, 'max_task_wei': max_task, 'expires_at': int(expiry.timestamp())}
        private_write(vault / f'{key_id}.keystore.json', json.dumps(encrypted))
        private_write(vault / f'{grant_id}.policy.json', json.dumps(policy, sort_keys=True))
        grant = AutomaticGrant(id=grant_id, user_id=user.id, wallet_id=wallet.id, chain_id=settings.AUTOMATIC_CHAIN_ID,
            account=wallet.address, context_hash=automatic.digest(policy), expires_at=expiry,
            scope={k: policy[k] for k in ('contracts','mint_kinds','max_task_wei')},
            budget_wei=budget, reserved_wei=0, spent_wei=0, status='enabled')
        db.add(grant)
        await db.commit()
        print(f'Policy provisioned: {grant_id}. No transaction was sent. Restart signer after provisioning.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--wallet-id', required=True)
    parser.add_argument('--contract', action='append', required=True)
    parser.add_argument('--mint-kind', action='append', choices=['public','allowlist','signed'], required=True)
    parser.add_argument('--budget-eth', required=True)
    parser.add_argument('--max-task-eth', required=True)
    parser.add_argument('--expires', required=True)
    parser.add_argument('--account-mode', choices=['eoa', 'eip7702-direct'], default='eoa')
    try:
        asyncio.run(provision(parser.parse_args()))
    except Exception:
        # Invalid key input must not appear in tracebacks or process logs.
        raise SystemExit('Provisioning failed. Check wallet ownership, policy limits, protected paths and secret configuration; no key is printed.') from None


if __name__ == '__main__':
    main()
