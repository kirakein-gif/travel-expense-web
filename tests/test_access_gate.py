from app.services.access_service import (
    create_session_token,
    owner_key_matches,
    verify_session_token,
)


def test_signed_session_is_valid_and_expires():
    secret = "owner-key-for-test"
    token = create_session_token(secret, now=1000)
    assert verify_session_token(token, secret, now=1001)
    assert not verify_session_token(token, "wrong-key", now=1001)
    assert not verify_session_token(token, secret, now=1000 + 12 * 60 * 60 + 1)


def test_owner_key_comparison():
    assert owner_key_matches("abc123", "abc123")
    assert not owner_key_matches("abc123", "ABC123")
    assert not owner_key_matches("", "abc123")
