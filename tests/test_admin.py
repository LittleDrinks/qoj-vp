from __future__ import annotations

import base64
import tempfile
import unittest

from qojvp import Application, ApplicationError
from tests.support import QojFixture
from tests.test_application import AT, CODE, ROOT


class LocalContestAdministrationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='admin-')
        self.clock = AT
        self.app = Application(self.directory.name, clock=lambda: self.clock)

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def create(self, **extra):
        return self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser',
            'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-admin', **extra})

    def action(self, name, session, **extra):
        return self.app.dispatch(name, {'sessionId': session['sessionId'], **extra},
                                 lambda _: self.fail('Local administration attempted HTTP'))

    def fact(self, session, sid, at):
        return self.app.ledger.save_submission(session['sessionId'], {'id': sid, 'account': 'FixtureUser',
            'problemId': '15419', 'problemLabel': 'A', 'submittedAt': at,
            'verdict': 'CORRECT', 'rawVerdict': 'AC', 'pending': False, 'state': 'confirmed'})

    def test_prepared_configuration_is_validated_and_locked_after_start(self):
        session = self.create()
        changed = self.action('update_session', session, title='Practice', durationMs=600000)
        self.assertEqual((changed['title'], changed['durationMs']), ('Practice', 600000))
        for value in (True, 0, -1, 14 * 24 * 3600000 + 1, '1000'):
            with self.subTest(duration=value), self.assertRaises(ApplicationError):
                self.action('update_session', session, durationMs=value)
        for value in ('', '   ', 'a' * 201, 'a\nb', 123):
            with self.subTest(title=value), self.assertRaises(ApplicationError):
                self.action('update_session', session, title=value)
        self.action('start_session', session)
        for args in ({'title': 'changed'}, {'durationMs': 700000}):
            with self.assertRaises(ApplicationError) as caught:
                self.action('update_session', session, **args)
            self.assertEqual(caught.exception.code, 'SESSION_NOT_PREPARED')
        self.assertIn('contest=other', self.action('update_session', session,
            ranklandUrl='https://vp.xcpc.link/?contest=other')['ranklandUrl'])

    def test_finish_is_local_freezes_elapsed_and_excludes_later_history_after_restart(self):
        session = self.create(startAt=AT - 600000)
        self.fact(session, '111', AT - 1000)
        finished = self.action('finish_session', session)
        self.assertEqual((finished['state'], finished['finishedAt'], finished['elapsedMs']), ('finished', AT, 600000))
        self.app.close()
        self.clock = AT + 7200000
        self.app = Application(self.directory.name, clock=lambda: self.clock)
        self.assertEqual(self.action('finish_session', session)['elapsedMs'], 600000)
        self.assertFalse(self.fact(session, '112', AT + 1000)['inSession'])
        self.assertEqual([row['submissionId'] for row in self.action('rankland_queue', session)['items']], ['111'])
        with self.assertRaises(ApplicationError):
            self.action('start_session', session)
        for record in (self.create(), self.create(startAt=self.clock + 1000)):
            with self.assertRaises(ApplicationError) as caught:
                self.action('finish_session', record)
            self.assertEqual(caught.exception.code, 'SESSION_NOT_RUNNING')

    def test_delete_requires_confirmation_and_running_session_must_end(self):
        session = self.create()
        for confirmation in (None, False, 1, 'true'):
            with self.subTest(confirmation=confirmation), self.assertRaises(ApplicationError) as caught:
                self.action('delete_session', session, confirmed=confirmation)
            self.assertEqual(caught.exception.code, 'CONFIRMATION_REQUIRED')
        self.action('start_session', session)
        with self.assertRaises(ApplicationError) as caught:
            self.action('delete_session', session, confirmed=True)
        self.assertEqual(caught.exception.code, 'SESSION_RUNNING')
        self.clock += session['durationMs']
        self.assertTrue(self.action('delete_session', session, confirmed=True)['deleted'])
        self.assertEqual(self.app.dispatch('list_sessions')['sessions'], [])

    def test_deleting_one_session_preserves_shared_facts_queues_and_resource_cache(self):
        first, second = self.create(startAt=AT - 600000), self.create(startAt=AT - 600000)
        self.fact(first, '111', AT - 1000)
        self.fact(second, '111', AT - 1000)
        self.fact(first, '112', AT - 2000)
        operation = {'sessionId': first['sessionId'], 'operationId': 'confirmed-only', 'submittedAt': AT - 1000,
                     'account': 'FixtureUser', 'id': '112'}
        self.app.ledger.begin_operation(operation, 'synthetic')
        self.app.ledger.save_operation(operation, 'confirmed')
        cache = self.app.resources.scope_path(first, '15419') / 'keep-shared.txt'
        cache.parent.mkdir(parents=True)
        cache.write_text('shared artifact sentinel')
        second_before = self.action('qoj_submissions', second, refresh=False)
        queue_before = self.action('rankland_queue', second)
        self.action('finish_session', first)
        self.assertEqual(self.action('delete_session', first, confirmed=True), {'deleted': True, 'sessionId': first['sessionId']})
        self.assertEqual(self.action('qoj_submissions', second, refresh=False), second_before)
        self.assertEqual(self.action('rankland_queue', second), queue_before)
        self.assertEqual(cache.read_text(), 'shared artifact sentinel')
        self.assertIsNone(self.app.ledger.operation('confirmed-only'))
        self.assertIsNone(self.app.ledger.provider_submission('FixtureUser', '112'))
        self.assertIsNotNone(self.app.ledger.provider_submission('FixtureUser', '111'))

    def test_unresolved_source_intents_block_deletion_even_after_archiving(self):
        for state in ('preparing', 'submitting', 'unknown'):
            with self.subTest(state=state):
                session = self.create(startAt=AT - 1000)
                record = {'sessionId': session['sessionId'], 'operationId': state, 'submittedAt': AT,
                          'account': 'FixtureUser', 'id': None}
                self.app.ledger.begin_operation(record, state)
                self.app.ledger.save_operation(record, state)
                self.action('archive_session', session)
                with self.assertRaises(ApplicationError) as caught:
                    self.action('delete_session', session, confirmed=True)
                self.assertEqual(caught.exception.code, 'UNRESOLVED_SUBMISSION')
                self.assertEqual(self.app.ledger.operation(state)['state'], state)
                self.assertEqual(self.action('inspect_session', session)['state'], 'archived')

    def test_finishing_during_form_lookup_prevents_the_later_source_post(self):
        session = self.create(startAt=AT - 1000)
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            ended = False
            def exchange(request):
                nonlocal ended
                reply = fixture.exchange(request)
                if '/problem/15419' in request['url'] and not ended:
                    ended = True
                    self.action('finish_session', session)
                return reply
            with self.assertRaises(ApplicationError):
                self.app.dispatch('qoj_submit', {'sessionId': session['sessionId'], 'operationId': 'finish-race',
                    'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20', 'filename': 'A.cpp',
                    'contentsBase64': base64.b64encode(CODE).decode()}, exchange)
            self.assertTrue(ended)
            self.assertEqual(fixture.posts, [])
            self.assertIsNone(self.app.ledger.operation('finish-race'))


if __name__ == '__main__':
    unittest.main()
