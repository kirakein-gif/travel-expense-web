from app.services.access_service import (
    create_session_token,
    is_allowed_referer,
    owner_key_matches,
    verify_session_token,
)


def test_accepts_short_guide_url():
    assert is_allowed_referer("https://bbs.ckwiki.kr/relese/73")
    assert is_allowed_referer("https://bbs.ckwiki.kr/relese/73/")


def test_accepts_board_php_guide_url():
    assert is_allowed_referer(
        "https://bbs.ckwiki.kr/bbs/board.php?bo_table=relese&wr_id=73"
    )
    assert is_allowed_referer(
        "https://bbs.ckwiki.kr/bbs/board.php?wr_id=73&bo_table=relese"
    )


def test_rejects_other_pages_and_hosts():
    assert not is_allowed_referer("https://bbs.ckwiki.kr/relese/72")
    assert not is_allowed_referer(
        "https://bbs.ckwiki.kr/bbs/board.php?bo_table=relese&wr_id=72"
    )
    assert not is_allowed_referer("https://example.com/relese/73")
    assert not is_allowed_referer(None)


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
