"""Password and opaque bearer-session primitives."""

import hashlib
import secrets

from argon2 import PasswordHasher, exceptions
from argon2.low_level import Type


_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
_dummy_hash = _hasher.hash(secrets.token_urlsafe(24))


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be 12 to 256 characters long.")
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _dummy_hash, password)
    except (exceptions.VerificationError, exceptions.InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(24)
