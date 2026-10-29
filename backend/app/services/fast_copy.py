"""Live source feeds beside durable historical scans; no private-key or signer access."""
import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
import logging
from urllib.parse import urlparse
import aiohttp
from eth_abi import decode
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from web3.exceptions import TransactionNotFound
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import CopyWatch, CopyRule, CopyEvent
from app.services import automatic, copy_mints, pending_copy
from app.services.networks import NETWORKS
from app.services.signer.base import SEADROP_V1_ADDRESS, MINT_PUBLIC_SELECTOR
from app.services.seadrop_mint import ALLOW_SELECTOR, SIGNED_SELECTOR

log = logging.getLogger('mintly.copy')


async def watches(factory, chain):
    async with factory() as db:
        rows = (await db.scalars(select(CopyWatch).where(CopyWatch.archived_at.is_(None)).limit(100))).all()
        active = set((await db.scalars(select(CopyRule.watch_id).where(CopyRule.chain_id==chain,
            CopyRule.status=='active', CopyRule.expires_at>datetime.now(timezone.utc)))).all())
        return [dict(id=w.id, address=w.address, cursor=dict(w.cursors.get(str(chain), {})),
            active=w.id in active) for w in rows if chain in w.chains]


async def record(factory, chain, observation, *, pending=False):
    """Persist before waking execution; canonical and pending paths share event IDs."""
    async with factory() as db:
        await automatic.lock_execution(db)
        rows = (await db.scalars(select(CopyWatch).where(CopyWatch.archived_at.is_(None),
            CopyWatch.address.ilike(observation['source_address'])))).all()
        ids = []
        for watch in rows:
            if chain not in watch.chains:
                continue
            if pending:
                active = await db.scalar(select(CopyRule.id).where(CopyRule.watch_id==watch.id,
                    CopyRule.chain_id==chain, CopyRule.status=='active',
                    CopyRule.resume_after_block<observation['seen_block'],
                    CopyRule.expires_at>datetime.now(timezone.utc)).limit(1))
                if not active:
                    continue
            key = automatic.digest([watch.id, chain, observation['source_hash'], observation['contract'].lower()])
            event = await db.get(CopyEvent, key)
            if event is None:
                db.add(CopyEvent(id=key, user_id=watch.user_id, watch_id=watch.id,
                    observation=observation, status='detected',
                    note='Pending mint detected. Checking your wallet and spending limits.' if pending else None))
            elif not pending and event.observation.get('source_pending') is True:
                event.observation = observation
            ids.append(watch.id)
        await db.commit()
        return ids


async def live_step(factory, chain, state):
    """One small shared log request per chain, independent of old cursor failures."""
    targets = await watches(factory, chain)
    state['watches'] = targets
    if not targets:
        return []
    web3 = await automatic.provider_for(chain)
    try:
        confirmations = max(2, settings.COPY_ETHEREUM_SOURCE_CONFIRMATIONS) if chain==1 else 2
        head = max(0, await web3.eth.block_number-(confirmations-1))
        last = min(max(0, head-20, w['cursor'].get('live_block', head-20)) for w in targets)
        last = min(last, head)
        # Re-read a small overlap for reorgs and newly followed wallets. The
        # historical cursor remains responsible for every older, unscanned block.
        start = max(0, last-2)
        addresses = sorted({'0x'+w['address'][2:].lower().rjust(64,'0') for w in targets})
        logs = await web3.eth.get_logs({'address':SEADROP_V1_ADDRESS,'fromBlock':start,'toBlock':head,
            'topics':[copy_mints.SEADROP_MINT,None,addresses]})
        if len(logs)>1000:
            raise ValueError('Live source range too dense')
        seen = set()
        for row in logs:
            if len(row.topics)!=4:
                continue
            sender = to_checksum_address(bytes(row.topics[2])[-20:])
            if sender.lower() not in {w['address'].lower() for w in targets}:
                continue
            contract = to_checksum_address(bytes(row.topics[1])[-20:])
            tx_hash = copy_mints.hex_value(row.transactionHash)
            key = (tx_hash,contract.lower())
            if key in seen:
                continue
            seen.add(key)
            try:
                observation = await copy_mints.observe(web3,chain,tx_hash,sender,contract)
            except (ValueError,KeyError):
                continue
            await record(factory,chain,observation)
        block = await web3.eth.get_block(head)
        async with factory() as db:
            await automatic.lock_execution(db)
            for target in targets:
                watch = await db.get(CopyWatch,target['id'])
                if not watch or watch.archived_at or chain not in watch.chains:
                    continue
                cursor = dict(watch.cursors.get(str(chain),{}))
                if cursor.get('live_block',-1)<=head:
                    watch.cursors = {**watch.cursors,str(chain):{**cursor,'live_block':head,
                        'live_hash':copy_mints.hex_value(block.hash),'live_checked_at':datetime.now(timezone.utc).isoformat()}}
            await db.commit()
        return [w['id'] for w in targets]
    finally:
        await web3.provider.disconnect()


