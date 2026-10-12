"""Exact cumulative native budgets, including values above signed 64-bit wei."""
from decimal import Decimal
from sqlalchemy import Numeric, String
from sqlalchemy.types import TypeDecorator


class BudgetWei(TypeDecorator):
    impl = Numeric(30, 0)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        # SQLite NUMERIC affinity may round large integers to floating point.
        return dialect.type_descriptor(String(30) if dialect.name == 'sqlite' else Numeric(30, 0))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        integer = int(value)
        if integer != value or not 0 <= integer < 10**30:
            raise ValueError('Invalid exact native budget')
        return f'{integer:030d}' if dialect.name == 'sqlite' else Decimal(integer)

    def process_result_value(self, value, dialect):
        return int(value) if value is not None else None
