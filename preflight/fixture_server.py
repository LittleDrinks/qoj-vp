"""Read-only QOJ-shaped fixtures for an explicitly scoped preflight test.

This is a test harness, not a product service. Importing it opens no sockets.
Use ``with FixtureServer() as fixture`` and pass ``fixture.origin`` to the
browser transport. Keep QojClient's logical response URL at https://qoj.ac.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SOURCE_COMMIT = "807ce1be13d67916b2716f8221a10a12731977fe"
CONTEST_ID = "3387"
PROBLEMS = {
    "A": {"id": "15419", "name": "New Gomoku"},
    "B": {"id": "15420", "name": "Abstract Portal"},
}
LANGUAGES = ["C++20", "Python3"]
FIXTURES = Path(__file__).with_name("fixtures")


class FixtureServer:
    """An ephemeral HTTP server with observable, payload-free request records.

    ``origin`` is available after start/enter. ``requests`` returns snapshots
    containing method/path/allowed query fields/status, never request bodies,
    cookies, or authorization headers. Every POST is rejected and counted.
    """

    def __init__(self, host="127.0.0.1", port=0, *, advertised_host=None):
        self.host = host
        self.requested_port = port
        self.advertised_host = advertised_host or host
        self._httpd = None
        self._thread = None
        self._records = []
        self._lock = threading.Lock()

    @property
    def origin(self):
        if self._httpd is None:
            raise RuntimeError("FixtureServer must be started before reading origin")
        return f"http://{self.advertised_host}:{self._httpd.server_port}"

    @property
    def requests(self):
        with self._lock:
            return [dict(item, query=dict(item["query"])) for item in self._records]

    @property
    def rejected_post_count(self):
        return sum(item["method"] == "POST" for item in self.requests)

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self._httpd is not None:
            raise RuntimeError("FixtureServer is already started")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "QojPreflightFixture/1"
            sys_version = ""

            def log_message(self, *_args):
                # Avoid corrupting native-messaging stdout and leaking headers.
                pass

            def record(self, status):
                parsed = urlsplit(self.path)
                raw = parse_qs(parsed.query)
                allowed = {"type", "id", "contest_id", "case", "page", "submitter", "form"}
                item = {
                    "method": self.command,
                    "path": parsed.path,
                    "query": {key: values for key, values in raw.items() if key in allowed},
                    "status": status,
                    "rejected": self.command == "POST",
                }
                with owner._lock:
                    owner._records.append(item)

            def respond(self, status, body, content_type, *, disposition=None):
                self.record(status)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-QOJ-Preflight-Fixture", "true")
                self.send_header("Connection", "close")
                origin = self.headers.get("Origin")
                self.send_header("Access-Control-Allow-Origin", origin or "*")
                if origin:
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.send_header("Vary", "Origin")
                if disposition:
                    self.send_header("Content-Disposition", disposition)
                if status == 405:
                    self.send_header("Allow", "GET, HEAD, OPTIONS")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                self.close_connection = True

            def json_response(self, status, data):
                self.respond(status, json.dumps(data).encode(), "application/json")

            def do_OPTIONS(self):
                self.record(204)
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

            def do_HEAD(self):
                self.do_GET()

            def do_POST(self):
                # Never parse, retain, forward, or execute a submitted payload.
                self.json_response(405, {"fixture": True, "error": "read_only_fixture_post_rejected"})

            def do_PUT(self):
                self.json_response(405, {"fixture": True, "error": "read_only_fixture"})

            do_PATCH = do_PUT
            do_DELETE = do_PUT

            def do_GET(self):
                parsed = urlsplit(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                case = query.get("case", [""])[0]
                if path in ("/healthz", "/fixture-metadata"):
                    return self.json_response(200, {
                        "fixture": True, "readOnly": True, "sourceCommit": SOURCE_COMMIT,
                        "contestId": CONTEST_ID, "problems": PROBLEMS,
                        "languages": LANGUAGES,
                        "statementPdfIsSynthetic": True,
                    })
                if path == "/":
                    return self.respond(200, (FIXTURES / "index.html").read_bytes(), "text/html; charset=utf-8")
                if path == "/contest/3387":
                    return self.respond(200, (FIXTURES / "contest-3387.html").read_bytes(), "text/html; charset=utf-8")
                if path == "/contest/3387/submissions":
                    page = query.get("page", ["1"])[0]
                    name = "submissions-empty.html" if page != "1" else "submissions-3387.html"
                    return self.respond(200, (FIXTURES / name).read_bytes(), "text/html; charset=utf-8")
                problem_paths = {
                    "/contest/3387/problem/15419": "problem-15419.html",
                    "/contest/3387/problem/15420": "problem-15420.html",
                    "/contest/3387/problem/15419/statement/zh_cn": "problem-15419.html",
                    "/contest/3387/problem/15420/statement/zh_cn": "problem-15420.html",
                }
                if path in problem_paths:
                    return self.respond(200, (FIXTURES / problem_paths[path]).read_bytes(), "text/html; charset=utf-8")
                if path == "/download.php":
                    if (query.get("type") != ["problem"] or query.get("contest_id") != ["3387"]
                            or query.get("id") not in (["15419"], ["15420"])):
                        return self.json_response(404, {"fixture": True, "error": "unknown_attachment"})
                    if case == "missing":
                        return self.json_response(404, {"fixture": True, "error": "missing_attachment"})
                    if case == "html":
                        return self.respond(200, b"<!doctype html><p>FIXTURE: attachment replaced by login/challenge HTML</p>", "text/html; charset=utf-8")
                    if case == "unsafe":
                        name = "attachment-unsafe.zip"
                    else:
                        name = f"attachment-{query['id'][0]}.zip"
                    return self.respond(200, (FIXTURES / name).read_bytes(), "application/zip",
                                        disposition='attachment; filename="fixture-attachment.zip"')
                if path == "/fixture-statements/A.pdf":
                    return self.respond(200, (FIXTURES / "statement-A.pdf").read_bytes(), "application/pdf",
                                        disposition='inline; filename="FIXTURE-statement-A.pdf"')
                if path in ("/submission/1000001", "/submission/1000002", "/submission/1000003", "/submission/1000004"):
                    return self.respond(200, (FIXTURES / f"submission-{path.rsplit('/', 1)[-1]}.html").read_bytes(),
                                        "text/html; charset=utf-8")
                return self.json_response(404, {"fixture": True, "error": "unknown_fixture_route"})

        self._httpd = ThreadingHTTPServer((self.host, self.requested_port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="qoj-preflight-fixture", daemon=True)
        self._thread.start()
        return self

    def shutdown(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=3)
        self._httpd = None

    close = shutdown

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.shutdown()

