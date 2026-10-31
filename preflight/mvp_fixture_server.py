"""Loopback-only QOJ fixture for actual Firefox/native MVP acceptance.

Extends the existing FixtureServer lifecycle and reuses its static fixtures.
It never contacts an OJ, executes source, or keeps source/token/header bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

from fixture_server import CONTEST_ID, FIXTURES, LANGUAGES, PROBLEMS, FixtureServer


SCENARIOS = {"accepted", "unknown503", "unknown503_no_record", "wrong_answer", "compiler_error"}
MAX_POST_BYTES = 2 * 1024 * 1024


class MvpFixtureServer(FixtureServer):
    """Use ``with MvpFixtureServer(scenario='accepted') as fixture``.

    ``judge_after_reads`` is the number of pending history/detail observations
    before a record becomes final. A POST receipt follow itself is one detail
    observation. ``submissions`` is a safe metadata snapshot, without payloads.
    """

    def __init__(self, host="127.0.0.1", port=0, *, scenario="accepted",
                 judge_after_reads=2, account="csj-test"):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("The acceptance fixture must bind only to loopback")
        if scenario not in SCENARIOS or not isinstance(judge_after_reads, int) or judge_after_reads < 0:
            raise ValueError("Unknown scenario or invalid judgement observation count")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", account):
            raise ValueError("Use a synthetic fixture account")
        super().__init__(host, port)
        self.scenario, self.judge_after_reads, self.account = scenario, judge_after_reads, account
        self._submissions = []
        self._next_id = 1000001

    @property
    def submissions(self):
        with self._lock:
            return [dict(item) for item in self._submissions]

    @property
    def post_count(self):
        return sum(item["method"] == "POST" for item in self.requests)

    @property
    def accepted_post_count(self):
        return sum(item["method"] == "POST" and item.get("formFieldsValid", False) for item in self.requests)

    @property
    def rejected_post_count(self):
        return sum(item["method"] == "POST" and item.get("rejected", False) for item in self.requests)

    def _observe(self, sid=None):
        with self._lock:
            rows = []
            for item in self._submissions:
                if sid is None or item["id"] == sid:
                    item["judgementReads"] += 1
                    rows.append(dict(item, pending=item["judgementReads"] <= self.judge_after_reads))
            return rows

    def start(self):
        if self._httpd is not None:
            raise RuntimeError("MvpFixtureServer is already started")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "QojMvpLoopbackFixture/1"
            sys_version = ""

            def log_message(self, *_args):
                pass

            def respond(self, status, body=b"", content_type="text/html; charset=utf-8", *, headers=None, metadata=None):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                record = {"method": self.command, "path": parsed.path,
                          "query": {key: values for key, values in query.items()
                                    if key in {"page", "submitter", "locale", "id", "contest_id", "type"}},
                          "status": status, "rejected": self.command == "POST" and status < 500 and status >= 400}
                record.update(metadata or {})
                with owner._lock:
                    owner._records.append(record)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-QOJ-Preflight-Fixture", "synthetic-mvp")
                self.send_header("Connection", "close")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                self.close_connection = True

            def json_response(self, status, value, **kwargs):
                return self.respond(status, json.dumps(value).encode(), "application/json", **kwargs)

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                parsed = urlsplit(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path in {"/healthz", "/fixture-metadata", "/__fixture/status"}:
                    return self.json_response(200, {"synthetic": True, "scenario": owner.scenario,
                        "account": owner.account, "contestId": CONTEST_ID,
                        "problems": PROBLEMS, "postCount": owner.post_count,
                        "submissions": owner.submissions})
                if path == "/":
                    return self.respond(200, (
                        '<!doctype html><title>SYNTHETIC MVP QOJ fixture</title>'
                        '<h1>Loopback acceptance fixture</h1><ul class="nav nav-pills float-right">'
                        '<li class="nav-item dropdown"><a class="nav-link dropdown-toggle">'
                        f'<a href="//qoj.ac/user/profile/{owner.account}">{owner.account}</a></a>'
                        '<ul class="dropdown-menu"><li>'
                        f'<a href="//qoj.ac/user/profile/{owner.account}">个人信息</a></li></ul></li>'
                        '<li class="nav-item"><a href="//qoj.ac/logout?_token=synthetic-fixture-logout">退出登录</a></li></ul>'
                        '<a href="/contest/3387">Fixture contest</a>').encode())
                if path == "/contest/3387":
                    return self.respond(200, (FIXTURES / "contest-3387.html").read_bytes())
                if path == "/contest/3387/submissions":
                    rows = owner._observe() if query.get("page", ["1"])[0] == "1" else []
                    requested = query.get("submitter", [owner.account])[0]
                    if requested.casefold() != owner.account.casefold():
                        rows = []
                    body = ['<!doctype html><title>SYNTHETIC history</title>',
                        '<h1>SYNTHETIC submission history</h1><table><thead><tr>',
                        '<th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Time</th>',
                        '</tr></thead><tbody>']
                    for item in reversed(rows):
                        sid, pid = item["id"], item["problemId"]
                        label = next(label for label, p in PROBLEMS.items() if p["id"] == pid)
                        score = 0 if owner.scenario in {"wrong_answer", "compiler_error"} else 100
                        result = f'<span id="status_details_{sid}">Judging</span>' if item["pending"] else str(score)
                        stamp = datetime.fromtimestamp(item["submittedAt"] / 1000, timezone.utc).isoformat(timespec="milliseconds")
                        body.append(f'<tr><td><a href="/submission/{sid}">{sid}</a></td>'
                            f'<td><a href="/user/profile/{owner.account}">{owner.account}</a></td>'
                            f'<td><a href="/contest/3387/problem/{pid}">{label}</a></td>'
                            f'<td>{result}</td><td>{html.escape(item["language"])}</td>'
                            f'<td><time datetime="{stamp}">{stamp}</time></td></tr>')
                    body.append('</tbody></table>')
                    return self.respond(200, ''.join(body).encode())
                match = re.fullmatch(r"/submission/(\d+)/?", path)
                if match:
                    rows = owner._observe(match[1])
                    if not rows:
                        return self.json_response(404, {"synthetic": True, "error": "unknown_submission"})
                    item = rows[0]
                    if item['pending']:
                        result = f'<span id="status_details_{item["id"]}">Judging</span>'
                    else:
                        label = {"wrong_answer": "Wrong Answer", "compiler_error": "Compile Error"}.get(owner.scenario, "Accepted")
                        result = f'<div class="col-sm-2">{label}</div>'
                    body = '<!doctype html><title>SYNTHETIC judgement</title><h1>Fixture</h1><div class="card"><div class="card-header">Details</div>' + result + '</div>'
                    return self.respond(200, body.encode())
                match = re.fullmatch(r"/contest/3387/problem/(15419|15420)(?:/statement/zh_cn)?/?", path)
                if match:
                    return self.respond(200, (FIXTURES / f"problem-{match[1]}.html").read_bytes())
                if path == "/download.php" and query.get("type") == ["problem"] and query.get("contest_id") == ["3387"] and query.get("id") in (["15419"], ["15420"]):
                    return self.respond(200, (FIXTURES / f"attachment-{query['id'][0]}.zip").read_bytes(), "application/zip",
                        headers={"Content-Disposition": 'attachment; filename="fixture-samples.zip"'})
                if path == "/fixture-statements/A.pdf":
                    return self.respond(200, (FIXTURES / "statement-A.pdf").read_bytes(), "application/pdf",
                        headers={"Content-Disposition": 'inline; filename="FIXTURE-statement-A.pdf"'})
                return self.json_response(404, {"synthetic": True, "error": "unknown_fixture_route"})

            def do_POST(self):
                match = re.fullmatch(r"/contest/3387/problem/(15419|15420)(?:/statement/zh_cn)?/?", urlsplit(self.path).path)
                if not match:
                    return self.json_response(405, {"synthetic": True, "error": "post_route_not_allowed"})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    length = 0
                if not 0 < length <= MAX_POST_BYTES:
                    return self.json_response(413, {"synthetic": True, "error": "invalid_body_size"})
                # Multipart is parsed in memory and discarded after validation.
                data = self.rfile.read(length)
                content_type = self.headers.get('Content-Type', '')
                try:
                    if not content_type.lower().startswith('multipart/form-data;'):
                        raise ValueError('multipart required')
                    message = BytesParser(policy=default).parsebytes(
                        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + data)
                    if not message.is_multipart():
                        raise ValueError('multipart required')
                    fields, files = {}, {}
                    for part in message.iter_parts():
                        name = part.get_param('name', header='content-disposition')
                        filename = part.get_filename()
                        payload = part.get_payload(decode=True)
                        if name in fields or name in files or payload is None:
                            raise ValueError('malformed multipart')
                        if filename is None:
                            fields[name] = payload.decode('utf-8')
                        else:
                            if not filename or '/' in filename or '\\' in filename:
                                raise ValueError('invalid source filename')
                            files[name] = {'filename': filename, 'bytes': len(payload),
                                           'sha256': hashlib.sha256(payload).hexdigest()}
                    pid = match[1]
                    label = 'A' if pid == '15419' else 'B'
                    valid = (set(fields) == {'_token', 'answer_answer_upload_type', 'answer_answer_language', 'submit-answer'}
                        and fields['_token'] == f'fixture-only-{label}-not-real-csrf'
                        and fields['answer_answer_upload_type'] == 'file'
                        and fields['submit-answer'] == 'answer'
                        and fields['answer_answer_language'] in LANGUAGES
                        and set(files) == {'answer_answer_file'}
                        and 0 < files['answer_answer_file']['bytes'] <= 512 * 1024)
                    if not valid:
                        raise ValueError('form fields invalid')
                    source = files['answer_answer_file']
                    metadata = {"formFieldsValid": True, "source": source,
                                "language": fields['answer_answer_language']}
                except (ValueError, UnicodeError, TypeError, KeyError):
                    return self.json_response(400, {"synthetic": True, "error": "invalid_multipart_form"},
                                              metadata={"formFieldsValid": False})
                if owner.scenario != 'unknown503_no_record':
                    with owner._lock:
                        sid = str(owner._next_id)
                        owner._next_id += 1
                        owner._submissions.append({'id': sid, 'problemId': pid, 'account': owner.account,
                            'language': fields['answer_answer_language'], 'filename': source['filename'],
                            'sourceBytes': source['bytes'], 'sourceSha256': source['sha256'],
                            'submittedAt': int(time.time() * 1000), 'judgementReads': 0})
                    metadata['submissionId'] = sid
                if owner.scenario in {'unknown503', 'unknown503_no_record'}:
                    return self.json_response(503, {"synthetic": True, "error": "receipt_uncertain"}, metadata=metadata)
                return self.respond(302, headers={'Location': f'/submission/{sid}'}, metadata=metadata)

            def do_PUT(self):
                return self.json_response(405, {"synthetic": True, "error": "method_not_allowed"})

            do_PATCH = do_PUT
            do_DELETE = do_PUT

        self._httpd = ThreadingHTTPServer((self.host, self.requested_port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name='qoj-mvp-loopback-fixture', daemon=True)
        self._thread.start()
        return self
