"""Pure Python protocol checks; these do NOT replace Firefox ESR tests."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor_py"))
from native_core import BrowserSession, ProtocolError  # noqa: E402
from native_host import read_frame, write_frame  # noqa: E402


def sample_archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("original/sample10.in", b"10\n")
        archive.writestr("original/sample10.ans", b"20\n")
        archive.writestr("original/sample2.in", b"2\n")
        archive.writestr("original/sample2.ans", b"4\n")
        archive.writestr("testing_tool.py", b"# retained special attachment\n")
    return buffer.getvalue()


class FixtureHandler(BaseHTTPRequestHandler):
    requests_seen = []

    def do_GET(self):
        parsed = urlparse(self.path)
        type(self).requests_seen.append(parsed.path)
        status = 200
        content_type = "text/html; charset=utf-8"
        if parsed.path == "/contest/7001":
            body = b'''<!doctype html><title>Native fixture - Dashboard - Contest - QOJ</title>
                <table><tr><td>A</td><td><a href="/contest/7001/problem/777">First problem</a></td></tr>
                <tr><td>B</td><td><a href="/contest/7001/problem/778">Second problem</a></td></tr></table>'''
        elif parsed.path == "/contest/7001/problem/777":
            body = b'''<!doctype html><title>Problem A</title>
                <a href="/statements/A.pdf">PDF statement</a>
                <form id="form-answer"><input name="_token" value="synthetic-fixture-value">
                <select name="answer_answer_language"><option value="C++20">C++20</option>
                <option value="Python3">Python3</option></select></form>'''
        elif parsed.path == "/download.php" and parse_qs(parsed.query).get("id") == ["777"]:
            body = sample_archive()
            content_type = "application/zip"
        else:
            status, body = 404, b"not found"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        type(self).requests_seen.append("UNEXPECTED_POST")
        self.send_error(405)

    def log_message(self, *_args):
        return


class NativePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qoj-native-test-")
        self.addCleanup(self.temp.cleanup)
        self.requests = []

    def task(self, method, args=None):
        env = {**os.environ, "QOJ_PREFLIGHT_STATE_DIR": self.temp.name,
               "QOJ_PREFLIGHT_QOJ_PATH": str(ROOT / "vendor/qoj-submitter"),
               "PYTHONPATH": str(ROOT / "vendor_py")}
        process = subprocess.Popen([sys.executable, str(ROOT / "native_host.py")], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            write_frame(process.stdin, {"type": "task", "id": "native-test", "method": method, "args": args or {}})
            while True:
                message = read_frame(process.stdout)
                self.assertIsNotNone(message, "Native process exited without a framed result")
                if message["type"] == "result":
                    process.stdin.close()
                    code = process.wait(timeout=5)
                    stderr = process.stderr.read().decode()
                    self.assertTrue(message["ok"], message.get("error"))
                    self.assertEqual(code, 0, stderr)
                    self.assertEqual(process.stdout.read(), b"", "Unexpected unframed stdout")
                    self.assertEqual(message["pid"], process.pid)
                    return message["result"], process.pid
                self.assertEqual(message["type"], "http.request")
                request = message["request"]
                self.requests.append(request)
                self.assertEqual(request["method"], "GET")
                self.assertNotIn("user-agent", {name.lower() for name in request["headers"]})
                with urlopen(Request(request["url"], headers=request["headers"]), timeout=5) as response:
                    body = response.read()
                    payload = {"status": response.status, "url": response.url,
                               "headers": dict(response.headers), "bodyBase64": base64.b64encode(body).decode(),
                               "transport": "python-test-driver", "pageOrigin": self.origin}
                write_frame(process.stdin, {"type": "http.response", "id": message["id"],
                                           "requestId": message["requestId"], "response": payload})
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()

    def test_native_frame_unicode_and_truncation(self):
        stream = io.BytesIO()
        value = {"type": "task", "id": "中文", "args": {}}
        write_frame(stream, value)
        payload = stream.getvalue()
        self.assertEqual(read_frame(io.BytesIO(payload)), value)
        self.assertIsNone(read_frame(io.BytesIO()))
        with self.assertRaises(ProtocolError):
            read_frame(io.BytesIO(payload[:-1]))

    def test_one_process_per_task_and_durable_two_hour_session(self):
        hello, first_pid = self.task("hello", {"pageUrl": "moz-extension://fixture-id/test.html"})
        self.assertEqual(hello["protocolVersion"], 1)
        started = int(time.time() * 1000) - 2 * 60 * 60 * 1000
        created, second_pid = self.task("create_session", {"sessionId": "two-hours", "startAt": started, "contestId": "7001"})
        inspected, third_pid = self.task("inspect_session", {"sessionId": "two-hours"})
        self.assertEqual(created["startAt"], inspected["startAt"])
        self.assertTrue(7200000 <= inspected["elapsedMs"] < 7210000)
        self.assertEqual(len({first_pid, second_pid, third_pid}), 3)
        listed, _pid = self.task("list_sessions")
        self.assertEqual([s["sessionId"] for s in listed["sessions"]], ["two-hours"])
        with sqlite3.connect(Path(self.temp.name) / "preflight.sqlite3") as db:
            trace = json.loads(db.execute("SELECT data_json FROM trace WHERE kind='hello'").fetchone()[0])
        self.assertEqual(trace["pageUrl"], "moz-extension://fixture-id/test.html")

    def test_real_qoj_modules_parse_and_normalize_single_problem_samples(self):
        result, _pid = self.task("qoj_contest_and_sample", {"contestId": "7001", "problemLabel": "A",
                                                          "fixtureOrigin": self.origin, "includeZip": True})
        self.assertEqual(result["source"], "fixture")
        self.assertEqual(result["qojLibrary"]["clientModule"], "qoj_submitter.client")
        self.assertEqual([p["label"] for p in result["problems"]], ["A", "B"])
        self.assertEqual(result["browserRequests"], 2)
        self.assertTrue(all(r["logicalUrl"].startswith("https://qoj.ac/") for r in self.requests))
        self.assertEqual([item["name"] for item in result["samples"]["files"]],
                         ["samples-A/1.in", "samples-A/1.ans", "samples-A/2.in", "samples-A/2.ans"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["samples"]["zipBase64"]))) as archive:
            self.assertEqual(archive.read("samples-A/1.in"), b"2\n")
            self.assertEqual(archive.read("samples-A/2.in"), b"10\n")
        self.assertTrue(result["samples"]["extraFiles"])
        self.assertNotIn("UNEXPECTED_POST", FixtureHandler.requests_seen)

    def test_form_token_is_used_but_never_returned(self):
        result, _pid = self.task("qoj_problem_form", {"contestId": "7001", "problemId": "777", "fixtureOrigin": self.origin})
        self.assertEqual(result["languages"], ["C++20", "Python3"])
        self.assertTrue(result["csrfPresent"])
        self.assertNotIn("synthetic-fixture-value", json.dumps(result))
        self.assertEqual(result["pdfCandidates"][0]["url"], "https://qoj.ac/statements/A.pdf")

    def test_transport_blocks_submission_before_exchange(self):
        def forbidden(_request):
            self.fail("POST must not reach the exchange callback")
        session = BrowserSession(forbidden, self.origin)
        import requests
        with self.assertRaises(requests.RequestException):
            session.post("https://qoj.ac/contest/7001/problem/777")


if __name__ == "__main__":
    unittest.main(verbosity=2)
