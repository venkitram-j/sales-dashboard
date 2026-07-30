from __future__ import annotations

from app.utils.security import generate_session_token, hash_session_token


def test_generate_session_token_returns_raw_and_hash():
    raw, hashed = generate_session_token()
    assert raw != hashed
    assert len(raw) > 20
    assert hashed == hash_session_token(raw)


def test_tokens_are_unique():
    raw1, _ = generate_session_token()
    raw2, _ = generate_session_token()
    assert raw1 != raw2


def test_hash_session_token_is_deterministic():
    raw, _ = generate_session_token()
    assert hash_session_token(raw) == hash_session_token(raw)


def test_hash_session_token_is_sha256_hex():
    raw, hashed = generate_session_token()
    assert len(hashed) == 64
    int(hashed, 16)  # raises if not valid hex
