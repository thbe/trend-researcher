"""Password hashing utilities using bcrypt directly."""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def normalize_username(raw: str) -> str:
    """Canonical username form: stripped + lowercased.

    Applied at every entry point (login, user create, password reset, seed)
    so that ``Admin@app.local`` and ``admin@app.local`` resolve to the same
    account. Stored values are always the normalised form — the unique
    index on ``users.username`` then enforces case-insensitive uniqueness.
    """
    return raw.strip().lower()


__all__ = ["hash_password", "verify_password", "normalize_username"]
