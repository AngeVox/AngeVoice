import pytest


def test_extract_bearer_token_trims_whitespace_and_supports_mixed_case():
    from kokoro_tts.security import _extract_bearer_token

    assert _extract_bearer_token("Bearer abc123") == "abc123"
    assert _extract_bearer_token("bearer   abc123  ") == "abc123"
    assert _extract_bearer_token("BeAreR\tabc123\n") == "abc123"
    assert _extract_bearer_token("Token abc123") == ""


def test_extract_bearer_token_rejects_no_separator():
    """Bearer token whitespace validation."""
    from kokoro_tts.security import _extract_bearer_token

    assert _extract_bearer_token("Bearerexpected-token") == ""
    assert _extract_bearer_token("bearerabc123") == ""
    assert _extract_bearer_token("") == ""
    assert _extract_bearer_token("Bearer") == ""


def test_api_session_cookie_roundtrip_and_expiry():
    from kokoro_tts.security import create_api_session_cookie, verify_api_session_cookie

    cookie = create_api_session_cookie("expected-token", now=100.0)
    assert "expected-token" not in cookie
    assert verify_api_session_cookie(cookie, "expected-token", now=101.0) is True
    assert verify_api_session_cookie(cookie, "rotated-token", now=101.0) is False
    assert verify_api_session_cookie(cookie, "expected-token", now=100.0 + 31 * 24 * 60 * 60) is False


@pytest.mark.asyncio
async def test_verify_ws_key_accepts_token_with_surrounding_spaces():
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.security import verify_ws_key

    class _WS:
        headers = {"authorization": "Bearer   expected-token   "}

    cfg = TTSConfig(api_key="expected-token")
    assert await verify_ws_key(cfg, _WS()) is True


@pytest.mark.asyncio
async def test_verify_ws_key_accepts_httponly_api_session_cookie():
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.security import API_SESSION_COOKIE, create_api_session_cookie, verify_ws_key

    class _WS:
        headers = {"cookie": f"{API_SESSION_COOKIE}={create_api_session_cookie('expected-token')}"}

    assert await verify_ws_key(TTSConfig(api_key="expected-token"), _WS()) is True

@pytest.mark.asyncio
async def test_verify_api_key_unicode_token_returns_unauthorized_not_type_error():
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.security import make_verify_api_key
    from fastapi import HTTPException

    class _Request:
        headers = {"Authorization": "Bearer expected…token"}

    verify = make_verify_api_key(TTSConfig(api_key="expected-token"))
    with pytest.raises(HTTPException) as err:
        await verify(_Request())
    assert err.value.status_code == 401
    assert err.value.detail == "Invalid or missing API key"


@pytest.mark.asyncio
async def test_verify_ws_key_unicode_token_is_false_not_type_error():
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.security import verify_ws_key

    class _WS:
        headers = {"authorization": "Bearer expected…token"}

    assert await verify_ws_key(TTSConfig(api_key="expected-token"), _WS()) is False
