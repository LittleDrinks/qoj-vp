from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from qojvp import Application, ApplicationError

ROOT = Path(__file__).resolve().parents[2]
AT = 1793540000000


class SessionSnapshotTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='session-snapshot-')
        # An unavailable upstream library must not matter for a local snapshot.
        self.app = Application(self.directory.name, qoj_path=ROOT / 'not-installed', clock=lambda: AT)
        self.session = self.app.dispatch('create_session', {
            'contestId': '3387', 'account': 'FixtureUser', 'startAt': AT - 10000})

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def snapshot(self, session=None):
        def forbidden_http(_):
            self.fail('A local session snapshot attempted a network request')
        return self.app.dispatch('session_snapshot', {'sessionId': (session or self.session)['sessionId']}, forbidden_http)

    def test_uncached_contest_returns_session_and_history_without_loading_upstream_or_http(self):
        snapshot = self.snapshot()
        self.assertIsNone(snapshot['contest'])
        self.assertEqual(snapshot['session'], self.app.dispatch('inspect_session', {'sessionId': self.session['sessionId']}))
        self.assertEqual(snapshot['history'], self.app.dispatch('qoj_submissions', {
            'sessionId': self.session['sessionId'], 'refresh': False}))

    def test_fourteen_cached_problems_and_unknown_history_are_available_without_reconcile(self):
        problems = {chr(65 + i): {'id': str(15419 + i), 'name': f'Problem {i}'} for i in range(14)}
        self.app.ledger.save_contest('FixtureUser', {'id': '3387', 'name': 'Cached practice', 'problems': problems})
        record = {'id': None, 'operationId': 'unknown-local', 'sessionId': self.session['sessionId'],
            'account': 'FixtureUser', 'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20',
            'submittedAt': AT, 'verdict': 'UNKNOWN', 'pending': False}
        self.app.ledger.begin_operation(record, 'snapshot-only')
        self.app.ledger.save_operation(record, 'unknown')
        snapshot = self.snapshot()
        self.assertEqual([p['label'] for p in snapshot['contest']['problems']], list('ABCDEFGHIJKLMN'))
        self.assertEqual(snapshot['contest']['source'], 'verified-cache')
        self.assertEqual(snapshot['history']['submissions'][0]['operationId'], 'unknown-local')
        self.assertEqual(snapshot['history']['submissions'][0]['state'], 'unknown')
        self.assertEqual(snapshot['history']['coverage']['complete'], False)
        self.assertFalse(self.app.ledger.db.in_transaction)

    def test_contest_cache_is_scoped_to_both_account_and_contest(self):
        contest = {'id': '3387', 'name': 'Other account', 'problems': {'A': {'id': '15419', 'name': 'A'}}}
        self.app.ledger.save_contest('OtherUser', contest)
        self.app.ledger.save_contest('FixtureUser', {**contest, 'id': '3388'})
        self.assertIsNone(self.snapshot()['contest'])
        anonymous = self.app.dispatch('create_session', {'contestId': '3387'})
        self.assertIsNone(self.snapshot(anonymous)['contest'])

    def test_deleted_session_is_not_revived_by_snapshot_and_read_transaction_closes(self):
        prepared = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser'})
        self.app.dispatch('delete_session', {'sessionId': prepared['sessionId'], 'confirmed': True})
        with self.assertRaises(ApplicationError) as caught:
            self.snapshot(prepared)
        self.assertEqual(caught.exception.code, 'NOT_FOUND')
        self.assertFalse(self.app.ledger.db.in_transaction)
        self.assertEqual(self.snapshot()['session']['sessionId'], self.session['sessionId'])

    def test_verified_navigation_survives_snapshot_and_rankland_compare_and_set_preserves_user_choice(self):
        self.app.ledger.save_contest('FixtureUser', {'id': '3387', 'name': 'Cached practice',
            'problems': {'A': {'id': '15419', 'name': 'A'}},
            'scoreboardUrl': 'https://qoj.ac/results/QOJ3387?mode=pc2',
            'discussionsUrl': 'https://qoj.ac/contest/3387/discussions'})
        snapshot = self.snapshot()
        self.assertEqual(snapshot['contest']['scoreboardUrl'], 'https://qoj.ac/results/QOJ3387?mode=pc2')
        sid = self.session['sessionId']
        automatic = self.app.dispatch('update_session', {'sessionId': sid, 'expectedRanklandUrl': None,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=automatic-match'})
        self.assertIn('contest=automatic-match', automatic['ranklandUrl'])
        chosen = self.app.dispatch('update_session', {'sessionId': sid,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=user-choice'})
        stale = self.app.dispatch('update_session', {'sessionId': sid, 'expectedRanklandUrl': None,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=stale-automatic-match'})
        self.assertEqual(stale, chosen)
        self.assertEqual(self.snapshot()['session']['ranklandUrl'], chosen['ranklandUrl'])

    def test_failed_rankland_compare_and_set_cannot_partially_change_other_fields(self):
        session = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser'})
        result = self.app.dispatch('update_session', {'sessionId': session['sessionId'],
            'expectedRanklandUrl': 'https://vp.xcpc.link/?contest=stale', 'title': 'Should not be written',
            'durationMs': 12345, 'ranklandUrl': 'https://vp.xcpc.link/?contest=ignored'})
        self.assertEqual(result, session)
        self.assertEqual(self.snapshot(session)['session'], session)

    def test_late_five_hour_lookup_cannot_bind_after_user_changes_prepared_contest_to_four_hours(self):
        lookup = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser',
            'durationMs': 5 * 60 * 60 * 1000})
        sid = lookup['sessionId']
        edited = self.app.dispatch('update_session', {'sessionId': sid, 'durationMs': 4 * 60 * 60 * 1000})
        self.assertIsNone(edited['ranklandUrl'], 'the URL alone cannot detect the intervening duration edit')
        stale = self.app.dispatch('update_session', {'sessionId': sid,
            'expectedRanklandUrl': lookup['ranklandUrl'], 'expectedDurationMs': lookup['durationMs'],
            'ranklandUrl': 'https://vp.xcpc.link/?contest=obsolete-five-hour-match',
            'title': 'Should not be written', 'durationMs': lookup['durationMs']})
        self.assertEqual(stale, edited)
        self.assertEqual(self.snapshot(lookup)['session'], edited)
        fresh = self.app.dispatch('update_session', {'sessionId': sid,
            'expectedRanklandUrl': edited['ranklandUrl'], 'expectedDurationMs': edited['durationMs'],
            'ranklandUrl': 'https://vp.xcpc.link/?contest=current-four-hour-match'})
        self.assertEqual(fresh['durationMs'], edited['durationMs'])
        self.assertIn('contest=current-four-hour-match', fresh['ranklandUrl'])


if __name__ == '__main__':
    unittest.main()
