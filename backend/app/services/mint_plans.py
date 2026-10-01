"""Schedule and recheck OpenSea mint opportunities without signing for users."""

from datetime import datetime, timedelta, timezone

from app.services.signer.base import MINT_PUBLIC_SELECTOR
from app.models import MintPlan, Wallet
from app.services.price_quote import eth_usdt_quote
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable, estimate_network_fee, stage_schedule, transaction_value_wei


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def refresh_mint_plan(plan: MintPlan, wallet: Wallet, client: OpenSeaClient | None = None,
                            now: datetime | None = None, detail: dict | None = None,
                            transaction_out: dict | None = None) -> MintPlan:
    """The only path to ready_for_approval is a successful OpenSea mint check."""
    now = now or datetime.now(timezone.utc)
    client = client or OpenSeaClient()
    detail = detail or await client.get_drop(plan.collection_slug)
    chain_id, chain_label = CHAINS[detail["chain"]]
    if (chain_id != plan.chain_id or detail["contract_address"].lower() != plan.contract_address.lower()
            or wallet.user_id != plan.user_id or wallet.id != plan.wallet_id):
        raise OpenSeaUnavailable("Drop contract, chain, or wallet changed; review this plan again.", 409)
    stages = stage_schedule(detail)
    active = [stage for stage in stages if stage["starts_at"] <= now < stage["ends_at"]]
    future = [stage for stage in stages if stage["starts_at"] > now]
    selected = active[0] if active else future[0] if future else None

    plan.collection_name = str(detail.get("collection_name") or plan.collection_slug)[:150]
    plan.chain = chain_label
    plan.last_checked_at = now
    plan.stage_uuid = selected["uuid"] if selected else None
    plan.stage_name = selected["name"] if selected else None
    plan.stage_type = selected["type"] if selected else None
    plan.starts_at = selected["starts_at"] if selected else None
    plan.ends_at = selected["ends_at"] if selected else None
    plan.price_wei = selected["price_wei"] if selected else None
    plan.mint_value_wei = None
    plan.estimated_network_fee_wei = None
    quote = await eth_usdt_quote()
    plan.eth_usdt_rate = quote[0] if quote else None
    plan.rate_checked_at = quote[1] if quote else None

    if not active:
        if future:
            plan.status = "scheduled"
            plan.status_note = ("Allowlist eligibility cannot be confirmed until its stage opens."
                                if selected["type"] != "public_sale" else
                                "Public stage is scheduled; wallet readiness will be checked when it opens.")
            plan.next_check_at = selected["starts_at"]
        else:
            plan.status = "ended"
            plan.status_note = "OpenSea reports no active or upcoming mint stage."
            plan.next_check_at = None
        return plan

    try:
        status, transaction = await client.build_mint(plan.collection_slug, wallet.address, plan.quantity or 1)
    except OpenSeaUnavailable as error:
        if error.status != 503:
            raise
        plan.status = "unverified"
        plan.status_note = str(error)
        plan.next_check_at = now + timedelta(minutes=5)
        return plan
    if status == 200 and transaction is not None:
        if transaction.get("chain") != detail["chain"]:
            raise OpenSeaUnavailable("OpenSea returned a different mint chain.")
        value = transaction_value_wei(transaction["value"])
        max_active_price = max((stage["price_wei"] or 0) for stage in active) * (plan.quantity or 1)
        if value > max_active_price or value >= 2**63:
            raise OpenSeaUnavailable("Mint value exceeds the verified active-stage price.")
        # OpenSea chooses the first *eligible* active stage, which need not be
        # the first entry in the schedule. Bind presale params to that stage.
        from app.services.seadrop_mint import decode_mint, match_stage, ALLOW_SELECTOR, SIGNED_SELECTOR
        if transaction['data'][2:10].lower() in (ALLOW_SELECTOR,SIGNED_SELECTOR):
            mint=decode_mint(transaction,plan.contract_address,wallet.address,plan.quantity)
            selected=match_stage(mint,active)
            plan.stage_uuid=selected['uuid'];plan.stage_name=selected['name'];plan.stage_type=selected['type']
            plan.starts_at=selected['starts_at'];plan.ends_at=selected['ends_at'];plan.price_wei=selected['price_wei']
        elif transaction['data'][2:10].lower() == MINT_PUBLIC_SELECTOR:
            public=[stage for stage in active if stage['type']=='public_sale']
            if len(public)!=1:raise OpenSeaUnavailable('The eligible public stage is ambiguous.',409)
            selected=public[0]
            plan.stage_uuid=selected['uuid'];plan.stage_name=selected['name'];plan.stage_type=selected['type']
            plan.starts_at=selected['starts_at'];plan.ends_at=selected['ends_at'];plan.price_wei=selected['price_wei']
        plan.status = "ready_for_approval"
        plan.status_note = "OpenSea prepared this wallet's mint. Approve the transaction in MetaMask."
        plan.mint_value_wei = value
        plan.estimated_network_fee_wei = await estimate_network_fee(transaction, wallet.address, detail["chain"])
        if transaction_out is not None:
            transaction_out.update(transaction)
        plan.next_check_at = plan.ends_at
        return plan

    if status == 422:
        plan.status = "not_ready"
        plan.status_note = "OpenSea could not prepare this wallet's mint. Check allowlist, balance, limit, and supply."
    else:
        plan.status = "scheduled"
        plan.status_note = "The OpenSea mint stage is not currently active."
    # A later allowlist or public stage can make the wallet mintable.
    plan.next_check_at = min(now + timedelta(minutes=5),
                             future[0]["starts_at"] if future else active[-1]["ends_at"])
    if plan.next_check_at <= now:
        plan.next_check_at = now + timedelta(minutes=5)
    return plan
