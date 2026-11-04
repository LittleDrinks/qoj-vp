from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from pathlib import Path
import re
import tempfile
import unittest

from qojvp import Application, ApplicationError
from qojvp.history import detail_verdict, parse_history, verdict
from tests.unit.support import QojFixture


ROOT = Path(__file__).resolve().parents[2]
SUBMITTED_AT = int(datetime.fromisoformat('2026-11-01T02:20:57+08:00').timestamp() * 1000)


def actual_schema_history(*, cid='1051', owner='LittleDrinks', score='100.000000', result='AC ✓',
                          time='2026-11-01T02:20:57+08:00', outside_owner=''):
    """Minimal raw-GET structure from safe-provider-probe.json; no source/token."""
    return ('<table><thead><tr><th>ID</th><th>Problem</th><th>Submitter</th><th>Result</th>'
            '<th>Language</th><th>File size</th><th>Submit time</th></tr></thead><tbody><tr>'
            '<td><a href="/submission/3331061">#3331061</a>' + outside_owner + '</td>'
            '<td><a href="/contest/' + cid + '/problem/5115">C. Clone Ranran</a></td>'
            '<td><span class="uoj-username">' + escape(owner) + '</span></td>'
            '<td><a href="/submission/3331061" class="uoj-score" data-score="' + escape(score) + '">'
            + escape(result) + '</a></td><td>C++20</td><td>537b</td><td><small>'
            '<time class="uoj-time" datetime="' + escape(time) + '">2026-11-01 02:20:57</time>'
            '</small></td></tr></tbody></table>')


def native_vp_schema_history(*, cid='1051'):
    html = actual_schema_history(cid=cid, score='0.000000', result='0').replace('3331061', '1511772')
    html = html.replace('<span class="uoj-username">LittleDrinks</span>',
                        '<span class="uoj-username">LittleDrinks</span><sup><a href="/contest/' + cid + '">#</a></sup>')
    return re.sub(r'<time[^>]*>[^<]*</time>', '04:13:36', html)


def mixed_schema_history(*, sid='1511578', current='TL', cid='1051', absolute=False):
    """Two-span, no-score result observed in both reported QOJ submissions.

    Structure is from artifacts/resource-split/dual-verdict.json. The optional
    absolute time is synthetic so an isolated integration test can queue it.
    """
    html = actual_schema_history(cid=cid).replace('5115', '5114').replace('C. Clone Ranran', 'B. Cells Coloring')
    html = re.sub(r'<td><a href="/submission/3331061" class="uoj-score"[^>]*>[^<]*</a></td>',
                  '<td><a href="/submission/3331061"><span>AC</span><span>, '
                  + escape(current) + '</span></a></td>', html)
    html = html.replace('3331061', sid)
    if not absolute:
        html = re.sub(r'<time[^>]*>[^<]*</time>', '03:42:08' if sid == '1511578' else '03:40:13', html)
    return html


def extra_test_details(result='Time Limit Exceeded'):
    """Minimized actual Details header: earlier AC then the extra-test failure.

    The real pages contain 22 Accepted test results before this same final
    Extra Test row. Test data, source code and tokens are not included.
    """
    return ('<div class="card border-info mb-3"><div class="card-header bg-info">'
            '<h4 class="card-title">Details</h4></div><div class="card-body">'
            '<div id="details_details_accordion"><div class="card card-uoj-accepted mb-3">'
            '<div class="card-header"><div class="row"><div class="col-sm-2">Accepted</div>'
            '</div></div></div><div class="card"><div class="card-header" data-toggle="collapse" '
            'data-target="#details_details_accordion_collapse_test_-1_Test"><div class="row">'
            '<div class="col-sm-2"><h4 class="card-title">Extra Test:</h4></div>'
            '<div class="col-sm-2">score: -3</div><div class="col-sm-2">Extra Test Failed : '
            + escape(result) + ' on 4</div><div class="col-sm-3"></div><div class="col-sm-3"></div>'
            '</div></div></div></div></div></div>')


