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

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py'),
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
            'PYTHONPATH': ':'.join(str(self.project / p) for p in ('src', 'tests/browser/vendor_py', 'vendor/qoj-submitter')),
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
            for path in sorted((self.project / 'src/firefox').rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(self.project / 'src/firefox')))
        require((self.project / 'tests/browser/tools/geckodriver').is_file(), 'Guest geckodriver missing')
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
        service = Service(str(self.project / 'tests/browser/tools/geckodriver'), log_output=str(self.results / 'geckodriver.log'))
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