def candidate(tx, addresses):
    if not isinstance(tx,dict) or str(tx.get('from','')).lower() not in addresses:
        return None
    if str(tx.get('to','')).lower()!=SEADROP_V1_ADDRESS.lower() or tx.get('blockHash') is not None:
        return None
    data = HexBytes(tx.get('input',tx.get('data',b'')))
    if len(data)<132 or data[:4].hex() not in (MINT_PUBLIC_SELECTOR,ALLOW_SELECTOR,SIGNED_SELECTOR):
        return None
    contract = to_checksum_address(decode(['address'],data[4:36])[0])
    return ('pending',copy_mints.hex_value(HexBytes(tx['hash'])),to_checksum_address(tx['from']),contract)


async def stream(url, chain, state, queue):
    """Request full transactions so unrelated hashes never fan out into RPC calls."""
    if urlparse(url).scheme!='wss':
        raise ValueError('Pending source feeds require TLS')
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url,heartbeat=20,max_msg_size=1024*1024,timeout=10) as ws:
            await ws.send_json({'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]})
            reply = await ws.receive_json(timeout=10)
            if int(reply.get('result','0x0'),16)!=chain:
                raise ValueError('Pending feed network mismatch')
            await ws.send_json({'jsonrpc':'2.0','id':2,'method':'eth_subscribe','params':['newPendingTransactions',True]})
            reply = await ws.receive_json(timeout=10)
            subscription = reply.get('result')
            if not isinstance(subscription,str):
                raise ValueError('Pending feed does not support full transaction subscriptions')
            seen, order = set(), deque()
            try:
                while True:
                    try:
                        message = await ws.receive_json(timeout=30)
                    except asyncio.TimeoutError:
                        if not any(w['active'] for w in state.get('watches',[])):
                            return
                        continue
                    params = message.get('params',{})
                    if params.get('subscription')!=subscription:
                        continue
                    tx = params.get('result')
                    if not isinstance(tx,dict):
                        raise ValueError('Pending feed returned hashes instead of full transactions')
                    addresses = {w['address'].lower() for w in state.get('watches',[]) if w['active']}
                    item = candidate(tx,addresses)
                    if item and item[1] not in seen and not queue.full():
                        queue.put_nowait(item)
                        seen.add(item[1]);order.append(item[1])
                        if len(order)>2048:
                            seen.remove(order.popleft())
            finally:
                if not ws.closed:
                    with suppress(Exception):
                        await asyncio.wait_for(ws.send_json({'jsonrpc':'2.0','id':3,'method':'eth_unsubscribe','params':[subscription]}),timeout=2)


async def chain_loop(factory, chain):
    state, queue, waiting = {}, asyncio.Queue(maxsize=64), set()
    def ready(watch_id):
        if watch_id not in waiting and not queue.full():
            queue.put_nowait(('ready',watch_id));waiting.add(watch_id)
    async def collect():
        delay = 2
        while True:
            try:
                for watch_id in await live_step(factory,chain,state):
                    ready(watch_id)
                delay = 2
            except Exception:
                log.warning('Live copy source check unavailable chain=%s',chain)
                delay = min(30,delay*2)
            await asyncio.sleep(delay)
    async def pending():
        url = getattr(settings,NETWORKS[chain].rpc_setting+'_WS','')
        if not settings.ENABLE_PENDING_COPY or not url:
            return
        delay = 5
        while True:
            if not any(w['active'] for w in state.get('watches',[])):
                await asyncio.sleep(2);continue
            try:
                await stream(url,chain,state,queue)
                delay = 5
            except Exception:
                log.warning('Pending copy source feed unavailable chain=%s; confirmed discovery remains active',chain)
            await asyncio.sleep(delay)
            delay = min(60,delay*2)
    async def consume():
        while True:
            item = await queue.get()
            try:
                if item[0]=='pending':
                    web3 = await automatic.provider_for(chain)
                    try:
                        for attempt in range(3):
                            try:
                                observation = await pending_copy.observe(web3,chain,*item[1:])
                                break
                            except TransactionNotFound:
                                if attempt==2:
                                    raise
                                await asyncio.sleep(0.5)
                    finally:
                        await web3.provider.disconnect()
                    for watch_id in await record(factory,chain,observation,pending=True):
                        ready(watch_id)
                else:
                    watch_id = item[1];waiting.discard(watch_id)
                    async with factory() as db:
                        from app.services import copy_checks
                        watch = await db.get(CopyWatch,watch_id)
                        if not watch or watch.archived_at or chain not in watch.chains:
                            continue
                        await copy_checks.process(db,watch,chain)
                        await db.commit()
                        await copy_mints.process_copy_events(db,watch_id,chain)
                        await db.commit()
            except Exception:
                log.warning('Early copy check deferred chain=%s; durable observations retained',chain)
            finally:
                queue.task_done()
    await asyncio.gather(collect(),pending(),consume())


async def run(factory=AsyncSessionLocal):
    await asyncio.gather(*(chain_loop(factory,row['chain_id']) for row in copy_mints.networks()))
