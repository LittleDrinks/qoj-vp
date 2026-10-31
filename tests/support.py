"""QOJ-shaped HTTP test server with explicit synthetic submit receipts."""
from __future__ import annotations

import base64
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

import requests

FIXTURES = Path(__file__).resolve().parents[1] / 'preflight/fixtures'


class QojFixture:
    def __init__(self):
        self.posts = []
        self.history_reads = []
        self.reject = False
        self.disconnect = False
        self.account = 'FixtureUser'
        self.receipt = '/submission/1000001'
        self.history_html = None
        self.detail_overrides = {}
        self.unknown_fields = False

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, code, content, content_type='text/html; charset=utf-8', headers=None):
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(content)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(content)

            def do_GET(self):
                parsed = urlsplit(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path == '/':
                    data = f'<a href="/logout">Logout</a><a href="/user/profile/{owner.account}">My Profile</a>'.encode()
                    return self.respond(200, data)
                if path == '/contest/3387':
                    name = 'contest-3387.html'
                elif path.startswith('/contest/3387/problem/'):
                    name = f"problem-{path.split('/')[4]}.html"
                elif path == '/contest/3387/submissions':
                    owner.history_reads.append(query)
                    if owner.history_html is not None and query.get('page', ['1'])[0] == '1':
                        return self.respond(200, owner.history_html.encode())
                    name = 'submissions-3387.html' if query.get('page', ['1'])[0] == '1' else 'submissions-empty.html'
                elif path.startswith('/submission/'):
                    sid = path.rsplit('/', 1)[-1]
                    if sid in owner.detail_overrides:
                        return self.respond(200, owner.detail_overrides[sid].encode())
                    name = f'submission-{sid}.html'
                elif path == '/download.php':
                    name = f"attachment-{query.get('id', [''])[0]}.zip"
                    return self.respond(200, (FIXTURES / name).read_bytes(), 'application/zip')
                elif path == '/fixture-statements/A.pdf':
                    return self.respond(200, (FIXTURES / 'statement-A.pdf').read_bytes(), 'application/pdf')
                else:
                    return self.respond(404, b'not found')
                target = FIXTURES / name
                if not target.is_file():
                    return self.respond(404, b'not found')
                return self.respond(200, target.read_bytes())

            def do_POST(self):
                data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                msg = BytesParser(policy=default).parsebytes(
                    ('Content-Type: ' + self.headers['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + data)
                fields, files = {}, {}
                for part in msg.iter_parts():
                    name = part.get_param('name', header='content-disposition')
                    if part.get_filename():
                        files[name] = {'filename': part.get_filename(), 'content': part.get_payload(decode=True)}
                    else:
                        fields[name] = part.get_payload(decode=True).decode()
                # Test-only inspection of a synthetic token and source. Never
                # used against a real OJ or written as production request logs.
                owner.posts.append({'path': urlsplit(self.path).path, 'fields': fields, 'files': files})
                if owner.disconnect:
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                if owner.reject:
                    return self.respond(400, b'rejected')
                return self.respond(302, b'', headers={'Location': owner.receipt})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def exchange(self, message):
        files = {item['field']: (item['filename'], base64.b64decode(item['contentsBase64']), item['contentType'])
                 for item in message.get('files', [])}
        try:
            response = requests.request(message['method'], message['url'], headers=message.get('headers'),
                                        data=message.get('data'), files=files or None,
                                        allow_redirects=message['allowRedirects'], timeout=4)
        except requests.RequestException:
            return {'error': {'code': 'SYNTHETIC_DISCONNECT'}}
        return {'response': {'status': response.status_code, 'url': response.url, 'headers': dict(response.headers),
                             'bodyBase64': base64.b64encode(response.content).decode(),
                             'transport': 'python-http-integration-driver'}}
