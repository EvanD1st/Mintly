"""Dedicated custody ingress. Route ONLY its two exact paths through HTTPS.

Never enable request-body logging, tracing payload capture or proxy disk buffering.
This process is a trusted key holder; it is not part of the regular API/worker.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid
import httpx

from eth_account import Account
from eth_utils import to_checksum_address
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from typing import Literal
from sqlalchemy import select, func

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models import AutomaticGrant, Wallet, LoginAttempt, User, MintTask, MintPlan, MintPermission
from app.services import automatic
from app.services.auth import verify_password
from app.services.custody import CustodyVault, private_read, private_write
from app.services.custody_accounts import inspect_account

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
    allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])
_capacity = asyncio.Semaphore(1)


class NetworkApproval(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    chain_id: int
    budget_eth: str = Field(max_length=40)
    max_task_eth: str = Field(max_length=40)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    request_id: uuid.UUID
    wallet_id: uuid.UUID | None = None
    account_address: str | None = Field(default=None, min_length=42, max_length=42)
    wallet_label: str = Field(default='Wallet', min_length=1, max_length=80)
    chain_id: int | None = None
    private_key: SecretStr
    password: SecretStr
    contract: str | None = Field(default=None, min_length=42, max_length=42)
    collection_scope: Literal['reviewed_mints'] | None = None
    budget_eth: str | None = Field(default=None, max_length=40)
    max_task_eth: str | None = Field(default=None, max_length=40)
    networks: list[NetworkApproval] | None = Field(default=None, min_length=1, max_length=4)
    expires_at: datetime
    consent: bool

    @model_validator(mode='after')
    def collection_selection(self):
        if (self.contract is None) == (self.collection_scope is None):
            raise ValueError('Select exactly one collection scope')
        if self.networks is not None:
            if (self.chain_id is not None or self.budget_eth is not None or self.max_task_eth is not None
                    or self.contract is not None or len({n.chain_id for n in self.networks}) != len(self.networks)):
                raise ValueError('Select distinct network approvals without single-network fields')
        elif self.budget_eth is None or self.max_task_eth is None:
            raise ValueError('Finite single-network limits are required')
        return self


def available():
    automatic.enabled()
    if not settings.ENABLE_CUSTODY_IMPORT:
        raise HTTPException(409, 'Wallet import is not enabled on this server.')
    vault = CustodyVault()
    if not vault.root.is_dir() or len(private_read(settings.CUSTODY_PASSWORD_FILE)) < 32:
        raise HTTPException(503, 'Protected import storage is unavailable.')


@app.middleware('http')
async def private_response(request, call_next):
    try:
        if settings.APP_ENV == 'production' and request.url.scheme != 'https':
            response = JSONResponse({'detail':'HTTPS is required for wallet import.'}, status_code=400)
        else:
            response = await call_next(request)
    except Exception:
        response = JSONResponse({'detail':'Wallet import unavailable. No secret is returned.'}, status_code=503)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


@app.get('/api/automatic/import/config')
async def config(user=Depends(get_current_user)):
    available()
    web3 = await automatic.provider()
    await web3.provider.disconnect()
    return {'chain_id':settings.AUTOMATIC_CHAIN_ID, 'max_expiry_days':30,
        'phrase_wallet_setup': True,
        'multi_network_import': True,
        'automatic_collection_selection': True,
        'networks': [{'chain_id': c, 'name': n} for c, n, flag in (
            (1, 'Ethereum', settings.ENABLE_ETHEREUM_AUTOMATIC),
            (8453, 'Base', settings.ENABLE_BASE_AUTOMATIC),
            (4663, 'Robinhood', settings.ENABLE_ROBINHOOD_AUTOMATIC),
            (settings.AUTOMATIC_CHAIN_ID, 'Test network', settings.AUTOMATIC_CHAIN_ID in (31337,11155111))) if flag]}


@app.post('/api/automatic/import')
async def import_wallet(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    available()
    # Parse ourselves: standard validation error responses can include raw inputs.
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > 4096:
            raise HTTPException(413, 'Import request is too large.')
        body.extend(part)
    try:
        req = ImportRequest.model_validate_json(body)
    except Exception:
        raise HTTPException(422, 'Invalid wallet import fields.') from None
    finally:
        body[:] = b'\x00' * len(body)
    async with _capacity:
        # Persist attempt limits even when password/key validation fails.
        await automatic.lock_execution(db)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        name = automatic.digest({'custody_import_user':user.id})
        count = (await db.execute(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.username_hash == name, LoginAttempt.attempted_at >= cutoff))).scalar_one()
        if count >= 5:
            raise HTTPException(429, 'Too many import attempts. Try again in 15 minutes.')
        db.add(LoginAttempt(username_hash=name))
        await db.commit()
        if not await asyncio.to_thread(verify_password, user.password_hash, req.password.get_secret_value()):
            raise HTTPException(403, 'Mintly password is incorrect.')
        req.password = SecretStr('')
        try:
            return await store_import(req, user, db)
        except HTTPException:
            raise
        except Exception:
            await db.rollback()
            raise HTTPException(409, 'Import could not complete. Verify the linked wallet, key, limits and server setup; retry with the same request.') from None
        finally:
            req.private_key = SecretStr('')


async def store_import(req, user, db):
    approvals = sorted(req.networks, key=lambda n: n.chain_id) if req.networks is not None else [NetworkApproval(
        chain_id=req.chain_id if req.chain_id is not None else settings.AUTOMATIC_CHAIN_ID,
        budget_eth=req.budget_eth, max_task_eth=req.max_task_eth)]
    limits = {}
    for approval in approvals:
        automatic.enabled(approval.chain_id)
        budget, maximum = automatic.wei(approval.budget_eth), automatic.wei(approval.max_task_eth)
        if not 0 < maximum <= budget < 2**63:
            raise ValueError('Invalid finite network budget')
        limits[approval.chain_id] = (budget, maximum)
    await automatic.lock_execution(db)
    wallet = await db.get(Wallet, str(req.wallet_id)) if req.wallet_id else None
    if req.wallet_id and (not wallet or wallet.user_id != user.id or wallet.is_demo):
        raise HTTPException(404, 'Linked wallet not found.')
    now = datetime.now(timezone.utc)
    if not req.consent or req.expires_at.tzinfo is None or not now < req.expires_at <= now + timedelta(days=30):
        raise ValueError('Invalid consent or expiry')
    account = Account.from_key(req.private_key.get_secret_value().strip())
    req.private_key = SecretStr('')
    if ((wallet and account.address.lower() != wallet.address.lower())
            or (req.account_address and account.address.lower() != req.account_address.lower())):
        raise HTTPException(409, 'Private key does not match the linked wallet. Nothing was imported.')
    contracts = [to_checksum_address(req.contract)] if req.contract else []
    grant_ids = [str(req.request_id) if i == 0 else str(uuid.uuid5(req.request_id, f'mintly-network:{n.chain_id}'))
        for i, n in enumerate(approvals)]
    # Pin the whole bundle in every independent signer policy, including retry after a DB failure.
    bundle = [{'chain_id': n.chain_id, 'budget_wei': limits[n.chain_id][0],
        'max_task_wei': limits[n.chain_id][1]} for n in approvals] if req.networks is not None else None
    vault = CustodyVault()
    old_grants = [await db.get(AutomaticGrant, grant_id) for grant_id in grant_ids]
    if any(old_grants):
        if not all(old_grants):
            raise ValueError('Incomplete existing import')
        old = old_grants[0]
        if wallet is None:
            wallet = await db.get(Wallet, old.wallet_id)
        if (old.user_id != user.id or not wallet or old.wallet_id != wallet.id
                or account.address.lower() != wallet.address.lower() or wallet.archived_at):
            raise ValueError('Request owner mismatch')
        for old, approval in zip(old_grants, approvals):
            policy = vault.policy(old)
            budget, maximum = limits[approval.chain_id]
            if (old.user_id != user.id or old.wallet_id != wallet.id or policy['chain_id'] != approval.chain_id
                    or policy['contracts'] != contracts or policy.get('collection_scope') != req.collection_scope
                    or policy['budget_wei'] != budget or policy['max_task_wei'] != maximum
                    or policy['expires_at'] != int(req.expires_at.timestamp()) or policy.get('network_approvals') != bundle):
                raise ValueError('Request changed')
        return import_result(req, wallet, old_grants)  # Never renew/reactivate or reset a budget on retry.
    matches = (await db.scalars(select(Wallet).join(User, User.id == Wallet.user_id).where(
        func.lower(Wallet.address) == account.address.lower(), User.is_active.is_(True), User.deleted_at.is_(None)))).all()
    if any(w.user_id != user.id and w.archived_at is None for w in matches):
        raise HTTPException(409, 'This wallet is still linked to another Mintly account. Unlink it there first.')
    # Address-level check includes archived/deleted owners and all networks. Signed raw transactions
    # can remain valid after software cancellation/expiry; only a settled receipt clears the hold.
    address_wallets = select(Wallet.id).where(func.lower(Wallet.address) == account.address.lower())
    pending = await db.scalar(select(MintTask.id).where(MintTask.wallet_id.in_(address_wallets),
        MintTask.signed_tx_raw.is_not(None), MintTask.status.not_in(('confirmed', 'reverted'))).limit(1))
    legacy_pending = await db.scalar(select(MintPermission.id).join(MintPlan, MintPlan.id == MintPermission.plan_id)
        .where(MintPlan.wallet_id.in_(address_wallets), MintPermission.raw_transaction.is_not(None),
            MintPermission.status.not_in(('confirmed', 'reverted'))).limit(1))
    if (wallet is None or wallet.archived_at) and (pending or legacy_pending):
        raise HTTPException(409, 'A previously signed mint for this wallet is unresolved. Wait for settlement before relinking.')
    if wallet is None or wallet.archived_at:
        await signer_relink_ready(account.address)
    if wallet is None:
        if not req.account_address:
            raise HTTPException(422, 'Confirm the account selected from your phrase.')
        wallet = next((w for w in matches if w.user_id == user.id), None)
        if wallet is not None and wallet.archived_at is None:
            raise HTTPException(409, 'This account is already linked. Choose another account or open its wallet details.')
        if wallet is None:
            active_count = await db.scalar(select(func.count()).select_from(Wallet).where(
                Wallet.user_id == user.id, Wallet.archived_at.is_(None)))
            if active_count >= 20:
                raise HTTPException(409, 'Unlink a wallet before adding more than 20.')
            wallet = Wallet(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'mintly-wallet:{user.id}:{account.address.lower()}')),
                user_id=user.id, label=req.wallet_label.strip() or 'Wallet',
                address=account.address, signing_capability='custodial', supported_chains=['Ethereum','Base','Robinhood Chain'],
                is_default=active_count == 0, is_demo=False)
            db.add(wallet)
            await db.flush()
    policies = []
    for grant_id, approval in zip(grant_ids, approvals):
        web3 = await automatic.provider_for(approval.chain_id)
        try:
            code = await web3.eth.get_code(account.address, 'pending')
            adapter = await inspect_account(web3, account.address, 'eip7702-direct' if code else 'eoa')
            if contracts and not await web3.eth.get_code(contracts[0]):
                raise ValueError('Collection has no deployed code')
        finally:
            await web3.provider.disconnect()
        budget, maximum = limits[approval.chain_id]
        policy = dict(grant_id=grant_id,key_id=str(req.request_id),user_id=user.id,wallet_id=wallet.id,
            account=account.address,chain_id=approval.chain_id,contracts=contracts,
            mint_kinds=['public','allowlist','signed'],account_adapter=adapter,budget_wei=budget,
            max_task_wei=maximum,expires_at=int(req.expires_at.timestamp()))
        if req.collection_scope:
            policy['collection_scope'] = req.collection_scope
        if bundle is not None:
            policy['network_approvals'] = bundle
        policies.append(policy)
    password = private_read(settings.CUSTODY_PASSWORD_FILE)
    if len(password) < 32:
        raise ValueError('Weak vault password')
    key_path = vault.root / f'{req.request_id}.keystore.json'
    if key_path.exists():
        # Recover a response/DB failure without creating another key or allowance.
        recovered = await asyncio.to_thread(Account.decrypt, json.loads(private_read(key_path)), password)
        if Account.from_key(recovered).address != account.address:
            raise ValueError('Conflicting key file')
        del recovered
    else:
        encrypted = await asyncio.to_thread(Account.encrypt, account.key, password, kdf='scrypt', iterations=262144)
        private_write(key_path, json.dumps(encrypted))
    del account, password
    grants = []
    for policy in policies:
        policy_path = vault.root / f'{policy["grant_id"]}.policy.json'
        if policy_path.exists():
            if json.loads(private_read(policy_path)) != policy:
                raise ValueError('Conflicting policy file')
        else:
            private_write(policy_path, json.dumps(policy, sort_keys=True))
        grant = AutomaticGrant(id=policy['grant_id'],user_id=user.id,wallet_id=wallet.id,
            chain_id=policy['chain_id'],account=wallet.address,context_hash=automatic.digest(policy),
            expires_at=req.expires_at,scope={k:policy[k] for k in ('contracts','mint_kinds','max_task_wei','collection_scope') if k in policy},
            budget_wei=policy['budget_wei'],reserved_wei=0,spent_wei=0,status='enabled')
        db.add(grant)
        grants.append(grant)
    if wallet.archived_at:
        active = await db.scalar(select(func.count()).select_from(Wallet).where(
            Wallet.user_id == user.id, Wallet.archived_at.is_(None), Wallet.id != wallet.id))
        if active >= 20:
            raise HTTPException(409, 'Unlink a wallet before adding more than 20.')
        wallet.is_default = active == 0
    wallet.archived_at = None
    wallet.signing_capability = 'custodial'
    wallet.supported_chains = sorted(set(wallet.supported_chains or []) | {'Ethereum','Base','Robinhood Chain'})
    if req.wallet_id is None:
        wallet.label = req.wallet_label.strip() or 'Wallet'
    await db.commit()
    return import_result(req, wallet, grants)


def import_result(req, wallet, grants):
    if req.networks is None:
        return automatic.public_grant(grants[0])
    return {'id': str(req.request_id), 'wallet_id': wallet.id, 'account': wallet.address,
        'grants': [automatic.public_grant(grant) for grant in grants]}


async def signer_relink_ready(address):
    try:
        token = private_read(settings.AUTOMATIC_SIGNER_TOKEN_FILE)
        if len(token) < 32:
            raise ValueError('Signer control unavailable')
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            result = await client.get(settings.AUTOMATIC_SIGNER_URL + f'/accounts/{address}/relink-ready',
                headers={'Authorization': 'Bearer ' + token})
            result.raise_for_status()
            if result.json() != {'ready': True}:
                raise ValueError('Outstanding signature')
    except Exception:
        raise HTTPException(409, 'The signer has not confirmed this wallet is clear of unresolved signed mints. No wallet was linked.') from None
