#!/usr/bin/env python3
"""Run only inside the VMware guest: real Firefox, real extension, fake judge.

The only code POST targets the loopback MvpFixtureServer. RankLand is the real
public upstream application, in a unique run and an isolated persistent Firefox
profile. No account cookies are imported or exported.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import traceback
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'preflight'), str(PROJECT / 'preflight/vendor_py'),
               str(PROJECT / 'vendor/qoj-submitter')]

from guest_preflight import atomic_json, process_exit, require, utc_now
from mvp_fixture_server import MvpFixtureServer

HOST = 'org.littledrinks.qoj_vp'
EXTENSION_ID = 'qoj-vp@littledrinks.local'
OWNER = 'QOJ VP isolated MVP QA native host v1'
TWO_HOURS = 7200000


class MvpHarness:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.run_id = uuid.uuid4().hex
        self.state = self.project / 'state'
        self.profile = self.state / 'qa-firefox-profile'
        self.native_state = self.state / 'qa-native' / self.run_id
        self.results = self.project / 'results' / 'mvp' / self.run_id
        self.results.mkdir(parents=True, exist_ok=True)
        self.driver = None
        self.ui_handle = self.ui_url = None
        self.manifest_path = Path.home() / '.mozilla/native-messaging-hosts' / (HOST + '.json')
        self.manifest_before = None
        self.manifest_installed = False
        self.phase = 'initializing'
        self.summary = {'schema': 'qoj-vp-mvp-qa-v1', 'runId': self.run_id, 'startedAt': utc_now(),
                        'project': str(self.project), 'profile': str(self.profile), 'nativeState': str(self.native_state),
                        'fixtureCodeSubmissionOnly': True, 'realQojAuthenticatedSubmission': 'not-tested-no-authentication-import',
                        'realRankland': True, 'checks': [], 'cleanup': {}}
        self.flush()

    def flush(self):
        self.summary['phase'] = self.phase
        self.summary['updatedAt'] = utc_now()
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/mvp-summary.json', self.summary)
        atomic_json(self.project / 'results/mvp-status.json', {
            'runId': self.run_id, 'phase': self.phase, 'status': self.summary.get('status', 'running'),
            'updatedAt': self.summary['updatedAt'], 'summary': str(self.results / 'summary.json'),
            'checks': [{'name': c['name'], 'status': c['status']} for c in self.summary['checks']],
            'cleanup': self.summary['cleanup']})

    def step(self, name, fn, *, optional=False):
        self.phase = name
        self.flush()
        check = {'name': name, 'startedAt': utc_now(), 'optional': optional}
        try:
            value = fn()
            check.update(status='passed', evidence=value)
            return value
        except Exception as exc:
            check.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)[:2200]})
            if self.driver:
                try:
                    screenshot = self.results / (name + '-failed.png')
                    self.driver.save_screenshot(str(screenshot))
                    check['screenshot'] = str(screenshot)
                except Exception:
                    pass
                if 'rankland' in name and any(part in name for part in ('sync', 'guard', 'concurrent')):
                    previous_handle = None
                    try:
                        previous_handle = self.driver.current_window_handle
                        diagnostic = self.diagnostic()
                        post_fields = {'method', 'requestPath', 'status', 'locationPath', 'source', 'observedAt'}
                        guard_fields = {'allowed', 'code', 'tabCount', 'tabId', 'matchingTabIds', 'at'}
                        safe = {
                            'http': {'postObservations': [
                                {key: row[key] for key in post_fields if key in row}
                                for row in diagnostic.get('http', {}).get('postObservations', [])]},
                            'ranklandGuards': [
                                {key: row[key] for key in guard_fields if key in row}
                                for row in diagnostic.get('ranklandGuards', [])],
                        }
                        path = self.results / (name + '-diagnostics.json')
                        atomic_json(path, safe)
                        check['browserDiagnostics'] = safe
                        check['browserDiagnosticsPath'] = str(path)
                    except Exception as diagnostic_error:
                        check['browserDiagnosticErrorType'] = type(diagnostic_error).__name__
                    finally:
                        try:
                            if previous_handle is not None and previous_handle in self.driver.window_handles:
                                self.driver.switch_to.window(previous_handle)
                        except Exception:
                            pass
            return None
        finally:
            check['finishedAt'] = utc_now()
            self.summary['checks'].append(check)
            self.flush()

    def skip(self, name, dependency):
        self.phase = name
        self.summary['checks'].append({'name': name, 'status': 'skipped', 'optional': False,
                                       'dependency': dependency, 'reason': 'Required earlier RankLand evidence did not pass',
                                       'startedAt': utc_now(), 'finishedAt': utc_now()})
        self.flush()
        return None

    def setup(self, fixture):
        self.profile.mkdir(parents=True, exist_ok=True)
        self.native_state.mkdir(parents=True, exist_ok=True)
        launcher = self.native_state / 'launcher.sh'
        environment = {
            'PYTHONPATH': ':'.join(str(self.project / p) for p in ('', 'preflight/vendor_py', 'vendor/qoj-submitter')),
            'QOJ_VP_STATE_DIR': str(self.native_state),
            'QOJ_VP_QOJ_PATH': str(self.project / 'vendor/qoj-submitter'),
            'QOJ_VP_FIXTURE_ORIGIN': fixture.origin,
        }
        launcher.write_text('#!/bin/sh\n' + ''.join('export ' + k + '=' + shlex.quote(v) + '\n' for k, v in environment.items())
                            + 'exec /usr/bin/python3 -B -m qojvp.native_host\n')
        launcher.chmod(0o700)
        manifest = {'name': HOST, 'description': OWNER, 'path': str(launcher), 'type': 'stdio',
                    'allowed_extensions': [EXTENSION_ID]}
        if self.manifest_path.exists():
            existing = json.loads(self.manifest_path.read_text())
            require(existing.get('description') == OWNER and
                    Path(existing.get('path', '')).is_relative_to(self.state / 'qa-native'),
                    'A native host manifest not owned by this QA run already exists')
            self.manifest_before = self.manifest_path.read_bytes()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.manifest_path, manifest)
        self.manifest_installed = True
        self.addon = self.results / 'workbench.xpi'
        with zipfile.ZipFile(self.addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((self.project / 'extension').rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(self.project / 'extension')))
        require((self.project / 'preflight/tools/geckodriver').is_file(), 'Guest geckodriver missing')
        return {'addon': str(self.addon), 'nativeManifest': str(self.manifest_path),
                'nativeState': str(self.native_state), 'fixtureOrigin': fixture.origin,
                'installation': 'persistent-path-not-base64'}

    def start_browser(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        options.add_argument('-headless')
        options.add_argument('-profile')
        options.add_argument(str(self.profile))
        options.set_capability('unhandledPromptBehavior', 'ignore')
        for key, value in {'browser.shell.checkDefaultBrowser': False, 'browser.startup.page': 0,
                           'browser.startup.homepage': 'about:blank', 'browser.sessionstore.resume_from_crash': False}.items():
            options.set_preference(key, value)
        service = Service(str(self.project / 'preflight/tools/geckodriver'), log_output=str(self.results / 'geckodriver.log'))
        self.driver = webdriver.Firefox(options=options, service=service)
        self.driver.set_page_load_timeout(45)
        self.driver.set_script_timeout(160)
        self.driver.set_window_size(1440, 1000)
        cap = self.driver.capabilities
        require(Path(cap['moz:profile']).resolve() == self.profile, 'Firefox profile was copied or not isolated')
        require(cap.get('moz:headless') is True, 'Browser is not headless')
        return {'pid': cap['moz:processID'], 'version': cap['browserVersion'], 'profile': cap['moz:profile'],
                'headless': True, 'profileCopied': False}

    def install_extension(self):
        installed = self.driver.execute('INSTALL_ADDON', {'path': str(self.addon), 'temporary': True})['value']
        require(installed == EXTENSION_ID, 'Unexpected extension identifier')
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                url = self.driver.current_url
                if url.startswith('moz-extension://') and urlsplit(url).path == '/ui.html':
                    if self.driver.execute_script('return !!window.qojVpUi && window.qojVpUi.getState().connected'):
                        self.ui_handle, self.ui_url = handle, url
                        return {'extensionId': installed, 'url': url, 'temporary': True, 'installation': 'persistent-path'}
            time.sleep(0.1)
        raise AssertionError('The real workbench UI did not connect to its native host')

    def focus_ui(self):
        if self.ui_handle not in self.driver.window_handles:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if self.driver.current_url.startswith('moz-extension://') and urlsplit(self.driver.current_url).path == '/ui.html':
                    self.ui_handle, self.ui_url = handle, self.driver.current_url
                    break
        require(self.ui_handle in self.driver.window_handles, 'No workbench tab remains')
        self.driver.switch_to.window(self.ui_handle)

    def call(self, method, args=None):
        self.focus_ui()
        response = self.driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          browser.runtime.sendMessage({type:'vp.task',method:arguments[0],args:arguments[1]})
            .then(done,error=>done({ok:false,error:{message:error.message}}));
        ''', method, args or {})
        require(response and response.get('ok'), 'Extension task failed: ' + str((response or {}).get('error')))
        result = response['result']
        if isinstance(result, dict) and isinstance(result.get('helperPid'), int):
            require(result.get('nativePortClosed') is True, 'Native port did not close')
            self.summary.setdefault('helperExits', []).append(process_exit(result['helperPid']))
        return result

    def diagnostic(self):
        self.focus_ui()
        response = self.driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          browser.runtime.sendMessage({type:'vp.diagnostics'}).then(done,error=>done({ok:false,error:{message:error.message}}));
        ''')
        require(response and response.get('ok'), 'Browser diagnostic response unavailable')
        return response['result']

    def quit_browser(self):
        if self.driver is None:
            return {'alreadyStopped': True}
        driver, self.driver = self.driver, None
        pid = driver.capabilities['moz:processID']
        driver.quit()
        self.ui_handle = None
        return process_exit(pid, timeout=20)

    def cleanup_manifest(self):
        if not self.manifest_installed:
            return {'modified': False}
        current = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else None
        require(current is None or (current.get('description') == OWNER and current.get('path') == str(self.native_state / 'launcher.sh')),
                'Native manifest changed ownership during the test')
        if self.manifest_before is None:
            self.manifest_path.unlink(missing_ok=True)
            return {'removedOwnedManifest': True}
        self.manifest_path.write_bytes(self.manifest_before)
        return {'restoredPriorOwnedManifest': True}

    def rankland_handle(self, session, *, navigate=True):
        target = urlsplit(session['ranklandUrl'])
        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            url = urlsplit(self.driver.current_url)
            if url.netloc == target.netloc and parse_qs(url.query).get('run') == [session['sessionId']]:
                return handle
        if not navigate:
            return None
        self.driver.switch_to.new_window('tab')
        self.driver.get(session['ranklandUrl'])
        return self.driver.current_window_handle

    def matching_rankland_tabs(self, session):
        """Observe the full original storage identity via the extension API."""
        self.focus_ui()
        return self.driver.execute_async_script('''
          const done=arguments[arguments.length-1], expected=arguments[0];
          function identity(raw){
            const u=new URL(raw),q=u.searchParams;
            return JSON.stringify([u.origin,q.get('contest'),q.get('run'),q.get('rule')||'auto',
              Number(q.get('count')??50),Number(q.get('ratio')??20),q.get('at')||'null',Number(q.get('from')||0)]);
          }
          browser.tabs.query({}).then(tabs=>done(tabs.filter(t=>{
            try{return identity(t.url)===identity(expected);}catch(_){return false;}
          }).map(t=>({id:t.id,url:t.url,status:t.status}))),e=>done({error:e.name}));
        ''', session['ranklandUrl'])

    def duplicate_rankland_guard(self, session):
        before = self.rankland_snapshot(session, 'before-duplicate-guard')
        duplicate = None
        try:
            self.driver.switch_to.new_window('tab')
            duplicate = self.driver.current_window_handle
            self.driver.get(session['ranklandUrl'])
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                loaded = self.driver.execute_script('''
                  return !!document.querySelector('[data-id="vp-ranklist-content"]') &&
                    !!document.querySelector('select[aria-label="题目"]') &&
                    [...document.querySelectorAll('.srk-user-name-text')].some(e=>e.textContent.trim()===arguments[0]);
                ''', before['value']['ownName'])
                if loaded:
                    break
                time.sleep(0.15)
            require(loaded, 'The deliberate duplicate original RankLand page did not actually load')
            self.driver.save_screenshot(str(self.results / 'rankland-deliberate-duplicate-tab.png'))
            matches = self.matching_rankland_tabs(session)
            require(isinstance(matches, list) and len(matches) == 2, 'The duplicate test does not have exactly two identity-matching tabs')
            blocked = self.call('rankland.sync', {'sessionId': session['sessionId']})
            require(blocked.get('state') == 'attention' and blocked.get('synced') == 0,
                    'Automatic sync was not blocked while two original RankLand pages could write the same storage slot')
            after = self.rankland_snapshot(session, 'duplicate-sync-blocked')
            require(after['value']['manual'] == before['value']['manual'], 'Duplicate-tab sync changed or duplicated the original record')
            return {'identityMatchingTabs': matches, 'sync': blocked,
                    'manualCountBefore': len(before['value']['manual']), 'manualCountAfter': len(after['value']['manual'])}
        finally:
            if duplicate is not None and duplicate in self.driver.window_handles:
                self.driver.switch_to.window(duplicate)
                self.driver.close()
            self.focus_ui()

    def concurrent_rankland_open(self, session, before):
        existing = self.matching_rankland_tabs(session)
        require(isinstance(existing, list) and len(existing) == 1, 'Concurrent-open test requires exactly one initial board tab')
        original = self.rankland_handle(session)
        self.driver.close()
        require(original not in self.driver.window_handles, 'The sole original scoreboard tab did not close')
        require(self.matching_rankland_tabs(session) == [], 'An identity-matching scoreboard remained before the concurrent calls')
        responses = self.driver.execute_async_script('''
          const done=arguments[arguments.length-1],sessionId=arguments[0];
          Promise.all([1,2].map(()=>browser.runtime.sendMessage({type:'vp.task',method:'rankland.open',args:{sessionId}})))
            .then(done,error=>done({error:error.name+': '+error.message}));
        ''', session['sessionId'])
        require(isinstance(responses, list) and len(responses) == 2 and all(r.get('ok') for r in responses),
                'One or both simultaneous rankland.open requests failed: ' + str(responses))
        ids = [r['result']['tabId'] for r in responses]
        require(ids[0] == ids[1], 'Simultaneous open calls returned different original scoreboard tabs')
        deadline = time.monotonic() + 8
        matches = []
        while time.monotonic() < deadline:
            matches = self.matching_rankland_tabs(session)
            if isinstance(matches, list) and matches:
                break
            time.sleep(0.15)
        require(isinstance(matches, list) and len(matches) == 1 and matches[0]['id'] == ids[0],
                'Concurrent opening created more or fewer than one full-identity scoreboard tab')
        current = self.rankland_snapshot(session, 'after-concurrent-open')
        require(current['value']['manual'] == before['value']['manual'], 'Concurrent reopening lost or duplicated the existing manual record')
        return {'originalTabClosed': True, 'concurrentResults': responses, 'identityMatchingTabs': matches,
                'manualCount': len(current['value']['manual']), 'snapshot': current}

    def rankland_snapshot(self, session, label, *, expected_manual=1):
        handle = self.rankland_handle(session)
        deadline = time.monotonic() + 50
        snapshot = None
        while time.monotonic() < deadline:
            snapshot = self.driver.execute_script('''
              const sid=arguments[0];
              const rows=Object.keys(localStorage).filter(k=>k.startsWith('RanklandVP2:')&&k.includes(':'+sid+':'))
                .map(key=>({key,value:JSON.parse(localStorage.getItem(key))}));
              if(rows.length!==1)return {keys:rows.map(r=>r.key)};
              const saved=rows[0], name=[...document.querySelectorAll('.srk-user-name-text')]
                .find(e=>e.textContent.trim()===saved.value.ownName);
              const cell=name?.closest('td'),row=name?.closest('tr'),cells=row?[...row.cells]:[],index=cells.indexOf(cell);
              return {url:location.href,key:saved.key,value:saved.value,
                ownRow:row?{text:row.innerText,score:cells[index+1]?.textContent.trim(),visible:!!row.getClientRects().length}:null};
            ''', session['sessionId'])
            if (snapshot.get('value', {}).get('manual') is not None and
                    len(snapshot['value']['manual']) == expected_manual and (snapshot.get('ownRow') or {}).get('score') == '1'):
                break
            time.sleep(0.2)
        atomic_json(self.results / ('rankland-' + label + '.json'), snapshot)
        self.driver.save_screenshot(str(self.results / ('rankland-' + label + '.png')))
        require((snapshot.get('ownRow') or {}).get('visible'), 'RankLand did not render its own test row')
        require(snapshot['ownRow']['score'] == '1', 'RankLand own row has not solved exactly one problem')
        manual = snapshot.get('value', {}).get('manual', [])
        require(len(manual) == expected_manual and manual[0]['result'] == 'AC', 'RankLand manual AC record missing or duplicated')
        require(snapshot['value']['elapsed'] >= TWO_HOURS, 'RankLand clock reset below the two-hour anchor')
        require(parse_qs(urlsplit(snapshot['url']).query).get('run') == [session['sessionId']], 'Wrong RankLand run')
        return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--scenario', choices=('accepted', 'unknown503'), default='accepted')
    parser.add_argument('--skip-domjudge-reference', action='store_true')
    args = parser.parse_args()
    h = MvpHarness(args.project)
    h.summary['scenario'] = args.scenario
    fixture = None
    phase1 = session = manifest = None
    rankland_verified = False
    try:
        fixture = MvpFixtureServer(scenario=args.scenario, judge_after_reads=2, account='csj-test').start()
        setup = h.step('isolated_native_setup', lambda: h.setup(fixture))
        first = h.step('first_firefox', h.start_browser) if setup else None
        installed = h.step('product_extension_install', h.install_extension) if first else None
        if installed:
            def hello():
                result = h.call('hello')
                require(result.get('fixture') is True, 'Native helper is not confined to the loopback fixture')
                require(Path(result['stateDir']).resolve() == h.native_state, 'Wrong persistent native state directory')
                return result
            h.step('native_fixture_guard_and_process_exit', hello)

            from mvp_ui_probe import run_ui_probe, resume_ui_probe
            source = h.results / 'A.cpp'
            source.write_bytes(b'// SYNTHETIC VM MVP ACCEPTANCE; loopback judge only\nint main(){return 0;}\n')
            rankland_url = 'https://vp.xcpc.link/?' + urlencode({
                'contest': 'icpc2025nanjing', 'rule': 'ICPC', 'team': 'qoj-vp-mvp-' + h.run_id[:12]})

            def ui_phase1():
                nonlocal phase1
                if args.scenario == 'unknown503':
                    from mvp_ui_probe import run_unknown_ui_probe
                    probe = run_unknown_ui_probe
                else:
                    probe = run_ui_probe
                phase1 = probe(h.driver, h.results, source, rankland_url, get_post_count=lambda: fixture.post_count)
                atomic_json(h.results / 'ui-phase1-outer.json', phase1)
                require(phase1.get('status') == 'phase1_passed_restart_pending', 'UI phase 1 failed; inspect its report')
                require(phase1.get('sessionId'), 'UI did not return a durable session ID')
                if args.scenario == 'unknown503':
                    require(phase1.get('unknownObserved') is True and phase1.get('reconciled') is True,
                            'Unknown receipt was not observed and explicitly reconciled through the real UI')
                return phase1
            phase_name = ('real_ui_unknown_receipt_no_retry_and_explicit_reconciliation' if args.scenario == 'unknown503'
                          else 'real_domjudge_style_ui_submit_cancel_confirm_and_judge')
            ui_result = h.step(phase_name, ui_phase1)
            # The probe may close/reopen the original UI handle itself.
            h.focus_ui()
            if phase1 and phase1.get('sessionId'):
                session = h.step('independent_session_readback', lambda: h.call('inspect_session', {'sessionId': phase1['sessionId']}))
                if session:
                    def source_and_receipt():
                        require(fixture.post_count == 1 and fixture.accepted_post_count == 1, 'Exactly one valid POST did not reach the fixture')
                        records = fixture.submissions
                        require(len(records) == 1, 'Fixture does not have exactly one submission')
                        require(records[0]['sourceSha256'] == hashlib.sha256(source.read_bytes()).hexdigest(), 'Selected source bytes changed in transit')
                        require(records[0]['filename'] == 'A.cpp', 'Filename did not reach the real multipart POST')
                        require(records[0]['language'] == 'C++20', 'Filename language inference did not use the real form option')
                        diag = h.diagnostic()
                        observed = diag.get('http', {}).get('postObservations', [])
                        if args.scenario == 'unknown503':
                            receipts = [r for r in observed if r.get('status') == 503 and r.get('locationPath') is None]
                            require(receipts, 'The uncertain submission did not retain its real webRequest 503/no-Location observation')
                            require(not any(r.get('status') == 302 for r in observed), 'A false successful redirect was invented for a 503 receipt')
                            require(phase1.get('unknownObserved') is True and phase1.get('reconciled') is True,
                                    'A confirmed ID cannot replace the unknown receipt without explicit reconciliation')
                        else:
                            receipts = [r for r in observed if r.get('status') == 302 and r.get('locationPath') == '/submission/' + records[0]['id']]
                            require(receipts, 'No original webRequest HTTP 302 Location was observed')
                        from qojvp.application import load_upstream
                        client_module, samples_module, _ = load_upstream(h.project / 'vendor/qoj-submitter')
                        client_hash = hashlib.sha256(Path(client_module.__file__).read_bytes()).hexdigest()
                        require(client_hash == '59462626522eb6a511b6ccfbaf7e93ee1adb422d0dc6ace9bf6946edc75d0211', 'Upstream client is not the pinned real implementation')
                        return {'postCount': fixture.post_count, 'sourceSha256': records[0]['sourceSha256'],
                                'submissionId': records[0]['id'], 'webRequestReceipts': receipts, 'scenario': args.scenario,
                                'qojClientModule': client_module.QojClient.__module__, 'qojClientSha256': client_hash,
                                'qojSamplesModule': samples_module.__name__, 'source': 'loopback-fixture-real-firefox-native'}
                    h.step('independent_multipart_source_and_observed_redirect', source_and_receipt)

                    def problem_form():
                        form = h.call('qoj_problem_form', {'sessionId': session['sessionId'], 'problemId': '15419'})
                        require(form['languages'] == ['C++20', 'Python3'] and form['csrfPresent'], 'Real upstream form parser did not return the fixture options')
                        require(form['pdfCandidates'], 'Fixture PDF link was not discovered')
                        require('token' not in json.dumps(form).lower(), 'A CSRF value was exposed')
                        return form
                    h.step('real_client_problem_form_pdf_discovery', problem_form)

                    def samples():
                        value = h.call('qoj_samples', {'sessionId': session['sessionId'], 'problemLabel': 'B'})
                        data = base64.b64decode(value.pop('zipBase64'), validate=True)
                        target = h.results / 'samples-B.zip'
                        target.write_bytes(data)
                        with zipfile.ZipFile(io.BytesIO(data)) as archive:
                            names = archive.namelist()
                            require('samples-B/2.in' in names and 'samples-B/2.ans' not in names, 'Missing answers were invented or samples dropped')
                            require(any(name.endswith('judge.cpp') for name in names), 'Special attachments were dropped')
                        require(value['warnings'], 'Incomplete sample pairs were not reported')
                        return {**value, 'artifact': str(target), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    h.step('single_problem_samples_through_browser_native_upstream', samples)

                    def history():
                        value = h.call('qoj_submissions', {'sessionId': session['sessionId'], 'refresh': True})
                        confirmed = [s for s in value['submissions'] if s.get('state') == 'confirmed']
                        require(len(confirmed) == 1 and confirmed[0]['id'] == phase1['expectedSubmissionId'], 'Provider receipt was not preserved')
                        require(confirmed[0]['verdict'] == 'CORRECT', 'Final provider verdict did not synchronize')
                        require(confirmed[0]['elapsedMs'] >= TWO_HOURS, 'Submission elapsed time lost the two-hour VP anchor')
                        return value
                    h.step('independent_final_history_and_elapsed_time', history)
                    if args.scenario == 'accepted':
                        def account_mismatch_before_post():
                            from mvp_ui_probe import run_account_mismatch_probe
                            database = h.native_state / 'vp.sqlite3'
                            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                                before_operations = db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
                            original_account = fixture.account
                            try:
                                value = run_account_mismatch_probe(h.driver, h.results, source,
                                    switch_account=lambda account: setattr(fixture, 'account', account),
                                    get_post_count=lambda: fixture.post_count)
                                atomic_json(h.results / 'account-mismatch-outer.json', value)
                                require(value.get('status') == 'passed',
                                        'The actual pre-POST account mismatch/retry UI regression failed; inspect its report')
                                require(fixture.post_count == 1, 'A rejected account mismatch or cancelled retry emitted a code POST')
                                with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                                    after_operations = db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
                                    require(after_operations == before_operations,
                                            'A known pre-POST rejection created a native submission intent')
                                    operation_id = value.get('rejectedOperationId')
                                    require(operation_id and db.execute('SELECT COUNT(*) FROM operations WHERE operation_id=?',
                                                                       (operation_id,)).fetchone()[0] == 0,
                                            'The rejected UI operation unexpectedly entered the native send ledger')
                                return {**value, 'nativeOperationsBefore': before_operations,
                                        'nativeOperationsAfter': after_operations, 'nativeRejectedIntentCount': 0}
                            finally:
                                fixture.account = original_account
                        h.step('known_pre_post_account_mismatch_rejects_without_orphan_unknown_or_native_intent',
                               account_mismatch_before_post)
                    opened_board = h.step('original_rankland_open', lambda: h.call('rankland.open', {'sessionId': session['sessionId']}))

                    def read_prepared_url():
                        nonlocal session
                        original_start = session['startAt']
                        session = h.call('inspect_session', {'sessionId': session['sessionId']})
                        require(session.get('ranklandPrepared') is True, 'RankLand URL was not prepared before opening')
                        require(session['startAt'] == original_start, 'Preparing the board changed the local VP start')
                        offset = float(parse_qs(urlsplit(session['ranklandUrl']).query)['from'][0])
                        require(offset * 60000 >= TWO_HOURS, 'First late board open did not encode the two-hour offset')
                        # The UI probe captured its restart manifest before the
                        # first board open, when from was still a placeholder.
                        # Preserve the now-final URL for restart comparisons.
                        if phase1.get('restart_manifest'):
                            path = Path(phase1['restart_manifest'])
                            value = json.loads(path.read_text())
                            value['ranklandUrl'] = session['ranklandUrl']
                            atomic_json(path, value)
                        return session
                    prepared_board = h.step('first_late_scoreboard_open_freezes_durable_two_hour_url', read_prepared_url)

                    def rankland_sync():
                        value = h.call('rankland.sync', {'sessionId': session['sessionId']})
                        require(value.get('state') == 'ready', 'Original RankLand delivery requires attention: ' + str(value))
                        return value
                    sync_result = (h.step('original_rankland_form_automatic_sync', rankland_sync)
                                   if opened_board and prepared_board else
                                   h.skip('original_rankland_form_automatic_sync', 'original_rankland_open/prepared_url'))
                    before = (h.step('original_rankland_own_row_and_single_manual_record', lambda: h.rankland_snapshot(session, 'before-close'))
                              if sync_result is not None else
                              h.skip('original_rankland_own_row_and_single_manual_record', 'original_rankland_form_automatic_sync'))
                    rankland_verified = before is not None
                    if rankland_verified:
                        h.step('duplicate_original_rankland_tab_blocks_automatic_sync_without_changing_manual',
                               lambda: h.duplicate_rankland_guard(session))
                        h.step('concurrent_rankland_open_creates_one_full_identity_tab_and_preserves_manual',
                               lambda: h.concurrent_rankland_open(session, before))
                    else:
                        h.skip('duplicate_original_rankland_tab_blocks_automatic_sync_without_changing_manual',
                               'original_rankland_own_row_and_single_manual_record')
                        h.skip('concurrent_rankland_open_creates_one_full_identity_tab_and_preserves_manual',
                               'original_rankland_own_row_and_single_manual_record')
                    h.focus_ui()
                    manifest = phase1.get('restart_manifest')
            old_pid = first['pid']
            h.step('first_firefox_process_exit', h.quit_browser)
            second = h.step('second_firefox_same_persistent_profile', h.start_browser)
            if second:
                h.step('distinct_firefox_process_after_restart', lambda: require(second['pid'] != old_pid, 'Firefox PID did not change') or {'before': old_pid, 'after': second['pid']})
                second_install = h.step('product_extension_reinstall_persistent_path', h.install_extension)
                if second_install and manifest:
                    def resumed_ui():
                        result = resume_ui_probe(h.driver, manifest)
                        atomic_json(h.results / 'ui-phase2-outer.json', result)
                        require(result.get('status') == 'passed', 'UI did not restore after a real Firefox process restart')
                        return result
                    h.step('ui_session_receipt_and_verdict_restore_after_firefox_restart', resumed_ui)
                if second_install and session:
                    def restored_session():
                        result = h.call('inspect_session', {'sessionId': session['sessionId']})
                        require(result['startAt'] == session['startAt'] and result['ranklandUrl'] == session['ranklandUrl'], 'Session start or exact RankLand URL changed')
                        require(result['elapsedMs'] >= TWO_HOURS, 'Session clock restarted at zero')
                        return result
                    h.step('native_session_and_scoreboard_url_restore_after_firefox_restart', restored_session)
                    def repeat_sync():
                        value = h.call('rankland.sync', {'sessionId': session['sessionId']})
                        require(value.get('state') == 'ready' and all(item['state'] == 'synced' for item in value.get('results', [])),
                                'Repeated RankLand synchronization did not reuse its durable receipt')
                        return value
                    if rankland_verified:
                        reopened = h.step('original_rankland_reopen_after_firefox_restart', lambda: h.call('rankland.open', {'sessionId': session['sessionId']}))
                        restored_board = (h.step('original_rankland_manual_and_own_row_restore_after_firefox_restart',
                                                lambda: h.rankland_snapshot(session, 'after-firefox-restart'))
                                          if reopened is not None else
                                          h.skip('original_rankland_manual_and_own_row_restore_after_firefox_restart',
                                                 'original_rankland_reopen_after_firefox_restart'))
                        repeated = (h.step('repeat_sync_uses_receipt_without_duplicate_original_record', repeat_sync)
                                    if restored_board is not None else
                                    h.skip('repeat_sync_uses_receipt_without_duplicate_original_record',
                                           'original_rankland_manual_and_own_row_restore_after_firefox_restart'))
                        if repeated is not None:
                            h.step('rankland_single_record_after_repeat_sync', lambda: h.rankland_snapshot(session, 'after-repeat-sync'))
                        else:
                            h.skip('rankland_single_record_after_repeat_sync', 'repeat_sync_uses_receipt_without_duplicate_original_record')
                    else:
                        for name in ('original_rankland_reopen_after_firefox_restart',
                                     'original_rankland_manual_and_own_row_restore_after_firefox_restart',
                                     'repeat_sync_uses_receipt_without_duplicate_original_record',
                                     'rankland_single_record_after_repeat_sync'):
                            h.skip(name, 'original_rankland_form_automatic_sync/original_own_row')
                    h.focus_ui()
                if second_install and not args.skip_domjudge_reference:
                    def reference():
                        from mvp_ui_probe import capture_domjudge_reference
                        value = capture_domjudge_reference(h.driver, h.results)
                        require(value.get('status') == 'passed', 'Official DOMjudge reference capture failed; see its report')
                        return value
                    h.step('real_domjudge_reference_pages', reference, optional=True)
    except Exception as exc:
        h.summary['fatalError'] = {'type': type(exc).__name__, 'message': str(exc)[:2200], 'traceback': traceback.format_exc()[-4000:]}
    finally:
        h.phase = 'cleanup'
        h.flush()
        for name, fn in (('firefox', h.quit_browser), ('fixtureServer', lambda: fixture.shutdown() if fixture else None),
                         ('nativeManifest', h.cleanup_manifest)):
            try:
                h.summary['cleanup'][name] = {'status': 'passed', 'evidence': fn()}
            except Exception as exc:
                h.summary['cleanup'][name] = {'status': 'failed', 'errorType': type(exc).__name__}
            h.flush()
        def native_processes_stopped():
            deadline = time.monotonic() + 15
            live = []
            while time.monotonic() < deadline:
                live = []
                for path in Path('/proc').iterdir():
                    if not path.name.isdigit():
                        continue
                    try:
                        parts = (path / 'cmdline').read_bytes().split(b'\0')
                        if b'qojvp.native_host' in parts:
                            live.append(int(path.name))
                    except OSError:
                        continue
                if not live:
                    return {'liveNativeHelperCount': 0}
                time.sleep(0.1)
            require(not live, 'Native helper processes remained after Firefox closed: ' + str(live))
        h.step('all_native_helpers_exit_after_browser_shutdown', native_processes_stopped)
        if fixture:
            atomic_json(h.results / 'fixture-requests.json', fixture.requests)
            atomic_json(h.results / 'fixture-submissions.json', fixture.submissions)

            def server_check():
                require(not fixture.running, 'Fixture server did not stop')
                require(fixture.post_count == 1, 'Code POST count changed during reopening/restarting')
                return {'serverStopped': True, 'postCount': fixture.post_count, 'acceptedPostCount': fixture.accepted_post_count}
            h.step('final_fixture_post_count_and_shutdown', server_check)
        if (h.native_state / 'vp.sqlite3').is_file():
            def ledger_check():
                with sqlite3.connect((h.native_state / 'vp.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
                    require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'SQLite ledger is not intact')
                    counts = {'sessions': db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],
                              'operations': db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],
                              'submissions': db.execute('SELECT COUNT(*) FROM submissions').fetchone()[0]}
                    require(counts['sessions'] >= 1 and counts['operations'] == 1 and counts['submissions'] == 1,
                            'The durable ledger does not contain the single intended submission')
                    return {'quickCheck': 'ok', **counts}
            h.step('persistent_ledger_integrity_after_browser_shutdown', ledger_check)
        failed = [c['name'] for c in h.summary['checks'] if c['status'] == 'failed' and not c['optional']]
        skipped = [c['name'] for c in h.summary['checks'] if c['status'] == 'skipped' and not c['optional']]
        cleanup_failed = any(c['status'] != 'passed' for c in h.summary['cleanup'].values())
        h.summary.update(finishedAt=utc_now(), requiredFailures=failed, requiredSkipped=skipped,
                         status='failed' if failed or skipped or cleanup_failed or h.summary.get('fatalError') else 'passed')
        h.phase = 'finished'
        h.flush()
        print(json.dumps({'status': h.summary['status'], 'summary': str(h.results / 'summary.json')}))
    return 0 if h.summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
