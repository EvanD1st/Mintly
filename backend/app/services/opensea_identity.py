"""Fixed-purpose OpenSea login and eligibility, entirely inside the custody boundary.

Wire format follows ProjectOpenSea/opensea-sdk src/auth/index.ts (MIT).
No arbitrary message, scope, host, cookie, signature or token crosses the API boundary.
"""
import asyncio,hashlib,hmac,json,re,secrets,time,math,base64
from weakref import WeakValueDictionary
from datetime import datetime,timezone
from urllib.parse import quote
from sqlalchemy import select
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx
from fastapi import HTTPException
from app.models import OpenSeaAccess,Wallet,User,AutomaticGrant
from app.services import automatic
from app.services.custody import CustodyVault,private_read
from app.services.mint_plans import aware
from app.services.opensea import SLUG_RE,OpenSeaUnavailable
from app.config import settings

ORIGIN='https://api.opensea.io'
SCOPES=['read:eligibility']
STATEMENT='Click to sign in and accept the OpenSea Terms of Service (https://opensea.io/tos) and Privacy Policy (https://opensea.io/privacy).'
TERMS_VERSION=hashlib.sha256(STATEMENT.encode()).hexdigest()
_locks=WeakValueDictionary()

class IdentityUnavailable(Exception):
    def __init__(self,status=503):self.status=status;super().__init__('OpenSea eligibility access is unavailable.')

class IdentityWalletMismatch(IdentityUnavailable):
    def __init__(self):super().__init__(409)


def require_wallet(token,address):
    # Token came directly from OpenSea over TLS. This extra check prevents an
    # account's primary/linked wallet from replacing the consented wallet.
    try:
        parts=token.split('.')
        if len(parts)!=3 or not parts[2]:raise ValueError()
        claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*(-len(parts[1])%4)))
        actual=claims.get('wallet')
        if not isinstance(actual,str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}',actual):raise ValueError()
        if actual.lower()!=address.lower():raise IdentityWalletMismatch()
    except IdentityWalletMismatch:raise
    except Exception:raise IdentityUnavailable() from None


def configuration(row,wallet):
    return dict(user_id=row.user_id,wallet_id=row.wallet_id,account=wallet.address.lower(),revision=row.revision,
        enabled=row.enabled,expires_at=int(aware(row.expires_at).timestamp()),terms_version=row.terms_version,scopes=SCOPES)

def tables(journal):
    journal.execute('CREATE TABLE IF NOT EXISTS opensea_identity (wallet TEXT PRIMARY KEY,revision INTEGER NOT NULL,intent TEXT NOT NULL,configuration TEXT NOT NULL,state BLOB,blocked INTEGER NOT NULL DEFAULT 0)')
    journal.execute('CREATE TABLE IF NOT EXISTS opensea_login_nonces (nonce TEXT PRIMARY KEY,used_at INTEGER NOT NULL)')
    journal.execute('CREATE TABLE IF NOT EXISTS opensea_revocations (id TEXT PRIMARY KEY,wallet TEXT NOT NULL,intent TEXT NOT NULL,state BLOB NOT NULL)')
    journal.commit()

def cipher():
    key=hmac.new(private_read(settings.CUSTODY_PASSWORD_FILE).encode(),b'mintly/opensea-eligibility/v1',hashlib.sha256).digest()
    return AESGCM(key)

def seal(state,pin):
    nonce=secrets.token_bytes(12)
    return nonce+cipher().encrypt(nonce,json.dumps(state,separators=(',',':')).encode(),pin['intent'].encode())

def unseal(pin):
    return json.loads(cipher().decrypt(pin['state'][:12],pin['state'][12:],pin['intent'].encode())) if pin['state'] else None

async def owned(db,wallet_id,*,enabled=True):
    wallet=await db.get(Wallet,wallet_id,populate_existing=True)
    row=await db.get(OpenSeaAccess,wallet_id,populate_existing=True)
    user=await db.get(User,wallet.user_id,populate_existing=True) if wallet else None
    if not wallet or not row or row.user_id!=wallet.user_id or not user or not user.is_active or user.deleted_at:
        raise ValueError('Eligibility consent owner unavailable')
    if enabled and (wallet.archived_at or wallet.signing_capability!='custodial' or not row.enabled
        or aware(row.expires_at)<=datetime.now(timezone.utc) or row.terms_version!=TERMS_VERSION):
        raise ValueError('Eligibility consent unavailable')
    return row,wallet

