"""Canonical phase comparisons without changing persisted authorization hashes."""
from uuid import UUID

def stage_key(value):
    try:return UUID(value).hex
    except (ValueError,TypeError,AttributeError):return value

def stage_kind(value):
    return {'public':'public','public_sale':'public','signed_presale':'signed','signed_sale':'signed','signed':'signed',
            'allowlist':'allowlist','allowlist_sale':'allowlist','allowlist_presale':'allowlist'}.get(value)

def stage_type(value):
    return {'public':'public_sale','signed':'signed_presale','allowlist':'allowlist'}.get(stage_kind(value),value)

def normalized(value):
    result=dict(value)
    result['uuid']=stage_key(result.get('uuid'))
    result['type']=stage_type(result.get('type'))
    return result

def same_phase(actual,approved):
    return normalized(actual)==normalized(approved)

def schedule_matches(stage,approved,pin):
    actual=pin(stage)
    if 'schedule_price_wei' in approved:
        expected={k:v for k,v in approved.items() if k not in ('schedule_price_wei','wallet_total_limit')}
        expected['price_wei']=approved['schedule_price_wei']
        return same_phase(actual,expected)
    return same_phase(actual,approved)
