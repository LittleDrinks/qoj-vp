from __future__ import annotations

from html import escape
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit

from qojvp import Application
from qojvp.history import submission_time_metadata
from tests.unit.support import QojFixture
from tests.unit.test_history import SUBMITTED_AT, actual_schema_history

ROOT = Path(__file__).resolve().parents[2]
ISO = '2026-11-01T02:20:57+08:00'


def detail_page(sid='3331061', owner='LittleDrinks', pid='5115', cid='3387', date=ISO, verdict='Accepted'):
    # Header topology is from the real native-VP submission metadata table.
    return ('<table><thead><tr><th>ID</th><th>Problem</th><th>Submitter</th><th>Result</th><th>Time</th>'
        '<th>Memory</th><th>Language</th><th>File size</th><th>Submit time</th></tr></thead><tbody><tr>'
        '<td><a href="/submission/' + sid + '">#' + sid + '</a></td>'
        '<td><a href="/contest/' + cid + '/problem/' + pid + '">C. Clone Ranran</a></td>'
        '<td><span class="uoj-username">' + escape(owner) + '</span></td><td>100</td>'
        '<td><time class="uoj-time" datetime="1999-01-01T01:00:00+00:00">execution column decoy</time></td>'
        '<td>32 KB</td><td>C++20</td><td>24b</td><td><time class="uoj-time" datetime="' + escape(date) + '">'
        + escape(date) + '</time></td></tr></tbody></table>'
        '<footer><time class="uoj-time" datetime="2030-01-01T00:00:00+08:00">footer decoy</time></footer>'
        '<div class="card"><div class="card-header">Details</div><div class="col-sm-2">' + verdict + '</div></div>')


def relative_history(sid='3331061', score='100.000000', result='AC ✓'):
    html = actual_schema_history(cid='3387', score=score, result=result).replace('3331061', sid)
    return re.sub(r'<time[^>]*>[^<]*</time>', '00:10:00', html)


class DetailMetadataParserTests(unittest.TestCase):
    def parse(self, html):
        return submission_time_metadata(html, '3387', 'LittleDrinks', '3331061', '5115')

    def test_exact_submit_time_column_beats_execution_time_and_footer(self):
        metadata = self.parse(detail_page())
        self.assertEqual(metadata['submittedAt'], SUBMITTED_AT)
        self.assertEqual(metadata['timeSource'], 'provider-absolute')

    def test_wrong_submission_account_problem_or_unzoned_clock_are_rejected(self):
        variants = [detail_page(sid='3331062'), detail_page(owner='OtherUser'), detail_page(pid='5116'),
                    detail_page(date='2026-11-01T02:20:57'), detail_page(date='00:10:00'),
                    detail_page().replace('<th>Submit time</th>', '<th>Unknown timestamp</th>'),
                    detail_page().replace('<span class="uoj-username">LittleDrinks</span>', 'LittleDrinks')]
        for html in variants:
            with self.subTest(html=html[:80]):
                self.assertIsNone(self.parse(html))

    def test_foreign_problem_link_and_ambiguous_metadata_tables_are_rejected(self):
        self.assertIsNone(self.parse(detail_page().replace('href="/contest/3387/problem/5115"',
                                                          'href="https://other.example/contest/3387/problem/5115"')))
        self.assertIsNone(self.parse(detail_page() + detail_page()))
        self.assertIsNone(self.parse(detail_page().replace('href="/contest/3387/problem/5115"', 'href="/problem/5115"')))


class DetailMetadataDispatchTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.state = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='provider-metadata-')
        self.fixture = QojFixture().__enter__()
        self.fixture.account = 'LittleDrinks'
        self.fixture.contest_html = ('<title>Synthetic practice</title><table><tr><td>C</td><td>'
            '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
        self.fixture.history_html = relative_history()
        self.fixture.detail_overrides['3331061'] = detail_page()
        self.clock = SUBMITTED_AT + 1000
        self.app = Application(self.state.name, fixture_origin=self.fixture.origin, clock=lambda: self.clock)
        self.session = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks',
            'startAt': SUBMITTED_AT - 60000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-metadata'})
        self.detail_gets = []

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.state.cleanup()

    def exchange(self, request):
        path = urlsplit(request['logicalUrl']).path
        if path.startswith('/submission/'):
            self.detail_gets.append(path)
        return self.fixture.exchange(request)

    def refresh(self):
        return self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, self.exchange)

    def restart(self):
        self.app.close()
        self.app = Application(self.state.name, fixture_origin=self.fixture.origin, clock=lambda: self.clock)

    def test_external_relative_ac_gets_provider_time_and_queue_then_reuses_it_after_restart(self):
        row = self.refresh()['submissions'][0]
        self.assertEqual((row['submittedAt'], row['timeSource'], row['verdict']), (SUBMITTED_AT, 'provider-absolute', 'CORRECT'))
        self.assertEqual(self.detail_gets, ['/submission/3331061'])
        queue = self.app.dispatch('rankland_queue', {'sessionId': self.session['sessionId']})['items']
        self.assertEqual((queue[0]['submissionId'], queue[0]['elapsedMs']), ('3331061', 60000))
        self.restart(); self.detail_gets.clear()
        self.assertEqual(self.refresh()['submissions'][0]['submittedAt'], SUBMITTED_AT)
        self.assertEqual(self.detail_gets, [])
        self.assertEqual(self.fixture.posts, [])

    def test_missing_metadata_retries_after_60_seconds_across_helper_restart(self):
        self.fixture.detail_overrides['3331061'] = detail_page(owner='OtherUser')
        self.assertIsNone(self.refresh()['submissions'][0]['submittedAt'])
        self.assertEqual(len(self.detail_gets), 1)
        self.fixture.detail_overrides['3331061'] = detail_page()
        self.restart(); self.detail_gets.clear()
        self.assertIsNone(self.refresh()['submissions'][0]['submittedAt'])
        self.assertEqual(self.detail_gets, [])
        self.clock += 60000
        self.assertEqual(self.refresh()['submissions'][0]['submittedAt'], SUBMITTED_AT)
        self.assertEqual(len(self.detail_gets), 1)

    def test_network_failure_negative_window_persists_without_adding_source_posts(self):
        def unavailable(request):
            if urlsplit(request['logicalUrl']).path.startswith('/submission/'):
                self.detail_gets.append('/submission/3331061')
                return {'error': {'code': 'SYNTHETIC_READ_FAILURE'}}
            return self.exchange(request)
        result = self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, unavailable)
        row = result['submissions'][0]
        self.assertIsNone(row['submittedAt'])
        self.assertEqual(row['timeProbeStatus'], 'unavailable')
        self.assertEqual(row['timeProbeAfter'], self.clock + 60000)
        self.restart(); self.detail_gets.clear(); self.refresh()
        self.assertEqual(self.detail_gets, [])
        self.assertEqual(self.fixture.posts, [])

    def test_prepared_session_does_not_backfill_provider_timestamps(self):
        prepared = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks'})
        result = self.app.dispatch('qoj_submissions', {'sessionId': prepared['sessionId']}, self.exchange)
        self.assertIsNone(result['submissions'][0]['submittedAt'])
        self.assertEqual(self.detail_gets, [])

    def test_one_detail_response_is_reused_for_current_zero_score_but_not_old_verdict(self):
        self.fixture.history_html = relative_history(score='0', result='0')
        self.fixture.detail_overrides['3331061'] = detail_page(verdict='Wrong Answer')
        row = self.refresh()['submissions'][0]
        self.assertEqual((row['verdict'], row['submittedAt']), ('WRONG-ANSWER', SUBMITTED_AT))
        self.assertEqual(len(self.detail_gets), 1)
        # A different historical SID with a verified date outside this local
        # window gets timestamp metadata only, without old verdict refinement.
        self.fixture.history_html = relative_history('1511772', score='0', result='0')
        self.fixture.detail_overrides['1511772'] = detail_page(sid='1511772', date='2025-10-14T21:37:53+08:00', verdict='Wrong Answer')
        old = next(r for r in self.refresh()['submissions'] if r['id'] == '1511772')
        self.assertIsNotNone(old['submittedAt'])
        self.assertEqual(old['verdict'], 'UNKNOWN')
        self.assertFalse(old['inSession'])

    def test_budget_three_metadata_probes_prioritizes_known_current_submission(self):
        self.fixture.history_html = actual_schema_history(cid='3387', score='0', result='0').replace('3331061', '9999999') + ''.join(
            relative_history(str(3331061 + i)) for i in range(6))
        self.fixture.detail_overrides = {'9999999': detail_page(sid='9999999', verdict='Wrong Answer')}
        self.refresh()
        self.assertEqual(self.detail_gets, ['/submission/9999999', '/submission/3331066', '/submission/3331065', '/submission/3331064'])
        # A background-only minute poll must reach untried IDs even when
        # failures at the newest IDs have just become eligible to retry.
        self.clock += 60000
        self.detail_gets.clear(); self.restart(); self.refresh()
        self.assertEqual(self.detail_gets, ['/submission/9999999', '/submission/3331063', '/submission/3331062', '/submission/3331061'])

    def test_unknown_operation_requires_explicit_reconcile_after_metadata_time_is_verified(self):
        record = {'id': None, 'operationId': 'preexisting-unknown-receipt', 'sessionId': self.session['sessionId'],
            'account': 'LittleDrinks', 'problemId': '5115', 'problemLabel': 'C', 'language': 'C++20', 'filename': 'C.cpp',
            'submittedAt': SUBMITTED_AT - 10000, 'timeSource': 'local-intent', 'verdict': 'UNKNOWN',
            'rawVerdict': 'Synthetic preexisting unknown intent', 'pending': False, 'url': None}
        self.app.ledger.begin_operation(record, 'synthetic-preexisting-only')
        self.app.ledger.save_operation(record, 'unknown')
        self.refresh()
        self.assertEqual(self.app.ledger.operation(record['operationId'])['state'], 'unknown')
        result = self.app.dispatch('qoj_reconcile', {'sessionId': self.session['sessionId'],
            'operationId': record['operationId'], 'submissionId': '3331061'}, self.exchange)
        self.assertEqual((result['state'], result['submission']['id']), ('confirmed', '3331061'))
        self.assertEqual(len(self.detail_gets), 1)
        self.assertEqual(self.fixture.posts, [])

    def test_explicit_reconcile_prioritizes_its_selected_sid_within_metadata_budget(self):
        self.fixture.history_html = ''.join(relative_history(str(3331061 + i)) for i in range(6))
        record = {'id': None, 'operationId': 'selected-unknown-receipt', 'sessionId': self.session['sessionId'],
            'account': 'LittleDrinks', 'problemId': '5115', 'problemLabel': 'C', 'language': 'C++20', 'filename': 'C.cpp',
            'submittedAt': SUBMITTED_AT - 10000, 'timeSource': 'local-intent', 'verdict': 'UNKNOWN',
            'rawVerdict': 'Synthetic preexisting unknown intent', 'pending': False, 'url': None}
        self.app.ledger.begin_operation(record, 'synthetic-selected-only')
        self.app.ledger.save_operation(record, 'unknown')
        result = self.app.dispatch('qoj_reconcile', {'sessionId': self.session['sessionId'],
            'operationId': record['operationId'], 'submissionId': '3331061'}, self.exchange)
        self.assertEqual(result['submission']['id'], '3331061')
        self.assertEqual(self.detail_gets[0], '/submission/3331061')
        self.assertLessEqual(len(self.detail_gets), 3)
        self.assertEqual(self.fixture.posts, [])


if __name__ == '__main__':
    unittest.main()