async def grant_policy(db,wallet,vault):
    grants=(await db.scalars(select(AutomaticGrant).where(AutomaticGrant.wallet_id==wallet.id,
        AutomaticGrant.user_id==wallet.user_id,AutomaticGrant.status=='enabled').order_by(AutomaticGrant.expires_at.desc()))).all()
    for grant in grants:
        if aware(grant.expires_at)>datetime.now(timezone.utc):
            policy=vault.policy(grant)
            if policy['account'].lower()!=wallet.address.lower():raise ValueError('Wallet identity differs')
            return policy
    raise ValueError('Active custody approval required')

class Transport:
    def __init__(self):self.client=httpx.AsyncClient(timeout=12,trust_env=False,follow_redirects=False)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):await self.client.aclose()
    async def request(self,method,path,*,body=None,headers=None):
        allowed=(path in ('/api/v2/auth/siwe/nonce','/api/v2/auth/siwe/verify','/api/v2/auth/tokens',
            '/api/v2/auth/tokens/exchange','/api/v2/auth/session/refresh') or
            re.fullmatch(r'/api/v2/auth/tokens/[A-Za-z0-9_-]{1,100}',path) or
            re.fullmatch(r'/api/v2/drops/[a-z0-9-]{1,100}/eligibility',path))
        if not allowed:raise IdentityUnavailable()
        try:
            async with self.client.stream(method,ORIGIN+path,json=body,headers=headers or {}) as response:
                content=bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content)>256*1024:raise IdentityUnavailable()
                if response.status_code not in (200,201,204):raise IdentityUnavailable(response.status_code)
                self.client.cookies.clear()  # Only explicitly scoped JWTs go to eligibility calls.
                data=json.loads(content) if content else {}
                if not isinstance(data,dict):raise IdentityUnavailable()
                cookies={}
                from http.cookies import SimpleCookie
                for raw in response.headers.get_list('set-cookie'):
                    parsed=SimpleCookie();parsed.load(raw)
                    for name in ('access_token','refresh_token'):
                        if name in parsed:cookies[name]=parsed[name].value
                return data,cookies
        except IdentityUnavailable:raise
        except Exception:raise IdentityUnavailable() from None

def secret(value):
    if not isinstance(value,str) or not 10<=len(value)<=16384 or re.search(r'[\x00-\x20;\x7f]',value):
        raise IdentityUnavailable()
    return value

def cookie_header(cookies):
    return '; '.join(name+'='+secret(cookies[name]) for name in ('access_token','refresh_token'))

def exchanged(data,scope):
    if data.get('tokenScopes',scope)!=SCOPES:raise IdentityUnavailable()
    ttl=data.get('expiresIn',3600)
    if type(ttl) is not int or not 60<=ttl<=86400:raise IdentityUnavailable()
    return secret(data.get('accessToken')),int(time.time())+ttl

async def revoke(transport,state):
    if not state:return True
    try:
        cookies=state['cookies']
        # Rotate the session cookies only to revoke this already-created token.
        _,fresh=await transport.request('POST','/api/v2/auth/session/refresh',headers={'Cookie':cookie_header(cookies)})
        cookies={**cookies,**fresh}
        await transport.request('DELETE','/api/v2/auth/tokens/'+quote(state['pat_id'],safe=''),headers={'Cookie':cookie_header(cookies)})
        return True
    except Exception:return False

async def check_pin(db,wallet_id,journal,expected):
    row,wallet=await owned(db,wallet_id)
    pin=journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(wallet_id,)).fetchone()
    actual=automatic.digest(configuration(row,wallet))
    if not pin or pin['intent']!=expected or actual!=expected or pin['blocked']:
        raise ValueError('Eligibility consent changed or requires reconnection')
    return row,wallet,pin

