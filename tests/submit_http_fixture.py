"""Run a packaged CLI against QOJ-shaped HTTP responses, with all traffic intercepted."""
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from html import escape
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

import requests

FIXTURES = Path(__file__).parent / 'browser/fixtures'


@contextmanager
def http_fixture(report, outcome):
    records, uploads = [], []

    def send(session, request, **kwargs):
        path = urlsplit(request.url).path
        records.append({'method': request.method, 'path': path})
        response = requests.Response()
        response.url = request.url
        response.status_code = 200
        response.encoding = 'utf-8'
        if request.method == 'POST':
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + request.headers['Content-Type'] + '\r\n\r\n').encode() + request.body)
            upload = {'path': path}
            for part in message.iter_parts():
                key = part.get_param('name', header='content-disposition')
                if part.get_filename():
                    upload['filename'] = part.get_filename()
                    upload['source'] = part.get_payload(decode=True).decode()
                elif key == 'answer_answer_language':
                    upload['language'] = part.get_payload(decode=True).decode()
            uploads.append(upload)
            if outcome == 'connection-error':
                raise requests.ConnectionError('fixture connection interrupted')
            response.status_code = 403 if outcome == 'rejected' else 302
            response.headers['Location'] = ('/contest/3387/submissions' if outcome == 'list-redirect'
                                            else '/submission/1000005')
            body = ''
        elif path == '/contest/3387':
            body = (FIXTURES / 'contest-3387.html').read_text()
        elif path in ('/contest/3387/problem/15419', '/contest/3387/problem/15420'):
            body = (FIXTURES / ('problem-' + path.rsplit('/', 1)[1] + '.html')).read_text()
        elif path == '/contest/3387/submissions':
            body = '<a href="/logout">Logout</a><a href="/user/profile/FixtureUser">My Profile</a>'
            body += '<table><tr><th>ID</th><th>Problem</th><th>Submitter</th><th>Language</th></tr>'
            if uploads:
                upload = uploads[-1]
                problem = upload['path'].split('/statement')[0]
                body += ('<tr><td><a href="/submission/1000005">1000005</a></td>'
                         f'<td><a href="{problem}">A</a></td>'
                         '<td><span class="uoj-username">FixtureUser</span></td>'
                         f'<td>{escape(upload["language"])}</td></tr>')
            body += '</table>'
        elif path == '/submission/1000005':
            body = '<pre><code class="sh_cpp">' + escape(uploads[-1]['source']) + '</code></pre>'
        else:
            raise AssertionError('Unexpected HTTP request: ' + request.method + ' ' + path)
        response._content = body.encode()
        return response

    try:
        with patch.object(requests.Session, 'send', send):
            yield
    finally:
        Path(report).write_text(json.dumps({'requests': records, 'uploads': uploads}))


def main():
    command, report, outcome, *arguments = sys.argv[1:]
    sys.argv = [command, *arguments]
    with http_fixture(report, outcome):
        runpy.run_path(command, run_name='__main__')


if __name__ == '__main__':
    main()
