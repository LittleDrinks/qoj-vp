"""Read-only history recovery of an already-sent, unknown local receipt."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from qojvp import Application, ApplicationError
from qojvp.history import submission_source_hashes
from tests.support import QojFixture
from tests.test_application import AT, CODE
from tests.test_detail_metadata import detail_page

ROOT = Path(__file__).resolve().parents[1]


def history_page(*rows):
    body = []
    for values in rows:
        item = {'sid': '1000001', 'owner': 'FixtureUser', 'pid': '15419', 'cid': '3387',
                'language': 'C++20', 'at': AT, 'verdict': 'AC ✓', **values}
        date = datetime.fromtimestamp(item['at'] / 1000, timezone.utc).isoformat() if item['at'] is not None else '00:01:44'
        body.append(f'<tr><td><a href="/submission/{item["sid"]}">#{item["sid"]}</a></td>'
            f'<td><span class="uoj-username">{item["owner"]}</span></td>'
            f'<td><a href="/contest/{item["cid"]}/problem/{item["pid"]}">A</a></td>'
            f'<td>{item["verdict"]}</td><td>{item["language"]}</td>'
            f'<td><time datetime="{date}">{date}</time></td></tr>')
    return ('<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th>'
            '<th>Language</th><th>Time</th></tr></thead><tbody>' + ''.join(body) + '</tbody></table>')


def source_detail(source=CODE, **metadata):
    # Topology verified from the real QOJ 3338719 page, with synthetic code.
    values = {'sid': '1000001', 'owner': 'FixtureUser', 'pid': '15419', 'date': '2026-10-31T09:00:00+08:00', **metadata}
    return detail_page(**values) + ('<div class="card"><div class="card-header">answer</div>'
        '<div class="card-body"><pre><code class="sh_cpp">' + escape(source.decode()) + '</code></pre></div></div>')


class ReceiptReconciliationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='receipt-recovery-')
        self.fixture = QojFixture().__enter__()
        self.fixture.disconnect = True
        self.fixture.history_html = history_page()
        self.clock = AT + 257
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: self.clock)
        self.session = self.app.dispatch('create_session', {
            'contestId': '3387', 'account': 'FixtureUser', 'startAt': AT - 60000})
        self.args = {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt',
            'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20', 'filename': 'A.cpp',
            'contentsBase64': base64.b64encode(CODE).decode()}

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def call(self, method, args=None):
        return self.app.dispatch(method, args or {'sessionId': self.session['sessionId']}, self.fixture.exchange)

    def lost_receipt(self):
        result = self.call('qoj_submit', self.args)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(len(self.fixture.posts), 1)
        self.fixture.disconnect = False
        self.fixture.history_html = history_page({})
        self.fixture.detail_overrides['1000001'] = source_detail()
        return result

    def assert_unknown(self, result):
        self.assertTrue(any(item.get('operationId') == 'lost-receipt' and item.get('id') is None
                            for item in result['submissions']))
        self.assertEqual(self.app.ledger.operation('lost-receipt')['state'], 'unknown')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_unique_same_source_history_replaces_unknown_operation_without_another_post(self):
        self.lost_receipt()
        refreshed = self.call('qoj_submissions')
        row = next(item for item in refreshed['submissions'] if item.get('id') == '1000001')
        self.assertEqual(row.get('operationId'), 'lost-receipt')
        self.assertFalse(any(item.get('operationId') == 'lost-receipt' and item.get('id') is None
                             for item in refreshed['submissions']))
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertEqual(self.call('qoj_submit', self.args)['state'], 'confirmed')
        self.assertEqual(len(self.call('qoj_submissions')['submissions']), 1)
        self.assertEqual(len(self.fixture.posts), 1)

    def test_real_list_redirect_can_recover_immediately_without_reposting_source(self):
        self.fixture.disconnect = False
        self.fixture.receipt = '/contest/3387/submissions'
        self.fixture.history_html = history_page({})
        self.fixture.detail_overrides['1000001'] = source_detail()
        result = self.call('qoj_submit', self.args)
        self.assertEqual((result['state'], result['submission']['id']), ('confirmed', '1000001'))
        self.assertEqual(result['submission']['verdict'], 'CORRECT')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_crlf_upload_matches_complete_html_lf_source_without_trimming(self):
        original = b'// synthetic unicode: \xe6\xa0\xb7\xe4\xbe\x8b\r\nint main() {\r\n  return 0;  \r\n}\r\n'
        self.args['contentsBase64'] = base64.b64encode(original).decode()
        self.lost_receipt()
        self.fixture.detail_overrides['1000001'] = source_detail(original.replace(b'\r\n', b'\n'))
        row = self.call('qoj_submissions')['submissions'][0]
        self.assertEqual((row['id'], row['operationId']), ('1000001', 'lost-receipt'))
        self.assertEqual(self.app.ledger.operation('lost-receipt')['sourceSha256'], hashlib.sha256(original).hexdigest())

    def test_different_source_at_same_time_is_not_merged_even_when_selected_manually(self):
        self.lost_receipt()
        self.fixture.detail_overrides['1000001'] = source_detail(b'int main() { return 1; }\n')
        self.assert_unknown(self.call('qoj_submissions'))
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_reconcile', {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt', 'submissionId': '1000001'})
        self.assertEqual(caught.exception.code, 'RECEIPT_SOURCE_MISMATCH')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_missing_final_newline_or_changed_space_never_matches_by_trimming(self):
        self.lost_receipt()
        for source in (CODE.rstrip(b'\n'), CODE.replace(b'return 0', b'return  0')):
            with self.subTest(source_digest=hashlib.sha256(source).hexdigest()):
                self.fixture.detail_overrides['1000001'] = source_detail(source)
                self.clock += 60001
                self.assert_unknown(self.call('qoj_submissions'))

    def test_multiple_same_source_candidates_require_explicit_unique_binding(self):
        self.lost_receipt()
        self.fixture.history_html = history_page({}, {'sid': '1000002'})
        self.fixture.detail_overrides['1000002'] = source_detail(sid='1000002')
        self.assert_unknown(self.call('qoj_submissions'))
        selected = self.call('qoj_reconcile', {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt', 'submissionId': '1000002'})
        self.assertEqual(selected['submission']['id'], '1000002')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_earlier_submission_and_unverified_source_metadata_remain_unknown(self):
        self.lost_receipt()
        self.fixture.history_html = history_page({'at': AT - 1000})
        self.assert_unknown(self.call('qoj_submissions'))
        self.fixture.history_html = history_page({})
        for metadata in ({'owner': 'OtherUser'}, {'pid': '15420'}, {'cid': '3388'}, {'sid': '1000002'},
                         {'date': '2026-10-31T09:00:01+08:00'}):
            with self.subTest(metadata=metadata):
                self.fixture.detail_overrides['1000001'] = source_detail(**metadata)
                self.clock += 60001
                self.assert_unknown(self.call('qoj_submissions'))

    def test_source_probe_failures_are_bounded_and_recovery_after_restart_is_read_only(self):
        self.lost_receipt()
        self.fixture.detail_overrides['1000001'] = '<p>Source is unavailable</p>'
        detail_gets = []
        def exchange(request):
            if urlsplit(request['logicalUrl']).path.startswith('/submission/'):
                detail_gets.append(request['method'])
            return self.fixture.exchange(request)
        self.assert_unknown(self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, exchange))
        self.app.close()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: self.clock)
        self.fixture.detail_overrides['1000001'] = source_detail()
        self.assert_unknown(self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, exchange))
        self.assertEqual(detail_gets, ['GET'])
        self.clock += 60001
        row = self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, exchange)['submissions'][0]
        self.assertEqual(row['operationId'], 'lost-receipt')
        self.assertEqual(detail_gets, ['GET', 'GET'])
        self.assertEqual(len(self.fixture.posts), 1)

    def test_rejudged_result_is_retained_when_receipt_is_recovered(self):
        self.lost_receipt()
        self.fixture.history_html = history_page({'verdict': 'AC, TL'})
        row = self.call('qoj_submissions')['submissions'][0]
        self.assertEqual((row['operationId'], row['verdict']), ('lost-receipt', 'TIMELIMIT'))
        self.fixture.history_html = history_page({'verdict': 'AC ✓'})
        row = self.call('qoj_submissions')['submissions'][0]
        self.assertEqual((row['operationId'], row['verdict']), ('lost-receipt', 'CORRECT'))
        self.assertNotIn(CODE.decode(), self.app.ledger.path.read_bytes().decode('utf-8', errors='ignore'))
        self.assertNotIn('sourceSha256', json.dumps(self.call('qoj_submissions')))

    def test_another_unknown_operation_blocks_automatic_binding_and_one_sid_cannot_be_claimed_twice(self):
        self.lost_receipt()
        other = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser', 'startAt': AT - 60000})
        self.fixture.history_html = history_page()
        self.fixture.disconnect = True
        result = self.call('qoj_submit', {**self.args, 'sessionId': other['sessionId'], 'operationId': 'other-lost-receipt'})
        self.assertEqual(result['state'], 'unknown')
        self.fixture.disconnect = False
        self.fixture.history_html = history_page({})
        self.call('qoj_submissions')
        self.assertEqual(self.app.ledger.operation('lost-receipt')['state'], 'unknown')
        self.assertEqual(self.app.ledger.operation('other-lost-receipt')['state'], 'unknown')
        selected = self.call('qoj_reconcile', {'sessionId': self.session['sessionId'], 'operationId': 'lost-receipt', 'submissionId': '1000001'})
        self.assertEqual(selected['state'], 'confirmed')
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_reconcile', {'sessionId': other['sessionId'], 'operationId': 'other-lost-receipt', 'submissionId': '1000001'})
        self.assertEqual(caught.exception.code, 'VALIDATION_ERROR')
        self.assertEqual(self.app.ledger.operation('other-lost-receipt')['state'], 'unknown')
        self.assertEqual(len(self.fixture.posts), 2)

    def test_two_helpers_refreshing_one_operation_produce_one_confirmed_receipt(self):
        self.lost_receipt()
        def refresh(_):
            with Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: self.clock) as app:
                return app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, self.fixture.exchange)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(refresh, (1, 2)))
        self.assertTrue(any(any(row.get('operationId') == 'lost-receipt' and row.get('id') == '1000001'
                                for row in result['submissions']) for result in results))
        final = self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId'], 'refresh': False})
        self.assertEqual(len(final['submissions']), 1)
        self.assertEqual(final['submissions'][0]['operationId'], 'lost-receipt')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_partial_or_malformed_history_cannot_establish_a_unique_automatic_candidate(self):
        self.lost_receipt()
        self.fixture.history_html = history_page({}) + '<a href="?page=2">2</a>'
        def incomplete(request):
            parsed = urlsplit(request['logicalUrl'])
            if parsed.path.endswith('/submissions') and parse_qs(parsed.query).get('page') == ['2']:
                return {'error': {'code': 'SYNTHETIC_PAGE_UNAVAILABLE'}}
            return self.fixture.exchange(request)
        result = self.app.dispatch('qoj_submissions', {'sessionId': self.session['sessionId']}, incomplete)
        self.assert_unknown(result)
        self.assertFalse(result['coverage']['complete'])
        self.fixture.history_html = history_page({}, {'sid': '1000002'}).replace(
            '<td><span class="uoj-username">FixtureUser</span></td>', '<td>Unverified owner</td>', 1)
        result = self.call('qoj_submissions')
        self.assert_unknown(result)
        self.assertFalse(result['coverage']['complete'])

    def test_missing_metadata_on_another_potential_candidate_does_not_get_ignored(self):
        self.lost_receipt()
        self.fixture.history_html = history_page({}, {'sid': '1000002', 'language': ''})
        self.assert_unknown(self.call('qoj_submissions'))
        self.fixture.history_html = history_page({}, {'sid': '1000002', 'at': None})
        self.fixture.detail_overrides['1000002'] = '<p>Metadata unavailable</p>'
        self.clock += 60001
        self.assert_unknown(self.call('qoj_submissions'))


class ReceiptSourceParserTests(unittest.TestCase):
    def parse(self, html):
        return submission_source_hashes(html, '3387', 'FixtureUser', '1000001', '15419', 'C++20')

    def test_only_answer_source_card_is_hashed_not_testcase_output(self):
        html = source_detail() + ('<div class="card"><div class="card-header">Details</div>'
            '<div class="card-body"><pre>unrelated judge output</pre></div></div>')
        evidence = self.parse(html)
        self.assertEqual(evidence['variants']['lf']['sha256'], hashlib.sha256(CODE).hexdigest())
        self.assertNotIn(CODE.decode(), json.dumps(evidence))

    def test_missing_duplicate_or_mislabeled_source_and_wrong_language_are_rejected(self):
        for html in (source_detail().replace('>answer<', '>Details<'), source_detail() + source_detail(),
                     source_detail().replace('sh_cpp', 'unrecognized'), source_detail().replace('<td>C++20</td>', '<td>Python3</td>')):
            with self.subTest(markup_digest=hashlib.sha256(html.encode()).hexdigest()):
                self.assertIsNone(self.parse(html))


if __name__ == '__main__':
    unittest.main()
