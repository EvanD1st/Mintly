"""Schedule and recheck OpenSea mint opportunities without signing for users."""

from datetime import datetime, timedelta, timezone

from app.models import MintPlan, Wallet
from app.services.opensea import CHAINS, OpenSeaClient, OpenSeaUnavailable, estimate_network_fee, stage_schedule


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def refresh_mint_plan(plan: MintPlan, wallet: Wallet, client: OpenSeaClient | None = None,
                            now: datetime | None = None, detail: dict | None = None) -> MintPlan:
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

    status, transaction = await client.build_mint(plan.collection_slug, wallet.address)
    if status == 200 and transaction is not None:
        if transaction.get("chain") != detail["chain"]:
            raise OpenSeaUnavailable("OpenSea returned a different mint chain.")
        value = int(transaction["value"], 16)
        max_active_price = max((stage["price_wei"] or 0) for stage in active)
        if value > max_active_price or value >= 2**63:
            raise OpenSeaUnavailable("Mint value exceeds the verified active-stage price.")
        plan.status = "ready_for_approval"
        plan.status_note = "OpenSea prepared this wallet's mint. Approve the transaction in MetaMask."
        plan.mint_value_wei = value
        plan.price_wei = value
        if len(active) > 1:
            plan.stage_name = "Eligible active stage"
        plan.estimated_network_fee_wei = await estimate_network_fee(transaction, wallet.address, detail["chain"])
        plan.next_check_at = min(stage["ends_at"] for stage in active)
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