async def login(db,wallet_id,journal,expected,vault,transport):
    nonce_data,_=await transport.request('POST','/api/v2/auth/siwe/nonce')
    nonce=nonce_data.get('nonce')
    if not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9]{8,128}',nonce):raise IdentityUnavailable()
    await automatic.lock_execution(db)
    row,wallet,pin=await check_pin(db,wallet_id,journal,expected)
    policy=await grant_policy(db,wallet,vault)
    nonce_hash=hashlib.sha256(nonce.encode()).hexdigest()
    journal.execute('DELETE FROM opensea_login_nonces WHERE used_at<?',(int(time.time())-86400,))
    journal.execute('INSERT INTO opensea_login_nonces VALUES (?,?)',(nonce_hash,int(time.time())))
    journal.commit()  # A replay cannot obtain a second login signature.
    issued=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    address=to_checksum_address(wallet.address)
    message={'domain':'opensea.io','address':address,'statement':STATEMENT,'uri':'https://opensea.io',
        'version':'1','chainId':'1','nonce':nonce,'issuedAt':issued,'accountType':'Ethereum'}
    text=f'opensea.io wants you to sign in with your Ethereum account:\n{address}\n\n{STATEMENT}\n\nURI: https://opensea.io\nVersion: 1\nChain ID: 1\nNonce: {nonce}\nIssued At: {issued}'
    signature='0x'+vault.account(policy).sign_message(encode_defunct(text=text)).signature.hex()
    await db.commit()  # HTTP never holds the mint execution lock.
    _,cookies=await transport.request('POST','/api/v2/auth/siwe/verify',body={'message':message,'signature':signature,'chainArch':'EVM'})
    cookie=cookie_header(cookies)
    days=max(1,min(7,math.ceil((aware(row.expires_at).timestamp()-time.time())/86400)))
    created,_=await transport.request('POST','/api/v2/auth/tokens',headers={'Cookie':cookie},
        body={'label':'Mintly eligibility','scopes':SCOPES,'expiresInDays':days})
    token_id=created.get('id')
    if not isinstance(token_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',token_id):raise IdentityUnavailable()
    state={'pat_id':token_id,'pat':secret(created.get('token')),'cookies':cookies,
        'pat_expires_at':int(time.time())+days*86400}
    try:
        if created.get('scopes')!=SCOPES:raise IdentityUnavailable()
        data,_=await transport.request('POST','/api/v2/auth/tokens/exchange',body={'subjectToken':state['pat'],'subjectTokenType':'ACCESS_TOKEN'})
        state['access_token'],state['expires_at']=exchanged(data,created['scopes'])
        require_wallet(state['access_token'],wallet.address)
        await automatic.lock_execution(db)
        await check_pin(db,wallet_id,journal,expected)
        journal.execute('UPDATE opensea_identity SET state=? WHERE wallet=? AND intent=?',(seal(state,{'intent':expected}),wallet_id,expected))
        journal.commit();await db.commit()
        return state
    except Exception:
        await db.rollback()
        if not await revoke(transport,state):
            # Retain only for revocation retry; never use an unconfirmed credential.
            journal.execute('UPDATE opensea_identity SET state=?,blocked=1 WHERE wallet=? AND intent=?',
                (seal(state,{'intent':expected}),wallet_id,expected));journal.commit()
        raise

async def connection(db,wallet_id,operation,*,slug=None,key=None):
    lock=_locks.setdefault(wallet_id,asyncio.Lock())
    async with lock:
        vault=CustodyVault();journal=vault.journal();tables(journal)
        try:
            row,wallet=await owned(db,wallet_id,enabled=operation!='register')
            config=configuration(row,wallet);expected=automatic.digest(config)
            pin=journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(wallet_id,)).fetchone()
            async with Transport() as transport:
                for pending in journal.execute('SELECT * FROM opensea_revocations WHERE wallet=?',(wallet_id,)).fetchall():
                    if await revoke(transport,unseal(pending)):
                        journal.execute('DELETE FROM opensea_revocations WHERE id=?',(pending['id'],));journal.commit()
                if operation=='register':
                    if pin and (row.revision<pin['revision'] or (row.revision==pin['revision'] and expected!=pin['intent'])):
                        raise ValueError('Eligibility consent revision differs')
                    if not pin or row.revision>pin['revision']:
                        old=unseal(pin) if pin else None
                        clean=await revoke(transport,old)
                        if old and not clean:
                            journal.execute('INSERT OR IGNORE INTO opensea_revocations VALUES (?,?,?,?)',(pin['intent'],wallet_id,pin['intent'],pin['state']))
                        journal.execute('INSERT OR REPLACE INTO opensea_identity VALUES (?,?,?,?,?,0)',
                            (wallet_id,row.revision,expected,json.dumps(config),None))
                        journal.commit()
                    if not row.enabled:
                        state=unseal(journal.execute('SELECT * FROM opensea_identity WHERE wallet=?',(wallet_id,)).fetchone())
                        if await revoke(transport,state):
                            journal.execute('UPDATE opensea_identity SET state=NULL WHERE wallet=?',(wallet_id,));journal.commit()
                        return {'status':'disabled','revision':row.revision,'scopes':SCOPES}
                row,wallet,pin=await check_pin(db,wallet_id,journal,expected)
                await grant_policy(db,wallet,vault)
                state=unseal(pin)
                await db.commit()
                if not state or state['pat_expires_at']<=int(time.time()):
                    state=await login(db,wallet_id,journal,expected,vault,transport)
                elif state['expires_at']<=int(time.time())+60:
                    try:
                        data,_=await transport.request('POST','/api/v2/auth/tokens/exchange',
                            body={'subjectToken':state['pat'],'subjectTokenType':'ACCESS_TOKEN'})
                        state['access_token'],state['expires_at']=exchanged(data,SCOPES)
                    except IdentityUnavailable as error:
                        if error.status in (401,403):
                            journal.execute('UPDATE opensea_identity SET blocked=1 WHERE wallet=?',(wallet_id,));journal.commit()
                        raise
                    await check_pin(db,wallet_id,journal,expected)
                    journal.execute('UPDATE opensea_identity SET state=? WHERE wallet=? AND intent=?',(seal(state,pin),wallet_id,expected));journal.commit()
                try:
                    require_wallet(state['access_token'],wallet.address)
                except IdentityWalletMismatch:
                    # One fixed-purpose reauthentication under the still-active
                    # consent can repair primary-wallet drift. No wider scope.
                    old=state
                    try:
                        state=await login(db,wallet_id,journal,expected,vault,transport)
                    except Exception:
                        await db.rollback()
                        clean=await revoke(transport,old)
                        journal.execute('UPDATE opensea_identity SET blocked=1,state=? WHERE wallet=?',
                            (None if clean else seal(old,pin),wallet_id));journal.commit()
                        raise IdentityWalletMismatch() from None
                    if not await revoke(transport,old):
                        journal.execute('INSERT OR IGNORE INTO opensea_revocations VALUES (?,?,?,?)',
                            (expected+'-'+old['pat_id'],wallet_id,expected,seal(old,pin)));journal.commit()
                if operation=='register':return {'status':'active','revision':row.revision,'scopes':SCOPES,'expires_at':aware(row.expires_at).isoformat()}
                if not slug or not SLUG_RE.fullmatch(slug):raise ValueError('Invalid collection')
                try:
                    data,_=await transport.request('GET',f'/api/v2/drops/{slug}/eligibility',
                        headers={'X-API-KEY':secret(key),'Authorization':'Bearer '+state['access_token']})
                except IdentityUnavailable as error:
                    if error.status in (401,403):
                        journal.execute('UPDATE opensea_identity SET blocked=1 WHERE wallet=?',(wallet_id,));journal.commit()
                    raise
                await check_pin(db,wallet_id,journal,expected)
                return normalize(data,wallet.address)
        finally:journal.close()


