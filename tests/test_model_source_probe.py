"""Offline HTTP handler tests: exercise urllib routing/redirects, never sockets."""

from email.message import Message
from io import BytesIO
import logging
import socket
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import BaseHandler, HTTPHandler, HTTPSHandler, ProxyHandler
from urllib.response import addinfourl

import pytest

from kokoro_tts import model_source_probe as transport
from kokoro_tts import model_sources

SECRET = "SYNTHETIC_PROBE_SECRET"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("probe tests must not open sockets")
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.delenv("MODEL_SOURCE_COUNTRY", raising=False)


class _OfflineHTTP(BaseHandler):
    handler_order = 100  # before the standard network HTTP(S) handlers

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.responses = []

    def http_open(self, request):
        self.calls.append(request)
        route = self.routes[request.full_url]
        if isinstance(route, Exception):
            raise route
        status, headers, payload = route
        message = Message()
        for key, value in headers.items():
            message[key] = value
        response = addinfourl(BytesIO(payload), message, request.full_url, status)
        response.msg = "Offline test response"
        self.responses.append(response)
        return response

    https_open = http_open


@pytest.fixture
def offline(monkeypatch):
    real_build_opener = transport.build_opener

    def install(routes):
        handler = _OfflineHTTP(routes)
        def build(*handlers):
            return real_build_opener(*handlers, handler)
        monkeypatch.setattr(transport, "build_opener", build)
        return handler
    return install


@pytest.mark.parametrize("url", [
    "", "example.com/path", "//example.com", "file:///tmp/value", "ftp://mirror.invalid/file",
    "data:text/plain,CN", "http:///missing", "https://", "https://user:pass@host.invalid",
    "https://user@host.invalid", "https://host.invalid:bad", "https://host.invalid:65536",
    "https://host.invalid:0", "https://host.invalid:", "https://[invalid]/", "https://host.invalid\\@evil.invalid",
    "https://ho st.invalid/", "https://host.invalid/\nvalue", "https://host.invalid/\x00value",
    "https://%65xample.invalid/", "https://host.invalid/\x7fvalue",
])
def test_invalid_initial_url_never_builds_a_network_opener(url, monkeypatch):
    def fail(*args):
        pytest.fail("invalid URL must be rejected before opener construction")
    monkeypatch.setattr(transport, "build_opener", fail)
    with pytest.raises(ValueError):
        transport.open_probe(url, timeout=1)


@pytest.mark.parametrize("url", [
    "https://mirror.invalid/models?signature=" + SECRET,
    "http://192.168.1.2:8080/health", "http://localhost:8101/health", "http://[::1]:8101/health",
])
@pytest.mark.parametrize("method", ["HEAD", "GET"])
def test_valid_custom_and_local_hosts_keep_method_timeout_and_headers(url, method, offline):
    handler = offline({url: (200, {}, b"CN")})
    with transport.open_probe(url, timeout=2.75, method=method) as response:
        assert response.read(16) == b"CN"
    request, = handler.calls
    assert request.full_url == url
    assert request.get_method() == method
    assert request.timeout == 2.75
    if method == "HEAD":
        assert request.get_header("User-agent") == "AngeVoice/model-source-probe"
    assert handler.responses[0].closed


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("target", ["/final", "https://mirror.invalid/final"])
def test_redirects_keep_head_and_standard_response_cleanup(code, target, offline):
    start = "http://source.invalid/start"
    final = "http://source.invalid/final" if target.startswith("/") else target
    handler = offline({start: (code, {"Location": target}, b""), final: (200, {}, b"")})
    assert model_sources._probe_url(start, 2.5) is True
    assert [req.full_url for req in handler.calls] == [start, final]
    assert [req.get_method() for req in handler.calls] == ["HEAD", "HEAD"]
    assert all(req.timeout == 2.5 for req in handler.calls)
    assert all(response.closed for response in handler.responses)


