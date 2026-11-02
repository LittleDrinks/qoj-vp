from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
import unittest

from qojvp import Application, ApplicationError
from tests.support import QojFixture
from tests.test_detail_metadata import detail_page

ROOT = Path(__file__).resolve().parents[1]
START = 1800000000000
MINUTE = 60000


class RanklandPlanTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-plan-')
        self.now = START + 25 * MINUTE
        self.app = Application(self.directory.name, clock=lambda: self.now)
        self.session = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser',
            'startAt': START, 'durationMs': 5 * 60 * MINUTE,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-delayed'})
        self.args = {'sessionId': self.session['sessionId']}

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def fact(self, sid, minute, verdict='CORRECT', problem='A', **extra):
        return self.app.ledger.save_submission(self.session['sessionId'], {
            'id': str(sid), 'account': 'FixtureUser', 'problemId': '15419' if problem == 'A' else '15420',
            'problemLabel': problem, 'submittedAt': START + minute * MINUTE,
            'timeSource': 'provider-absolute', 'verdict': verdict, 'rawVerdict': verdict,
            'pending': verdict == 'JUDGING', 'state': 'confirmed', 'language': 'C++20',
            'url': f'https://qoj.ac/submission/{sid}', **extra})

    def plan(self):
        return self.app.dispatch('rankland_plan', self.args)

    def ack(self, item):
        return self.app.dispatch('rankland_ack', {**self.args, 'queueId': item['queueId'],
            'revision': item['revision'], 'state': 'synced',
            'receipt': {'targetKey': 'synthetic', 'problemIndex': 0, 'timeMs': item['elapsedMs'], 'result': 'AC'}})

    def ack_plan(self, plan=None):
        plan = plan or self.plan()
        return self.app.dispatch('rankland_ack_batch', {**self.args, 'planToken': plan['planToken'],
            'acknowledgements': [{'queueId': item['queueId'], 'revision': item['revision'], 'state': 'synced'}
                                 for item in plan['allItems']]})

    def due(self):
        return self.app.dispatch('refresh_sessions')['sessions']

    @staticmethod
    def history(rows):
        result = ['<table><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Time</th></tr>']
        for sid, minute, verdict, problem in rows:
            at = datetime.fromtimestamp((START + minute * MINUTE) / 1000, timezone.utc).isoformat()
            pid = '15419' if problem == 'A' else '15420'
            value = f'<span id="status_details_{sid}">Judging</span>' if verdict == 'JUDGING' else verdict
            result.append(f'<tr><td><a href="/submission/{sid}">{sid}</a></td>'
                '<td><a href="/user/profile/FixtureUser">FixtureUser</a></td>'
                f'<td><a href="/contest/3387/problem/{pid}">{problem}</a></td><td>{value}</td><td>C++20</td>'
                f'<td><time datetime="{at}">{at}</time></td></tr>')
        return ''.join(result) + '</table>'

    def test_five_minute_delay_keeps_original_time_and_blocks_only_its_problem(self):
        self.fact('101', 20, 'JUDGING')
        self.fact('102', 22)
        self.fact('103', 23, problem='B')
        waiting = self.plan()
        self.assertEqual([item['submissionId'] for item in waiting['items']], ['103'])
        self.assertEqual(waiting['pendingCount'], 1)
        self.assertEqual(waiting['blockedCount'], 1)
        self.assertEqual({item['submissionId'] for item in waiting['waiting']}, {'101', '102'})
        self.now = START + 25 * MINUTE
        self.fact('101', 20, 'WRONG-ANSWER')
        ready = self.plan()
        self.assertEqual([(item['submissionId'], item['elapsedMs']) for item in ready['items']],
                         [('101', 20 * MINUTE), ('102', 22 * MINUTE), ('103', 23 * MINUTE)])
        self.assertEqual(ready['waiting'], [])

    def test_distinct_same_minute_attempts_keep_source_identity_and_numeric_order(self):
        self.fact('10', 20, 'WRONG-ANSWER')
        self.fact('9', 20, 'WRONG-ANSWER')
        items = self.plan()['items']
        self.assertEqual([item['submissionId'] for item in items], ['9', '10'])
        self.assertEqual(len({item['sourceId'] for item in items}), 2)
        self.assertEqual(len({item['queueId'] for item in items}), 2)

    def test_rejudge_replaces_one_source_and_pending_rejudge_withdraws_old_final(self):
        self.fact('101', 20)
        original = self.plan()['items'][0]
        self.ack(original)
        self.fact('101', 20, 'TIMELIMIT')
        corrected = self.plan()['items'][0]
        self.assertEqual(corrected['sourceId'], original['sourceId'])
        self.assertEqual(corrected['queueId'], original['queueId'])
        self.assertEqual(corrected['verdict'], 'TIMELIMIT')
        self.assertGreater(corrected['revision'], original['revision'])
        self.assertFalse(self.ack(original)['accepted'])
        self.fact('101', 20, 'JUDGING')
        self.fact('102', 21)
        plan = self.plan()
        self.assertEqual(plan['items'], [])
        self.assertEqual(plan['pendingCount'], 1)
        self.assertEqual({item['submissionId'] for item in plan['allItems']}, {'101', '102'})

    def test_confirmed_time_correction_outside_session_is_not_kept_in_projection(self):
        self.fact('101', 20)
        original = self.plan()['items'][0]
        self.ack(original)
        self.fact('101', -1)
        plan = self.plan()
        self.assertEqual(plan['items'], [])
        self.assertEqual(len(plan['allItems']), 1, 'retain ownership metadata so the old projection can be withdrawn')
        self.assertGreater(plan['allItems'][0]['revision'], original['revision'])

    def test_unknown_receipt_blocks_later_same_problem_without_fabricating_a_submission(self):
        record = {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt',
            'account': 'FixtureUser', 'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20',
            'submittedAt': START + 20 * MINUTE, 'verdict': 'UNKNOWN', 'pending': False, 'state': 'unknown'}
        self.app.ledger.begin_operation(record, 'synthetic-source-fingerprint')
        self.app.ledger.save_operation(record, 'unknown')
        self.fact('102', 22)
        self.fact('103', 23, problem='B')
        plan = self.plan()
        self.assertEqual([item['submissionId'] for item in plan['items']], ['103'])
        self.assertEqual(plan['pendingCount'], 1)
        self.assertEqual(plan['waiting'][0]['operationId'], 'lost-receipt')

    def test_finished_pending_record_remains_due_after_helper_restart(self):
        self.fact('101', 299, 'JUDGING')
        self.now = START + 304 * MINUTE
        self.app.dispatch('finish_session', self.args)
        self.app.close()
        self.app = Application(self.directory.name, clock=lambda: self.now)
        due = self.due()
        self.assertEqual(len(due), 1)
        self.assertTrue(due[0]['refreshRequired'])
        self.assertEqual(due[0]['pendingCount'], 1)
        self.fact('101', 299)
        self.assertEqual(self.plan()['items'][0]['elapsedMs'], 299 * MINUTE)

    def test_prepared_future_and_archived_sessions_are_not_automatically_polled(self):
        self.app.dispatch('archive_session', self.args)
        for extra in ({}, {'startAt': self.now + MINUTE}):
            self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser', **extra})
        self.assertEqual(self.due(), [])

    def test_post_deadline_history_pass_retries_failure_then_stops_after_delivery(self):
        self.now = START + 301 * MINUTE
        self.assertTrue(self.due()[0]['refreshRequired'])
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            fixture.history_html = self.history([('101', 299, 'AC', 'A')])
            def failed(request):
                if '/submissions?' in request['url']:
                    return {'error': {'code': 'SYNTHETIC_OFFLINE'}}
                return fixture.exchange(request)
            result = self.app.dispatch('qoj_submissions', self.args, failed)
            self.assertFalse(result['coverage']['complete'])
            self.assertTrue(self.due()[0]['refreshRequired'])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            due = self.due()
            self.assertFalse(due[0]['refreshRequired'])
            self.assertTrue(due[0]['syncRequired'])
            self.ack_plan()
            self.assertEqual(self.due(), [])
            self.assertEqual(fixture.posts, [])

    def test_qoj_history_delay_across_deadline_then_rejudge_uses_same_id_and_timestamp(self):
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            self.now = START + 299 * MINUTE
            fixture.history_html = self.history([('102', 299, 'AC', 'A'), ('101', 297, 'JUDGING', 'A')])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            self.assertEqual(self.plan()['items'], [])
            self.now = START + 304 * MINUTE
            fixture.history_html = self.history([('102', 299, 'AC', 'A'), ('101', 297, 'WA', 'A')])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            original = self.plan()['items']
            self.assertEqual([(item['submissionId'], item['elapsedMs'], item['verdict']) for item in original],
                [('101', 297 * MINUTE, 'WRONG-ANSWER'), ('102', 299 * MINUTE, 'CORRECT')])
            self.ack_plan()
            self.assertEqual(self.due(), [])
            fixture.history_html = self.history([('102', 299, 'AC, TL', 'A'), ('101', 297, 'WA', 'A')])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            updated = self.plan()['items'][1]
            self.assertEqual((updated['queueId'], updated['sourceId'], updated['elapsedMs']),
                (original[1]['queueId'], original[1]['sourceId'], original[1]['elapsedMs']))
            self.assertEqual(updated['verdict'], 'TIMELIMIT')
            self.assertTrue(self.due()[0]['syncRequired'])
            self.assertFalse(self.due()[0]['refreshRequired'])
            self.assertEqual(fixture.posts, [])

    def test_history_pass_started_before_deadline_does_not_settle_the_end_of_contest(self):
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            fixture.history_html = self.history([])
            self.now = START + 300 * MINUTE - 1
            def slow(request):
                response = fixture.exchange(request)
                if '/submissions?' in request['url']:
                    self.now = START + 300 * MINUTE + 1
                return response
            self.app.dispatch('qoj_submissions', self.args, slow)
            self.assertTrue(self.due()[0]['refreshRequired'])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            self.ack_plan()
            self.assertEqual(self.due(), [])

    def test_local_send_time_is_not_used_when_qoj_acceptance_was_delayed(self):
        self.fact('101', 20, 'JUDGING', timeSource='local-intent')
        self.now = START + 304 * MINUTE
        self.app.dispatch('finish_session', self.args)
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            fixture.history_html = re.sub(r'<time[^>]*>[^<]*</time>', '00:25:00', self.history([('101', 25, 'AC', 'A')]))
            fixture.detail_overrides['101'] = '<p>Synthetic temporarily unavailable submission detail</p>'
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            pending = self.plan()
            self.assertEqual(pending['items'], [], 'local send time is not an authoritative QOJ receipt timestamp')
            self.assertEqual(pending['waiting'][0]['reason'], 'time-unverified')
            self.now += MINUTE
            accepted = datetime.fromtimestamp((START + 25 * MINUTE) / 1000, timezone.utc).isoformat()
            fixture.detail_overrides['101'] = detail_page(sid='101', owner='FixtureUser', pid='15419', date=accepted)
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            self.assertEqual(self.plan()['items'][0]['elapsedMs'], 25 * MINUTE)
            self.assertEqual(fixture.posts, [])

    def test_batch_ack_is_atomic_and_stale_revision_cannot_ack_other_items(self):
        self.fact('101', 20, 'WRONG-ANSWER')
        self.fact('102', 22)
        items = self.plan()['items']
        acknowledgements = [{'queueId': item['queueId'], 'revision': item['revision'], 'state': 'synced'} for item in items]
        self.fact('102', 22, 'TIMELIMIT')
        stale = self.app.dispatch('rankland_ack_batch', {**self.args, 'acknowledgements': acknowledgements})
        self.assertFalse(stale['accepted'])
        self.assertEqual(stale['reason'], 'stale-revision')
        self.assertTrue(all(item['state'] != 'synced' for item in self.plan()['allItems']))
        updated = [{**item, 'revision': row['revision']} for item, row in zip(acknowledgements, self.plan()['items'])]
        accepted = self.app.dispatch('rankland_ack_batch', {**self.args, 'acknowledgements': updated})
        self.assertTrue(accepted['accepted'])
        self.assertEqual(len(accepted['results']), 2)
        self.assertTrue(all(item['state'] == 'synced' for item in self.plan()['allItems']))

    def test_batch_ack_rejects_duplicate_invalid_or_oversized_batches_without_mutation(self):
        self.fact('101', 20)
        item = self.plan()['items'][0]
        ack = {'queueId': item['queueId'], 'revision': item['revision'], 'state': 'synced'}
        invalid = [None, {}, [ack, ack], [dict(ack, revision=True)], [dict(ack, state='pending')], [ack] * 10001]
        for acknowledgements in invalid:
            with self.subTest(batch_type=type(acknowledgements).__name__), self.assertRaises(ApplicationError):
                self.app.dispatch('rankland_ack_batch', {**self.args, 'acknowledgements': acknowledgements})
        self.assertEqual(self.plan()['allItems'][0]['state'], 'pending')
        self.assertEqual(self.app.dispatch('rankland_ack_batch', {**self.args, 'acknowledgements': []}),
                         {'accepted': True, 'results': []})

    def test_withdrawn_final_batch_ack_stops_finished_delivery_retries(self):
        self.fact('101', 20)
        self.ack(self.plan()['items'][0])
        self.fact('101', -1)
        self.now = START + 301 * MINUTE
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now, complete=True)
        self.assertFalse(self.due()[0]['refreshRequired'])
        self.assertTrue(self.due()[0]['syncRequired'])
        self.ack_plan()
        self.assertEqual(self.due(), [])

    def test_plan_token_catches_receipt_resolution_without_a_changed_provider_revision(self):
        record = {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt',
            'account': 'FixtureUser', 'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20',
            'submittedAt': START + 20 * MINUTE, 'verdict': 'UNKNOWN', 'pending': False, 'state': 'unknown'}
        self.app.ledger.begin_operation(record, 'synthetic-source-fingerprint')
        self.app.ledger.save_operation(record, 'unknown')
        self.fact('102', 22)
        self.now = START + 301 * MINUTE
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now, complete=True)
        blocked = self.plan()
        self.ack_plan(blocked)
        self.assertTrue(self.due()[0]['refreshRequired'])
        self.assertFalse(self.due()[0]['syncRequired'])
        self.app.ledger.confirm_operation('lost-receipt', '102')
        ready = self.plan()
        self.assertEqual(ready['allItems'][0]['revision'], blocked['allItems'][0]['revision'])
        self.assertNotEqual(ready['planToken'], blocked['planToken'])
        self.assertFalse(self.due()[0]['refreshRequired'])
        self.assertTrue(self.due()[0]['syncRequired'])
        self.assertEqual(self.ack_plan(blocked)['reason'], 'stale-plan')
        self.ack_plan(ready)
        self.assertEqual(self.due(), [])

    def test_plan_token_is_stable_across_polling_delivery_bookkeeping_and_helper_restart(self):
        self.fact('101', 20)
        first = self.plan()['planToken']
        self.ack_plan()
        self.now += MINUTE
        self.fact('101', 20)
        self.assertEqual(self.plan()['planToken'], first)
        self.app.close()
        self.app = Application(self.directory.name, clock=lambda: self.now)
        self.assertEqual(self.plan()['planToken'], first)
        self.assertFalse(self.due()[0]['syncRequired'])
        self.app.dispatch('update_session', {**self.args, 'ranklandUrl': 'https://vp.xcpc.link/?contest=another-target'})
        self.assertNotEqual(self.plan()['planToken'], first)
        self.assertTrue(self.due()[0]['syncRequired'])

    def test_empty_plan_can_settle_but_partial_projection_acknowledgement_is_rejected(self):
        self.now = START + 301 * MINUTE
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now, complete=True)
        self.assertTrue(self.due()[0]['syncRequired'])
        self.ack_plan()
        self.assertEqual(self.due(), [])
        self.fact('101', 20)
        with self.assertRaises(ApplicationError):
            self.app.dispatch('rankland_ack_batch', {**self.args, 'planToken': self.plan()['planToken'], 'acknowledgements': []})

    def test_failed_explicit_refresh_reopens_finished_settlement_until_complete_retry(self):
        self.now = START + 301 * MINUTE
        with QojFixture() as fixture:
            self.app.fixture_origin = fixture.origin
            fixture.history_html = self.history([('101', 20, 'AC', 'A')])
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            self.ack_plan()
            self.assertEqual(self.due(), [])
            previous_complete = self.app.dispatch('inspect_session', self.args)['lastHistoryCompleteAt']
            self.now += MINUTE
            def unavailable(request):
                if '/submissions?' in request['url']:
                    return {'error': {'code': 'SYNTHETIC_OFFLINE'}}
                return fixture.exchange(request)
            cached = self.app.dispatch('qoj_submissions', self.args, unavailable)
            self.assertEqual((cached['coverage']['complete'], cached['coverage']['pages']), (False, 0))
            session = self.app.dispatch('inspect_session', self.args)
            self.assertFalse(session['lastHistoryRefreshComplete'])
            self.assertEqual(session['lastHistoryCompleteAt'], previous_complete)
            self.assertTrue(self.due()[0]['refreshRequired'])
            self.app.close()
            self.app = Application(self.directory.name, fixture_origin=fixture.origin, clock=lambda: self.now)
            self.assertTrue(self.due()[0]['refreshRequired'])
            self.now += MINUTE
            self.app.dispatch('qoj_submissions', self.args, fixture.exchange)
            self.assertTrue(self.app.dispatch('inspect_session', self.args)['lastHistoryRefreshComplete'])
            self.assertEqual(self.due(), [])
            self.assertEqual(fixture.posts, [])

    def test_older_complete_pass_cannot_hide_newer_incomplete_refresh(self):
        self.now = START + 301 * MINUTE
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now, complete=True)
        self.ack_plan()
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now + MINUTE, complete=False)
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now + 1, complete=True)
        session = self.app.dispatch('inspect_session', self.args)
        self.assertFalse(session['lastHistoryRefreshComplete'])
        self.assertEqual(session['lastHistoryRefreshAt'], self.now + MINUTE)
        self.assertTrue(self.due()[0]['refreshRequired'])

    def test_failure_before_history_get_is_still_retried_after_finished_settlement(self):
        self.now = START + 301 * MINUTE
        self.app.ledger.mark_history_refresh(self.session['sessionId'], self.now, complete=True)
        self.ack_plan()
        self.assertEqual(self.due(), [])
        self.now += MINUTE
        with self.assertRaises(ApplicationError):
            self.app.dispatch('qoj_submissions', self.args, lambda _: {'error': {'code': 'SYNTHETIC_OFFLINE'}})
        self.assertFalse(self.app.dispatch('inspect_session', self.args)['lastHistoryRefreshComplete'])
        self.assertTrue(self.due()[0]['refreshRequired'])


if __name__ == '__main__':
    unittest.main()
