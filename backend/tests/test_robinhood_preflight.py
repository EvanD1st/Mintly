from decimal import Decimal
import pytest
from app.robinhood_preflight import usd_cap_wei, padded_gas


def test_usd_cap_rounds_down_and_nitro_data_gas_is_not_added_twice():
    cap = usd_cap_wei('0.50', '2728.29')
    price = Decimal('2728.29')
    assert Decimal(cap) * price / 10**18 <= Decimal('0.50')
    assert Decimal(cap + 1) * price / 10**18 > Decimal('0.50')
    assert padded_gas(100000, 110000, 30000) == 132000


@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity'])
def test_invalid_reference_price_cannot_generate_a_budget(value):
    with pytest.raises(ValueError):
        usd_cap_wei('0.50', value)


def test_inconsistent_l1_component_is_rejected():
    with pytest.raises(ValueError):
        padded_gas(100000, 100000, 100001)
