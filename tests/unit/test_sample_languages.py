from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse
import zipfile

from qojvp import Application
from qojvp.inline_samples import statement_sample_files
from tests.unit.support import QojFixture

ROOT = Path(__file__).resolve().parents[2]
ACTUAL_SAMPLES = (ROOT / 'tests/fixtures/qoj-1051-a-samples.html').read_text()
INPUT_SHA = '707961cefb6a97e0bc613828115d4336a58a352885b46026483890d38454c92e'
ANSWER_SHA = '6aa1db1e2ae35c7bf7321313636bfce971ab42b1620530ca7bbde2bc8371ca3c'
PROBLEM_PATH = '/contest/3387/problem/5113'


class StatementLanguageTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='sample-language-')
        self.fixture = QojFixture().__enter__()
        self.fixture.contest_html = ('<table><tr><td>A</td><td><a href="' + PROBLEM_PATH + '">Bridge</a></td></tr></table>')
        self.fixture.attachment_overrides['5113'] = (404, b'not found', 'text/plain')
        self.requests = []
        self.pages = {}
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin)
        self.session = self.app.dispatch('create_session', {'contestId': '3387', 'account': self.fixture.account})

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def exchange(self, request):
        path = urlparse(request['logicalUrl']).path
        self.requests.append((request['method'], path))
        if path in self.pages:
            html, status, target = self.pages[path]
            return {'response': {'status': status, 'url': target or request['logicalUrl'],
                'headers': {'Content-Type': 'text/html; charset=utf-8'},
                'bodyBase64': base64.b64encode(html.encode()).decode(), 'transport': 'sample-language-fixture'}}
        return self.fixture.exchange(request)

    def prepare(self, **args):
        return self.app.dispatch('prepare_resource', {'sessionId': self.session['sessionId'], 'problemId': '5113', **args}, self.exchange)

    def default_page(self, links):
        self.fixture.problem_html['5113'] = ('<div class="tab-pane active"><iframe src="/download.php?type=statement&amp;id=5113"></iframe></div>'
            + ''.join('<a href="' + href + '">Language</a>' for href in links))

    def assert_samples(self, entry):
        self.assertEqual((entry['status'], entry.get('kind'), entry.get('sampleSource')), ('ready', 'samples', 'inline-statement'))
        chunk = self.app.dispatch('resource_chunk', {'sessionId': self.session['sessionId'], 'problemId': '5113',
            'resourceId': entry['resourceId'], 'offset': 0})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(chunk['bytesBase64']))) as archive:
            self.assertEqual(sorted(archive.namelist()), ['samples-A/1.ans', 'samples-A/1.in'])
            self.assertEqual(hashlib.sha256(archive.read('samples-A/1.in')).hexdigest(), INPUT_SHA)
            self.assertEqual(hashlib.sha256(archive.read('samples-A/1.ans')).hexdigest(), ANSWER_SHA)
        self.assertFalse(any(method != 'GET' for method, _ in self.requests))

    def test_actual_xian_a_markup_already_parses_without_relaxing_sample_scope(self):
        files = statement_sample_files(ACTUAL_SAMPLES)
        self.assertEqual(hashlib.sha256(files['inline-1.in']).hexdigest(), INPUT_SHA)
        self.assertEqual(hashlib.sha256(files['inline-1.ans']).hexdigest(), ANSWER_SHA)
        self.fixture.problem_html['5113'] = ACTUAL_SAMPLES + '<a href="' + PROBLEM_PATH + '/statement/en">English</a>'
        self.assert_samples(self.prepare())
        self.assertFalse(any('/statement/' in path for _, path in self.requests))

    def test_default_pdf_follows_advertised_chinese_statement_before_other_languages(self):
        self.default_page([PROBLEM_PATH + '/statement/en', PROBLEM_PATH + '/statement/default', PROBLEM_PATH + '/statement/zh_cn'])
        self.pages[PROBLEM_PATH + '/statement/zh_cn'] = (ACTUAL_SAMPLES, 200, None)
        self.assert_samples(self.prepare())
        self.assertEqual([path for _, path in self.requests if '/statement/' in path], [PROBLEM_PATH + '/statement/zh_cn'])

    def test_other_problem_external_and_query_links_are_not_followed(self):
        self.default_page(['https://example.org' + PROBLEM_PATH + '/statement/zh_cn',
            '/contest/3387/problem/5114/statement/zh_cn', PROBLEM_PATH + '/statement/zh_cn?token=synthetic',
            'https://qoj.ac@evil.example' + PROBLEM_PATH + '/statement/en', PROBLEM_PATH + '/statement/en#fragment', 'http://['])
        self.assertEqual(self.prepare()['status'], 'unknown')
        self.assertFalse(any('/statement/' in path for _, path in self.requests))

    def test_discovery_is_bounded_and_does_not_invent_unadvertised_urls(self):
        languages = ['fr', 'default', 'en', 'zh', 'zh_cn']
        self.default_page([PROBLEM_PATH + '/statement/' + language for language in languages])
        for language in languages:
            self.pages[PROBLEM_PATH + '/statement/' + language] = ('not found', 404, None)
        self.assertEqual(self.prepare()['status'], 'unknown')
        self.assertEqual([path for _, path in self.requests if '/statement/' in path],
            [PROBLEM_PATH + '/statement/' + language for language in ['zh_cn', 'zh', 'en']])

    def test_interactive_hint_stops_statement_and_language_fallback(self):
        self.default_page([PROBLEM_PATH + '/statement/zh_cn'])
        self.pages[PROBLEM_PATH + '/statement/zh_cn'] = (ACTUAL_SAMPLES, 200, None)
        self.assertEqual(self.prepare(interactiveHint=True)['status'], 'unknown')
        self.assertFalse(any(path.startswith(PROBLEM_PATH) for _, path in self.requests))

    def test_language_redirect_cannot_import_another_problem_or_login_page(self):
        for target, code in [('https://qoj.ac/contest/3387/problem/5114/statement/zh_cn', 'SAMPLES_UNAVAILABLE'),
                             ('https://qoj.ac/login', 'LOGIN_REQUIRED')]:
            with self.subTest(target=target):
                self.default_page([PROBLEM_PATH + '/statement/zh_cn'])
                self.pages[PROBLEM_PATH + '/statement/zh_cn'] = (ACTUAL_SAMPLES, 200, target)
                entry = self.prepare()
                self.assertEqual(entry['status'], 'unknown')
                self.assertEqual(entry['lastAttempt']['code'], code)


if __name__ == '__main__':
    unittest.main()
