from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlsplit

OFFICIAL_GUIDE_URL = "https://bbs.ckwiki.kr/relese/73"
SESSION_TOKEN_VERSION = "v1"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


def is_allowed_referer(value: str | None) -> bool:
    if not value:
        return False

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False

    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != "bbs.ckwiki.kr":
        return False

    path = parsed.path.rstrip("/") or "/"
    if path == "/relese/73":
        return True

    if parsed.path == "/bbs/board.php":
        query = parse_qs(parsed.query, keep_blank_values=True)
        return (
            query.get("bo_table") == ["relese"]
            and query.get("wr_id") == ["73"]
        )

    return False


def _signing_key(owner_access_key: str) -> bytes:
    return hashlib.sha256(
        f"ddalkkak-access-session:{owner_access_key}".encode("utf-8")
    ).digest()


def create_session_token(owner_access_key: str, now: int | None = None) -> str:
    if not owner_access_key:
        raise ValueError("OWNER_ACCESS_KEY가 설정되지 않았습니다.")

    issued_at = int(time.time() if now is None else now)
    nonce = secrets.token_urlsafe(18)
    payload = f"{SESSION_TOKEN_VERSION}.{issued_at}.{nonce}"
    signature = hmac.new(
        _signing_key(owner_access_key),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(
    token: str | None,
    owner_access_key: str,
    *,
    now: int | None = None,
) -> bool:
    if not token or not owner_access_key:
        return False

    parts = token.split(".")
    if len(parts) != 4:
        return False

    version, issued_text, nonce, signature = parts
    if version != SESSION_TOKEN_VERSION or not nonce:
        return False

    try:
        issued_at = int(issued_text)
    except ValueError:
        return False

    current = int(time.time() if now is None else now)
    if issued_at > current + 60:
        return False
    if current - issued_at > SESSION_MAX_AGE_SECONDS:
        return False

    payload = f"{version}.{issued_at}.{nonce}"
    expected = hmac.new(
        _signing_key(owner_access_key),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def owner_key_matches(submitted: str, configured: str) -> bool:
    if not submitted or not configured:
        return False
    return hmac.compare_digest(submitted, configured)
