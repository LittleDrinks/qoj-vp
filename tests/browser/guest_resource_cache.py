#!/usr/bin/env python3
"""Guest-only, isolated real Firefox/UI/cache download acceptance; GET-only OJ.

The fixture is synthetic and loopback-only. No real QOJ account, source submit,
official VP action, permanent native host, or user Firefox profile is touched.
Offline proof covers manifest/file reads in an already loaded contest context,
not a claim that the whole workbench can bootstrap without the judge.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py'),
               str(PROJECT / 'vendor/qoj-submitter')]

import guest_visual_parity as visual
from guest_preflight import atomic_json, process_exit, require, utc_now


def zipped(files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return result.getvalue()


class ResourceFixture(visual.VisualQojFixture):
    """Reuse the existing QOJ-shaped account/contest/form/history renderer."""
    def __init__(self, configuration):
        super().__init__(configuration)
        self.stopped = False
        self.a, self.b, self.c, self.d = [str(problem['probid']) for problem in self.problems[:4]]
        self.a_input, self.a_answer = b'1 2\n', b'3\n'
        # Deterministic incompressible-enough comment data makes the actual
        # cached ZIP exceed one native chunk. This file is never executed.
        self.interactor = (b'// SYNTHETIC INTERACTOR RESOURCE FIXTURE; NEVER EXECUTE\n/*\n' +
                           hashlib.shake_256(b'qoj-vp-resource-cache-fixture').hexdigest(300000).encode() + b'\n*/\n')
        self.packages = {self.a: zipped({'sample/input1.in': self.a_input, 'sample/input1.ans': self.a_answer}),
                         self.b: zipped({'tools/interactor.cpp': self.interactor})}
        self.expected = {self.a: {'samples-A/1.in': self.a_input, 'samples-A/1.ans': self.a_answer},
                         self.b: {'attachment-extras/problem-B/tools/interactor.cpp': self.interactor}}
        self.mixed_original = {'1.in': b'4 5\n', '1.ans': b'9\n',
                               'tools/interactor.py': b'# synthetic attachment; never executed\n'}
        self.packages[self.d] = zipped(self.mixed_original)
        self.mixed_expected = {
            'samples': {'samples-D/1.in': self.mixed_original['1.in'],
                        'samples-D/1.ans': self.mixed_original['1.ans']},
            'attachment': {'attachment-extras/problem-D/' + name: data
                           for name, data in self.mixed_original.items()},
        }

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def emit(self, status, body, kind):
                parsed = urlsplit(self.path)
                raw = parse_qs(parsed.query)
                owner.requests.append({'method': self.command, 'path': parsed.path, 'status': status,
                                       'query': {key: value for key, value in raw.items() if key in {'type', 'id', 'contest_id', 'page', 'submitter'}}})
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                if parsed.path == '/download.php' and query.get('type') == ['problem'] and query.get('contest_id') == ['3387']:
                    payload = owner.packages.get(query.get('id', [''])[0])
                    return self.emit(200 if payload else 404, payload or b'Unknown resource; absence is not established',
                                     'application/zip' if payload else 'text/plain')
                return self.emit(*owner.response(parsed.path, self.headers.get('X-Requested-With', '').lower() == 'xmlhttprequest'))

            do_HEAD = do_GET

            def do_POST(self):
                owner.post_count += 1
                self.emit(405, b'GET-only resource fixture; no body is read', 'text/plain')

            do_PUT = do_POST
            do_PATCH = do_POST
            do_DELETE = do_POST

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        if not self.stopped:
            super().shutdown()
            self.stopped = True


class ResourceHarness(visual.VisualHarness):
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.run_id = uuid.uuid4().hex
        # The inherited alias builder uses its module globals. Change those
        # only in this standalone QA process, never in any product file.
        visual.HOST = 'org.littledrinks.qoj_vp_resources_' + self.run_id
        visual.EXTENSION_ID = 'qoj-vp-resources-' + self.run_id + '@littledrinks.local'
        visual.OWNER = 'QOJ VP isolated resource cache QA native host v1'
        self.state = self.project / 'state/resource-cache' / self.run_id
        self.profile = self.state / 'firefox-profile'
        self.native_state = self.state / 'native'
        self.downloads = self.state / 'downloads'
        self.results = self.project / 'results/resource-cache' / self.run_id
        self.results.mkdir(parents=True, exist_ok=True)
        self.driver = None
        self.ui_handle = self.ui_url = None
        self.manifest_path = Path.home() / '.mozilla/native-messaging-hosts' / (visual.HOST + '.json')
        self.permanent_path = self.manifest_path.with_name('org.littledrinks.qoj_vp.json')
        self.permanent_before = self.permanent_path.read_bytes() if self.permanent_path.exists() else None
        self.manifest_before = None
        self.manifest_installed = False
        self.helper_pids = self.state / 'native-helper-pids'
        self.width, self.height = 1440, 1000
        self.phase = 'initializing'
        self.captures = {}
        self.summary = {'schema': 'qoj-vp-resource-cache-browser-v1', 'runId': self.run_id, 'startedAt': utc_now(),
                        'profile': str(self.profile), 'downloads': str(self.downloads), 'checks': [], 'cleanup': {},
                        'sourceFilesSelected': 0, 'realQojRequests': 'not-authorized-and-not-used',
                        'wholePageOfflineBootstrap': 'not-implemented-and-not-tested',
                        'offlineScope': 'Manifest and file reads after an online reload/selection retained the normal UI contest context.'}
        self.flush()

    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/resource-cache-summary.json', self.summary)
        atomic_json(self.project / 'results/resource-cache-status.json', {'runId': self.run_id, 'phase': self.phase,
                    'status': self.summary.get('status', 'running'), 'summary': str(self.results / 'summary.json'),
                    'checks': [{'name': check['name'], 'status': check['status']} for check in self.summary['checks']]})

    def start_browser(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        self.downloads.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        options.add_argument('-headless')
        options.add_argument('-profile')
        options.add_argument(str(self.profile))
        options.set_capability('unhandledPromptBehavior', 'ignore')
        preferences = {'browser.shell.checkDefaultBrowser': False, 'browser.startup.page': 0,
                       'browser.startup.homepage': 'about:blank', 'browser.sessionstore.resume_from_crash': False,
                       'browser.download.folderList': 2, 'browser.download.dir': str(self.downloads),
                       'browser.download.useDownloadDir': True, 'browser.download.alwaysOpenPanel': False,
                       'browser.download.manager.showWhenStarting': False,
                       'browser.helperApps.neverAsk.saveToDisk': 'application/zip,application/octet-stream'}
        for key, value in preferences.items():
            options.set_preference(key, value)
        service = Service(str(self.project / 'tests/browser/tools/geckodriver'), log_output=str(self.results / 'geckodriver.log'))
        self.driver = webdriver.Firefox(options=options, service=service)
        self.driver.set_page_load_timeout(45)
        self.driver.set_script_timeout(160)
        self.driver.set_window_size(self.width, self.height)
        capabilities = self.driver.capabilities
        require(Path(capabilities['moz:profile']).resolve() == self.profile, 'Firefox did not use the isolated resource profile')
        require(capabilities.get('moz:headless') is True, 'The resource browser is not headless')
        return {'pid': capabilities['moz:processID'], 'version': capabilities['browserVersion'],
                'headless': True, 'profileCopied': False, 'downloadDirectory': str(self.downloads)}

    def ui_state(self):
        self.focus_ui()
        return self.driver.execute_script('return window.qojVpUi.getState();')

    def enter_jury(self, session_id):
        from selenium.webdriver.common.by import By
        self.focus_ui()
        team_link = self.driver.find_element(By.ID, 'nav-jury')
        if team_link.is_displayed():
            team_link.click()
        else:
            self.driver.find_element(By.ID, 'nav-contests').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-list-view').is_displayed(), 'Jury contest list')
        self.driver.find_element(By.CSS_SELECTOR, f'[data-jury-session="{session_id}"]').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-detail-view').is_displayed() and
                  self.ui_state()['session']['sessionId'] == session_id and self.ui_state().get('contest'),
                  'selected Jury contest details')

    def enter_team(self):
        from selenium.webdriver.common.by import By
        link = self.driver.find_element(By.ID, 'nav-team')
        if link.is_displayed():
            link.click()
        self.wait(lambda: self.driver.find_element(By.ID, 'home-view').is_displayed(), 'Team Home')

    def prepared_entry(self, pid):
        state = self.ui_state()
        return next((entry for entry in state.get('resources', []) if entry.get('problemId') == pid), None)

    def prepare_one(self, index, pid, expected_status, expected_kind=None, *, interactive=False):
        from selenium.webdriver.common.by import By
        self.wait_resource_modal()
        rows = self.driver.find_elements(By.CSS_SELECTOR, '#resources-list tr')
        require(len(rows) == 12, 'The real preparation modal does not contain all twelve fixture problems')
        if interactive:
            rows[index].find_element(By.CSS_SELECTOR, 'input[type=checkbox]').click()
            rows = self.driver.find_elements(By.CSS_SELECTOR, '#resources-list tr')
        rows[index].find_element(By.CSS_SELECTOR, '[data-prepare-problem]').click()
        self.wait(lambda: (entry := self.prepared_entry(pid)) and entry.get('status') == expected_status and
                  not self.ui_state().get('resourcePreparing'), 'single-problem preparation result', timeout=60)
        entry = self.prepared_entry(pid)
        require(entry.get('kind') == expected_kind, 'Prepared resource kind differs from its actual fixture contents')
        require(self.ui_state()['session'].get('startAt') is None, 'Resource preparation started the local timer')
        return {key: entry[key] for key in ('problemId', 'status', 'kind', 'resourceId', 'filename', 'totalBytes', 'sha256', 'sampleCount', 'pairCount', 'sampleSource', 'lastAttempt', 'downloads') if key in entry}

    def wait_resource_modal(self):
        return self.wait(lambda: self.driver.execute_script('''
          const modal=document.getElementById('resources-modal'),state=window.qojVpUi?.getState();
          const instance=window.bootstrap?.Modal?.getInstance(modal);
          return !!state?.resourcesLoaded && state.resourceReading===false && !state.resourcePreparing &&
            !!instance?._isShown && instance._isTransitioning===false &&
            document.querySelectorAll('#resources-list tr').length===12;
        '''), 'completed resource manifest read and real Bootstrap shown transition')

    def download_one(self, pid, expected, kind=None):
        from selenium.webdriver.common.by import By
        before = {path.name for path in self.downloads.iterdir()}
        selector = f'#problems-list [data-resource-problem="{pid}"]'
        if kind:
            selector += f'[data-resource-kind="{kind}"]'
        self.driver.find_element(By.CSS_SELECTOR, selector).click()

        def saved():
            error = self.driver.find_element(By.ID, 'resources-error')
            require(not error.is_displayed(), 'The real UI reported a resource download error: ' + error.text[:240])
            candidates = [path for path in self.downloads.iterdir() if path.name not in before and path.is_file() and not path.name.endswith('.part')]
            for path in candidates:
                if zipfile.is_zipfile(path):
                    return path
            return None
        downloaded = self.wait(saved, 'real Firefox cached ZIP download', timeout=60)
        entry = self.prepared_entry(pid)
        if kind:
            choices = [item for item in entry.get('downloads', []) if item['kind'] == kind]
            require(len(choices) == 1, 'Manifest did not identify the selected independent download')
            entry = choices[0]
        payload = downloaded.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == entry['sha256'] and len(payload) == entry['totalBytes'],
                'Downloaded ZIP differs from its verified resource manifest')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            require(set(archive.namelist()) == set(expected), 'Downloaded resource paths differ from CLI organization')
            require(all(archive.read(name) == data for name, data in expected.items()), 'Downloaded sample/interactor bytes changed')
        return {'problemId': pid, 'kind': kind or entry['kind'], 'downloadedFile': downloaded.name,
                'bytes': len(payload), 'sha256': entry['sha256'],
                'members': [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in expected.items()],
                'originalBytesVerified': True, 'nativeChunksRequired': (len(payload) + 262143) // 262144}

    def cards(self, fixture):
        self.focus_ui()
        value = self.driver.execute_script('''
          return [...document.querySelectorAll('#problems-list .card')].map(card=>({
            label:card.querySelector('.problem-badge')?.textContent.trim(),
            resources:[...card.querySelectorAll('[data-resource-problem]')].map(link=>({
              problemId:link.dataset.resourceProblem,kind:link.dataset.resourceKind,
              label:link.textContent.trim(),href:link.getAttribute('href'),role:link.getAttribute('role')}))}));
        ''')
        require(len(value) == 12, 'The real Problemset has a different card count')
        require(value[0]['resources'] == [{'problemId': fixture.a, 'kind': 'samples', 'label': 'samples', 'href': None, 'role': 'button'}], 'A is not a cache-only samples control')
        require(value[1]['resources'] == [{'problemId': fixture.b, 'kind': 'attachment', 'label': '附件', 'href': None, 'role': 'button'}], 'B extras are mislabeled as samples')
        require(value[3]['resources'] == [
            {'problemId': fixture.d, 'kind': 'samples', 'label': 'samples', 'href': None, 'role': 'button'},
            {'problemId': fixture.d, 'kind': 'attachment', 'label': '附件', 'href': None, 'role': 'button'},
        ], 'D must expose independent samples and attachment buttons')
        require(all(not card['resources'] for i, card in enumerate(value) if i not in (0, 1, 3)),
                'An unknown resource is advertised as downloadable')
        return value

    def observe_judge_requests(self, origin):
        self.driver.execute_script('''
          window.__resourceCacheObservedRequests=[];
          window.__resourceCacheRequestObserver=details=>{
            const url=new URL(details.url);
            window.__resourceCacheObservedRequests.push({method:details.method,origin:url.origin,path:url.pathname});
          };
          browser.webRequest.onBeforeRequest.addListener(window.__resourceCacheRequestObserver,
            {urls:[arguments[0]+'/*','https://qoj.ac/*']});
        ''', origin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--configuration', type=Path)
    args = parser.parse_args()
    harness = ResourceHarness(args.project)
    fixture = None
    try:
        configuration_path = args.configuration or harness.project / 'tests/browser/visual-reference/rendered/configuration.json'
        configuration = json.loads(configuration_path.read_text())
        fixture = ResourceFixture(configuration).start()
        setup = harness.step('isolated_alias_product_bytes_and_native_host', lambda: harness.setup_visual(fixture))
        require(setup is not None, 'The isolated resource alias could not be prepared')
        require(harness.step('headless_firefox_and_private_download_preferences', harness.start_browser) is not None, 'Firefox did not start')
        require(harness.step('temporary_resource_alias_install', harness.install_extension) is not None, 'Temporary alias did not install')
        hello = harness.call('hello')
        require(hello.get('fixture') is True, 'Native requests are not confined to the synthetic judge')
        account = harness.call('qoj_contest', {'contestId': '3387'})
        session = harness.call('create_session', {'contestId': '3387', 'title': 'Resource cache fixture',
                                                'account': account['account'], 'durationMs': 18000000})
        # These names belong to the inherited readiness helper. Both refer to
        # the one actually PREPARED session; neither starts any timer or VP.
        harness.running_session_id = harness.prepared_session_id = session['sessionId']
        harness.driver.refresh()
        require(harness.step('prepared_session_ui_boot_and_manifest_load', harness.wait_boot_ready) is not None, 'UI bootstrap did not finish')
        harness.select_visual_session(session['sessionId'])
        from selenium.webdriver.common.by import By
        harness.enter_jury(session['sessionId'])
        harness.driver.find_element(By.ID, 'open-resources').click()
        harness.wait(lambda: harness.driver.find_element(By.ID, 'resources-modal').is_displayed(), 'normal resource preparation modal')
        require(harness.step('real_ui_prepare_ordinary_paired_samples', lambda: harness.prepare_one(0, fixture.a, 'ready', 'samples')) is not None, 'A sample preparation failed')
        require(harness.step('real_ui_prepare_extras_only_interactor', lambda: harness.prepare_one(1, fixture.b, 'ready', 'attachment', interactive=True)) is not None, 'B attachment preparation failed')
        require(harness.step('real_ui_404_stays_unknown', lambda: harness.prepare_one(2, fixture.c, 'unknown')) is not None, 'C did not preserve uncertainty')
        require(harness.step('real_ui_prepare_samples_and_interactor', lambda: harness.prepare_one(3, fixture.d, 'ready', 'attachment', interactive=True)) is not None,
                'D mixed resource preparation failed')
        harness.close_modal('extension', 'resources-online')
        harness.enter_team()
        harness.driver.find_element(By.ID, 'nav-problems').click()
        harness.wait(lambda: harness.driver.find_element(By.ID, 'problems-view').is_displayed(), 'normal Problemset route')
        harness.step('ready_samples_attachment_and_unknown_card_labels', lambda: harness.cards(fixture))
        for name, pid in [('samples', fixture.a), ('attachment', fixture.b)]:
            harness.step('real_ui_download_' + name + '_and_verify_original_zip_bytes', lambda pid=pid: harness.download_one(pid, fixture.expected[pid]))
        for kind in ('samples', 'attachment'):
            harness.step('real_ui_download_mixed_' + kind + '_separately',
                         lambda kind=kind: harness.download_one(fixture.d, fixture.mixed_expected[kind], kind))
        harness.driver.save_screenshot(str(harness.results / 'resource-problemset.png'))

        def offline_recovery():
            # Reload/normal selection happens ONLINE because the current page
            # bootstrap still obtains its contest table from the judge.
            harness.driver.refresh()
            harness.wait_boot_ready()
            harness.select_visual_session(session['sessionId'])
            require(harness.ui_state().get('resourcesLoaded') is True, 'Reload did not restore the cached manifest')
            harness.driver.find_element(By.ID, 'nav-home').click()
            harness.observe_judge_requests(fixture.origin)
            online_request_count = len(fixture.requests)
            fixture.shutdown()
            # Recreate a version-0.2.0 combined-only record in this test's own
            # cache. Remove the derived objects so the real manifest task must
            # migrate the verified old ZIP while the judge is offline.
            from qojvp.resources import ResourceCache
            cache = ResourceCache(harness.native_state)
            manifest_path = cache.scope_path(session, fixture.d) / 'manifest.json'
            legacy = json.loads(manifest_path.read_text())
            entry = legacy['entry']
            derived = entry.pop('downloads', [])
            require({item['kind'] for item in derived} == {'samples', 'attachment'},
                    'Mixed fixture did not produce two independent resources before legacy replay')
            for item in derived:
                if item['resourceId'] != entry['resourceId']:
                    cache.object_path(session, fixture.d, item).unlink()
            cache.atomic_write(manifest_path, json.dumps(legacy).encode())
            # This is the same ordinary, read-only manifest task used by the
            # modal. Check its completed response explicitly; an already true
            # resourcesLoaded flag alone cannot prove a fresh offline read.
            restored = harness.call('resource_manifest', {'sessionId': session['sessionId']})
            restored_entries = {entry['problemId']: entry for entry in restored['problems']}
            require(restored_entries[fixture.a]['kind'] == 'samples' and restored_entries[fixture.b]['kind'] == 'attachment' and
                    restored_entries[fixture.c]['status'] == 'unknown', 'Completed offline manifest read changed resource facts')
            require({item['kind'] for item in restored_entries[fixture.d].get('downloads', [])} == {'samples', 'attachment'},
                    'The real offline manifest task did not migrate the old combined resource')
            harness.enter_jury(session['sessionId'])
            harness.driver.find_element(By.ID, 'open-resources').click()
            harness.wait_resource_modal()
            harness.wait(lambda: not harness.driver.find_element(By.ID, 'resources-error').is_displayed(), 'successful offline manifest read')
            require(harness.ui_state().get('resourcesLoaded') is True, 'Offline manifest is unavailable')
            harness.close_modal('extension', 'resources-offline')
            harness.enter_team()
            harness.driver.find_element(By.ID, 'nav-problems').click()
            harness.cards(fixture)
            downloads = [harness.download_one(pid, fixture.expected[pid]) for pid in (fixture.a, fixture.b)]
            downloads.extend(harness.download_one(fixture.d, fixture.mixed_expected[kind], kind)
                             for kind in ('samples', 'attachment'))
            observed = harness.driver.execute_script('return window.__resourceCacheObservedRequests;')
            require(observed == [], 'A judge request was attempted during offline manifest/file reads: ' + json.dumps(observed))
            require(len(fixture.requests) == online_request_count, 'A new request reached the stopped judge fixture')
            require(fixture.stopped and fixture.post_count == 0, 'The fixture was not stopped or received a POST')
            return {'onlineReloadAndNormalSelectionCompleted': True, 'cachedUiContextRetained': True,
                    'fixtureServerStopped': True, 'newJudgeRequestsObserved': observed, 'newFixtureRequests': 0,
                    'completedOfflineManifestRead': True,
                    'combinedLegacyCacheMigratedWithoutNetwork': True,
                    'downloads': downloads, 'wholePageOfflineBootstrap': 'not-implemented-and-not-tested'}
        harness.step('reload_manifest_then_server_offline_real_ui_downloads', offline_recovery)
    except Exception as error:
        harness.summary['fatalError'] = {'type': type(error).__name__, 'message': str(error)[:1400]}
    finally:
        for name, action in [('firefox', harness.quit_browser), ('fixtureServer', lambda: fixture.shutdown() if fixture else None),
                             ('ownedAliasAndPermanentHost', harness.cleanup_manifest)]:
            try:
                harness.summary['cleanup'][name] = {'status': 'passed', 'evidence': action()}
            except Exception as error:
                harness.summary['cleanup'][name] = {'status': 'failed', 'errorType': type(error).__name__}
            harness.flush()

        def safety():
            require(fixture is not None and fixture.post_count == 0, 'A POST reached the GET-only resource fixture')
            pids = sorted(set(int(line) for line in harness.helper_pids.read_text().splitlines())) if harness.helper_pids.exists() else []
            return {'qojPostCount': fixture.post_count, 'sourceFilesSelected': 0,
                    'nativeHelperExits': [process_exit(pid, timeout=12) for pid in pids],
                    'permanentHostUnchanged': (harness.permanent_path.read_bytes() if harness.permanent_path.exists() else None) == harness.permanent_before}
        harness.step('zero_qoj_posts_and_all_owned_helpers_exit', safety)
        try:
            require(harness.summary['cleanup']['firefox']['status'] == 'passed', 'Keep the owned profile until browser exit is confirmed')
            require(harness.profile.parent == harness.state and harness.profile.resolve().is_relative_to(harness.project / 'state/resource-cache'), 'Refusing to clean an unowned profile')
            if harness.profile.exists():
                shutil.rmtree(harness.profile)
            harness.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'passed', 'userProfileAccessed': False}
        except Exception as error:
            harness.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'failed', 'errorType': type(error).__name__}
        if fixture:
            atomic_json(harness.results / 'qoj-fixture-requests.json', fixture.requests)
        failed = [check['name'] for check in harness.summary['checks'] if check['status'] != 'passed']
        harness.summary.update(finishedAt=utc_now(), requiredFailures=failed,
                               status='failed' if failed or harness.summary.get('fatalError') or any(value['status'] != 'passed' for value in harness.summary['cleanup'].values()) else 'passed')
        harness.phase = 'finished'
        harness.flush()
        print(json.dumps({'status': harness.summary['status'], 'summary': str(harness.results / 'summary.json')}))
    return 0 if harness.summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