def normalize(data,address):
    """Whitelist output fields. Unknown provider shapes are never guessed eligible."""
    reported=data.get('wallet_address') or data.get('address')
    if reported is not None and (not isinstance(reported,str) or reported.lower()!=address.lower()):
        raise IdentityUnavailable()
    rows=data.get('stages',[])
    if isinstance(rows,dict):rows=[{'stage_uuid':key,**value} for key,value in rows.items() if isinstance(value,dict)]
    if not isinstance(rows,list) or len(rows)>100:raise IdentityUnavailable()
    def number(value):
        if type(value) is int and 0<=value<2**256:return value
        if isinstance(value,str) and re.fullmatch(r'[0-9]{1,78}',value) and int(value)<2**256:return int(value)
        return None
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):continue
        uid=row.get('stage_uuid') or row.get('uuid')
        if not isinstance(uid,str) or not 1<=len(uid)<=100 or uid in seen:raise IdentityUnavailable()
        seen.add(uid)
        eligible=row.get('eligible',row.get('is_eligible'))
        result.append({'stage_uuid':uid,'eligible':eligible if type(eligible) is bool else None,
            'max_total_mintable_by_wallet':number(row.get('max_total_mintable_by_wallet')),
            'remaining':number(row.get('remaining_mints',row.get('remaining'))),
            'price_wei':number(row.get('mint_price',row.get('price')))})
    return {'address':address,'stages':result}
