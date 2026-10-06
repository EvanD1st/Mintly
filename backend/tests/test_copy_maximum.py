"""Maximum free quantity reads on-chain capacity and includes all quoted fees."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eth_abi import encode
import pytest
from fastapi import HTTPException
from app.services import copy_mints

@pytest.mark.parametrize("chain,fee,accepted",[(1,9,True),(4663,9,True),(8453,11,False)])
async def test_maximum_free_execution_ceiling_and_full_fee_quote(monkeypatch,chain,fee,accepted):
 rule=dict(quantity_mode="max_free",free_only=True,quantity=100,price_cap_wei=0,fee_cap_wei=10,account="0x"+"1"*40)
 stage=dict(price_wei=0,start=1,end=100,limit=300)
 observation=dict(contract="0x"+"2"*40,chain_id=chain,**stage)
 web3=SimpleNamespace(eth=SimpleNamespace(call=AsyncMock(return_value=encode(["uint256"]*3,[0,1,1000])),get_balance=AsyncMock(return_value=20)))
 monkeypatch.setattr(copy_mints,"public_stage",AsyncMock(return_value=stage))
 prepare=AsyncMock(return_value={"target":"0x"+"3"*40,"data":"0x1234","value":"0"})
 monkeypatch.setattr(copy_mints.automatic,"prepare_mint",prepare)
 monkeypatch.setattr(copy_mints,"quote_gas",AsyncMock(return_value=(1,1)))
 quoted=AsyncMock(return_value=fee);monkeypatch.setattr(copy_mints,"maximum_fee",quoted)
 if accepted: assert await copy_mints.maximum_free_quantity(web3,observation,rule)==100
 else:
  with pytest.raises(HTTPException,match="network-fee limit"): await copy_mints.maximum_free_quantity(web3,observation,rule)
 assert prepare.call_args.args[1]["quantity"]==100
 assert quoted.call_args.args[2]==chain
 web3.eth.get_balance.assert_awaited_once_with(rule["account"],"pending")
