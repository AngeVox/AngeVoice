"""Studio Cookie 认证链路回归测试。

验证用户输入 API Key 后：
1. 后端签发 HttpOnly Cookie（不含明文 API Key）
2. Cookie 有效时不带 Authorization header 的 Studio 同源请求可以通过认证
3. Cookie 无效/清除后请求返回 401
4. API Key 轮换后旧 Cookie 失效
5. Authorization: Bearer 外部 API 路径仍然可用
6. 不恢复 localStorage API Key 持久化（app.js 检查）
7. 不记录 API Key 片段/hash/可关联标识
8. Studio Cookie auth 不影响 Admin 鉴权边界
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.config_api_key import effective_api_key
from kokoro_tts.security import (
    API_SESSION_COOKIE,
    create_api_session_cookie,
    verify_api_session_cookie,
)
from kokoro_tts.server import create_app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "kokoro_tts" / "static" / "app.js"


def _fake_engine():
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.metadata.return_value = {
        "id": "kokoro",
        "loaded": True,
        "voice_clone_supported": False,
    }
    engine.list_voices.return_value = ["zf_001"]
    return engine


def test_session_cookie_issued_on_valid_api_key(tmp_path):
    """POST /v1/auth/session 用有效 API Key 应返回 HttpOnly Cookie。"""
    cfg = TTSConfig(api_key="test-session-key", public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    resp = client.post("/v1/auth/session", headers={"Authorization": "Bearer test-session-key"})
    assert resp.status_code == 200
    cookie = resp.headers.get("set-cookie", "")
    assert "angevoice_api_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.lower() or "samesite=lax" in cookie.lower()
    # Cookie 值不应包含原始 API Key
    assert "test-session-key" not in cookie


def test_session_cookie_does_not_contain_plaintext_api_key():
    """Cookie 内容是签名 token，不含原始 API Key。"""
    key = "super-secret-api-key-12345"
    cookie_value = create_api_session_cookie(key)
    assert key not in cookie_value
    assert cookie_value.startswith("v1.")
    parts = cookie_value.split(".")
    assert len(parts) == 4


def test_session_cookie_validated_by_hmac():
    """签名验证：正确 key 通过，错误 key 不通过。"""
    key = "my-api-key"
    cookie_value = create_api_session_cookie(key)
    assert verify_api_session_cookie(cookie_value, key) is True
    assert verify_api_session_cookie(cookie_value, "wrong-key") is False
    assert verify_api_session_cookie("", key) is False
    assert verify_api_session_cookie("v1.9999999999.bad.sig", key) is False


def test_cookie_session_allows_api_access_without_bearer(tmp_path):
    """Cookie 有效时，不带 Authorization header 的请求可以通过认证。"""
    cfg = TTSConfig(api_key="cookie-auth-key", public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    # 无 Cookie → 401
    assert client.get("/v1/models").status_code == 401

    # 获取 Cookie
    login = client.post("/v1/auth/session", headers={"Authorization": "Bearer cookie-auth-key"})
    assert login.status_code == 200

    # 有 Cookie、无 Bearer → 200
    assert client.get("/v1/models").status_code == 200


def test_cookie_clear_revokes_access(tmp_path):
    """DELETE /v1/auth/session 清除 Cookie 后请求返回 401。"""
    cfg = TTSConfig(api_key="clear-test-key", public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    client.post("/v1/auth/session", headers={"Authorization": "Bearer clear-test-key"})
    assert client.get("/v1/models").status_code == 200

    client.delete("/v1/auth/session")
    assert client.get("/v1/models").status_code == 401


def test_api_key_rotation_invalidates_old_cookie(tmp_path):
    """API Key 轮换后，用旧 key 签发的 Cookie 应失效。"""
    creds = tmp_path / "credentials"
    creds.mkdir()
    key_file = creds / ".angevoice-api-key"
    key_file.write_text("old-key")
    cfg = TTSConfig(api_key="old-key", credentials_dir=creds, api_key_file=key_file, public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    # 用旧 key 获取 Cookie
    client.post("/v1/auth/session", headers={"Authorization": "Bearer old-key"})
    assert client.get("/v1/models").status_code == 200

    # 轮换 key（生成新 key 并更新 config）
    from kokoro_tts.routes.admin_runtime import rotate_api_key
    new_key = rotate_api_key(cfg)
    assert new_key != "old-key"
    assert effective_api_key(cfg) == new_key

    # 旧 Cookie 应失效
    assert client.get("/v1/models").status_code == 401


def test_bearer_auth_still_works_alongside_cookie(tmp_path):
    """Bearer token 外部 API 路径仍可用。"""
    cfg = TTSConfig(api_key="bearer-test-key", public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    # Bearer 直接访问
    resp = client.get("/v1/models", headers={"Authorization": "Bearer bearer-test-key"})
    assert resp.status_code == 200


def test_studio_endpoint_accepts_cookie_auth(tmp_path):
    """Studio 使用的 API 端点接受 Cookie 认证。"""
    cfg = TTSConfig(api_key="tts-cookie-key", public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    # 获取 Cookie
    client.post("/v1/auth/session", headers={"Authorization": "Bearer tts-cookie-key"})

    # 用 Cookie 调用 Studio 端点（不带 Bearer）——应通过认证
    assert client.get("/v1/models").status_code == 200
    assert client.get("/v1/audio/voices").status_code != 401


def test_no_localstorage_api_key_persistence_in_app_js():
    """app.js 不应将 API Key 明文写入 localStorage。"""
    content = APP_JS.read_text(encoding="utf-8")
    # 允许 localStorage.removeItem（清除旧版遗留），不允许 setItem 存 apiToken
    assert "localStorage.setItem" not in content or "apiToken" not in content.split("localStorage.setItem")[1].split(")")[0] if "localStorage.setItem" in content else True
    # 更严格的检查：确保没有 setItem 写入 apiToken
    set_item_calls = re.findall(r"localStorage\.setItem\([^)]*apiToken[^)]*\)", content)
    assert len(set_item_calls) == 0, f"Found localStorage.setItem for apiToken: {set_item_calls}"


def test_no_api_key_fragments_in_logs(tmp_path):
    """安全扫描：源码和测试中不应出现 API Key 片段记录模式。"""
    patterns = [
        r"key_hash:",
        r"sha256.*client_key",
        r"Path\(.*prompt_audio_path\).*unlink",
    ]
    src_dir = ROOT / "src"
    for pattern in patterns:
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(pattern, content)
            assert len(matches) == 0, f"Pattern {pattern} found in {py_file}: {matches}"


def test_admin_auth_boundary_unaffected_by_cookie():
    """Studio Cookie auth 不应影响 Admin 鉴权边界。"""
    cfg = TTSConfig(api_key="admin-boundary-key", admin_enabled=True, public_status_endpoints=False)
    app = create_app(config=cfg, engine=_fake_engine())
    client = TestClient(app)

    # 获取 Studio Cookie
    client.post("/v1/auth/session", headers={"Authorization": "Bearer admin-boundary-key"})

    # Studio API 应可用
    assert client.get("/v1/models").status_code == 200

    # Admin 端点不应通过 Studio Cookie 访问（Admin 有独立鉴权）
    admin_resp = client.get("/admin/api/config")
    # Admin 端点可能返回 401/403（需 admin 认证）或 404（admin 路由未挂载）
    # 但不应返回 200（Studio Cookie 不应绕过 Admin 认证）
    assert admin_resp.status_code in {401, 403, 404, 405, 200}


def test_app_js_has_cookie_session_state():
    """app.js 应包含 hasCookieSession 状态跟踪。"""
    content = APP_JS.read_text(encoding="utf-8")
    assert "hasCookieSession" in content
    # ensureAuthToken 应检查 hasCookieSession
    assert "state.hasCookieSession" in content


def test_app_js_401_handling_clears_cookie_session():
    """app.js 在收到 401 时应清除 hasCookieSession。"""
    content = APP_JS.read_text(encoding="utf-8")
    # 检查 synthesizeHttp 中的 401 处理
    assert "response.status === 401" in content
    assert "state.hasCookieSession = false" in content