@pytest.mark.parametrize("target", [
    "ftp://mirror.invalid/file", "file:///tmp/data", "data:text/plain,CN",
    "https://user:" + SECRET + "@mirror.invalid/", "http://host.invalid:65536/",
    "http:///", "https://host.invalid\\@other.invalid/",
])
def test_unsafe_redirect_target_is_never_opened_and_is_not_logged(target, offline, caplog):
    start = "https://source.invalid/start?token=" + SECRET
    handler = offline({start: (302, {"Location": target}, b"")})
    with caplog.at_level(logging.DEBUG, logger=model_sources.__name__):
        assert model_sources._probe_url(start, 1) is False
    assert len(handler.calls) == 1
    assert handler.responses[0].closed
    assert SECRET not in caplog.text
    assert target not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_redirect_loop_remains_bounded(offline):
    url = "https://mirror.invalid/loop"
    handler = offline({url: (302, {"Location": url}, b"")})
    assert model_sources._probe_url(url, 1) is False
    assert 1 < len(handler.calls) <= 11
    assert all(response.closed for response in handler.responses)


@pytest.mark.parametrize(("status", "reachable"), [(200, True), (401, True), (403, True), (404, True), (500, False), (503, False)])
def test_real_http_error_processor_preserves_reachability_and_closes_response(status, reachable, offline):
    url = "https://provider.invalid/"
    handler = offline({url: (status, {}, b"error")})
    assert model_sources._probe_url(url, 1) is reachable
    assert handler.responses[0].closed


def test_country_get_survives_redirect_and_bounds_read(offline):
    url = "https://country.invalid/start"
    handler = offline({url: (302, {"Location": "/final"}, b""), "https://country.invalid/final": (200, {}, b"cn\n" + b"x" * 100)})
    cfg = SimpleNamespace(model_source_country="", model_source_detect_url=url, model_source_detect_timeout_seconds=1.25)
    assert model_sources._detect_country(cfg) == (b"cn\n" + b"x" * 13).decode().upper()
    assert [req.get_method() for req in handler.calls] == ["GET", "GET"]
    assert all(response.closed for response in handler.responses)


@pytest.mark.parametrize("error_type", [TimeoutError, OSError, URLError, RuntimeError])
def test_probe_and_country_exception_chains_are_not_rendered(error_type, offline, caplog):
    url = "https://provider.invalid/?token=" + SECRET
    error = error_type(SECRET)
    error.__cause__ = RuntimeError("nested " + SECRET)
    offline({url: error})
    cfg = SimpleNamespace(model_source_country="", model_source_detect_url=url)
    with caplog.at_level(logging.DEBUG, logger=model_sources.__name__):
        assert model_sources._probe_url(url, 1) is False
        assert model_sources._detect_country(cfg) == ""
    assert len(caplog.records) == 2
    assert SECRET not in caplog.text
    assert "Traceback" not in caplog.text
    assert error_type.__name__ in caplog.text


def test_default_proxy_tls_handlers_are_retained_without_global_opener_change(monkeypatch):
    import urllib.request
    previous = urllib.request._opener
    built = []
    original = transport.build_opener
    def build(*handlers):
        opener = original(*handlers)
        built.extend(opener.handlers)
        opener.open = lambda *args, **kwargs: "response"
        return opener
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:3128")
    monkeypatch.setattr(transport, "build_opener", build)
    assert transport.open_probe("https://mirror.invalid", timeout=1) == "response"
    assert any(isinstance(handler, ProxyHandler) for handler in built)
    assert any(isinstance(handler, HTTPHandler) for handler in built)
    assert any(isinstance(handler, HTTPSHandler) for handler in built)
    assert urllib.request._opener is previous


def test_unsupported_method_is_rejected_before_opening(monkeypatch):
    monkeypatch.setattr(transport, "build_opener", lambda *args: pytest.fail("must not open"))
    with pytest.raises(ValueError):
        transport.open_probe("https://mirror.invalid", timeout=1, method="POST")
