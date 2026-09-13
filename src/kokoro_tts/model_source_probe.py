"""HTTP-only transport for model-source probes, without source-selection policy.

Use a private opener so default proxy/TLS handlers and redirect limits remain
intact, without installing a process-global opener or enabling FTP/file access.
"""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def _validate_probe_url(url: str) -> None:
    # urlsplit strips some controls, so reject them before parsing.
    if any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise ValueError("Invalid model-source probe URL")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Model-source probes require an HTTP(S) host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Model-source probe URL credentials are not supported")
    # Accessing port validates numeric syntax and the upper range.
    if parsed.port == 0 or parsed.netloc.endswith(":"):
        raise ValueError("Invalid model-source probe port")
    if "%" in parsed.hostname:
        raise ValueError("Invalid model-source probe host")


class _HttpProbeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _validate_probe_url(newurl)
        except ValueError:
            fp.close()
            raise
        request = super().redirect_request(req, fp, code, msg, headers, newurl)
        # urllib's default redirect constructor changes HEAD to GET.
        if request is not None:
            request.method = req.get_method()
        return request


def open_probe(url: str, *, timeout: float, method: str = "GET"):
    """Open a validated probe; callers own the response and failure semantics.

    Only GET (bounded country read) and HEAD (reachability) are supported. Errors
    are deliberately propagated so the existing country/cache/fallback policies
    stay with model_sources. This transport does not load models or log URLs.
    """
    _validate_probe_url(url)
    if method not in {"GET", "HEAD"}:
        raise ValueError("Unsupported model-source probe method")
    headers = {"User-Agent": "AngeVoice/model-source-probe"} if method == "HEAD" else {}
    request = Request(url, method=method, headers=headers)
    try:
        return build_opener(_HttpProbeRedirectHandler()).open(request, timeout=timeout)
    except HTTPError as exc:
        # HTTPError owns the response for rejected redirects and error statuses.
        exc.close()
        raise
