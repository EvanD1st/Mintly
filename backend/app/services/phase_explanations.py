"""Safe display explanations; these helpers never alter mint authorization."""
LEGACY_TERMS_NOTES=frozenset((
    'The approved phase price, method or allowance changed. Review this mint again.',
    'The collection or network changed. Review this mint again.',
    'The approved phase was removed or cannot be identified. Review this mint again.',
    'The approved mint method changed. Review this mint again.',
    'The phase opening moved beyond your approved deadline. Review this mint again.',
))
PREFIXES=('Public mint price changed from ','Mint price changed from ',
    'Public mint price can no longer be verified.','Mint price can no longer be verified.',
    'Mint method changed from ','Stage wallet limit changed from ')


def is_terms_change(note):
    return isinstance(note,str) and len(note)<=1500 and (note in LEGACY_TERMS_NOTES or note.startswith(PREFIXES))


def price(value,currency):
    if value is None:return 'an unverified price'
    if value==0:return 'free'
    whole,fraction=divmod(value,10**18)
    decimal=str(whole)+(('.'+str(fraction).zfill(18).rstrip('0')) if fraction else '')
    return f'{decimal} {currency}'


def explain(approved,actual,chain_id,*,free_only=False):
    from app.services.networks import symbol
    currency=symbol(chain_id)
    label='Public mint' if approved['type']=='public_sale' else 'Mint'
    changes=[]
    if actual['price_wei']!=approved['price_wei']:
        if actual['price_wei'] is None:
            changes.append(f'{label} price can no longer be verified.')
        else:
            changes.append(f"{label} price changed from {price(approved['price_wei'],currency)} to {price(actual['price_wei'],currency)} per NFT.")
    if actual['type']!=approved['type']:
        methods={'public_sale':'public','allowlist':'whitelist','signed_presale':'signed whitelist'}
        before=methods.get(approved['type'],'the approved method')
        after=methods.get(actual['type'],'another mint method')
        changes.append(f'Mint method changed from {before} to {after}.')
    if actual['max_per_wallet']!=approved['max_per_wallet']:
        changes.append(f"Stage wallet limit changed from {approved['max_per_wallet']} to {actual['max_per_wallet']} NFTs.")
    if not changes:return None
    stopped='Free-only mint stopped.' if free_only and actual['price_wei'] is not None and actual['price_wei']>0 else 'Mint stopped.'
    return ' '.join(changes+[stopped,'Review the updated stage.'])
