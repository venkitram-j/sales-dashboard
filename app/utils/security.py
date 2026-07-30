"""Password hashing + session token helpers.

Uses bcrypt directly (rather than passlib, which is effectively unmaintained
and has compatibility issues with recent bcrypt releases). bcrypt has a
72-byte input limit; passwords are UTF-8 encoded and truncated defensively
to stay under that limit rather than silently failing.
"""
from __future__ import annotations

import hashlib
import secrets

import bcrypt

_MAX_PASSWORD_BYTES = 72


def _prepare(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        encoded = encoded[:_MAX_PASSWORD_BYTES]
    return encoded


def hash_password(password: str) -> str:
    """Returns a bcrypt hash (including its salt) as a str, safe to store."""
    hashed = bcrypt.hashpw(_prepare(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time comparison of a plaintext password against a stored hash."""
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/legacy hash -- fail closed.
        return False


def hash_session_token(raw_token: str) -> str:
    """SHA-256 of a session token. Session tokens are already high-entropy
    random values (not user-chosen secrets), so a fast cryptographic hash
    is appropriate here -- unlike passwords, which need bcrypt's slowness.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_session_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash) for a new 'remember me' session.

    Only token_hash is ever persisted to the database; raw_token is sent to
    the browser (as a cookie) and never stored server-side in that form, so
    a database leak alone can't be used to forge sessions.
    """
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_session_token(raw_token)
