"""Signer-only key vault and independent, fsync-backed signing journal.

The API and scheduler must not mount this directory or the password secret.
The journal charges the full maximum until a canonical receipt is confirmed.
"""
import json
import os
import stat
from pathlib import Path
import sqlite3
import uuid

from eth_account import Account
from app.config import settings
from app.services.automatic import digest
from app.services.mint_plans import aware


def private_read(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Signer secret file unavailable')
    # Check the opened descriptor, not a path that can change between stat/read.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'r', encoding='utf-8') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Signer secret must be a regular file')
        if os.name != 'nt' and (info.st_mode & 0o077 or info.st_uid != os.geteuid()):
            raise ValueError('Signer secret files must be owned and readable only by the service account')
        return file.read().strip()


def private_write(path, value):
    # Never overwrite a prior key or policy. Provisioning is an explicit operation.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(value)
        file.flush()
        os.fsync(file.fileno())
    if os.name != 'nt':
        directory = os.open(str(Path(path).parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class CustodyVault:
    def __init__(self):
        self.root = Path(settings.CUSTODY_VAULT_DIR)
        if not settings.CUSTODY_VAULT_DIR or not settings.CUSTODY_PASSWORD_FILE or not settings.CUSTODY_JOURNAL_FILE:
            raise ValueError('Signer vault, password and durable journal must be configured separately')
        if os.name == 'nt' and settings.APP_ENV == 'production':
            raise ValueError('Production signer isolation requires the documented Linux service/container')

    def policy(self, grant):
        policy_id = str(uuid.UUID(grant.id))
        policy = json.loads(private_read(self.root / f'{policy_id}.policy.json'))
        if (digest(policy) != grant.context_hash or policy['grant_id'] != grant.id
                or policy['user_id'] != grant.user_id or policy['wallet_id'] != grant.wallet_id
                or policy['account'].lower() != grant.account.lower() or policy['chain_id'] != grant.chain_id
                or int(policy['budget_wei']) != grant.budget_wei
                or int(policy['expires_at']) != int(aware(grant.expires_at).timestamp())):
            raise ValueError('Database policy does not match the independently provisioned signer policy')
        return policy

    def account(self, policy):
        key_id = str(uuid.UUID(policy['key_id']))
        keyfile = json.loads(private_read(self.root / f'{key_id}.keystore.json'))
        password = private_read(settings.CUSTODY_PASSWORD_FILE)
        account = Account.from_key(Account.decrypt(keyfile, password))
        if account.address.lower() != policy['account'].lower():
            raise ValueError('Keystore address differs from authorized wallet')
        return account

    def journal(self):
        path = Path(settings.CUSTODY_JOURNAL_FILE)
        if path.is_symlink():
            raise ValueError('Signer journal cannot be a symlink')
        if not path.exists():
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('Signer journal permissions are too broad')
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('''CREATE TABLE IF NOT EXISTS signed (
            task TEXT PRIMARY KEY, policy TEXT NOT NULL, intent TEXT NOT NULL,
            address TEXT NOT NULL, chain INTEGER NOT NULL, nonce INTEGER NOT NULL,
            liability INTEGER NOT NULL, raw TEXT NOT NULL, hash TEXT NOT NULL,
            actual INTEGER, UNIQUE(chain,address,nonce))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS recoveries (
            id TEXT PRIMARY KEY, task TEXT NOT NULL UNIQUE, intent TEXT NOT NULL,
            nonce INTEGER NOT NULL, raw TEXT NOT NULL, hash TEXT NOT NULL)''')
        conn.execute('CREATE TABLE IF NOT EXISTS copy_rules (id TEXT PRIMARY KEY, intent TEXT NOT NULL, snapshot TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS copy_signed (task TEXT PRIMARY KEY, rule TEXT, stage TEXT NOT NULL UNIQUE)')
        conn.execute('CREATE TABLE IF NOT EXISTS copy_collections (task TEXT PRIMARY KEY, address TEXT NOT NULL, chain INTEGER NOT NULL, contract TEXT NOT NULL, kind TEXT NOT NULL)')
        conn.execute('CREATE INDEX IF NOT EXISTS copy_collections_wallet ON copy_collections(address,chain,contract)')
        conn.commit()
        return conn
