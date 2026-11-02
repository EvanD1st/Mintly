"""Admin-approved recovery using the existing password sign-in screen."""
import re
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from app.models import AccountRecoveryCode, ActivityEvent, User
from app.services.auth import token_digest
from app.services.mint_plans import aware

CODE_PATTERN = re.compile(r'MRC-[A-Za-z0-9_-]{32}')


async def issue_recovery_code(db, user, admin):
    """Caller holds the member row lock and has freshly verified the admin."""
    now = datetime.now(timezone.utc)
    await db.execute(update(AccountRecoveryCode).where(
        AccountRecoveryCode.user_id == user.id,
        AccountRecoveryCode.used_at.is_(None),
        AccountRecoveryCode.revoked_at.is_(None),
    ).values(revoked_at=now))
    code = 'MRC-' + secrets.token_urlsafe(24)
    expires_at = now + timedelta(minutes=10)
    db.add(AccountRecoveryCode(user_id=user.id, issued_by=admin.id,
        code_hash=token_digest(code), expires_at=expires_at))
    for owner, detail in ((admin.id, f'Recovery code issued for {user.username}.'),
                          (user.id, f'Recovery code authorized by {admin.username}.')):
        db.add(ActivityEvent(user_id=owner, event_type='account_recovery_issued',
            label='Account recovery authorized', detail=detail, icon_name='key', is_demo=False))
    return code, expires_at


async def consume_recovery_code(db, user, code):
    """Caller holds the member lock; consumption and session issuance commit together."""
    now = datetime.now(timezone.utc)
    row = await db.scalar(select(AccountRecoveryCode).where(
        AccountRecoveryCode.user_id == user.id,
        AccountRecoveryCode.code_hash == token_digest(code),
    ))
    if not row or row.used_at or row.revoked_at or aware(row.expires_at) <= now:
        return False
    # Member -> administrator -> code is also the issuance lock order. This
    # serializes administrator revocation without cross-account FK deadlocks.
    issuer = await db.scalar(select(User).where(User.id == row.issued_by).with_for_update()
        .execution_options(populate_existing=True))
    if (not issuer or issuer.role != 'admin' or not issuer.is_active
            or issuer.deleted_at or issuer.must_change_password):
        return False
    row = await db.scalar(select(AccountRecoveryCode).where(AccountRecoveryCode.id == row.id)
        .with_for_update().execution_options(populate_existing=True))
    now = datetime.now(timezone.utc)
    if row.used_at or row.revoked_at or aware(row.expires_at) <= now:
        return False
    row.used_at = now
    db.add(ActivityEvent(user_id=user.id, event_type='account_recovery_used',
        label='Recovery sign-in completed',
        detail=f'Signed in with a one-time code authorized by {issuer.username}. Password unchanged.',
        icon_name='key', is_demo=False))
    db.add(ActivityEvent(user_id=issuer.id, event_type='account_recovery_used',
        label='Recovery sign-in completed', detail=f'{user.username} used the authorized recovery code.',
        icon_name='key', is_demo=False))
    return True