class RealHistorySchemaTests(unittest.TestCase):
    def parse(self, html):
        return parse_history(html, '1051', 'LittleDrinks', {'C': {'id': '5115'}})

    def test_raw_username_span_score_attribute_and_explicit_time_import(self):
        result = self.parse(actual_schema_history())
        self.assertEqual(result['malformedRows'], 0)
        self.assertEqual(result['warnings'], [])
        row = result['submissions'][0]
        self.assertEqual((row['account'], row['id'], row['problemId'], row['language']),
                         ('LittleDrinks', '3331061', '5115', 'C++20'))
        self.assertEqual((row['verdict'], row['score'], row['submittedAt']), ('CORRECT', 100, SUBMITTED_AT))
        self.assertFalse(row['pending'])
        self.assertEqual(row['rawVerdict'], 'AC ✓')

    def test_other_owner_cannot_be_overridden_by_current_profile_in_another_column(self):
        html = actual_schema_history(owner='OtherUser', outside_owner='<a href="/user/profile/LittleDrinks">My Profile</a>')
        self.assertEqual(self.parse(html)['submissions'], [])
        self.assertEqual(self.parse(actual_schema_history(owner='LittleDrinks#', time='02:20:57'))['submissions'], [])
        html = actual_schema_history(owner='OtherUser').replace(
            '<span class="uoj-username">OtherUser</span>',
            '<a href="/user/profile/OtherUser">OtherUser</a>')
        self.assertEqual(self.parse(html)['submissions'], [])

    def test_ambiguous_owner_is_not_imported(self):
        html = actual_schema_history().replace('</span></td>', '</span><a href="/user/profile/OtherUser">OtherUser</a></td>')
        result = self.parse(html)
        self.assertEqual(result['submissions'], [])
        self.assertEqual(result['malformedRows'], 1)

    def test_zero_partial_or_ambiguous_verdict_cannot_become_ac(self):
        for score in ('0.000000', '42.500000'):
            with self.subTest(score=score):
                row = self.parse(actual_schema_history(score=score))['submissions'][0]
                self.assertEqual(row['score'], float(score))
                self.assertNotEqual(row['verdict'], 'CORRECT')
        for text in ('AC, TL', 'AC / WA', 'AC WRONG ANSWER'):
            with self.subTest(text=text):
                self.assertNotEqual(verdict(text), 'CORRECT')
                self.assertNotEqual(verdict(text, 100), 'CORRECT')
        self.assertEqual(verdict('AC ✓'), 'CORRECT')
        self.assertNotEqual(verdict('AC ✓', 0), 'CORRECT')

    def test_current_result_after_contest_ac_controls_mixed_verdict(self):
        for raw, expected in (('AC, TL', 'TIMELIMIT'), ('AC, WA', 'WRONG-ANSWER'),
                              ('AC, Pending', 'JUDGING'), ('AC, Judging', 'JUDGING')):
            with self.subTest(raw=raw):
                self.assertEqual(verdict(raw), expected)
                self.assertEqual(verdict(raw, 0), expected)

    def test_unrecognized_mixed_result_does_not_reuse_contest_ac(self):
        for raw in ('AC, unknown', 'AC,', 'AC / WA', 'AC WRONG ANSWER',
                    'unknown, AC', 'AC, WA, AC'):
            with self.subTest(raw=raw):
                self.assertEqual(verdict(raw, 100), 'UNKNOWN')

    def test_pending_current_result_is_pending_without_a_live_polling_script(self):
        row = self.parse(actual_schema_history(result='AC, Pending'))['submissions'][0]
        self.assertEqual(row['verdict'], 'JUDGING')
        self.assertTrue(row['pending'])
        self.assertEqual(row['rawVerdict'], 'AC, Pending')

    def test_observed_two_span_results_have_no_numeric_score_and_keep_original_text(self):
        for sid in ('1511578', '1511566'):
            for current, expected in (('TL', 'TIMELIMIT'), ('WA', 'WRONG-ANSWER'), ('Pending', 'JUDGING')):
                with self.subTest(sid=sid, current=current):
                    row = parse_history(mixed_schema_history(sid=sid, current=current), '1051',
                                        'LittleDrinks', {'B': {'id': '5114'}})['submissions'][0]
                    self.assertEqual((row['id'], row['verdict']), (sid, expected))
                    self.assertEqual(row['rawVerdict'], 'AC , ' + current)
                    self.assertIsNone(row['score'])
                    self.assertEqual(row['pending'], current == 'Pending')
                    self.assertEqual(row['verdictSource'], 'history-result')
                    self.assertEqual(row['historyResult']['rawVerdict'], row['rawVerdict'])
                    self.assertIsNone(row['submittedAt'], 'A historical relative clock is not a current VP time')

    def test_extra_test_failure_overrides_prior_accepted_results_and_old_full_score(self):
        for current, expected in (('Time Limit Exceeded', 'TIMELIMIT'), ('Wrong Answer', 'WRONG-ANSWER')):
            for score in (None, 0, 100):
                with self.subTest(current=current, score=score):
                    parsed = detail_verdict(extra_test_details(current), score)
                    self.assertEqual(parsed['verdict'], expected)
                    self.assertEqual(parsed['rawVerdict'], 'Extra Test Failed : ' + current + ' on 4')
                    self.assertFalse(parsed['pending'])
                    self.assertEqual(parsed['verdictSource'], 'submission-detail')

    def test_unrecognized_extra_failure_never_reuses_an_earlier_ac(self):
        for result in ('Unrecognized Failure', 'Accepted', 'Pending'):
            with self.subTest(result=result):
                parsed = detail_verdict(extra_test_details(result), 100)
                self.assertEqual(parsed['verdict'], 'UNKNOWN')
                self.assertIn('Extra Test Failed', parsed['rawVerdict'])

    def test_no_zone_or_native_vp_relative_clock_remains_unverified(self):
        for raw in ('2026-11-01T02:20:57', '02:20:57'):
            with self.subTest(raw=raw):
                html = actual_schema_history(time=raw) + '<footer>Server Time: 2026-11-01 02:30:00 (UTC+8)</footer>'
                row = self.parse(html)['submissions'][0]
                self.assertIsNone(row['submittedAt'])
                self.assertEqual(row['timeSource'], 'unverified-display')

    def test_actual_native_vp_sup_marker_does_not_fabricate_an_absolute_clock(self):
        row = self.parse(native_vp_schema_history())['submissions'][0]
        self.assertEqual((row['account'], row['id'], row['score']), ('LittleDrinks', '1511772', 0))
        self.assertEqual(row['rawTime'], '04:13:36')
        self.assertIsNone(row['submittedAt'])
        self.assertEqual(row['timeSource'], 'unverified-display')


