"""Shared read model and retry decisions; execution records remain authoritative."""
ACTIVE = frozenset(('armed','preparing','prepared','submitting','submitted','uncertain'))
TERMINAL = frozenset(('confirmed','reverted','failed','expired','disarmed','already_minted'))
MARKET_REASONS = frozenset(('auto_arm_gas_limit','supply_exhausted','wallet_not_allowlisted','wallet_limit','allowance_or_supply_exhausted',
    'stage_not_active','insufficient_funds','creator_payout_missing','terms_changed','wrong_phase'))
OPERATOR_REASONS = frozenset(('api_key_unavailable','api_access_denied','upstream_access_denied','wallet_approval_changed'))
SERVICE_REASONS = frozenset(('timeout','network_error','invalid_response','upstream_server_error','upstream_rate_limited',
    'signer_timeout','signer_connection_error','rpc_unavailable','api_key_unavailable','api_access_denied','upstream_access_denied'))


def reason_text(code):
    from app.services.mint_diagnostics import PREPARATION_REASONS
    return PREPARATION_REASONS.get(code) or {
        'arming_unavailable':'Mint setup is temporarily unavailable.',
        'arming_rejected':'Mint setup was rejected. Review the wallet approval and selected stage.',
        'arming_error':'Mint setup could not complete. Operator review is needed.',
        'incomplete_check':'Collection details are incomplete. Wait for a verified eligibility check.',
        'upstream_access_denied':'OpenSea denied API access. Operator review is needed.',
        'signer_timeout':'The signer response timed out. Check task status before retrying.',
        'signer_connection_error':'The signer could not be reached.',
        'temporary_checks_unavailable':'Copy checks are temporarily unavailable. Mintly will retry within the approved phase.',
        'temporary_preparation_error':'Copy preparation is temporarily unavailable. Mintly will retry within the approved phase.',
        'validation_rejected':'The stage, source transaction or receiving wallet checks rejected this copy. Review its eligibility and approval.',
    }.get(code,(code or 'Unknown reason').replace('_',' '))


def reason_from_note(note):
    from app.services.mint_diagnostics import PREPARATION_REASONS
    from app.services.phase_explanations import is_terms_change
    if is_terms_change(note):return 'terms_changed'
    for code,text in PREPARATION_REASONS.items():
        if note in (text,text+' Checks stopped. No transaction was sent.'):return code
    return {'This collection is sold out. No transaction sent.':'supply_exhausted',
        'This collection is sold out. No transaction was sent.':'supply_exhausted'}.get(note)


def read_model(task):
    from app.services.mint_diagnostics import public_note
    status=task.status
    reason=reason_from_note(getattr(task,'failure_reason',None))
    label={'armed':'Armed','preparing':'Preparing mint','prepared':'Mint prepared',
        'submitting':'Submitting mint','submitted':'Mint submitted','uncertain':'Checking transaction',
        'confirmed':'Minted','already_minted':'Already minted','reverted':'Transaction reverted',
        'failed':'Mint stopped','expired':'Mint window ended','disarmed':'Mint paused or cancelled'}.get(status,'Checking mint status')
    if status in ('failed','expired') and reason=='supply_exhausted':label='Sold out'
    if status in ('failed','expired') and reason=='terms_changed':label='Mint terms changed'
    return {'status':status,'label':label,'terminal':status in TERMINAL,'active':status in ACTIVE,
        'reason_code':reason,'detail':public_note(getattr(task,'failure_reason',None)),
        'task_id':getattr(task,'id',None),'source':'execution_record'}


def preparation_disposition(status,reason,attempt,maximum,*,copy=False,transport_error=False):
    """Preserve bounded copy/automatic behavior with one reason-aware decision."""
    permanent=status==409 and reason not in ('wallet_limit','allowance_or_supply_exhausted')
    temporary=transport_error or status in (429,500,502,503,504)
    exhausted=(not temporary and attempt>=6) if copy else attempt>=max(1,maximum)
    return permanent,exhausted
