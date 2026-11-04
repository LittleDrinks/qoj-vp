from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from qojvp import Application, ApplicationError
from qojvp.history import detail_verdict, parse_history
from qojvp.native_host import read_frame, write_frame
from tests.support import FIXTURES, QojFixture, account_menu

ROOT = Path(__file__).resolve().parents[1]
AT = int(datetime.fromisoformat('2026-10-31T09:00:00+08:00').timestamp() * 1000)
CODE = b'int main() { return 0; }\n'


def inline_sample_statement(input_text='1 2', output_text='3'):
    # Actual QOJ 1051/C ancestry and heading types, using synthetic sample data.
    from html import escape
    return ('<div class="tab-pane active"><article class="uoj-article top-buffer-md">'
            '<h2>描述</h2><pre>unlabelled implementation example, not sample data</pre>'
            '<h2>样例</h2><h4>输入 1</h4><pre>' + escape(input_text) + '</pre>'
            '<h4>输出 1</h4><pre>' + escape(output_text) + '</pre>'
            '<h2>提示</h2><pre>not a sample either</pre></article></div>')


class ApplicationIntegrationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='backend-')
        self.fixture = QojFixture().__enter__()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT)
        self.session = self.app.dispatch('create_session', {
            'contestId': '3387', 'account': 'FixtureUser', 'startAt': AT - 10 * 60000,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=icpc2025nanjing&run=default&from=120&rule=ICPC'})

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def args(self, operation_id='test-operation'):
        return {'sessionId': self.session['sessionId'], 'operationId': operation_id,
                'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20', 'filename': 'A.cpp',
                'contentsBase64': base64.b64encode(CODE).decode()}

    def call(self, method, args):
        return self.app.dispatch(method, args, self.fixture.exchange)

    def test_real_upstream_submit_history_and_samples_cross_same_public_seam(self):
        contest = self.call('qoj_contest', {'contestId': '3387'})
        self.assertEqual([p['label'] for p in contest['problems']], ['A', 'B'])
        form = self.call('qoj_problem_form', {'sessionId': self.session['sessionId'], 'problemId': '15419'})
        self.assertEqual(form['languages'], ['C++20', 'Python3'])
        self.assertNotIn('token', json.dumps(form).lower())
        receipt = self.call('qoj_submit', self.args())
        self.assertEqual((receipt['state'], receipt['submission']['id']), ('confirmed', '1000001'))
        self.assertEqual(receipt['submission']['verdict'], 'JUDGING')
        post = self.fixture.posts[0]
        self.assertEqual(post['fields']['answer_answer_language'], 'C++20')
        self.assertEqual(post['fields']['answer_answer_upload_type'], 'file')
        self.assertEqual(post['files']['answer_answer_file']['content'], CODE)
        self.call('qoj_submit', self.args())
        self.assertEqual(len(self.fixture.posts), 1)
        refreshed = self.call('qoj_submissions', {'sessionId': self.session['sessionId']})
        facts = {item['id']: item for item in refreshed['submissions']}
        self.assertEqual(facts['1000001']['verdict'], 'CORRECT')
        self.assertEqual(facts['1000001']['operationId'], 'test-operation')
        self.assertEqual(facts['1000002']['verdict'], 'WRONG-ANSWER')
        self.assertEqual(facts['1000003']['verdict'], 'JUDGING')
        self.assertEqual(refreshed['coverage'], {'complete': True, 'pages': 2})
        download = self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'B'})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(download['zipBase64']))) as archive:
            self.assertIn('samples-B/2.in', archive.namelist())
            self.assertNotIn('samples-B/2.ans', archive.namelist())
            self.assertTrue(any(name.endswith('judge.cpp') for name in archive.namelist()))
        self.assertTrue(download['warnings'])

    def inline_problem(self, html, *, attachment=None):
        self.fixture.contest_html = ('<title>Inline sample fixture</title><table><tr><td>C</td>'
            '<td><a href="/contest/3387/problem/5115">Synthetic inline problem</a></td></tr></table>')
        self.fixture.problem_html['5115'] = html
        self.fixture.attachment_overrides['5115'] = attachment or (404, b'not found', 'text/plain')

    def test_missing_attachment_without_verified_inline_samples_is_unavailable_not_empty_zip(self):
        self.inline_problem('<main><pre>unrelated source code is not a sample</pre></main>')
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'C'})
        self.assertEqual(cm.exception.code, 'SAMPLES_UNAVAILABLE')
        self.assertEqual(self.fixture.posts, [])

    def test_missing_attachment_uses_verified_qoj_inline_samples_and_real_upstream_packaging(self):
        self.inline_problem(inline_sample_statement('1 2\n3 4', '3\n7'))
        result = self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'C'})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['zipBase64']))) as archive:
            self.assertEqual(sorted(archive.namelist()), ['samples-C/1.ans', 'samples-C/1.in'])
            self.assertEqual(archive.read('samples-C/1.in'), b'1 2\n3 4\n')
            self.assertEqual(archive.read('samples-C/1.ans'), b'3\n7\n')
        self.assertEqual(result['sampleSource'], 'inline-statement')
        self.assertEqual(result['extraFiles'], [])
        self.assertEqual(self.fixture.posts, [])

    def test_inline_samples_require_verified_section_scope_and_complete_pairing(self):
        cases = [
            inline_sample_statement().replace('<h2>样例</h2>', '<h2>实现代码</h2>'),
            inline_sample_statement().replace('class="uoj-article top-buffer-md"', 'class="unrelated-article"'),
            inline_sample_statement().replace('<h4>输出 1</h4>', '<h4>输出 2</h4>'),
            inline_sample_statement().replace('class="tab-pane active"', 'class="tab-pane"'),
        ]
        for html in cases:
            with self.subTest(html=html[:60]):
                self.inline_problem(html)
                with self.assertRaises(ApplicationError) as cm:
                    self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'C'})
                self.assertEqual(cm.exception.code, 'SAMPLES_UNAVAILABLE')

    def test_unsafe_attachment_error_is_not_hidden_by_an_inline_fallback(self):
        self.inline_problem(inline_sample_statement(),
            attachment=(200, (FIXTURES / 'attachment-unsafe.zip').read_bytes(), 'application/zip'))
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'C'})
        self.assertEqual(cm.exception.code, 'QOJ_ERROR')

    def test_corrupt_attachment_error_is_not_hidden_by_an_inline_fallback(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as stream:
            stream.writestr('1.in', b'unique-crc-content')
        data = archive.getvalue().replace(b'unique-crc-content', b'broken-crc-content')
        self.inline_problem(inline_sample_statement(), attachment=(200, data, 'application/zip'))
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_samples', {'sessionId': self.session['sessionId'], 'problemLabel': 'C'})
        self.assertEqual(cm.exception.code, 'QOJ_ERROR')

    def test_lost_receipt_does_not_repeat_even_after_restart_or_new_operation_id(self):
        self.fixture.disconnect = True
        result = self.call('qoj_submit', self.args())
        self.assertEqual(result['state'], 'unknown')
        self.app.close()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT)
        self.fixture.disconnect = False
        existing = self.call('qoj_submit', self.args())
        self.assertEqual(existing['state'], 'unknown')
        again = self.call('qoj_submit', {**self.args('different-click'), 'filename': 'renamed.cpp'})
        self.assertEqual(again['submission']['operationId'], 'test-operation')
        self.assertEqual(len(self.fixture.posts), 1)
        history = self.call('qoj_submissions', {'sessionId': self.session['sessionId']})
        unknown = [item for item in history['submissions'] if item.get('state') == 'unknown']
        self.assertEqual(len(unknown), 1)
        from tests.test_detail_metadata import detail_page
        self.fixture.detail_overrides['1000001'] = detail_page(sid='1000001', owner='FixtureUser', pid='15419',
            date='2026-10-31T09:00:00+08:00') + ('<div class="card"><div class="card-header">answer</div>'
            '<div class="card-body"><pre><code class="sh_cpp">' + CODE.decode() + '</code></pre></div></div>')
        resolved = self.call('qoj_reconcile', {'sessionId': self.session['sessionId'],
                                              'operationId': 'test-operation', 'submissionId': '1000001'})
        self.assertEqual(resolved['submission']['id'], '1000001')
        self.assertEqual(self.call('qoj_submit', self.args())['state'], 'confirmed')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_reject_before_post_and_definite_http_rejection_are_distinct(self):
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_submit', {**self.args(), 'language': 'invalid-language'})
        self.assertEqual(cm.exception.code, 'VALIDATION_ERROR')
        self.assertFalse(self.fixture.posts)
        self.fixture.reject = True
        result = self.call('qoj_submit', self.args())
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['error']['code'], 'SUBMISSION_REJECTED')
        self.assertEqual(self.call('qoj_submit', self.args())['state'], 'rejected')
        self.assertEqual(len(self.fixture.posts), 1)

    def test_redirect_to_another_host_stays_unknown(self):
        self.fixture.receipt = 'https://example.com/submission/1000001'
        result = self.call('qoj_submit', self.args())
        self.assertEqual(result['state'], 'unknown')
        self.assertIsNone(result['submission']['id'])

    def test_account_switch_cannot_send_or_import_other_account(self):
        self.fixture.account = 'OtherUser'
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_submit', self.args())
        self.assertEqual(cm.exception.code, 'ACCOUNT_MISMATCH')
        self.assertFalse(self.fixture.posts)

    def test_contest_does_not_expose_upstream_unknown_account_placeholder(self):
        self.fixture.root_html = '<nav><a href="/logout">退出登录</a></nav><main>训练赛</main>'
        contest = self.call('qoj_contest', {'contestId': '3387'})
        self.assertIsNone(contest['account'])
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_submit', self.args())
        self.assertEqual(cm.exception.code, 'ACCOUNT_UNKNOWN')
        self.assertEqual(self.fixture.posts, [])

    def test_another_users_body_profile_cannot_be_taken_as_current_account(self):
        self.fixture.root_html = ('<nav><a href="/logout">退出登录</a></nav>'
                                  '<main><a href="/user/profile/OtherUser">My Profile</a></main>')
        contest = self.call('qoj_contest', {'contestId': '3387'})
        self.assertIsNone(contest['account'])
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_submit', self.args())
        self.assertEqual(cm.exception.code, 'ACCOUNT_UNKNOWN')
        self.assertEqual(self.fixture.posts, [])

    def test_chinese_menu_resolves_own_account_and_ignores_body_and_footer_profiles(self):
        self.fixture.root_html = account_menu('LittleDrinks',
            body='<a href="/user/profile/OtherUser">My Profile</a>')
        contest = self.call('qoj_contest', {'contestId': '3387'})
        self.assertEqual(contest['account'], 'LittleDrinks')
        current = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'LittleDrinks', 'startAt': AT})
        form = self.call('qoj_problem_form', {'sessionId': current['sessionId'], 'problemId': '15419'})
        self.assertTrue(form['csrfPresent'])
        self.assertEqual(self.fixture.posts, [])

    def test_chinese_menu_account_switch_is_rejected_before_send_intent(self):
        self.fixture.root_html = account_menu('OtherUser')
        with self.assertRaises(ApplicationError) as cm:
            self.call('qoj_submit', self.args())
        self.assertEqual(cm.exception.code, 'ACCOUNT_MISMATCH')
        self.assertEqual(self.fixture.posts, [])
        self.assertEqual(self.app.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0], 0)

    def test_atomic_operation_claim_across_two_helpers(self):
        def send(_):
            with Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT) as app:
                return app.dispatch('qoj_submit', self.args(), self.fixture.exchange)
        with ThreadPoolExecutor(2) as executor:
            outcomes = list(executor.map(send, (1, 2)))
        self.assertEqual(len(self.fixture.posts), 1)
        self.assertTrue(any(item['state'] == 'confirmed' for item in outcomes))

    def test_outbox_is_revisioned_and_rejudge_does_not_blindly_append(self):
        self.call('qoj_submissions', {'sessionId': self.session['sessionId']})
        queue = self.app.dispatch('rankland_queue', {'sessionId': self.session['sessionId']})['items']
        self.assertEqual({item['submissionId'] for item in queue}, {'1000001', '1000002'})
        item = next(item for item in queue if item['submissionId'] == '1000001')
        self.app.dispatch('rankland_ack', {'sessionId': self.session['sessionId'], 'queueId': item['queueId'],
                                          'revision': item['revision'], 'state': 'synced',
                                          'receipt': {'problemIndex': 0, 'timeMs': 600000, 'result': 'AC'}})
        self.app.dispatch('update_session', {'sessionId': self.session['sessionId'],
                                              'ranklandUrl': self.session['ranklandUrl']})
        unchanged = next(x for x in self.app.dispatch('rankland_queue', {'sessionId': self.session['sessionId']})['items']
                         if x['submissionId'] == '1000001')
        self.assertEqual(unchanged['state'], 'synced', 'Saving an unchanged URL must not replay delivered facts')
        self.fixture.history_html = (FIXTURES / 'submissions-3387.html').read_text().replace('<td>100</td>', '<td>0</td>')
        self.fixture.detail_overrides['1000001'] = (FIXTURES / 'submission-1000004.html').read_text()
        self.call('qoj_submissions', {'sessionId': self.session['sessionId']})
        changed = next(x for x in self.app.dispatch('rankland_queue', {'sessionId': self.session['sessionId']})['items']
                       if x['submissionId'] == '1000001')
        self.assertEqual((changed['verdict'], changed['state']), ('COMPILER-ERROR', 'needs-review'))
        self.assertEqual(changed['receipt']['result'], 'AC')
        self.assertTrue(changed['rejudge'])
        old_ack = self.app.dispatch('rankland_ack', {'sessionId': self.session['sessionId'], 'queueId': item['queueId'],
                                                    'revision': item['revision'], 'state': 'synced'})
        self.assertFalse(old_ack['accepted'])

    def test_clock_and_rankland_anchor_survive_process_restart(self):
        prepared = self.app.dispatch('create_session', {'contestId': '3387', 'ranklandUrl': 'https://vp.xcpc.link/?contest=X&run=default&from=120'})
        started = self.app.dispatch('start_session', {'sessionId': prepared['sessionId']})
        self.assertEqual(started['startAt'], AT)
        self.assertIn('at=', started['ranklandUrl'])
        self.assertIn('from=0', started['ranklandUrl'])
        self.app.close()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT + 7200000)
        restored = self.app.dispatch('inspect_session', {'sessionId': prepared['sessionId']})
        self.assertEqual(restored['elapsedMs'], 7200000)
        self.assertEqual(restored['ranklandUrl'], started['ranklandUrl'])
        self.assertEqual(self.app.dispatch('start_session', {'sessionId': prepared['sessionId']})['startAt'], AT)

    def test_first_late_rankland_open_preserves_start_across_reopen_and_settings_save(self):
        from urllib.parse import parse_qs, urlsplit
        sid = self.session['sessionId']
        # The board has not been opened while the local VP has run for two hours.
        self.app.clock = lambda: self.session['startAt'] + 7200123
        before = self.app.dispatch('inspect_session', {'sessionId': sid})
        self.assertEqual(parse_qs(urlsplit(before['ranklandUrl']).query)['from'], ['0'])
        prepared = self.app.dispatch('prepare_rankland', {'sessionId': sid})
        offset = float(parse_qs(urlsplit(prepared['ranklandUrl']).query)['from'][0])
        self.assertEqual(offset, 0)
        self.assertTrue(prepared['ranklandPrepared'])
        self.app.clock = lambda: self.session['startAt'] + 10800000
        again = self.app.dispatch('prepare_rankland', {'sessionId': sid})
        self.assertEqual(again['ranklandUrl'], prepared['ranklandUrl'])
        saved = self.app.dispatch('update_session', {'sessionId': sid, 'ranklandUrl': prepared['ranklandUrl']})
        self.assertEqual(saved['ranklandUrl'], prepared['ranklandUrl'])
        # Re-pasting the original base URL with a different query order must
        # not zero the established clock or create a new storage key.
        saved_base = self.app.dispatch('update_session', {'sessionId': sid,
            'ranklandUrl': 'https://vp.xcpc.link/?rule=ICPC&contest=icpc2025nanjing'})
        self.assertEqual(saved_base['ranklandUrl'], prepared['ranklandUrl'])
        self.app.close()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin,
                               clock=lambda: self.session['startAt'] + 14400000)
        restored = self.app.dispatch('prepare_rankland', {'sessionId': sid})
        self.assertEqual(restored['ranklandUrl'], prepared['ranklandUrl'])
        self.assertEqual(restored['ranklandPreparedAt'], prepared['ranklandPreparedAt'])
        changed = self.app.dispatch('update_session', {'sessionId': sid,
            'ranklandUrl': 'https://vp.xcpc.link/?contest=different-contest&rule=ICPC'})
        self.assertFalse(changed['ranklandPrepared'])
        reanchored = self.app.dispatch('prepare_rankland', {'sessionId': sid})
        self.assertEqual(parse_qs(urlsplit(reanchored['ranklandUrl']).query)['from'], ['0'])
        self.assertEqual(parse_qs(urlsplit(reanchored['ranklandUrl']).query)['at'],
                         parse_qs(urlsplit(prepared['ranklandUrl']).query)['at'])

    def test_unstarted_session_cannot_freeze_a_rankland_clock(self):
        session = self.app.dispatch('create_session', {'contestId': '3387',
            'ranklandUrl': 'https://vp.xcpc.link/?contest=icpc2025nanjing'})
        with self.assertRaises(ApplicationError) as cm:
            self.app.dispatch('prepare_rankland', {'sessionId': session['sessionId']})
        self.assertEqual(cm.exception.code, 'SESSION_NOT_RUNNING')

    def test_no_source_or_csrf_is_persisted(self):
        self.call('qoj_submit', self.args())
        self.app.ledger.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        data = self.app.ledger.path.read_bytes()
        self.assertNotIn(CODE, data)
        self.assertNotIn(b'fixture-dummy', data)


class NativeProcessTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='native-')
        self.fixture = QojFixture().__enter__()

    def tearDown(self):
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def process(self):
        env = {**os.environ, 'QOJ_VP_STATE_DIR': self.directory.name,
               'QOJ_VP_QOJ_PATH': str(ROOT / 'vendor/qoj-submitter'), 'QOJ_VP_FIXTURE_ORIGIN': self.fixture.origin}
        return subprocess.Popen([sys.executable, '-m', 'qojvp.native_host'], cwd=ROOT,
                                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run_task(self, method, args):
        process = self.process()
        try:
            write_frame(process.stdin, {'type': 'task', 'id': 'task', 'method': method, 'args': args})
            while True:
                frame = read_frame(process.stdout)
                self.assertIsNotNone(frame)
                if frame['type'] == 'result':
                    process.stdin.close()
                    process.wait(timeout=10)
                    self.assertEqual(process.stdout.read(), b'')
                    return frame
                self.assertEqual(frame['type'], 'http.request')
                write_frame(process.stdin, {'type': 'http.response', 'id': frame['id'],
                                             'requestId': frame['requestId'], **self.fixture.exchange(frame['request'])})
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                stream.close()

    def test_native_stdout_frames_and_task_process_exit(self):
        created = self.run_task('create_session', {'contestId': '3387', 'account': 'FixtureUser', 'startAt': AT})['result']
        result = self.run_task('qoj_samples', {'sessionId': created['sessionId'], 'problemLabel': 'A'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['zipFilename'], 'samples-A.zip')

    def test_killed_helper_after_post_intent_never_resends_after_restart(self):
        created = self.run_task('create_session', {'contestId': '3387', 'account': 'FixtureUser',
                                                 'startAt': AT, 'durationMs': 14 * 24 * 3600000})['result']
        # Use the current time to keep the synthetic native session running.
        import time
        with Application(self.directory.name) as app:
            session = app.ledger.session(created['sessionId'])
            session['startAt'] = int(time.time() * 1000)
            app.ledger.save_session(session)
        args = {'sessionId': created['sessionId'], 'operationId': 'crash-at-post',
                'problemId': '15419', 'problemLabel': 'A', 'language': 'C++20', 'filename': 'A.cpp',
                'contentsBase64': base64.b64encode(CODE).decode()}
        process = self.process()
        try:
            write_frame(process.stdin, {'type': 'task', 'id': 'task', 'method': 'qoj_submit', 'args': args})
            while True:
                frame = read_frame(process.stdout)
                self.assertEqual(frame['type'], 'http.request')
                reply = self.fixture.exchange(frame['request'])
                if frame['request']['method'] == 'POST':
                    # The synthetic server accepted a POST, but the process
                    # dies before receiving the receipt. Its SQLite intent
                    # must survive and block all implicit retry paths.
                    process.terminate()
                    process.wait(timeout=5)
                    break
                write_frame(process.stdin, {'type': 'http.response', 'id': frame['id'],
                                             'requestId': frame['requestId'], **reply})
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        resumed = self.run_task('qoj_submit', args)
        self.assertTrue(resumed['ok'])
        self.assertEqual(resumed['result']['state'], 'unknown')
        self.assertEqual(len(self.fixture.posts), 1)


class HistorySafetyTests(unittest.TestCase):
    def test_zero_score_never_uses_earlier_ac_as_final_verdict(self):
        result = detail_verdict((FIXTURES / 'submission-1000002.html').read_text(), 0)
        self.assertEqual(result['verdict'], 'WRONG-ANSWER')
        only_pass = detail_verdict((FIXTURES / 'submission-1000001.html').read_text(), 0)
        self.assertEqual(only_pass['verdict'], 'UNKNOWN')

    def test_unverified_relative_time_and_other_accounts_never_become_vp_facts(self):
        html = (FIXTURES / 'submissions-3387.html').read_text()
        html = html.replace('<time datetime="2026-10-31T09:00:00+08:00">2026-10-31 09:00:00</time>', '01:23:45')
        parsed = parse_history(html, '3387', 'FixtureUser', {'A': {'id': '15419'}, 'B': {'id': '15420'}})
        item = next(item for item in parsed['submissions'] if item['id'] == '1000001')
        self.assertIsNone(item['submittedAt'])
        self.assertTrue(parsed['warnings'])
        other = parse_history(html, '3387', 'OtherUser', {'A': {'id': '15419'}, 'B': {'id': '15420'}})
        self.assertEqual(other['submissions'], [])


if __name__ == '__main__':
    unittest.main()
