"""Dedicated custody ingress. Route ONLY its two exact paths through HTTPS.

Never enable request-body logging, tracing payload capture or proxy disk buffering.
This process is a trusted key holder; it is not part of the regular API/worker.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

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
from app.models import AutomaticGrant, Wallet, LoginAttempt
from app.services import automatic
from app.services.auth import verify_password
from app.services.custody import CustodyVault, private_read, private_write
from app.services.custody_accounts import inspect_account

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
    allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])
_capacity = asyncio.Semaphore(1)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    request_id: uuid.UUID
    wallet_id: uuid.UUID
    chain_id: int | None = None
    private_key: SecretStr
    password: SecretStr
    contract: str | None = Field(default=None, min_length=42, max_length=42)
    collection_scope: Literal['reviewed_mints'] | None = None
    budget_eth: str = Field(max_length=40)
    max_task_eth: str = Field(max_length=40)
    expires_at: datetime
    consent: bool

    @model_validator(mode='after')
    def collection_selection(self):
        if (self.contract is None) == (self.collection_scope is None):
            raise ValueError('Select exactly one collection scope')
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
    chain_id = req.chain_id if req.chain_id is not None else settings.AUTOMATIC_CHAIN_ID
    automatic.enabled(chain_id)
    await automatic.lock_execution(db)
    wallet = await db.get(Wallet, str(req.wallet_id))
    if not wallet or wallet.user_id != user.id or wallet.is_demo:
        raise HTTPException(404, 'Linked wallet not found.')
    now = datetime.now(timezone.utc)
    if not req.consent or req.expires_at.tzinfo is None or not now < req.expires_at <= now + timedelta(days=30):
        raise ValueError('Invalid consent or expiry')
    budget, maximum = automatic.wei(req.budget_eth), automatic.wei(req.max_task_eth)
    if not 0 < maximum <= budget < 2**63:
        raise ValueError('Invalid finite budget')
    account = Account.from_key(req.private_key.get_secret_value().strip())
    req.private_key = SecretStr('')
    if account.address.lower() != wallet.address.lower():
        raise HTTPException(409, 'Private key does not match the linked wallet. Nothing was imported.')
    contracts = [to_checksum_address(req.contract)] if req.contract else []
    grant_id = str(req.request_id)
    vault = CustodyVault()
    old = await db.get(AutomaticGrant, grant_id)
    if old:
        if old.user_id != user.id or old.wallet_id != wallet.id:
            raise ValueError('Request owner mismatch')
        policy = vault.policy(old)
        if (policy['chain_id'] != chain_id or policy['contracts'] != contracts or policy.get('collection_scope') != req.collection_scope or policy['budget_wei'] != budget or
                policy['max_task_wei'] != maximum or policy['expires_at'] != int(req.expires_at.timestamp())):
            raise ValueError('Request changed')
        return automatic.public_grant(old)  # Never renew/reactivate or reset a budget on retry.
    web3 = await automatic.provider_for(chain_id)
    try:
        code = await web3.eth.get_code(account.address, 'pending')
        adapter = await inspect_account(web3, account.address, 'eip7702-direct' if code else 'eoa')
        if contracts and not await web3.eth.get_code(contracts[0]):
            raise ValueError('Collection has no deployed code')
    finally:
        await web3.provider.disconnect()
    policy = dict(grant_id=grant_id,key_id=grant_id,user_id=user.id,wallet_id=wallet.id,
        account=account.address,chain_id=chain_id,contracts=contracts,
        mint_kinds=['public','allowlist','signed'],account_adapter=adapter,budget_wei=budget,
        max_task_wei=maximum,expires_at=int(req.expires_at.timestamp()))
    if req.collection_scope:
        policy['collection_scope'] = req.collection_scope
    password = private_read(settings.CUSTODY_PASSWORD_FILE)
    if len(password) < 32:
        raise ValueError('Weak vault password')
    key_path = vault.root / f'{grant_id}.keystore.json'
    policy_path = vault.root / f'{grant_id}.policy.json'
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
    if policy_path.exists():
        if json.loads(private_read(policy_path)) != policy:
            raise ValueError('Conflicting policy file')
    else:
        private_write(policy_path, json.dumps(policy, sort_keys=True))
    grant = AutomaticGrant(id=grant_id,user_id=user.id,wallet_id=wallet.id,
        chain_id=chain_id,account=wallet.address,context_hash=automatic.digest(policy),
        expires_at=req.expires_at,scope={k:policy[k] for k in ('contracts','mint_kinds','max_task_wei','collection_scope') if k in policy},
        budget_wei=budget,reserved_wei=0,spent_wei=0,status='enabled')
    db.add(grant)
    await db.commit()
    return automatic.public_grant(grant)
