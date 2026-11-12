from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from qojvp import Application, ApplicationError
from tests.unit.support import account_menu, FIXTURES


class SubmitterReadinessTests(unittest.TestCase):
    def test_cli_binding_dry_run_and_account_are_independent_of_browser_login(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_DATA_HOME': directory}):
            with Application(Path(directory) / 'vp') as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser'})
                args = {'sessionId': session['sessionId'], 'problem': 'A', 'language': 'cpp'}
                traffic = []
                account = ['FixtureUser']

                def send(client, request, **kwargs):
                    traffic.append((request.method, urlsplit(request.url).path))
                    self.assertEqual(request.method, 'GET', 'A dry-run must never upload source')
                    path = urlsplit(request.url).path
                    if path == '/':
                        body = account_menu(account[0])
                    elif path == '/contest/3387':
                        body = (FIXTURES / 'contest-3387.html').read_text()
                    elif path == '/contest/3387/problem/15419':
                        body = (FIXTURES / 'problem-15419.html').read_text()
                    else:
                        self.fail('Unexpected request: ' + path)
                    response = requests.Response()
                    response.url, response.status_code = request.url, 200
                    response._content = body.encode()
                    response.encoding = 'utf-8'
                    return response

                with patch.object(requests.Session, 'send', send), redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(ApplicationError) as missing:
                        app.dispatch('submitter_check', args)
                    self.assertEqual(missing.exception.code, 'SUBMITTER_CONTEST_REQUIRED')
                    ready = app.dispatch('submitter_bind', args)
                    self.assertEqual(ready['account'], 'FixtureUser')
                    self.assertTrue(ready['ready'])
                    self.assertIn('Dry run:', ready['output'])
                    config = json.loads((Path(directory) / 'qoj-submitter/config.json').read_text())
                    self.assertEqual(str(config['contests']['https://qoj.ac']['id']), '3387')
                    self.assertTrue(app.dispatch('submitter_check', args)['ready'])
                    account[0] = 'AnotherUser'
                    with self.assertRaises(ApplicationError) as mismatch:
                        app.dispatch('submitter_check', args)
                    self.assertEqual(mismatch.exception.code, 'SUBMITTER_ACCOUNT_MISMATCH')
                    self.assertEqual(output.getvalue(), '', 'CLI output must not corrupt native messaging')
                self.assertTrue(traffic)
