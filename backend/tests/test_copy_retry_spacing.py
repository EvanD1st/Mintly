from datetime import datetime, timedelta, timezone
from app.services.copy_retry import next_copy_retry


def test_backoff_and_stagger_do_not_shorten_provider_cooldown():
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=1)
    waits = [(next_copy_retry(now, deadline, n, 'jenny') - now).total_seconds() for n in (1, 2, 3, 4, 50)]
    assert 60 <= waits[0] <= 75
    assert 120 <= waits[1] <= 135
    assert 240 <= waits[2] <= 255
    assert 300 <= waits[3] <= 315
    assert waits[3] == waits[4]
    assert next_copy_retry(now, deadline, 50, 'jenny', 900) == now + timedelta(seconds=900)
    assert next_copy_retry(now, deadline, 50, 'jenny') != next_copy_retry(now, deadline, 50, 'user')


def test_phase_or_approval_deadline_never_extended():
    now = datetime.now(timezone.utc)
    for remaining in (0, 10, 59, 180):
        deadline = now + timedelta(seconds=remaining)
        assert next_copy_retry(now, deadline, 50, 'event', 900) == deadline


def test_expensive_future_stage_does_not_block_free_signed_stage():
    from app.services.opensea import stage_schedule, transaction_value_wei, OpenSeaUnavailable
    import pytest
    common = dict(start_time='2026-10-12T17:00:00Z', end_time='2026-10-12T18:00:00Z',
                  max_per_wallet='1', price_currency_address='0x' + '0' * 40)
    stages = stage_schedule({'stages': [
        dict(common, uuid='future', stage_type='public_sale', price=str(100 * 10**18),
             start_time='2026-10-12T18:00:00Z', end_time='2026-10-13T18:00:00Z'),
        dict(common, uuid='fcfs', stage_type='signed_presale', price='0')]})
    assert stages[0]['uuid'] == 'fcfs' and stages[0]['price_wei'] == 0
    assert stages[1]['price_wei'] == 100 * 10**18
    with pytest.raises(OpenSeaUnavailable):
        transaction_value_wei(str(100 * 10**18))
    for price in (-1, 2**256):
        with pytest.raises(OpenSeaUnavailable):
            stage_schedule({'stages': [dict(common, uuid='bad', stage_type='public_sale', price=str(price))]})
