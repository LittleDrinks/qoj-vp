#!/usr/bin/env python3
"""VM Firefox comparison against original DOMjudge 9.0.1 rendering.

Supports a real reference service or hash-verified official-server-rendered
snapshots with their original assets. This script does not claim pixel equality;
it emits raw PNGs, strict computed-style comparisons and visible-field checks.
QOJ is a local GET-only display fixture. No source file is ever selected.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import shlex
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'preflight'), str(PROJECT / 'preflight/vendor_py'),
               str(PROJECT / 'vendor/qoj-submitter')]

from guest_mvp import MvpHarness
from guest_preflight import atomic_json, process_exit, require, utc_now

HOST = 'org.littledrinks.qoj_vp_visual'
EXTENSION_ID = 'qoj-vp-visual@littledrinks.local'
OWNER = 'QOJ VP isolated visual parity native host v1'
STYLE_PROPERTIES = (
    'color', 'background-color', 'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width',
    'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
    'font-size', 'font-family', 'font-weight', 'font-style', 'line-height',
    'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    'border-top-left-radius', 'border-top-right-radius', 'border-bottom-left-radius', 'border-bottom-right-radius',
    'opacity', 'width', 'height',
)


def compare_component_captures(captures):
    """Exact CSS values decide CSS parity; raw rectangles remain evidence."""
    differences, bounding_differences = [], []
    for name in ('cardSubmit', 'statement', 'samples', 'navbarSubmit', 'modalSubmit'):
        for state in ('normal', 'hover', 'active', 'disabled'):
            original = captures['reference'].get(name, {}).get(state)
            product = captures['extension'].get(name, {}).get(state)
            if original is None or product is None:
                missing = {'component': name, 'state': state, 'property': 'capture',
                           'reference': bool(original), 'extension': bool(product)}
                differences.append(missing)
                bounding_differences.append(missing)
                continue
            for key in STYLE_PROPERTIES:
                if original['computed'][key] != product['computed'][key]:
                    differences.append({'component': name, 'state': state, 'property': key,
                                        'reference': original['computed'][key], 'extension': product['computed'][key]})
            if original['dimensions'] != product['dimensions']:
                bounding_differences.append({'component': name, 'state': state, 'property': 'boundingDimensions',
                                            'reference': original['dimensions'], 'extension': product['dimensions']})
    return {'computedEqual': not differences, 'computedStylePropertiesEqual': not differences,
            'computedDifferences': differences,
            'computedDimensionsEqual': not any(row['property'] in {'capture', 'width', 'height'} for row in differences),
            'rawBoundingDimensionsExactlyEqual': not bounding_differences,
            'rawBoundingDifferences': bounding_differences,
            'dimensionComparisonMethod': 'Exact getComputedStyle width/height strings; raw DOMRect differences retained separately without rounding or tolerance',
            'rawBoundingDimensionsAffectCssVerdict': False}


class ReadOnlyServer:
    def __init__(self):
        self.requests = []
        self.post_count = 0
        self.server = self.thread = None

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def response(self, path, xhr):
        raise NotImplementedError

    def response_request(self, raw_path, xhr):
        return self.response(urlsplit(raw_path).path, xhr)

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def emit(self, status, body, content_type):
                owner.requests.append({'method': self.command, 'path': urlsplit(self.path).path, 'status': status})
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def do_GET(self):
                status, body, kind = owner.response_request(self.path,
                    self.headers.get('X-Requested-With', '').lower() == 'xmlhttprequest')
                self.emit(status, body, kind)

            do_HEAD = do_GET

            def do_POST(self):
                # Never parse or save source, credentials, cookies or CSRF.
                owner.post_count += 1
                self.emit(405, b'Read-only visual parity fixture', 'text/plain')

            do_PUT = do_POST
            do_PATCH = do_POST
            do_DELETE = do_POST

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(5)
        require(not self.thread or not self.thread.is_alive(), 'Visual fixture server did not stop')


class SnapshotReference(ReadOnlyServer):
    """Serve literal server captures; never synthesize a version/business API."""
    def __init__(self, directory):
        super().__init__()
        self.root = Path(directory).resolve()
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        require(self.manifest.get('providerVersion') == '9.0.1', 'Frozen reference is not DOMjudge 9.0.1')
        self.verified = []
        for name, item in self.manifest['captures'].items():
            self.verify(name + '.html', item)
        asset_metadata = self.manifest.get('offlineResources', 'site-assets-manifest.json')
        asset_name = asset_metadata.get('manifest') if isinstance(asset_metadata, dict) else asset_metadata
        asset_manifest = self.root / asset_name
        require(asset_manifest.resolve().is_relative_to(self.root), 'Asset manifest escaped the snapshot directory')
        self.asset_manifest = json.loads(asset_manifest.read_text())
        require(self.asset_manifest.get('providerVersion') == '9.0.1', 'Assets are not from the same official version')
        self.assets = self.asset_manifest['resources']
        for item in self.assets.values():
            self.verify(item['mirrorPath'], item)

    def verify(self, relative, item):
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root), 'Snapshot path escaped its directory')
        data = path.read_bytes()
        require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
                'Frozen reference hash mismatch: ' + relative)
        self.verified.append({'path': relative, 'bytes': len(data), 'sha256': item['sha256']})

    def response(self, path, xhr):
        pages = {'/team': 'home', '/team/': 'home', '/team/problems': 'problemset',
                 '/team/submit': 'submit-modal-generic' if xhr else 'submit-page',
                 '/team/submit/4': 'submit-modal-a'}
        if path in pages:
            return 200, (self.root / (pages[path] + '.html')).read_bytes(), 'text/html; charset=utf-8'
        if path in self.assets:
            item = self.assets[path]
            return 200, (self.root / item['mirrorPath']).read_bytes(), item.get('contentType', 'application/octet-stream')
        # Timers/updates may request live endpoints. A snapshot cannot provide
        # their authoritative responses, and does not fake them for the test.
        return 404, b'Not captured from original service', 'text/plain'


class VisualQojFixture(ReadOnlyServer):
    def __init__(self, configuration):
        super().__init__()
        self.configuration = configuration
        self.problems = configuration['problems']
        require(len(self.problems) == 12, 'Visual configuration must contain the original twelve Xian problems')
        self.ids = {str(p['probid']): p for p in self.problems}
        self.account = configuration['team']['id']
        self.resource_gets = []
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('synthetic-visual-example.in', b'1 2\n')
            archive.writestr('synthetic-visual-example.ans', b'3\n')
        self.sample_archive = output.getvalue()

    def response_request(self, raw_path, xhr):
        parsed = urlsplit(raw_path)
        if parsed.path == '/download.php':
            query = parse_qs(parsed.query)
            pid = query.get('id', [''])[0]
            if query.get('type') == ['problem'] and query.get('contest_id') == ['3387'] and pid in self.ids:
                self.resource_gets.append({'problemId': pid, 'bytes': len(self.sample_archive),
                                           'sha256': hashlib.sha256(self.sample_archive).hexdigest()})
                return 200, self.sample_archive, 'application/zip'
            return 404, b'Unknown synthetic resource request', 'text/plain'
        return self.response(parsed.path, xhr)

    def response(self, path, xhr):
        kind = 'text/html; charset=utf-8'
        if path == '/':
            account = html.escape(self.account)
            body = ('<ul class="nav nav-pills float-right"><li class="nav-item dropdown">'
                    '<a class="nav-link dropdown-toggle" href="//qoj.ac/user/profile/' + account + '">' + account + '</a>'
                    '<ul class="dropdown-menu"><li><a href="//qoj.ac/user/profile/' + account + '">个人信息</a></li></ul></li>'
                    '<li class="nav-item"><a href="//qoj.ac/logout">退出登录</a></li></ul>')
            return 200, body.encode(), kind
        if path == '/contest/3387':
            title = html.escape(self.configuration['contest']['name'])
            rows = ''.join('<tr><td>' + html.escape(p['label']) + '</td><td><a href="/contest/3387/problem/' + str(p['probid']) + '">'
                           + html.escape(p['title']) + '</a></td></tr>' for p in self.problems)
            return 200, ('<title>' + title + ' - Dashboard - Contest - QOJ.ac</title><table>' + rows + '</table>').encode(), kind
        if path == '/contest/3387/submissions':
            return 200, b'<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Time</th></tr></thead><tbody></tbody></table>', kind
        if path.startswith('/contest/3387/problem/'):
            pid = path.split('/')[4]
            if pid in self.ids:
                return 200, ('<article class="uoj-article top-buffer-md"><h2>' + html.escape(self.ids[pid]['title']) + '</h2></article>'
                    '<form id="form-answer" method="post"><input name="_token" value="visual-fixture-only">'
                    '<select name="answer_answer_language"><option value="C++20">C++20</option><option value="Python3">Python3</option></select>'
                    '</form>').encode(), kind
        return 404, b'No visual fixture route', 'text/plain'


class VisualHarness(MvpHarness):
    def __init__(self, project, width, height):
        self.project = Path(project).resolve()
        self.run_id = uuid.uuid4().hex
        self.state = self.project / 'state/visual-parity' / self.run_id
        self.profile = self.state / 'firefox-profile'
        self.native_state = self.state / 'native'
        self.results = self.project / 'results/visual-parity' / self.run_id
        self.results.mkdir(parents=True, exist_ok=True)
        self.driver = None
        self.ui_handle = self.ui_url = None
        self.manifest_path = Path.home() / '.mozilla/native-messaging-hosts' / (HOST + '.json')
        self.permanent_path = self.manifest_path.with_name('org.littledrinks.qoj_vp.json')
        self.permanent_before = self.permanent_path.read_bytes() if self.permanent_path.exists() else None
        self.manifest_before = None
        self.manifest_installed = False
        self.phase = 'initializing'
        self.width, self.height = width, height
        self.helper_pids = self.state / 'native-helper-pids'
        self.captures = {'reference': {}, 'extension': {}}
        self.summary = {'schema': 'qoj-vp-visual-parity-v1', 'runId': self.run_id, 'startedAt': utc_now(),
                        'profile': str(self.profile), 'checks': [], 'cleanup': {}, 'sourceFilesSelected': 0,
                        'pixelEquality': 'not-assessed-raw-PNG-artifacts-only', 'stylePropertyAllowlist': STYLE_PROPERTIES,
                        'disabledStateMethod': 'Product card/navbar use a real prepared local session; remaining controls/reference use explicit validated CSS state probes'}
        self.flush()

    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/visual-parity-summary.json', self.summary)
        atomic_json(self.project / 'results/visual-parity-status.json', {'runId': self.run_id, 'phase': self.phase,
            'status': self.summary.get('status', 'running'), 'summary': str(self.results / 'summary.json'),
            'checks': [{'name': c['name'], 'status': c['status']} for c in self.summary['checks']]})

    def setup_visual(self, fixture):
        self.native_state.mkdir(parents=True, exist_ok=True)
        self.profile.mkdir(parents=True, exist_ok=True)
        clone = self.state / 'extension'
        changes = []
        byte_manifest = []
        for source in sorted((self.project / 'extension').rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(self.project / 'extension')
            data = original = source.read_bytes()
            if str(relative) == 'manifest.json':
                require(data.count(b'qoj-vp@littledrinks.local') == 1, 'Unexpected extension ID declarations')
                data = data.replace(b'qoj-vp@littledrinks.local', EXTENSION_ID.encode())
            elif str(relative) == 'background.js':
                require(data.count(b'"org.littledrinks.qoj_vp"') == 1, 'Unexpected native host declarations')
                data = data.replace(b'"org.littledrinks.qoj_vp"', ('"' + HOST + '"').encode())
            target = clone / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if data != original:
                changes.append(str(relative))
            require(data == original or str(relative) in {'manifest.json', 'background.js'}, 'Unexpected product byte changes')
            byte_manifest.append({'path': str(relative), 'sourceSha256': hashlib.sha256(original).hexdigest(),
                                  'aliasSha256': hashlib.sha256(data).hexdigest(), 'changed': data != original})
        require(changes == ['background.js', 'manifest.json'], 'Only the two namespace files may differ')
        atomic_json(self.results / 'alias-byte-verification.json', byte_manifest)
        launcher = self.native_state / 'launcher.sh'
        env = {'PYTHONPATH': ':'.join(str(self.project / p) for p in ('', 'preflight/vendor_py', 'vendor/qoj-submitter')),
               'QOJ_VP_STATE_DIR': str(self.native_state), 'QOJ_VP_QOJ_PATH': str(self.project / 'vendor/qoj-submitter'),
               'QOJ_VP_FIXTURE_ORIGIN': fixture.origin}
        launcher.write_text('#!/bin/sh\n' + ''.join('export ' + k + '=' + shlex.quote(v) + '\n' for k, v in env.items())
            + 'printf \'%s\\n\' "$$" >> ' + shlex.quote(str(self.helper_pids)) + '\n'
            + 'exec /usr/bin/python3 -B -m qojvp.native_host\n')
        launcher.chmod(0o700)
        if self.manifest_path.exists():
            old = json.loads(self.manifest_path.read_text())
            require(old.get('description') == OWNER and Path(old.get('path', '')).is_relative_to(self.project / 'state/visual-parity'),
                    'Refusing to overwrite an alias manifest not owned by this visual harness')
            self.manifest_before = self.manifest_path.read_bytes()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.manifest_path, {'name': HOST, 'description': OWNER, 'path': str(launcher), 'type': 'stdio',
                                      'allowed_extensions': [EXTENSION_ID]})
        self.manifest_installed = True
        self.addon = self.state / 'visual.xpi'
        with zipfile.ZipFile(self.addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(clone.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(clone)))
        return {'aliasHost': HOST, 'aliasExtensionId': EXTENSION_ID, 'onlyNamespaceDifferences': changes,
                'productBytesOtherwiseUnchanged': True, 'verifiedFileCount': len(byte_manifest),
                'byteManifest': str(self.results / 'alias-byte-verification.json')}

    def start_browser(self):
        evidence = super().start_browser()
        self.driver.set_window_size(self.width, self.height)
        evidence['viewport'] = self.driver.execute_script('return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio};')
        return evidence

    def install_extension(self):
        result = self.driver.execute('INSTALL_ADDON', {'path': str(self.addon), 'temporary': True})['value']
        require(result == EXTENSION_ID, 'Visual alias installation returned a different extension')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                url = self.driver.current_url
                if url.startswith('moz-extension://') and urlsplit(url).path == '/ui.html':
                    if self.driver.execute_script('return !!window.qojVpUi && window.qojVpUi.getState().connected;'):
                        self.ui_handle, self.ui_url = handle, url
                        return {'extensionId': result, 'temporary': True, 'installation': 'persistent-path'}
            time.sleep(.1)
        raise AssertionError('Visual alias workbench did not connect')

    def cleanup_manifest(self):
        if self.manifest_installed:
            current = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else None
            require(current is None or (current.get('description') == OWNER and current.get('path') == str(self.native_state / 'launcher.sh')),
                    'Alias manifest ownership changed')
            if self.manifest_before is None:
                self.manifest_path.unlink(missing_ok=True)
            else:
                self.manifest_path.write_bytes(self.manifest_before)
        actual = self.permanent_path.read_bytes() if self.permanent_path.exists() else None
        require(actual == self.permanent_before, 'The permanent production native host manifest changed')
        return {'permanentHostUnchanged': True, 'ownedAliasCleaned': True}

    def wait(self, predicate, description, timeout=35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.1)
        raise AssertionError('Timed out waiting for ' + description)

    def fonts(self):
        self.driver.execute_async_script('const done=arguments[arguments.length-1];document.fonts.ready.then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>done(true))));')

    def pointer(self, x, y, action=None):
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        actions = ActionBuilder(self.driver, mouse=PointerInput('mouse', 'visual-parity-pointer'))
        actions.pointer_action.move_to_location(int(x), int(y))
        if action == 'down':
            actions.pointer_action.pointer_down()
        elif action == 'up':
            actions.pointer_action.pointer_up()
        actions.perform()

    def reset_pointer(self):
        """Release real input state and clear Firefox's sticky :active chain."""
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        ActionBuilder(self.driver).clear_actions()
        # A neutral click clears a stale active ancestor without dismissing a
        # modal or activating a navigation/source-send control.
        neutral = self.driver.execute_script('''
          const header=document.querySelector('.modal.show .modal-header');
          if(header){const r=header.getBoundingClientRect();return {x:r.x+8,y:r.y+8};}
          return {x:1,y:1};
        ''')
        self.pointer(neutral['x'], neutral['y'], 'down')
        self.pointer(neutral['x'], neutral['y'], 'up')
        self.pointer(1, 1)
        self.driver.execute_script('if(document.activeElement?.blur)document.activeElement.blur();window.getSelection()?.removeAllRanges();')

    def select_visual_session(self, session_id):
        result = self.driver.execute_async_script('''
          const targetId=arguments[0],done=arguments[arguments.length-1];
          const before=window.qojVpUi.getState();
          const snapshot=()=>{const s=window.qojVpUi.getState();return {
            selectedSessionId:s.session?.sessionId||null,connected:s.connected,
            problemCount:s.contest?.problemCount??null,lastError:s.lastError||null,
            refreshDisabled:document.getElementById('refresh-submissions')?.disabled,
            refreshStatus:document.getElementById('refresh-status')?.textContent.trim()};};
          Promise.resolve(window.qojVpUi.selectSession(targetId)).then(()=>{
            const after=snapshot();done({ok:after.selectedSessionId===targetId&&after.problemCount===12&&!after.lastError,
              targetId,beforeSessionId:before.session?.sessionId||null,after});
          },error=>done({ok:false,targetId,after:snapshot(),rejection:{name:error.name,
            code:error.code||null,message:String(error.message||'').slice(0,250)}}));
        ''', session_id)
        self.summary.setdefault('sessionSelectionObservations', []).append(result)
        self.flush()
        require(isinstance(result, dict) and result.get('ok') is True,
                'The one normal UI session-selection RPC did not finish: ' + json.dumps(result, ensure_ascii=False))
        self.fonts()

    def wait_boot_ready(self):
        """Wait for initialize/listSessions to finish before one selection RPC.

        connected becomes true immediately after hello. initialize then calls
        listSessions/selectSession, whose generation guard can supersede an
        early external selection. These are read-only observations, not retries
        of the selection request or patches to the product initialization.
        """
        observations = []
        stable_since = None
        last_signature = None
        required_ids = {self.running_session_id, self.prepared_session_id}

        def ready():
            nonlocal stable_since, last_signature
            value = self.driver.execute_script('''
              const s=window.qojVpUi?.getState(),menu=document.getElementById('session-select');
              return {connected:!!s?.connected,selectedSessionId:s?.session?.sessionId||null,
                problemCount:s?.contest?.problemCount??null,lastError:s?.lastError||null,
                optionIds:menu?[menu.dataset.currentContest,...menu.querySelectorAll('[data-session-id]')].map(value=>typeof value==='string'?value:value.dataset.sessionId).filter(Boolean):[],
                selectValue:menu?.dataset.currentContest||null,
                refreshDisabled:document.getElementById('refresh-submissions')?.disabled??null,
                refreshStatus:document.getElementById('refresh-status')?.textContent.trim()||''};
            ''')
            signature = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if not observations or observations[-1] != value:
                observations.append(value)
            self.summary['uiBootstrapObservations'] = observations[-30:]
            self.flush()
            require(not value['lastError'], 'UI initialization reported an actual error: ' + json.dumps(value['lastError'], ensure_ascii=False))
            complete = (value['connected'] and value['selectedSessionId'] in required_ids and
                        value['problemCount'] == 12 and set(value['optionIds']) == required_ids and
                        value['selectValue'] == value['selectedSessionId'] and value['refreshDisabled'] is False and
                        bool(value['refreshStatus']) and not value['refreshStatus'].startswith('正在'))
            if complete and signature == last_signature:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= .3:
                    return value
            else:
                stable_since = None
            last_signature = signature
            return None
        return self.wait(ready, 'completed UI initialization, both options and stable provider refresh')

    def contest_navigation(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        before = self.driver.execute_script('return window.qojVpUi.getState().session.sessionId;')
        target = self.prepared_session_id if before == self.running_session_id else self.running_session_id
        require(not self.driver.find_elements(By.CSS_SELECTOR, 'nav select, #home-view #new-session'),
                'A native select remains in the navbar or New contest remains in Home')
        require(self.driver.execute_script('''
          const create=document.querySelector('#jury-list-view #new-session');
          return create?.classList.contains('btn-primary') &&
            !document.querySelector('#session-select #new-session') &&
            !document.querySelector('#home-view #rankland-settings, #home-view #open-resources, #home-view #start-session');
        '''), 'Creation and administration must belong to the Jury view')
        toggle = self.driver.find_element(By.ID, 'navbarDropdownContests')
        require('nav-link dropdown-toggle' in toggle.get_attribute('class'), 'Contest toggle lost the original navbar classes')
        toggle.click()
        self.wait(lambda: toggle.get_attribute('aria-expanded') == 'true', 'normal Bootstrap dropdown click')
        require(self.driver.find_element(By.CSS_SELECTOR, f'#session-select [data-session-id="{target}"]').is_displayed(),
                'The alternate session is not visible in the dropdown')
        require(self.driver.get_screenshot_as_file(str(self.results / 'extension-contest-dropdown.png')),
                'Could not capture the real contest dropdown')
        toggle.send_keys(Keys.ESCAPE)
        self.wait(lambda: toggle.get_attribute('aria-expanded') == 'false', 'Escape dismissing the dropdown')
        toggle.send_keys(Keys.ARROW_DOWN)
        self.wait(lambda: self.driver.execute_script('return document.activeElement?.dataset.sessionId;') == target,
                  'ArrowDown focusing the alternate contest')
        self.driver.switch_to.active_element.send_keys(Keys.ENTER)
        self.wait(lambda: self.driver.execute_script('''
          const s=window.qojVpUi.getState();return s.session?.sessionId===arguments[0]&&s.contest?.problemCount===12;
        ''', target), 'Enter selecting the alternate contest')
        self.wait_boot_ready()
        require(toggle.get_attribute('aria-expanded') == 'false', 'Selecting a contest left the dropdown open')
        self.driver.find_element(By.ID, 'nav-jury').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-list-view').is_displayed(), 'Jury contest list')
        self.driver.find_element(By.ID, 'new-session').click()
        self.wait(lambda: self.driver.execute_script('''
          return document.querySelector('#session-modal')?.classList.contains('show');
        '''), 'Jury Add new contest opening setup')
        self.close_modal('extension', 'new-contest-setup')
        self.driver.find_element(By.ID, 'nav-team').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'home-view').is_displayed(), 'return from Jury to Team')
        return {'clickOpens': True, 'escapeCloses': True, 'arrowDownFocusesChoice': True,
                'enterSelects': True, 'previousSessionId': before, 'selectedSessionId': target,
                'newContestInJuryOpensSetup': True, 'adminControlsAbsentFromHome': True,
                'upstream': 'DOMjudge 9.0.1 menu_change_contest.html.twig and jury/contests.html.twig adaptation'}

    def capture_control(self, side, name, visual_selector, trigger_selector=None):
        from selenium.webdriver.common.by import By
        self.fonts()
        output = self.captures[side].setdefault(name, {})
        for state in ('normal', 'hover', 'active', 'disabled'):
            real_prepared = side == 'extension' and name in {'cardSubmit', 'navbarSubmit'} and state == 'disabled'
            if real_prepared:
                self.select_visual_session(self.prepared_session_id)
            visual = self.driver.find_element(By.CSS_SELECTOR, visual_selector)
            trigger = self.driver.find_element(By.CSS_SELECTOR, trigger_selector or visual_selector)
            self.reset_pointer()
            self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', visual)
            require(not self.driver.execute_script("return arguments[0].matches(':active')||arguments[1].matches(':active');", visual, trigger),
                    'Previous pointer activation was not cleared before ' + state)
            old = None
            try:
                if state == 'disabled' and not real_prepared:
                    old = self.driver.execute_script('''
                      return [...new Set([arguments[0],arguments[1]])].map(e=>{const attrs={};for(const a of e.attributes)attrs[a.name]=a.value;
                        e.classList.add('disabled');e.setAttribute('disabled','');e.setAttribute('aria-disabled','true');return attrs;});
                    ''', visual, trigger)
                if real_prepared:
                    # Cross an actual renderClock tick. No timer is stopped,
                    # patched or fought by a MutationObserver.
                    time.sleep(1.15)
                if state in ('hover', 'active'):
                    # WebElement.rect is document-relative; pointer actions use
                    # the viewport rectangle after scrollIntoView.
                    center = self.driver.execute_script('const r=arguments[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};', visual)
                    self.pointer(center['x'], center['y'], 'down' if state == 'active' else None)
                time.sleep(.25)  # Let the original Bootstrap transitions settle.
                value = self.driver.execute_script('''
                  const e=arguments[0],properties=arguments[1],s=getComputedStyle(e),r=e.getBoundingClientRect();
                  return {computed:Object.fromEntries(properties.map(p=>[p,s.getPropertyValue(p)])),
                    dimensions:{width:r.width,height:r.height},tag:e.tagName,className:e.className,
                    state:{hover:e.matches(':hover'),active:e.matches(':active'),disabled:e.matches(':disabled')||e.classList.contains('disabled')},
                    triggerState:{hover:arguments[2].matches(':hover'),active:arguments[2].matches(':active')}};
                ''', visual, list(STYLE_PROPERTIES), trigger)
                active = value['state']['active'] or value['triggerState']['active']
                hovered = value['state']['hover'] or value['triggerState']['hover']
                require(value['state']['disabled'] == (state == 'disabled'), 'The captured disabled state is not real: ' + side + '/' + name + '/' + state)
                if state == 'active':
                    require(active and hovered, 'The actual pointer did not put the control into its active state')
                else:
                    require(not active, 'A stale active pseudo-class contaminated ' + state)
                    require(hovered == (state == 'hover'), 'The captured hover state does not match ' + state)
                png = self.results / f'{side}-{name}-{state}.png'
                require(visual.screenshot(str(png)), 'Element PNG was not saved')
                after = self.driver.execute_script('''
                  return {active:arguments[0].matches(':active')||arguments[1].matches(':active'),
                    disabled:arguments[0].matches(':disabled')||arguments[0].classList.contains('disabled')};
                ''', visual, trigger)
                require(after['active'] == (state == 'active') and after['disabled'] == (state == 'disabled'),
                        'Control state changed during its screenshot')
                value['png'] = str(png)
                value.update(stateValidated=True, stateAfterScreenshot=after,
                             stateSetup='real-prepared-session' if real_prepared else 'temporary-disabled-CSS-probe' if state == 'disabled' else 'real-pointer')
                output[state] = value
            finally:
                if state == 'active':
                    # Release outside the button. Never click Submit, navigate
                    # statement/samples or send an empty form for an active PNG.
                    self.pointer(1, 1, 'up')
                    self.reset_pointer()
                if old is not None:
                    self.driver.execute_script('''
                      [...new Set([arguments[0],arguments[1]])].forEach((e,i)=>{for(const a of [...e.attributes])e.removeAttribute(a.name);
                        for(const [k,v]of Object.entries(arguments[2][i]))e.setAttribute(k,v);});
                    ''', visual, trigger, old)
                if real_prepared:
                    self.select_visual_session(self.running_session_id)
        atomic_json(self.results / 'component-captures.json', self.captures)
        return output

    def modal_fields(self, side, kind):
        from selenium.webdriver.common.by import By
        # openSubmit shows the dialog before its QOJ language request finishes.
        # Reading WebElement option handles at .show can race with replacing the
        # loading placeholder. Wait for the actual usable form, on both sides;
        # a failed language load must fail this check rather than look complete.
        readiness = []

        def form_ready():
            value = self.driver.execute_script('''
              const modal=document.querySelector('.modal.show');
              const instance=modal&&window.bootstrap?.Modal?.getInstance(modal);
              const source=modal?.querySelector('#submit_problem_code');
              const problem=modal?.querySelector('#submit_problem_problem');
              const language=modal?.querySelector('#submit_problem_language');
              const value={visible:!!modal?.getClientRects().length,
                shown:instance?instance._isShown===true&&!instance._isTransitioning:false,
                sourceEnabled:!!source&&!source.disabled,
                problemCount:problem?[...problem.options].filter(o=>o.value).length:0,
                languageEnabled:!!language&&!language.disabled,
                languageCount:language?[...language.options].filter(o=>o.value).length:0};
              return value;
            ''')
            if not readiness or readiness[-1] != value:
                readiness.append(value)
            return value if (value['visible'] and value['shown'] and value['sourceEnabled'] and
                             value['problemCount'] > 0 and value['languageEnabled'] and
                             value['languageCount'] > 0) else None

        self.summary.setdefault('modalFormReadiness', {}).setdefault(side, {})[kind] = readiness
        self.wait(form_ready, 'fully shown submit dialog with usable problem and language options')
        modal = self.driver.find_element(By.CSS_SELECTOR, '.modal.show')
        data = {'title': modal.find_element(By.CSS_SELECTOR, '.modal-title').text.strip(), 'fields': {}}
        for field, selector in (('source', '#submit_problem_code'), ('problem', '#submit_problem_problem'),
                                ('language', '#submit_problem_language'), ('entryPoint', '#submit_problem_entry_point')):
            element = modal.find_element(By.CSS_SELECTOR, selector)
            label = modal.find_element(By.CSS_SELECTOR, 'label[for="' + selector[1:] + '"]')
            data['fields'][field] = {'visible': element.is_displayed(), 'label': label.text.strip(),
                                    'required': element.get_attribute('required') is not None,
                                    'multiple': element.get_attribute('multiple') is not None}
            if field in ('problem', 'language'):
                data['fields'][field]['options'] = [o.text.strip() for o in element.find_elements(By.TAG_NAME, 'option')]
                data['fields'][field]['selectedText'] = self.driver.execute_script('return arguments[0].selectedOptions[0]?.textContent.trim()||"";', element)
        require(data['fields']['source']['visible'] and not data['fields']['source']['multiple'], 'Source file is not a visible single-file field')
        data['sourceFileCount'] = self.driver.execute_script('return arguments[0].files.length;', modal.find_element(By.ID, 'submit_problem_code'))
        require(data['sourceFileCount'] == 0, 'The visual-only harness unexpectedly selected a source file')
        require(data['fields']['language']['visible'], 'Language field is not visible')
        require(data['fields']['problem']['visible'] == (kind == 'generic'), 'Problem selector visibility is wrong for the modal entry point')
        if kind == 'per-problem':
            require(data['fields']['problem']['selectedText'].startswith('A - Bridge'), 'Problem A was not preselected')
        require(self.driver.get_full_page_screenshot_as_file(str(self.results / f'{side}-submit-{kind}-full.png')),
                'Firefox did not save the complete modal/page screenshot')
        self.summary.setdefault('modalFields', {}).setdefault(side, {})[kind] = data
        return data

    def modal_state(self):
        """Read only structural/animation state; never retain form values."""
        return self.driver.execute_script('''
          const describe=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();
            const instance=window.bootstrap?.Modal?.getInstance(e);
            return {tag:e.tagName,className:e.className,display:s.display,opacity:s.opacity,
              visible:!!e.getClientRects().length,ariaHidden:e.getAttribute('aria-hidden'),
              ariaModal:e.getAttribute('aria-modal'),active:e.matches(':active'),
              transitionDuration:s.transitionDuration,transitionDelay:s.transitionDelay,
              dimensions:{x:r.x,y:r.y,width:r.width,height:r.height},
              bootstrap:instance?{isShown:instance._isShown,isTransitioning:instance._isTransitioning}:null};};
          return {at:performance.now(),readyState:document.readyState,bodyClass:document.body.className,
            modalCount:document.querySelectorAll('.modal').length,
            shownCount:document.querySelectorAll('.modal.show').length,
            modals:[...document.querySelectorAll('.modal')].map(describe),
            backdrops:[...document.querySelectorAll('.modal-backdrop')].map(describe),
            events:(window.__qojVpVisualModalEvents||[]).slice(-30)};
        ''')

    def close_modal(self, side, kind):
        from selenium.webdriver.common.by import By
        name = side + '-' + kind + '-close'
        record = {'side': side, 'kind': kind, 'status': 'running', 'startedAt': utc_now(),
                  'closeClicks': 0, 'stateMutation': False, 'observations': []}
        self.summary.setdefault('modalInteractions', []).append(record)
        self.driver.execute_script('''
          if(!window.__qojVpVisualModalEvents){
            window.__qojVpVisualModalEvents=[];
            for(const type of ['show.bs.modal','shown.bs.modal','hide.bs.modal','hidden.bs.modal'])
              document.addEventListener(type,e=>{window.__qojVpVisualModalEvents.push({
                type,at:performance.now(),className:e.target.className,defaultPrevented:e.defaultPrevented});
                if(window.__qojVpVisualModalEvents.length>60)window.__qojVpVisualModalEvents.shift();});
          }
        ''')
        record['beforeWait'] = self.modal_state()
        try:
            def fully_shown():
                state = self.modal_state()
                shown = [m for m in state['modals'] if 'show' in m['className'].split()]
                current = {'at': state['at'], 'shownCount': state['shownCount'],
                           'bootstrap': [m['bootstrap'] for m in shown]}
                if not record['observations'] or current['bootstrap'] != record['observations'][-1]['bootstrap']:
                    record['observations'].append(current)
                # Bootstrap sets .show before its dialog transition finishes.
                # Its real hide() intentionally ignores calls during that
                # transition, so a visible modal alone is not ready to close.
                return len(shown) == 1 and shown[0]['bootstrap'] == {'isShown': True, 'isTransitioning': False}
            self.wait(fully_shown, 'the real Bootstrap shown transition before one close click', timeout=10)
            record['beforeClick'] = self.modal_state()
            modal = self.driver.find_element(By.CSS_SELECTOR, '.modal.show')
            modal.find_element(By.CSS_SELECTOR, '[data-bs-dismiss="modal"]').click()
            record['closeClicks'] = 1
            self.wait(lambda: self.driver.execute_script('''
              return !document.querySelector('.modal.show') && !document.querySelector('.modal-backdrop') &&
                !document.body.classList.contains('modal-open');
            '''), 'modal, backdrop and body modal-open cleanup', timeout=10)
            record['status'] = 'passed'
            self.reset_pointer()
            return record
        except Exception as exc:
            record.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)[:1000]})
            png = self.results / (name + '-failed.png')
            try:
                record['screenshotSaved'] = self.driver.save_screenshot(str(png))
                record['screenshot'] = str(png)
            except Exception as screenshot_error:
                record['screenshotErrorType'] = type(screenshot_error).__name__
            raise
        finally:
            try:
                record['after'] = self.modal_state()
            except Exception as state_error:
                record['stateErrorType'] = type(state_error).__name__
            record['finishedAt'] = utc_now()
            atomic_json(self.results / (name + '-state.json'), record)
            self.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    reference_group = parser.add_mutually_exclusive_group()
    reference_group.add_argument('--reference-url')
    reference_group.add_argument('--reference-snapshot', type=Path)
    parser.add_argument('--credentials-file', type=Path)
    parser.add_argument('--configuration', type=Path)
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--height', type=int, default=1000)
    args = parser.parse_args()
    h = VisualHarness(args.project, args.width, args.height)
    reference_server = fixture = None
    try:
        configuration_path = args.configuration or (args.reference_snapshot / 'configuration.json' if args.reference_snapshot
            else h.project / 'preflight/visual-reference/rendered/configuration.json')
        configuration = json.loads(configuration_path.read_text())
        require(configuration['providerVersion'] == '9.0.1', 'Visual configuration is not the pinned provider version')
        if args.reference_snapshot:
            reference_server = SnapshotReference(args.reference_snapshot).start()
            base = reference_server.origin
            h.summary.update(referenceMode='official-server-rendered-snapshot', credentialsUsed=False,
                referenceVersionSource='Hash-verified frozen manifest; live service API/image independently verified by the root agent',
                referenceManifest=reference_server.manifest, verifiedSnapshots=reference_server.verified,
                referenceLimitations=['Snapshot replay is not a running DOMjudge backend.', 'Live update endpoints are not fabricated.',
                                      'Token values alone were redacted by the capture exporter.'])
        else:
            credentials = json.loads(args.credentials_file.read_text()) if args.credentials_file else {}
            base = args.reference_url or credentials.get('referenceBaseUrl')
            require(isinstance(base, str), 'A reference service URL or snapshot directory is required')
            parsed = urlsplit(base)
            require(parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                    'Invalid reference service URL')
            base = base.rstrip('/')
            h.summary.update(referenceMode='official-live-service', credentialsUsed=bool(credentials))
        fixture = VisualQojFixture(configuration).start()
        setup = h.step('isolated_alias_byte_verification_and_native_setup', lambda: h.setup_visual(fixture))
        browser = h.step('actual_guest_firefox_fixed_viewport', h.start_browser) if setup else None
        addon = h.step('temporary_alias_extension_install', h.install_extension) if browser else None
        if addon:
            hello = h.call('hello')
            require(hello.get('fixture') is True, 'The visual workbench is not confined to its GET-only fixture')
            account = h.call('qoj_contest', {'contestId': '3387'})
            require(len(account['problems']) == 12 and account['account'] == configuration['team']['id'], 'Fixture did not expose the aligned twelve-problem contest')
            session = h.call('create_session', {'contestId': '3387', 'title': configuration['contest']['name'], 'account': account['account'], 'durationMs': 18000000})
            prepared = h.call('create_session', {'contestId': '3387', 'title': 'Visual prepared state', 'account': account['account'], 'durationMs': 18000000})
            h.running_session_id, h.prepared_session_id = session['sessionId'], prepared['sessionId']

            def prepare_visual_resources():
                entries = []
                for problem in account['problems']:
                    pid, label = str(problem['id']), problem['label']
                    entry = h.call('prepare_resource', {'sessionId': session['sessionId'], 'problemId': pid})
                    require(entry.get('status') == 'ready' and entry.get('kind') == 'samples' and
                            entry.get('sampleCount') == entry.get('pairCount') == 1,
                            'The real preparation pipeline did not produce ordinary synthetic samples for ' + label)
                    require({file['name'] for file in entry['files']} == {f'samples-{label}/1.in', f'samples-{label}/1.ans'},
                            'The pinned library did not organize the expected synthetic sample pair')
                    entries.append(entry)
                before = len(fixture.requests)
                running_manifest = h.call('resource_manifest', {'sessionId': session['sessionId']})
                prepared_manifest = h.call('resource_manifest', {'sessionId': prepared['sessionId']})
                require(len(fixture.requests) == before, 'The local manifest read unexpectedly queried QOJ')
                require(len(running_manifest['problems']) == len(prepared_manifest['problems']) == 12 and
                        running_manifest['problems'] == prepared_manifest['problems'],
                        'The two local sessions do not share the same account/contest resource cache')
                require(sorted(item['problemId'] for item in fixture.resource_gets) == sorted(fixture.ids),
                        'Each of the twelve resource packages was not obtained by one actual fixture GET')
                return {'entries': entries, 'downloadGets': fixture.resource_gets,
                        'bothSessionsShareScope': True, 'manifestReadQojRequests': 0,
                        'preparationPath': 'production extension task -> native Application -> pinned samples.download/organize/zip_bytes -> persistent cache',
                        'resourceContent': 'synthetic sample inputs and answers only; no contestant source'}
            resource_setup = h.step('twelve_actual_native_resource_preparations_and_shared_offline_cache', prepare_visual_resources)
            require(resource_setup is not None, 'The ready-only UI resources were not prepared through production RPC')
            h.driver.refresh()
            boot = h.step('ui_bootstrap_finishes_before_one_visual_session_selection', h.wait_boot_ready)
            require(boot is not None, 'The real UI initialization did not complete before visual setup')
            require(h.step('original_contest_dropdown_click_and_keyboard', h.contest_navigation) is not None,
                    'The real Bootstrap contest dropdown failed its navigation checks')
            h.select_visual_session(h.running_session_id)
            def resources_rendered():
                value = h.driver.execute_script('''
                  const s=window.qojVpUi.getState();return {resourcesLoaded:s.resourcesLoaded,
                    readyCount:s.resources.filter(r=>r.status==='ready'&&r.kind==='samples').length,
                    sampleControlCount:document.querySelectorAll('#problems-list .card a[data-samples-problem]').length};
                ''')
                return value if value == {'resourcesLoaded': True, 'readyCount': 12, 'sampleControlCount': 12} else None
            require(h.step('normal_ui_manifest_load_renders_twelve_real_samples_controls',
                           lambda: h.wait(resources_rendered, 'normal loadResourceManifest rendering twelve ready sample controls')) is not None,
                    'The real UI did not load and render the prepared resource manifest')
            from selenium.webdriver.common.by import By
            h.driver.find_element(By.ID, 'nav-jury').click()
            h.wait(lambda: h.driver.find_element(By.ID, 'jury-list-view').is_displayed(), 'Jury contest list before local start')
            h.driver.find_element(By.CSS_SELECTOR, f'[data-jury-session="{h.running_session_id}"]').click()
            h.wait(lambda: h.driver.find_element(By.ID, 'jury-detail-view').is_displayed() and
                           h.driver.find_element(By.ID, 'start-session').is_displayed(), 'selected Jury start control')
            h.driver.find_element(By.ID, 'start-session').click()
            confirmation = h.driver.switch_to.alert
            require('本地' in confirmation.text and 'QOJ' in confirmation.text,
                    'The start confirmation is not the expected local-only timer action')
            confirmation.accept()
            h.wait(lambda: (h.driver.execute_script('return window.qojVpUi.getState().session?.startAt;')), 'real UI local start')
            h.driver.find_element(By.ID, 'nav-team').click()
            h.wait(lambda: h.driver.find_element(By.ID, 'home-view').is_displayed(), 'Team after local start')
            h.driver.find_element(By.ID, 'nav-problems').click()
            h.wait(lambda: h.driver.find_element(By.ID, 'problems-view').is_displayed() and
                           len(h.driver.find_elements(By.CSS_SELECTOR, '#problems-list .card')) == 12,
                   'visible product Problemset and twelve problem cards')
            h.fonts()
            product_viewport = h.driver.execute_script('return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio};')
            require(h.driver.get_full_page_screenshot_as_file(str(h.results / 'extension-problemset-full.png')),
                    'Firefox did not save the complete product Problemset')

            def product_problemset_scope():
                value = h.driver.execute_script('''
                  const visible=e=>e&&!!e.getClientRects().length;
                  return {teamSummaryVisible:visible(document.querySelector('#teamscoresummary')),
                    summaryInsideProblemset:!!document.querySelector('#problems-view #teamscoresummary'),
                    globalSuccessNoticeVisible:visible(document.querySelector('#notice.alert-success'))};
                ''')
                require(not any(value.values()), 'Home team summary or global success notice leaked into Problemset')
                return value
            h.step('problemset_has_no_home_summary_or_global_success_notice', product_problemset_scope)
            for name, visual, trigger in (
                ('cardSubmit', '#problems-list .card a.justify-content-center > span.btn-success', '#problems-list .card a.justify-content-center'),
                ('statement', '#problems-list .card a[data-statement-problem]', None),
                ('samples', '#problems-list .card a[data-samples-problem]', None),
                ('navbarSubmit', '#open-submit > span.btn-success', '#open-submit')):
                h.step('extension_' + name + '_four_states', lambda n=name, v=visual, t=trigger: h.capture_control('extension', n, v, t))
            h.driver.find_element(By.CSS_SELECTOR, '#problems-list .card a.justify-content-center').click()
            h.step('extension_per_problem_modal_visible_fields', lambda: h.modal_fields('extension', 'per-problem'))
            require(h.step('extension_per_problem_modal_close_interaction', lambda: h.close_modal('extension', 'per-problem')) is not None,
                    'The extension per-problem modal did not close normally')
            h.driver.find_element(By.ID, 'open-submit').click()
            h.step('extension_generic_modal_visible_fields', lambda: h.modal_fields('extension', 'generic'))
            h.step('extension_modalSubmit_four_states', lambda: h.capture_control('extension', 'modalSubmit', '#submit-modal .modal-footer button[type="submit"]'))
            require(h.step('extension_generic_modal_close_interaction', lambda: h.close_modal('extension', 'generic')) is not None,
                    'The extension generic modal did not close normally')

            h.driver.switch_to.new_window('tab')
            h.driver.get(base + ('/team/problems' if args.reference_snapshot else '/login'))
            if not args.reference_snapshot:
                def live_login_and_version():
                    value = h.driver.execute_async_script('''
                      const done=arguments[arguments.length-1];fetch('/api').then(r=>r.json()).then(d=>done(d.domjudge?.version||null),()=>done(null));
                    ''')
                    require(value == '9.0.1', 'The actual reference service API did not report DOMjudge 9.0.1')
                    require(credentials.get('username') and credentials.get('password'), 'Reference login credentials were not supplied')
                    try:
                        h.driver.find_element(By.NAME, '_username').send_keys(credentials['username'])
                        h.driver.find_element(By.NAME, '_password').send_keys(credentials['password'])
                        h.driver.find_element(By.CSS_SELECTOR, 'form button[type="submit"],form input[type="submit"]').click()
                        h.wait(lambda: '/login' not in urlsplit(h.driver.current_url).path, 'original reference login')
                    except Exception as exc:
                        raise AssertionError('Reference browser login failed: ' + type(exc).__name__) from None
                    return {'version': value, 'credentialsReturnedOrStored': False}
                login = h.step('actual_reference_service_version_and_form_login', live_login_and_version)
                require(login is not None, 'The original reference service could not be authenticated')
                credentials.clear()
                h.driver.get(base + '/team/problems')
            h.wait(lambda: len(h.driver.find_elements(By.CSS_SELECTOR, '.problem-list .card')) == 12, 'twelve original reference cards')
            h.fonts()
            reference_viewport = h.driver.execute_script('return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio};')
            require(reference_viewport == product_viewport, 'The actual reference/product viewports differ')
            h.summary['sameActualViewport'] = reference_viewport
            require(h.driver.get_full_page_screenshot_as_file(str(h.results / 'reference-problemset-full.png')),
                    'Firefox did not save the complete original Problemset')
            for name, visual, trigger in (
                ('cardSubmit', '.problem-list .card a.justify-content-center > span.btn-success', '.problem-list .card a.justify-content-center'),
                ('statement', '.problem-list .card a[href$="/statement"]', None),
                ('samples', '.problem-list .card a[href$="/samples.zip"]', None),
                ('navbarSubmit', 'nav a[data-ajax-modal][href="/team/submit"] > span.btn-success', 'nav a[data-ajax-modal][href="/team/submit"]')):
                h.step('reference_' + name + '_four_states', lambda n=name, v=visual, t=trigger: h.capture_control('reference', n, v, t))
            h.driver.find_element(By.CSS_SELECTOR, '.problem-list .card a.justify-content-center').click()
            h.step('reference_per_problem_ajax_modal_visible_fields', lambda: h.modal_fields('reference', 'per-problem'))
            h.step('reference_per_problem_modal_close_interaction', lambda: h.close_modal('reference', 'per-problem'))
            # Keep independent visual collection possible if the original
            # close interaction fails. A fresh, real document is navigation,
            # not backdrop removal or CSS repair; the failed check remains.
            h.summary['referenceGenericModalIsolation'] = 'fresh-navigation-after-recorded-per-problem-close'
            h.driver.get(base + '/team/problems')
            h.wait(lambda: len(h.driver.find_elements(By.CSS_SELECTOR, '.problem-list .card')) == 12,
                   'twelve original reference cards in the independent generic-modal document')
            h.fonts()
            h.driver.find_element(By.CSS_SELECTOR, 'nav a[data-ajax-modal][href="/team/submit"]').click()
            h.step('reference_generic_ajax_modal_visible_fields', lambda: h.modal_fields('reference', 'generic'))
            h.step('reference_modalSubmit_four_states', lambda: h.capture_control('reference', 'modalSubmit', '.modal.show .modal-footer button[type="submit"]'))
            h.step('reference_generic_modal_close_interaction', lambda: h.close_modal('reference', 'generic'))
            h.driver.get(base + '/team/submit')
            h.fonts()
            require(h.driver.get_full_page_screenshot_as_file(str(h.results / 'reference-submit-page-full.png')),
                    'Firefox did not save the complete original submit page')

            def compare():
                result = compare_component_captures(h.captures)
                field_differences = []
                for kind in ('generic', 'per-problem'):
                    original = h.summary.get('modalFields', {}).get('reference', {}).get(kind)
                    product = h.summary.get('modalFields', {}).get('extension', {}).get(kind)
                    if original is None or product is None:
                        field_differences.append({'modal': kind, 'property': 'capture', 'reference': bool(original), 'extension': bool(product)})
                        continue
                    for field in ('source', 'problem', 'language', 'entryPoint'):
                        for key in ('visible', 'label', 'required', 'multiple'):
                            if original['fields'][field][key] != product['fields'][field][key]:
                                field_differences.append({'modal': kind, 'field': field, 'property': key,
                                    'reference': original['fields'][field][key], 'extension': product['fields'][field][key]})
                interactions = h.summary.get('modalInteractions', [])
                required_submit_interactions = {(side, kind) for side in ('extension', 'reference')
                                                for kind in ('generic', 'per-problem')}
                required_setup_interaction = ('extension', 'new-contest-setup')
                interaction_ids = [(row.get('side'), row.get('kind')) for row in interactions]
                required_interactions = required_submit_interactions | {required_setup_interaction}
                interactions_passed = (len(interaction_ids) == len(required_interactions)
                                       and set(interaction_ids) == required_interactions
                                       and all(row.get('status') == 'passed' for row in interactions))
                result.update({'modalFieldsEqual': not field_differences, 'modalFieldDifferences': field_differences,
                          'pixelEquality': 'not-assessed', 'platformLanguageChoicesComparedForParity': False,
                          'modalInteractionsPassed': interactions_passed,
                          'requiredModalInteractions': [{'side': side, 'kind': kind}
                                                        for side, kind in sorted(required_interactions)],
                          'interactionChecksSeparateFromVisualComparison': True})
                atomic_json(h.results / 'comparison.json', result)
                h.summary['comparison'] = result
                require(result['computedStylePropertiesEqual'] and result['modalFieldsEqual'] and result['modalInteractionsPassed'],
                        'Original DOMjudge 9.0.1 computed styles, visible fields or normal modal interactions differ; see comparison.json')
                return result
            h.step('strict_computed_style_and_visible_field_parity', compare)
    except Exception as exc:
        h.summary['fatalError'] = {'type': type(exc).__name__, 'message': str(exc)[:1200]}
    finally:
        for name, fn in (('firefox', h.quit_browser), ('qojFixtureServer', lambda: fixture.shutdown() if fixture else None),
                         ('referenceSnapshotServer', lambda: reference_server.shutdown() if reference_server else None),
                         ('ownedAliasAndPermanentHost', h.cleanup_manifest)):
            try:
                h.summary['cleanup'][name] = {'status': 'passed', 'evidence': fn()}
            except Exception as exc:
                h.summary['cleanup'][name] = {'status': 'failed', 'errorType': type(exc).__name__}
            h.flush()
        def final_safety():
            require(fixture is not None and fixture.post_count == 0, 'A POST reached the GET-only QOJ visual fixture')
            require(reference_server is None or reference_server.post_count == 0, 'A POST reached the snapshot reference')
            pids = sorted(set(int(line) for line in h.helper_pids.read_text().splitlines())) if h.helper_pids.exists() else []
            exits = [process_exit(pid, timeout=12) for pid in pids]
            return {'qojPostCount': fixture.post_count, 'referenceSnapshotPostCount': reference_server.post_count if reference_server else None,
                    'sourceFilesSelected': 0, 'nativeHelperExits': exits}
        h.step('zero_source_posts_and_all_owned_native_helpers_exit', final_safety)
        def owned_profile_cleanup():
            require(h.summary['cleanup']['firefox']['status'] == 'passed', 'Browser exit is unconfirmed; keeping its isolated profile')
            require(h.profile.parent == h.state and h.profile.name == 'firefox-profile' and
                    h.profile.resolve().is_relative_to(h.project / 'state/visual-parity'), 'Refusing to clean an unowned Firefox profile')
            if h.profile.exists():
                shutil.rmtree(h.profile)
            return {'isolatedProfileRemoved': True, 'userProfileAccessed': False}
        try:
            h.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'passed', 'evidence': owned_profile_cleanup()}
        except Exception as exc:
            h.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'failed', 'errorType': type(exc).__name__}
        if fixture:
            atomic_json(h.results / 'qoj-fixture-requests.json', fixture.requests)
        if reference_server:
            atomic_json(h.results / 'snapshot-reference-requests.json', reference_server.requests)
        failed = [c['name'] for c in h.summary['checks'] if c['status'] == 'failed']
        cleanup_failed = any(c['status'] != 'passed' for c in h.summary['cleanup'].values())
        h.summary.update(finishedAt=utc_now(), requiredFailures=failed, captures=h.captures,
                         status='failed' if failed or cleanup_failed or h.summary.get('fatalError') else 'passed')
        h.phase = 'finished'
        h.flush()
        print(json.dumps({'status': h.summary['status'], 'summary': str(h.results / 'summary.json')}))
    return 0 if h.summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
