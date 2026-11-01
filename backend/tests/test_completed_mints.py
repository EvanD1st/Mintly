"""Receipt reconciliation must never infer a phase from ownership or a 422."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from eth_abi import encode
from hexbytes import HexBytes
import pytest
from web3.datastructures import AttributeDict

from app.services import completed_mints
from app.services.seadrop_mint import SIGNED_SELECTOR, PARAM_TYPE
from app.services.signer.base import SEADROP_V1_ADDRESS


@pytest.fixture
def chain():
    account, contract, fee = ['0x' + value * 40 for value in ('1','2','3')]
    scope = dict(account=account, contract=contract, chain_id=31337, stage_name='GTD',
        mint_kind='signed', start=1000, end=3000, price_wei=0, quantity=1,
        onchain_stage_index=2, selected_phase={'wallet_total_limit':1})
    params = (0,1,1000,3000,2,720,0,False)
    data = '0x' + SIGNED_SELECTOR + encode(['address','address','address','uint256',PARAM_TYPE,'uint256','bytes'],
        [contract,fee,account,1,params,7,bytes(65)]).hex()
    tx_hash, block_hash = HexBytes('0x'+'a'*64), HexBytes('0x'+'b'*64)
    log = AttributeDict(dict(address=contract, topics=[HexBytes(completed_mints.TRANSFER),HexBytes(bytes(32)),
        HexBytes(bytes.fromhex(account[2:].rjust(64,'0'))),HexBytes((1).to_bytes(32,'big'))],
        blockNumber=100, blockHash=block_hash, transactionHash=tx_hash, logIndex=0))
    receipt = AttributeDict(dict(status=1, blockNumber=100, blockHash=block_hash, logs=[log]))
    tx = AttributeDict(dict(to=SEADROP_V1_ADDRESS, input=HexBytes(data), value=0, **{'from':account}))
    state = SimpleNamespace(scope=scope, params=params, receipt=receipt, tx=tx, minted=1,
        canonical=True, finalized=True, log=log)
    class Eth:
        @property
        async def block_number(self):return 110
        async def call(self, request):return encode(['uint256']*3,[state.minted,200,720])
        async def get_block(self, number):
            return AttributeDict(dict(number=108 if number=='finalized' and state.finalized else 99 if number=='finalized'
                else 110 if number=='latest' else number, timestamp=2000 if number else 0,
                hash=block_hash if state.canonical else HexBytes(bytes(32))))
        get_logs = AsyncMock(return_value=[log])
        async def get_transaction_receipt(self, value):return state.receipt
        async def get_transaction(self, value):return state.tx
    state.web3 = SimpleNamespace(eth=Eth())
    return state


async def test_exact_finalized_mint_is_separate_public_evidence(chain):
    found = await completed_mints.find_completed_mint(chain.web3, chain.scope)
    assert found['stage_name']=='GTD' and found['stage_index']==2 and found['quantity']==1
    assert found['transaction_hash']=='0x'+'a'*64
    assert found['wallet_minted']==found['wallet_total_limit']==1
    assert 'signature' not in str(found) and 'execution' not in found


@pytest.mark.parametrize('case',['remaining','wrong_phase','wrong_wallet','failed','reorg','unfinalized','transfer'])
async def test_insufficient_or_unrelated_evidence_cannot_stop_retries(chain, case):
    if case=='remaining':chain.scope['selected_phase']['wallet_total_limit']=2
    if case=='wrong_phase':chain.scope['onchain_stage_index']=3
    if case=='wrong_wallet':chain.scope['account']='0x'+'4'*40
    if case=='failed':chain.receipt=AttributeDict({**chain.receipt,'status':0})
    if case=='reorg':chain.canonical=False
    if case=='unfinalized':
        chain.scope['chain_id']=4663
        chain.finalized=False
    if case=='transfer':
        transfer=AttributeDict({**chain.log,'topics':[chain.log.topics[0],HexBytes('0x'+'c'*64),*chain.log.topics[2:]]})
        chain.receipt=AttributeDict({**chain.receipt,'logs':[transfer]})
    assert await completed_mints.find_completed_mint(chain.web3,chain.scope) is None


async def test_provider_or_history_failure_does_not_invent_completion(monkeypatch, chain):
    provider=AsyncMock(side_effect=RuntimeError('unavailable'))
    monkeypatch.setattr('app.services.network_reads.provider_for',provider)
    assert await completed_mints.reconcile_rejection(chain.scope,[]) is None
    provider.assert_not_called()
    assert await completed_mints.reconcile_rejection(chain.scope,[], 'wallet_limit') is None
    provider.assert_awaited_once()


async def test_today_uses_completed_evidence_without_new_eligibility_work(test_db,monkeypatch):
    from test_today_armed import armed_fixture
    from app.api.drops import list_drops
    from app.services.feed_checks import queue_checks
    from app.models import FeedWalletCheck
    from sqlalchemy import select,func
    users,wallets,drop,task,auth=await armed_fixture(test_db,monkeypatch)
    task.status='already_minted'
    task.external_mint={'quantity':1,'stage_name':'Approved GTD','minted_at':'2026-11-01T17:30:01+00:00'}
    await test_db.commit()
    await queue_checks(test_db,users[0],wallets[0],[drop])
    result=await list_drops('all',users[0],test_db,wallet_id=wallets[0].id,daily_only=True)
    assert result.drops[0].automatic_mint['status']=='already_minted'
    assert result.drops[0].automatic_mint['quantity']==1
    assert 'already minted' in result.drops[0].wallet_check['note']
    assert not result.drops[0].wallet_check['setup_enabled']
    assert await test_db.scalar(select(func.count()).select_from(FeedWalletCheck))==0