class HistoryApplicationIntegrationTests(unittest.TestCase):
    def test_mixed_rejudge_updates_one_fact_and_requires_review_of_delivered_ac(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='history-mixed-rejudge-') as state, QojFixture() as fixture:
            fixture.account = 'LittleDrinks'
            fixture.contest_html = ('<title>Synthetic rejudge fixture</title><table><tr><td>C</td><td>'
                '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
            sid = '1000099'
            fixture.history_html = actual_schema_history(cid='3387').replace('3331061', sid)
            # Training mode or an unavailable detail card must not erase an
            # explicit current result already observed in the history row.
            fixture.detail_overrides[sid] = '<html><body>Details unavailable</body></html>'
            with Application(state, fixture_origin=fixture.origin, clock=lambda: SUBMITTED_AT) as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks',
                    'startAt': SUBMITTED_AT - 60000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-rejudge'})
                args = {'sessionId': session['sessionId']}
                app.dispatch('qoj_submissions', args, fixture.exchange)
                original = app.dispatch('rankland_queue', args)['items'][0]
                receipt = {'problemIndex': 0, 'timeMs': 60000, 'result': 'AC'}
                app.dispatch('rankland_ack', {**args, 'queueId': original['queueId'],
                    'revision': original['revision'], 'state': 'synced', 'receipt': receipt})
                cases = []
                for current, expected in (('TL', 'TIMELIMIT'), ('WA', 'WRONG-ANSWER'), ('Pending', 'JUDGING')):
                    numeric = actual_schema_history(cid='3387', score='0', result='AC, ' + current).replace('3331061', sid)
                    no_score = mixed_schema_history(sid=sid, cid='3387', current=current, absolute=True).replace('5114', '5115')
                    cases.extend((('AC, ' + current, expected, numeric), ('AC , ' + current, expected, no_score)))
                for raw, expected, html in cases:
                    fixture.history_html = html
                    with self.subTest(raw=raw):
                        refreshed = app.dispatch('qoj_submissions', args, fixture.exchange)
                        self.assertEqual(len(refreshed['submissions']), 1)
                        row = refreshed['submissions'][0]
                        self.assertEqual((row['id'], row['verdict']), (sid, expected))
                        self.assertEqual(row['pending'], expected == 'JUDGING')
                        self.assertEqual(row['historyResult']['rawVerdict'], raw)
                        queue = app.dispatch('rankland_queue', args)['items']
                        self.assertEqual(len(queue), 1)
                        self.assertEqual(queue[0]['queueId'], original['queueId'])
                        self.assertEqual((queue[0]['verdict'], queue[0]['state']), (expected, 'needs-review'))
                        self.assertEqual(queue[0]['receipt'], receipt)
                        self.assertTrue(queue[0]['rejudge'])
                        revision = queue[0]['revision']
                        app.dispatch('qoj_submissions', args, fixture.exchange)
                        repeated = app.dispatch('rankland_queue', args)['items'][0]
                        self.assertEqual((repeated['queueId'], repeated['revision']), (original['queueId'], revision))
                        self.assertFalse(app.dispatch('rankland_ack', {**args, 'queueId': original['queueId'],
                            'revision': original['revision'], 'state': 'synced'})['accepted'])
                self.assertEqual(fixture.posts, [])

    def test_only_current_window_zero_scores_fetch_details_and_other_accounts_never_queue(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='history-window-') as state, QojFixture() as fixture:
            fixture.account = 'LittleDrinks'
            fixture.contest_html = ('<title>Synthetic practice fixture</title><table><tr><td>C</td><td>'
                '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
            current = actual_schema_history(cid='3387', score='0.000000', result='0')
            old = ''.join(native_vp_schema_history(cid='3387').replace('1511772', str(1511772 + i)) for i in range(13))
            other = actual_schema_history(cid='3387', owner='OtherUser', score='0', result='0').replace('3331061', '3331062')
            outside = actual_schema_history(cid='3387', time='2026-10-31T02:20:57+08:00', score='0', result='0').replace('3331061', '3331063')
            fixture.history_html = current + old + other + outside
            fixture.detail_overrides['3331061'] = '<div class="card"><div class="card-header">Details</div><div class="col-sm-2">Wrong Answer</div></div>'
            requests = []
            def exchange(message):
                requests.append(message['logicalUrl'])
                return fixture.exchange(message)
            with Application(state, fixture_origin=fixture.origin, clock=lambda: SUBMITTED_AT) as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks',
                    'startAt': SUBMITTED_AT - 60000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-history'})
                probed_old_ids = set()
                for _ in range(2):
                    requests.clear()
                    result = app.dispatch('qoj_submissions', {'sessionId': session['sessionId']}, exchange)
                    details = [url for url in requests if '/submission/' in url]
                    self.assertEqual(details[0], 'https://qoj.ac/submission/3331061?locale=en')
                    # Unknown absolute clocks now get at most three metadata
                    # probes after current verdicts. They are not old-verdict
                    # refinement, and negative probes do not repeat next poll.
                    self.assertEqual(len(details), 4)
                    old_ids = set(details[1:])
                    self.assertEqual(len(old_ids), 3)
                    self.assertTrue(old_ids.isdisjoint(probed_old_ids))
                    self.assertTrue(all('/submission/15117' in url for url in old_ids))
                    probed_old_ids.update(old_ids)
                    rows = {row['id']: row for row in result['submissions']}
                    self.assertEqual(rows['3331061']['verdict'], 'WRONG-ANSWER')
                    self.assertEqual(rows['1511772']['verdict'], 'UNKNOWN')
                    self.assertIsNone(rows['1511772']['submittedAt'])
                    self.assertNotIn('3331062', rows)
                    queue = app.dispatch('rankland_queue', {'sessionId': session['sessionId']})['items']
                    self.assertEqual({row['submissionId'] for row in queue}, {'3331061'})
                self.assertEqual(fixture.posts, [])

    def test_raw_get_import_and_explicit_reconcile_use_existing_receipt_without_repost(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='history-real-schema-') as state, QojFixture() as fixture:
            fixture.account = 'LittleDrinks'
            fixture.contest_html = ('<title>Synthetic practice fixture</title><table><tr><td>C</td><td>'
                '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
            fixture.problem_html['5115'] = ('<form id="form-answer"><input name="_token" value="fixture-only">'
                '<select name="answer_answer_language"><option value="C++20">C++20</option></select></form>')
            fixture.history_html = actual_schema_history(cid='3387')
            with Application(state, fixture_origin=fixture.origin, clock=lambda: SUBMITTED_AT - 10000) as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks',
                    'startAt': SUBMITTED_AT - 60000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-history'})
                args = {'sessionId': session['sessionId'], 'operationId': 'synthetic-lost-receipt',
                        'problemId': '5115', 'problemLabel': 'C', 'language': 'C++20', 'filename': 'C.cpp',
                        'contentsBase64': base64.b64encode(b'int main() { return 0; }\n').decode()}
                fixture.disconnect = True
                unknown = app.dispatch('qoj_submit', args, fixture.exchange)
                self.assertEqual(unknown['state'], 'unknown')
                self.assertEqual(len(fixture.posts), 1, 'Only the loopback synthetic POST may have occurred')
                fixture.disconnect = False
                imported = app.dispatch('qoj_submissions', {'sessionId': session['sessionId']}, fixture.exchange)
                row = next(row for row in imported['submissions'] if row['id'] == '3331061')
                self.assertEqual((row['verdict'], row['submittedAt']), ('CORRECT', SUBMITTED_AT))
                self.assertEqual(app.ledger.operation(args['operationId'])['state'], 'unknown')
                from tests.unit.test_detail_metadata import detail_page
                fixture.detail_overrides['3331061'] = detail_page() + (
                    '<div class="card"><div class="card-header">answer</div><div class="card-body">'
                    '<pre><code class="sh_cpp">int main() { return 0; }\n</code></pre></div></div>')
                reconciled = app.dispatch('qoj_reconcile', {'sessionId': session['sessionId'],
                    'operationId': args['operationId'], 'submissionId': '3331061'}, fixture.exchange)
                self.assertEqual((reconciled['state'], reconciled['submission']['id']), ('confirmed', '3331061'))
                self.assertEqual(reconciled['submission']['operationId'], args['operationId'])
                # An explicitly reconciled receipt remains eligible for
                # details if a later list rendering exposes only a clock.
                fixture.history_html = actual_schema_history(cid='3387', score='0', result='0', time='02:20:57')
                fixture.detail_overrides['3331061'] = '<div class="card"><div class="card-header">Details</div><div class="col-sm-2">Wrong Answer</div></div>'
                linked = app.dispatch('qoj_submissions', {'sessionId': session['sessionId']}, fixture.exchange)
                fact = next(row for row in linked['submissions'] if row.get('id') == '3331061')
                self.assertEqual(fact['verdict'], 'WRONG-ANSWER')
                self.assertEqual(fact['operationId'], args['operationId'])
                self.assertEqual(len(fixture.posts), 1, 'History refresh and reconciliation must never POST again')

    def test_unverified_absolute_or_relative_time_is_never_queued_to_rankland(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='history-unverified-time-') as state, QojFixture() as fixture:
            fixture.account = 'LittleDrinks'
            fixture.contest_html = ('<title>Synthetic practice fixture</title><table><tr><td>C</td><td>'
                '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
            with Application(state, fixture_origin=fixture.origin, clock=lambda: SUBMITTED_AT) as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks',
                    'startAt': SUBMITTED_AT - 60000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=synthetic-history'})
                for time in ('02:20:57', '2026-11-01T02:20:57'):
                    fixture.history_html = actual_schema_history(cid='3387', time=time)
                    result = app.dispatch('qoj_submissions', {'sessionId': session['sessionId']}, fixture.exchange)
                    self.assertIsNone(result['submissions'][0]['submittedAt'])
                    self.assertEqual(app.dispatch('rankland_queue', {'sessionId': session['sessionId']})['items'], [])
                fixture.history_html = native_vp_schema_history(cid='3387')
                result = app.dispatch('qoj_submissions', {'sessionId': session['sessionId']}, fixture.exchange)
                old = next(row for row in result['submissions'] if row['id'] == '1511772')
                self.assertEqual(old['account'], 'LittleDrinks')
                self.assertIsNone(old['submittedAt'])
                self.assertFalse(old['inSession'])
                self.assertEqual(app.dispatch('rankland_queue', {'sessionId': session['sessionId']})['items'], [])
                self.assertEqual(fixture.posts, [])


if __name__ == '__main__':
    unittest.main()
