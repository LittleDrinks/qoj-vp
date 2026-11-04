from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from qojvp import Application, ApplicationError

ROOT = Path(__file__).resolve().parents[2]
NOW = 1800000000000


class RanklandFixtureOriginTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-origin-')
        self.now = NOW

    def tearDown(self):
        self.directory.cleanup()

    def create(self, app, url):
        return app.dispatch('create_session', {'contestId': '3387', 'ranklandUrl': url})

    def test_fixture_only_loopback_origin_survives_create_start_prepare_and_update(self):
        with Application(self.directory.name, fixture_origin='http://127.0.0.1:34567', clock=lambda: self.now) as app:
            created = self.create(app, 'http://localhost:34568/?contest=fixture&rule=ICPC&run=default&from=120')
            sid = created['sessionId']
            args = {'sessionId': sid}
            started = app.dispatch('start_session', args)
            self.now += 20 * 60000
            prepared = app.dispatch('prepare_rankland', args)
            self.assertEqual(urlsplit(prepared['ranklandUrl']).netloc, 'localhost:34568')
            q = parse_qs(urlsplit(prepared['ranklandUrl']).query)
            self.assertNotIn('run', q)
            self.assertEqual((q['from'], q['speed']), (['0'], ['1']))
            self.assertIn('at', q)
            self.assertEqual(started['startAt'], NOW)
            unchanged = app.dispatch('update_session', {**args, 'ranklandUrl': prepared['ranklandUrl']})
            self.assertEqual(unchanged['ranklandUrl'], prepared['ranklandUrl'])
            changed = app.dispatch('update_session', {**args, 'ranklandUrl': 'http://127.0.0.1:34569/?contest=fixture&rule=ICPC'})
            self.assertEqual(urlsplit(changed['ranklandUrl']).netloc, '127.0.0.1:34569')
            self.assertFalse(changed['ranklandPrepared'])

    def test_production_rejects_loopback_and_arguments_cannot_enable_fixture_mode(self):
        with Application(self.directory.name, clock=lambda: self.now) as app:
            for url in ('http://localhost:34568/?contest=fixture', 'https://127.0.0.1:34568/?contest=fixture'):
                with self.subTest(url=url), self.assertRaises(ApplicationError):
                    app.dispatch('create_session', {'contestId': '3387', 'ranklandUrl': url,
                        'fixture_origin': 'http://localhost:34567', 'allow_loopback': True})
            official = self.create(app, 'https://vp.xcpc.link/?contest=official')
            self.assertEqual(urlsplit(official['ranklandUrl']).netloc, 'vp.xcpc.link')

    def test_fixture_mode_still_rejects_other_origins_credentials_and_missing_ports(self):
        urls = ['http://localhost/?contest=x', 'http://127.0.0.1/?contest=x',
            'http://localhost:0/?contest=x', 'http://localhost:65536/?contest=x',
            'http://evil.example:1234/?contest=x', 'https://vp.xcpc.link:443/?contest=x',
            'http://127.0.0.1.evil.example:1234/?contest=x', 'http://[::1]:1234/?contest=x',
            'http://user:password@localhost:1234/?contest=x', 'http://@localhost:1234/?contest=x',
            'http://localhost:1234/path?contest=x', 'http://localhost:1234/;params?contest=x',
            'http://localhost:1234/?contest=x#fragment', 'ftp://localhost:1234/?contest=x']
        with Application(self.directory.name, fixture_origin='http://127.0.0.1:34567', clock=lambda: self.now) as app:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ApplicationError):
                    self.create(app, url)


if __name__ == '__main__':
    unittest.main()
