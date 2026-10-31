from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from qojvp import Application

ROOT = Path(__file__).resolve().parents[1]
START = 1800000000000


class RanklandCompletedFirstOpenTests(unittest.TestCase):
    def test_first_open_at_or_after_end_uses_last_legal_second_without_changing_clock(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-completed-') as state:
            with Application(state, clock=lambda: START) as app:
                for lateness in (0, 7200000):
                    with self.subTest(lateness=lateness):
                        session = app.dispatch('create_session', {'contestId': '1051', 'account': 'SyntheticUser',
                            'startAt': START, 'durationMs': 18000000,
                            'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-lifecycle&rule=ICPC'})
                        app.clock = lambda: START + 18000000 + lateness
                        board = app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})
                        minutes = float(parse_qs(urlsplit(board['ranklandUrl']).query)['from'][0])
                        self.assertAlmostEqual(minutes * 60000, 18000000 - 1000, places=2)
                        self.assertEqual((board['effectiveState'], board['elapsedMs'], board['startAt']),
                                         ('finished', 18000000, START))
                        app.clock = lambda: START + 36000000
                        reopened = app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})
                        self.assertEqual(reopened['ranklandUrl'], board['ranklandUrl'])
                        self.assertEqual(reopened['ranklandPreparedAt'], board['ranklandPreparedAt'])

    def test_subsecond_duration_uses_zero_and_finished_state_survives_restart(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-short-') as state:
            with Application(state, clock=lambda: START + 1000) as app:
                session = app.dispatch('create_session', {'contestId': '1051', 'account': 'SyntheticUser',
                    'startAt': START, 'durationMs': 500, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-lifecycle'})
                board = app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})
                self.assertEqual(parse_qs(urlsplit(board['ranklandUrl']).query)['from'], ['0'])
                self.assertEqual((board['effectiveState'], board['elapsedMs']), ('finished', 500))
            with Application(state, clock=lambda: START + 10000) as app:
                self.assertEqual(app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})['ranklandUrl'], board['ranklandUrl'])

    def test_previously_frozen_url_is_never_migrated_even_if_old_offset_is_at_end(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-preserve-') as state:
            with Application(state, clock=lambda: START + 18000001) as app:
                session = app.dispatch('create_session', {'contestId': '1051', 'account': 'SyntheticUser',
                    'startAt': START, 'durationMs': 18000000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-lifecycle'})
                previous = app.ledger.session(session['sessionId'])
                previous['ranklandUrl'] = previous['ranklandUrl'].replace('from=0', 'from=300')
                previous.update(ranklandPrepared=True, ranklandPreparedAt=START + 18000000)
                app.ledger.save_session(previous)
                board = app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})
                self.assertEqual(board['ranklandUrl'], previous['ranklandUrl'])
                self.assertEqual(board['ranklandPreparedAt'], previous['ranklandPreparedAt'])


if __name__ == '__main__':
    unittest.main()
