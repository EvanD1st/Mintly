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
                            transaction_out: dict | None = None, db=None) -> MintPlan:
    """The only path to ready_for_approval is a successful OpenSea mint check."""
    now = now or datetime.now(timezone.utc)
    client = client or OpenSeaClient()
    detail = detail or await client.get_drop(plan.collection_slug)
    chain_id, chain_label = CHAINS[detail["chain"]]
    if (chain_id != plan.chain_id or detail["contract_address"].lower() != plan.contract_address.lower()
            or wallet.user_id != plan.user_id or wallet.id != plan.wallet_id):
        raise OpenSeaUnavailable("Drop contract, chain, or wallet changed; review this plan again.", 409)
    previous_stage = tuple(getattr(plan, key, None) for key in ('stage_uuid', 'starts_at', 'ends_at', 'price_wei'))
    def invalidate_context():
        if (plan.stage_uuid, aware(plan.starts_at), aware(plan.ends_at), plan.price_wei) != (
                previous_stage[0], aware(previous_stage[1]), aware(previous_stage[2]), previous_stage[3]):
            plan.automatic_drop_id, plan.automatic_stage_id = None, None
    stages = stage_schedule(detail)
    active = [stage for stage in stages if stage["starts_at"] <= now < stage["ends_at"]]
    future = [stage for stage in stages if stage["starts_at"] > now]
    selected = active[0] if active else future[0] if future else None
    if getattr(plan,'selected_stage',None):
        from app.services.mint_stage_choice import pinned
        selected=next((stage for stage in stages if stage['uuid']==plan.selected_stage['uuid']),None)
        if not selected or pinned(selected)!=plan.selected_stage:
            plan.status='unverified';plan.status_note='Your selected phase changed. Review its details again.'
            plan.automatic_drop_id=plan.automatic_stage_id=None
            return plan
        active=[selected] if selected['starts_at']<=now<selected['ends_at'] else []
        future=[selected] if selected['starts_at']>now else []

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
            plan.status_note = ("Whitelist phase is scheduled. Check wallet eligibility in Choose mint phase; mint instructions are checked when it opens."
                                if selected["type"] != "public_sale" else
                                "Public stage is scheduled; wallet readiness will be checked when it opens.")
            if db is not None and selected["type"] != "public_sale" and plan.id:
                try:
                    from app.services.mint_stage_choice import stages as wallet_stages
                    result,_=await wallet_stages(db,plan,plan.user_id)
                    item=next((row for row in result['stages'] if row['id']==selected['uuid']),None)
                    if item and item['eligibility']=='eligible':
                        plan.status_note=f"{selected['name'].strip()} eligibility verified. Waiting for the stage to open."
                    elif item and item['eligibility']=='not_eligible':
                        plan.status_note=f"This wallet is not eligible for {selected['name'].strip()}. Choose another phase."
                    elif result.get('note'):
                        plan.status_note=result['note']
                except Exception:
                    pass  # Verification failure must never become invented eligibility.
            plan.next_check_at = selected["starts_at"]
        else:
            plan.status = "ended"
            plan.status_note = "OpenSea reports no active or upcoming mint stage."
            plan.next_check_at = None
        invalidate_context()
        return plan

    try:
        status, transaction = await client.build_mint(plan.collection_slug, wallet.address, plan.quantity or 1)
    except OpenSeaUnavailable as error:
        if error.status != 503:
            raise
        plan.status = "unverified"
        plan.status_note = str(error)
        plan.next_check_at = now + timedelta(minutes=5)
        invalidate_context()
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
        chosen=selected
        if transaction['data'][2:10].lower() in (ALLOW_SELECTOR,SIGNED_SELECTOR):
            mint=decode_mint(transaction,plan.contract_address,wallet.address,plan.quantity)
            selected=match_stage(mint,stages if getattr(plan,'selected_stage',None) else active)
            if getattr(plan,'selected_stage',None) and selected['uuid']!=plan.selected_stage['uuid']:
                plan.status='not_ready';plan.status_note='OpenSea prepared another phase. Mintly will not switch your selected phase.'
                return plan
            plan.stage_uuid=selected['uuid'];plan.stage_name=selected['name'];plan.stage_type=selected['type']
            plan.starts_at=selected['starts_at'];plan.ends_at=selected['ends_at'];plan.price_wei=selected['price_wei']
        elif transaction['data'][2:10].lower() == MINT_PUBLIC_SELECTOR:
            public=[stage for stage in active if stage['type']=='public_sale']
            if len(public)!=1:raise OpenSeaUnavailable('The selected phase is not the public phase returned by OpenSea.',409)
            if getattr(plan,'selected_stage',None) and public[0]['uuid']!=plan.selected_stage['uuid']:
                plan.status='not_ready';plan.status_note='OpenSea prepared another phase. No public fallback is allowed.'
                return plan
            selected=public[0]
            plan.stage_uuid=selected['uuid'];plan.stage_name=selected['name'];plan.stage_type=selected['type']
            plan.starts_at=selected['starts_at'];plan.ends_at=selected['ends_at'];plan.price_wei=selected['price_wei']
        plan.status = "ready_for_approval"
        plan.status_note = "OpenSea prepared this wallet’s mint. Review automatic signing access and spending limits before confirming."
        plan.mint_value_wei = value
        plan.estimated_network_fee_wei = await estimate_network_fee(transaction, wallet.address, detail["chain"])
        if transaction_out is not None:
            transaction_out.update(transaction)
        plan.next_check_at = plan.ends_at
        invalidate_context()
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
    invalidate_context()
    return plan
