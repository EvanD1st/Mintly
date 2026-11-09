"""One eligibility selector shared by arming and observation-only measurements."""
from app.services.phase_identity import stage_kind


def eligible_phases(display,approval,mint_kinds):
    if not display['setup_enabled']:return []
    phases=[p for p in display['stages'] if p['eligibility']=='eligible' and p['timing']!='ended'
        and p.get('price_wei')=='0' and p.get('remaining') is not None
        and (p['remaining']>0 if approval.get('quantity_mode')=='wallet_max' else p['remaining']>=approval['quantity'])
        and stage_kind(p['type']) in mint_kinds]
    return sorted(phases,key=lambda p:(p['timing']!='open',stage_kind(p['type'])=='public',p['starts_at'],p['id']))
