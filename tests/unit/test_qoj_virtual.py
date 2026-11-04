from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from qojvp import Application, ApplicationError
from tests.unit.support import account_menu

ROOT = Path(__file__).resolve().parents[2]
AT = int(datetime.fromisoformat('2026-11-03T16:00:00+08:00').timestamp() * 1000)
CID = '2644'


def register_page(account='FixtureUser', minutes=300):
    # Form/action/button identities were captured from real QOJ 2644 on Nov 3.
    return account_menu(account, body=(
        '<h1>Virtual Contest Rules</h1><ul>'
        f'<li>The contest is {minutes} minutes long.</li>'
        '<li>Each wrong submission adds 20 minutes of penalty.</li></ul>'
        '<form id="form-register_vp" method="post" action="/contest/2644/virtual/register">'
        '<input type="hidden" name="_token" value="synthetic-registration-secret">'
        '<button id="button-submit-register_vp" name="submit-register_vp" type="submit">Start!</button>'
        '</form>'))


def dashboard(account='FixtureUser', card=None):
    if card is None:
        card = ('<b>The virtual contest is in progress. You can start your participation.</b>'
                '<form id="form-regvir" method="post" action="/contest/2644">'
                '<button id="button-submit-regvir" name="submit-regvir" type="submit">Start!</button></form>')
    return account_menu(account, body=(
        '<title>Synthetic Warm up - Dashboard - Contest - QOJ.ac</title>'
        '<table><tr><td>A</td><td><a href="/contest/2644/problem/15419">Synthetic A</a></td></tr></table>'
        '<div class="card border-primary top-buffer-lg"><h4 class="card-header bg-primary">Virtual Contest</h4>'
        '<div class="card-body">' + card + '</div></div>'))


def active_dashboard(account='FixtureUser', server_time='2026-11-03 18:07:28', rest=17384, timezone='+8'):
    # Server-rendered card/footer observed after the original 2644 Start POST.
    return dashboard(account, card='<b>Participation active</b>').replace(
        '<div class="card border-primary top-buffer-lg"><h4 class="card-header bg-primary">Virtual Contest</h4>'
        '<div class="card-body"><b>Participation active</b></div></div>',
        '<div class="card border-info top-buffer-lg"><h4 class="card-header bg-info">Contest ends in</h4>'
        f'<div class="card-body text-center countdown" data-rest="{rest}"></div></div>'
        f'<div class="uoj-footer"><p>Server Time: {server_time} (UTC{timezone})</p></div>')


class VirtualFixture:
    def __init__(self):
        self.account = 'FixtureUser'
        self.root = None
        self.dashboard = None
        self.register = None
        self.register_status = 200
        self.register_url = None
        self.requests = []
        self.disconnected = False
        self.before_register_response = None
        self.before_dashboard_response = None
        self.lock = threading.Lock()

    def exchange(self, request):
        with self.lock:
            self.requests.append(deepcopy(request))
        if request['method'] != 'GET':
            raise AssertionError('Native VP binding must never send a POST')
        if self.disconnected:
            return {'error': {'code': 'SYNTHETIC_OFFLINE'}}
        path = urlsplit(request['url']).path
        status, url = 200, request['url']
        if path == '/':
            body = self.root if self.root is not None else account_menu(self.account)
        elif path == '/contest/2644':
            body = self.dashboard if self.dashboard is not None else dashboard(self.account)
            if self.before_dashboard_response:
                self.before_dashboard_response()
        elif path == '/contest/2644/virtual/register':
            body = self.register if self.register is not None else register_page(self.account)
            status, url = self.register_status, self.register_url or url
            if self.before_register_response:
                self.before_register_response()
        else:
            status, body = 404, 'not found'
        return {'response': {'status': status, 'url': url,
                'headers': {'content-type': 'text/html; charset=utf-8'},
                'bodyBase64': base64.b64encode(body.encode()).decode()}}


class QojNativeVirtualTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='qoj-virtual-')
        self.app = Application(self.directory.name, clock=lambda: AT)
        self.fixture = VirtualFixture()

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def call(self, method, args=None):
        return self.app.dispatch(method, args, self.fixture.exchange)

    def bind(self):
        return self.call('qoj_bind_virtual', {'contestId': CID})

    def test_register_binding_uses_upstream_account_contest_and_rules_without_starting(self):
        result = self.bind()
        session = result['session']
        self.assertEqual((session['contestId'], session['account'], session['durationMs']), (CID, 'FixtureUser', 18000000))
        self.assertEqual(session['state'], 'prepared')
        self.assertIsNone(session['startAt'])
        self.assertEqual(session['qojVirtual']['mode'], 'qoj-native')
        self.assertEqual(result['virtual']['state'], 'not_started')
        self.assertEqual(result['contest']['problems'][0]['id'], '15419')
        self.assertEqual(self.app.ledger.contest('FixtureUser', CID)['problems']['A']['id'], '15419')
        self.assertNotIn('synthetic-registration-secret', json.dumps(result))
        self.assertTrue(all(r['method'] == 'GET' for r in self.fixture.requests))

    def test_repeated_bind_reuses_the_same_prepared_session(self):
        first, second = self.bind(), self.bind()
        self.assertEqual(first['session']['sessionId'], second['session']['sessionId'])
        self.assertEqual(len(self.app.ledger.sessions()), 1)

    def test_existing_prepared_session_and_target_are_preserved(self):
        old = self.app.dispatch('create_session', {'contestId': CID, 'account': 'FixtureUser', 'title': 'My practice',
            'ranklandUrl': 'https://vp.xcpc.link/?contest=known-target'})
        result = self.bind()['session']
        self.assertEqual(result['sessionId'], old['sessionId'])
        self.assertEqual(result['title'], 'My practice')
        self.assertEqual(result['ranklandUrl'], old['ranklandUrl'])

    def test_manual_running_session_is_not_retimed(self):
        old = self.app.dispatch('create_session', {'contestId': CID, 'account': 'FixtureUser', 'startAt': AT - 60000})
        result = self.bind()['session']
        self.assertNotEqual(result['sessionId'], old['sessionId'])
        self.assertEqual(self.app.ledger.session(old['sessionId'])['startAt'], AT - 60000)

    def test_stale_prepare_response_reuses_a_concurrently_started_native_session(self):
        old = self.bind()['session']
        def started_in_another_helper():
            with Application(self.directory.name, clock=lambda: AT) as helper:
                with helper.ledger.transaction():
                    session = helper.ledger.session(old['sessionId'])
                    session.update(startAt=AT - 10000, state='running', ranklandPrepared=True,
                                   ranklandPreparedAt=AT - 5000)
                    session['qojVirtual'].update(state='running', startAt=AT - 10000,
                                                 timeSource='provider-absolute')
                    helper.ledger.save_session(session)
        self.fixture.before_dashboard_response = started_in_another_helper
        result = self.bind()['session']
        self.assertEqual(result['sessionId'], old['sessionId'])
        self.assertEqual(len(self.app.ledger.sessions()), 1)
        self.assertEqual(result['startAt'], AT - 10000)
        self.assertEqual(result['qojVirtual']['state'], 'running')
        self.assertTrue(result['ranklandPrepared'])

    def test_prepared_duration_conflict_is_reported_without_mutation(self):
        old = self.app.dispatch('create_session', {'contestId': CID, 'account': 'FixtureUser', 'durationMs': 3600000})
        with self.assertRaises(ApplicationError) as caught:
            self.bind()
        self.assertEqual(caught.exception.code, 'QOJ_VIRTUAL_DURATION_MISMATCH')
        self.assertEqual(self.app.ledger.session(old['sessionId'])['durationMs'], 3600000)
        self.assertNotIn('qojVirtual', self.app.ledger.session(old['sessionId']))

    def test_changed_account_or_redirect_does_not_bind(self):
        for change in ({'register': register_page('OtherUser')},
                       {'dashboard': dashboard('OtherUser')},
                       {'register_url': 'https://qoj.ac/contest/999/virtual/register'},
                       {'register_url': 'https://elsewhere.invalid/contest/2644/virtual/register'}):
            with self.subTest(change=list(change)):
                self.fixture = VirtualFixture()
                for key, value in change.items():
                    setattr(self.fixture, key, value)
                with self.assertRaises(ApplicationError):
                    self.bind()
                self.assertEqual(self.app.ledger.sessions(), [])

    def test_invalid_or_ambiguous_register_form_never_starts_or_creates(self):
        for page in (register_page().replace('submit-register_vp', 'submit-unrelated'),
                     register_page() + register_page(),
                     register_page().replace('300 minutes long', 'several hours long'),
                     register_page().replace('action="/contest/2644/virtual/register"', 'action="/contest/999/virtual/register"')):
            with self.subTest(page=page[-100:]):
                self.fixture.register = page
                with self.assertRaises(ApplicationError):
                    self.bind()
                self.assertEqual(self.app.ledger.sessions(), [])

    def test_logged_out_binding_is_rejected(self):
        self.fixture.root = '<a href="/login">Login</a>'
        with self.assertRaises(ApplicationError) as caught:
            self.bind()
        self.assertEqual(caught.exception.code, 'LOGIN_REQUIRED')
        self.assertEqual(self.app.ledger.sessions(), [])

    def test_waiting_and_unknown_confirmation_keep_the_original_prepared_clock(self):
        session = self.bind()['session']
        args = {'sessionId': session['sessionId']}
        waiting = self.call('qoj_confirm_virtual_start', args)
        self.assertEqual(waiting['virtual']['state'], 'not_started')
        self.assertIsNone(waiting['session']['startAt'])
        self.fixture.dashboard = dashboard(card='<b>A page shape that has not been verified</b>')
        unknown = self.call('qoj_confirm_virtual_start', args)
        self.assertEqual(unknown['virtual']['state'], 'unknown')
        self.assertIsNone(unknown['session']['startAt'])
        self.assertEqual(self.app.ledger.session(session['sessionId'])['state'], 'prepared')

    def test_native_start_uses_same_response_server_countdown_and_registered_duration(self):
        session = self.bind()['session']
        self.fixture.dashboard = active_dashboard()
        # Local time is intentionally nearly two hours wrong; it is not the
        # provider clock nor the time when the Start POST was observed.
        result = self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})
        expected = int(datetime.fromisoformat('2026-11-03T17:57:12+08:00').timestamp() * 1000)
        self.assertEqual(result['session']['sessionId'], session['sessionId'])
        self.assertEqual(result['session']['startAt'], expected)
        self.assertEqual(result['session']['state'], 'running')
        self.assertEqual(result['virtual']['timeSource'], 'provider-countdown')
        self.assertEqual(result['virtual']['remainingMs'], 17384000)
        self.assertEqual(result['session']['qojVirtual']['source'], 'qoj-native-server-countdown')
        self.assertTrue(all(r['method'] == 'GET' for r in self.fixture.requests))

    def test_binding_after_start_uses_its_verified_rules_when_register_redirects(self):
        session = self.bind()['session']
        self.fixture.dashboard = active_dashboard()
        self.fixture.register_url = 'https://qoj.ac/contests'
        self.fixture.requests.clear()
        result = self.bind()
        self.assertEqual(result['session']['sessionId'], session['sessionId'])
        self.assertEqual(result['virtual']['state'], 'running')
        self.assertIsNone(result['session']['startAt'])
        self.assertFalse(any('/virtual/register' in r['url'] for r in self.fixture.requests))
        confirmed = self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})
        self.assertEqual(confirmed['session']['startAt'], result['virtual']['startAt'])

    def test_direct_start_binds_captured_register_rules_after_server_redirects(self):
        self.fixture.dashboard = active_dashboard()
        self.fixture.register_url = 'https://qoj.ac/contests'
        result = self.call('qoj_bind_virtual', {'contestId': CID, 'registrationPage': {
            'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': register_page()}})
        self.assertEqual(result['session']['state'], 'prepared')
        self.assertEqual(result['virtual']['state'], 'running')
        self.assertFalse(any('/virtual/register' in r['url'] for r in self.fixture.requests))
        self.assertNotIn('synthetic-registration-secret', json.dumps(self.app.ledger.sessions()))
        self.assertNotIn('registrationPage', json.dumps(self.app.ledger.sessions()))
        confirmed = self.call('qoj_confirm_virtual_start', {'sessionId': result['session']['sessionId']})
        expected = int(datetime.fromisoformat('2026-11-03T17:57:12+08:00').timestamp() * 1000)
        self.assertEqual(confirmed['session']['startAt'], expected)
        again = self.call('qoj_bind_virtual', {'contestId': CID, 'registrationPage': {
            'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': register_page()}})
        self.assertEqual(again['session']['sessionId'], result['session']['sessionId'])

    def test_direct_start_cannot_use_cross_account_cid_or_invalid_snapshot(self):
        self.fixture.dashboard = active_dashboard()
        for snapshot in ({'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': register_page('OtherUser')},
                         {'url': 'https://qoj.ac/contest/999/virtual/register', 'html': register_page()},
                         {'url': 'https://attacker.invalid/contest/2644/virtual/register', 'html': register_page()},
                         {'url': 'https://qoj.ac/contest/2644', 'html': register_page()},
                         {'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': dashboard()},
                         {'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': 'x' * 131073}):
            with self.subTest(url=snapshot['url']):
                with self.assertRaises(ApplicationError):
                    self.call('qoj_bind_virtual', {'contestId': CID, 'registrationPage': snapshot})
                self.assertEqual(self.app.ledger.sessions(), [])

    def test_snapshot_duration_cannot_replace_an_existing_verified_binding(self):
        session = self.bind()['session']
        self.fixture.dashboard = active_dashboard()
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_bind_virtual', {'contestId': CID, 'registrationPage': {
                'url': 'https://qoj.ac/contest/2644/virtual/register', 'html': register_page(minutes=240)}})
        self.assertEqual(caught.exception.code, 'QOJ_VIRTUAL_DURATION_MISMATCH')
        self.assertEqual(self.app.ledger.session(session['sessionId'])['durationMs'], 18000000)
        self.assertIsNone(self.app.ledger.session(session['sessionId'])['startAt'])

    def test_repeated_native_start_confirmation_preserves_verified_rankland_start(self):
        session = self.bind()['session']
        sid = session['sessionId']
        self.app.dispatch('update_session', {'sessionId': sid, 'ranklandUrl': 'https://vp.xcpc.link/?contest=known-target'})
        self.fixture.dashboard = active_dashboard()
        first = self.call('qoj_confirm_virtual_start', {'sessionId': sid})['session']
        self.app.clock = lambda: first['startAt'] + 900000
        frozen = self.app.dispatch('prepare_rankland', {'sessionId': sid})
        q = parse_qs(urlsplit(frozen['ranklandUrl']).query)
        self.assertEqual(q['from'], ['0'])
        self.assertNotIn('run', q)
        self.assertNotIn('anchor', q)
        self.assertEqual(int(datetime.fromisoformat(q['at'][0].replace('Z', '+00:00')).timestamp() * 1000),
                         first['startAt'])
        self.fixture.dashboard = active_dashboard(server_time='2026-11-03 18:08:28', rest=17324)
        repeated = self.call('qoj_confirm_virtual_start', {'sessionId': sid})['session']
        self.assertEqual(repeated['startAt'], first['startAt'])
        self.assertEqual(repeated['ranklandUrl'], frozen['ranklandUrl'])
        self.assertEqual(repeated['ranklandPreparedAt'], frozen['ranklandPreparedAt'])
        self.assertTrue(repeated['ranklandPrepared'])

    def test_ambiguous_or_invalid_countdown_cannot_start_a_session(self):
        session = self.bind()['session']
        for page in (active_dashboard(rest=18001), active_dashboard(rest=-1),
                     active_dashboard(timezone=''), active_dashboard(server_time='2026-02-30 18:07:28'),
                     active_dashboard().replace('Server Time:', 'Client Time:'),
                     active_dashboard() + '<div class="countdown" data-rest="17384"></div>',
                     active_dashboard().replace('Contest ends in', 'Contest begins in')):
            with self.subTest(page=page[-100:]):
                self.fixture.dashboard = page
                result = self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})
                self.assertEqual(result['virtual']['state'], 'unknown')
                self.assertIsNone(result['session']['startAt'])

    def test_native_clock_conflict_does_not_retime_an_existing_session(self):
        session = self.bind()['session']
        self.fixture.dashboard = active_dashboard()
        first = self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})['session']
        self.fixture.dashboard = active_dashboard(rest=17000)
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})
        self.assertEqual(caught.exception.code, 'QOJ_VIRTUAL_CLOCK_CONFLICT')
        self.assertEqual(self.app.ledger.session(session['sessionId'])['startAt'], first['startAt'])

    def test_failed_start_or_offline_confirmation_cannot_start_local_clock(self):
        session = self.bind()['session']
        self.fixture.disconnected = True
        with self.assertRaises(ApplicationError):
            self.call('qoj_confirm_virtual_start', {'sessionId': session['sessionId']})
        self.assertIsNone(self.app.ledger.session(session['sessionId'])['startAt'])
        self.assertEqual(self.app.ledger.session(session['sessionId'])['state'], 'prepared')

    def test_manual_start_does_not_bypass_native_bound_clock(self):
        session = self.bind()['session']
        with self.assertRaises(ApplicationError) as caught:
            self.app.dispatch('start_session', {'sessionId': session['sessionId']})
        self.assertEqual(caught.exception.code, 'QOJ_VIRTUAL_START_REQUIRED')
        self.assertIsNone(self.app.ledger.session(session['sessionId'])['startAt'])

    def test_unbound_or_other_account_confirmation_is_rejected(self):
        plain = self.app.dispatch('create_session', {'contestId': CID, 'account': 'FixtureUser'})
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_confirm_virtual_start', {'sessionId': plain['sessionId']})
        self.assertEqual(caught.exception.code, 'QOJ_VIRTUAL_NOT_BOUND')
        bound = self.bind()['session']
        self.fixture.account = 'OtherUser'
        with self.assertRaises(ApplicationError) as caught:
            self.call('qoj_confirm_virtual_start', {'sessionId': bound['sessionId']})
        self.assertEqual(caught.exception.code, 'ACCOUNT_MISMATCH')

    def test_concurrent_binds_from_separate_helpers_create_one_session(self):
        barrier = threading.Barrier(2)
        def bind():
            with Application(self.directory.name, clock=lambda: AT) as app:
                barrier.wait(timeout=5)
                return app.dispatch('qoj_bind_virtual', {'contestId': CID}, self.fixture.exchange)['session']['sessionId']
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: bind(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(len(self.app.ledger.sessions()), 1)


if __name__ == '__main__':
    unittest.main()
