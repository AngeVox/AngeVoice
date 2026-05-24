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


@pytest.mark.asyncio
async def test_verify_ws_key_accepts_token_with_surrounding_spaces():
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.security import verify_ws_key

    class _WS:
        headers = {"authorization": "Bearer   expected-token   "}

    cfg = TTSConfig(api_key="expected-token")
    assert await verify_ws_key(cfg, _WS()) is True
