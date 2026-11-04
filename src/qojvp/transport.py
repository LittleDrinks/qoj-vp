"""Requests-compatible HTTP seam; Firefox retains authentication and networking."""
from __future__ import annotations

import base64
from urllib.parse import urlparse, urlunparse

import requests
from requests.structures import CaseInsensitiveDict

BASE = "https://qoj.ac"
MAX_SOURCE_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
FORBIDDEN_HEADERS = {"user-agent", "cookie", "cookie2", "host", "origin", "referer",
                     "content-length", "connection", "accept-encoding", "authorization",
                     "proxy-authorization"}


class BrowserSession:
    def __init__(self, exchange, *, allow_post=False, fixture_origin=None):
        self.exchange = exchange
        self.allow_post = allow_post
        self.headers = CaseInsensitiveDict()
        self.cookies = requests.cookies.RequestsCookieJar()
        self.last_response = None
        self.transports = []
        self.fixture_origin = None
        if fixture_origin:
            parsed = urlparse(fixture_origin)
            if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                raise ValueError("Fixture origin must be a loopback HTTP origin")
            self.fixture_origin = fixture_origin.rstrip("/")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "qoj.ac" or parsed.username or parsed.password:
            raise requests.RequestException("Only the QOJ origin is allowed")
        if method not in {"GET", "POST"} or (method == "POST" and not self.allow_post):
            raise requests.RequestException("HTTP method is not authorized for this task")
        if method == "POST" and kwargs.get("allow_redirects") is not False:
            raise requests.RequestException("Submissions require an observed redirect receipt")
        target = str(url)
        if self.fixture_origin:
            target = self.fixture_origin + urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))
        headers = {key: value for key, value in {**self.headers, **kwargs.get("headers", {})}.items()
                   if key.lower() not in FORBIDDEN_HEADERS
                   and not key.lower().startswith(("sec-", "proxy-", "access-control-request-"))}
        request = {"method": method, "url": target, "logicalUrl": str(url), "headers": headers,
                   "timeoutMs": min(30000, max(1000, int(float(kwargs.get("timeout", 20)) * 1000))),
                   "allowRedirects": kwargs.get("allow_redirects", True), "fixture": bool(self.fixture_origin)}
        if method == "POST":
            request["data"] = dict(kwargs.get("data") or {})
            files = []
            for field, item in (kwargs.get("files") or {}).items():
                filename, contents, content_type = item
                if not isinstance(contents, bytes) or len(contents) > MAX_SOURCE_BYTES:
                    raise requests.RequestException("Source file exceeds the native message limit")
                files.append({"field": field, "filename": filename, "contentType": content_type,
                              "contentsBase64": base64.b64encode(contents).decode("ascii")})
            request["files"] = files
        try:
            reply = self.exchange(request)
        except Exception as exc:
            raise requests.ConnectionError("Browser request connection ended") from exc
        if not isinstance(reply, dict) or reply.get("error"):
            error = requests.ConnectionError("Browser HTTP request failed")
            details = reply.get("error", {}) if isinstance(reply, dict) else {}
            if isinstance(details, dict):
                code = details.get("code")
                if isinstance(code, str):
                    error.bridge_code = code
            raise error
        payload = reply.get("response", reply)
        try:
            data = base64.b64decode(payload["bodyBase64"], validate=True)
            status = int(payload["status"])
            if len(data) > MAX_RESPONSE_BYTES or status < 100 or status > 599:
                raise ValueError()
        except (ValueError, KeyError, TypeError) as exc:
            raise requests.ConnectionError("Browser returned an invalid HTTP envelope") from exc
        actual_url = str(payload.get("url") or target)
        if self.fixture_origin and actual_url.startswith(self.fixture_origin + "/"):
            actual_url = BASE + actual_url[len(self.fixture_origin):]
        response_headers = CaseInsensitiveDict(payload.get("headers", {}))
        # A fixture's Location can use its own origin; restore the logical URL
        # before the unchanged QojClient validates the submission receipt.
        location = response_headers.get("Location", "")
        if self.fixture_origin and location.startswith(self.fixture_origin + "/"):
            response_headers["Location"] = BASE + location[len(self.fixture_origin):]
        response = requests.Response()
        response.status_code, response.url, response.headers = status, actual_url, response_headers
        response._content = data
        response.encoding = requests.utils.get_encoding_from_headers(response.headers) or "utf-8"
        response.request = requests.Request(method, str(url)).prepare()
        self.last_response = response
        self.transports.append({"transport": payload.get("transport"), "pageOrigin": payload.get("pageOrigin"),
                                "tabId": payload.get("tabId")})
        return response

    def close(self):
        pass
