#!/usr/bin/env python3
"""Compare official DOMjudge 9.0.1 Home columns/headings and capture both pages.

Uses isolated GET-only fixtures; whole-page pixel identity is not claimed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
import shlex
import sys
import time
import threading
import uuid

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py')]
import guest_visual_parity as visual
from guest_preflight import atomic_json, process_exit, require, utc_now


class DelayedHomeFixture(visual.VisualQojFixture):
    """Gate real fixture HTTP after priming the normal persistent snapshot."""
    def __init__(self, configuration):
        super().__init__(configuration)
        self.delay_contest = False
        self.release = threading.Event()
        self.release.set()
        self.blocked = []
        self.fail_delayed = False
        self.submitted_at = datetime.fromtimestamp(time.time() - 60, timezone.utc).isoformat(timespec='seconds')

    def response(self, path, xhr):
        if path == '/contest/3387' and self.delay_contest:
            self.blocked.append({'path': path, 'at': time.monotonic()})
            released = self.release.wait(45)
            if not released or self.fail_delayed:
                return 503, b'Synthetic delayed fixture unavailable', 'text/plain'
        if path == '/contest/3387/submissions':
            problem = self.problems[0]
            body = ('<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Time</th></tr></thead><tbody>'
                    '<tr><td><a href="/submission/900001">900001</a></td><td><span class="uoj-username">' + html.escape(self.account) +
                    '</span></td><td><a href="/contest/3387/problem/' + str(problem['probid']) + '">' + html.escape(problem['label']) +
                    '</a></td><td>AC</td><td>C++20</td><td><time datetime="' + self.submitted_at + '">' + self.submitted_at +
                    '</time></td></tr></tbody></table>')
            return 200, body.encode(), 'text/html; charset=utf-8'
        return super().response(path, xhr)

    def shutdown(self):
        self.release.set()
        super().shutdown()


class HomeHarness(visual.VisualHarness):
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.run_id = uuid.uuid4().hex
        visual.HOST = 'org.littledrinks.qoj_vp_home_' + self.run_id
        visual.EXTENSION_ID = 'qoj-vp-home-' + self.run_id + '@littledrinks.local'
        visual.OWNER = 'QOJ VP isolated Home screenshot QA native host v1'
        self.state = self.project / 'state/home-parity' / self.run_id
        self.profile = self.state / 'firefox-profile'
        self.native_state = self.state / 'native'
        self.results = self.project / 'results/home-parity' / self.run_id
        self.results.mkdir(parents=True, exist_ok=True)
        self.driver = self.ui_handle = self.ui_url = None
        self.manifest_path = Path.home() / '.mozilla/native-messaging-hosts' / (visual.HOST + '.json')
        self.permanent_path = self.manifest_path.with_name('org.littledrinks.qoj_vp.json')
        self.permanent_before = self.permanent_path.read_bytes() if self.permanent_path.exists() else None
        self.manifest_before = None
        self.manifest_installed = False
        self.helper_pids = self.state / 'native-helper-pids'
        self.width, self.height = 1440, 1000
        self.phase = 'initializing'
        self.captures = {}
        self.summary = {'schema': 'qoj-vp-home-capture-v1', 'runId': self.run_id, 'startedAt': utc_now(),
                        'profile': str(self.profile), 'checks': [], 'cleanup': {}, 'sourceFilesSelected': 0,
                        'homeParityCertified': False, 'pixelEquality': 'not-assessed',
                        'referenceMode': 'official-server-rendered-snapshot',
                        'scope': 'One browser boot, Home column/heading comparison and screenshots; no source submit or RankLand.'}
        self.flush()

    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/home-parity-summary.json', self.summary)

    def capture_home(self, side):
        self.fonts()
        value = self.driver.execute_script('''
          const visible=e=>!!e&&!!e.getClientRects().length;
          const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
          const describe=e=>{const c=getComputedStyle(e);return {tag:e.tagName,id:e.id,className:e.className,
            text:e.textContent.trim().replace(/\\s+/g,' ').slice(0,220),rect:rect(e),
            computed:{fontSize:c.fontSize,lineHeight:c.lineHeight,fontWeight:c.fontWeight,
              marginTop:c.marginTop,marginBottom:c.marginBottom,padding:c.padding}};};
          const root=document.querySelector('#home-view')||document.querySelector('[data-ajax-refresh-target]');
          const summary=root?.querySelector('#teamscoresummary');
          const headings=[...root.querySelectorAll('.teamoverview')].filter(visible);
          return {viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},
            rootVisible:visible(root),rootRect:rect(root),headings:headings.map(describe),
            columns:headings.map(e=>({heading:e.textContent.trim(),parentTag:e.parentElement.tagName,
              parentClass:e.parentElement.className,parentRect:rect(e.parentElement)})),
            summary:{visible:visible(summary),rect:summary?rect(summary):null,
              visibleTables:[...summary.querySelectorAll('table')].filter(visible).map(e=>({className:e.className,rect:rect(e),
                headers:[...e.querySelectorAll('thead th')].map(n=>n.textContent.trim()),
                rowCellCounts:[...e.querySelectorAll('tbody tr')].map(n=>n.cells.length)}))},
            alerts:[...root.querySelectorAll('.alert')].filter(visible).map(describe),
            visibleButtons:[...root.querySelectorAll('button,a.btn')].filter(visible).map(describe),
            overviewColumnCount:headings[0]?.parentElement.parentElement.children.length,
            administrationInHome:root.querySelectorAll('#rankland-settings,#open-resources,#new-session,#start-session,#finish-session,#delete-session').length,
            clarificationNotes:[...headings[1]?.parentElement.querySelectorAll('.nodata')||[]].map(e=>e.textContent.trim()),
            clarificationLink:(()=>{const a=root.querySelector('#qoj-clarifications-link');return a?{
              href:a.href,target:a.target,rel:a.rel,ajaxModal:a.hasAttribute('data-ajax-modal')}:null;})(),
            submissionTableHeaders:[...root.querySelectorAll('table.submissions-table thead th')].map(e=>e.textContent.trim()),
            sourceFileCount:[...document.querySelectorAll('input[type="file"]')].reduce((n,e)=>n+e.files.length,0)};
        ''')
        require(value['rootVisible'] and value['summary']['visible'], 'The actual Home summary is not visible')
        require(value['sourceFileCount'] == 0, 'Home QA unexpectedly selected a source file')
        png = self.results / (side + '-home-full.png')
        require(self.driver.get_full_page_screenshot_as_file(str(png)), 'Home full-page PNG was not saved')
        value['png'] = str(png)
        self.summary.setdefault('home', {})[side] = value
        atomic_json(self.results / (side + '-home-structure.json'), value)
        return value

    def compare_home_columns(self, product, original):
        expected = ['Submissions', 'Clarifications', 'Clarification Requests']
        require([item['text'] for item in original['headings']] == expected, 'The pinned reference Home changed its headings')
        require([item['text'] for item in product['headings']] == expected, 'Home does not retain all three official headings')
        require(product['overviewColumnCount'] == original['overviewColumnCount'] == 2, 'Home is no longer the official two-column row')
        require(product['administrationInHome'] == 0, 'Jury management controls leaked into Team Home')
        for index, (actual, reference) in enumerate(zip(product['columns'], original['columns'])):
            require(actual['parentTag'] == reference['parentTag'] == 'DIV' and actual['parentClass'] == reference['parentClass'] == 'col',
                    f'Heading {index} lost its original column container')
            for dimension in ('x', 'width'):
                require(abs(actual['parentRect'][dimension] - reference['parentRect'][dimension]) <= 1,
                        f'Heading {index} column {dimension} differs from the fixed-viewport original')
            require(product['headings'][index]['computed'] == original['headings'][index]['computed'],
                    f'Heading {index} typography/spacing differs from the original stylesheet')
        require(abs(product['headings'][0]['rect']['y'] - product['headings'][1]['rect']['y']) <= 1,
                'Submissions and Clarifications headings are not aligned')
        require(product['columns'][0]['parentRect']['x'] < product['columns'][1]['parentRect']['x'],
                'Clarifications is not the right-hand column')
        require('尚未接入 QOJ 讨论同步。' in product['clarificationNotes'],
                'Clarification availability must be honest about the absent backend')
        link = product['clarificationLink']
        require(link and link['href'] == 'https://qoj.ac/contest/3387' and link['target'] == '_blank' and
                {'noopener', 'noreferrer'} <= set(link['rel'].split()) and not link['ajaxModal'],
                'The clarification action must be an ordinary original-site link, not a simulated local request')
        return {'referenceHeadings': expected, 'twoOfficialColumns': True, 'columnWidthsAndPositionsMatch': True,
                'headingComputedStylesMatch': True, 'juryControlsAbsent': True, 'unavailableBackendDisclosed': True,
                'originalSiteLink': link, 'wholePagePixelEquality': 'not-assessed'}

    def delayed_reload_keeps_views(self, fixture):
        from selenium.webdriver.common.by import By
        self.focus_ui()
        require(len(self.driver.find_elements(By.CSS_SELECTOR, '#submissions-body tr')) == 1,
                'The normal online refresh did not prime the real cached submission')
        fixture.delay_contest = True
        fixture.release.clear()
        before = len(fixture.blocked)
        reloads = []
        try:
            for index in range(3):
                started = time.monotonic()
                self.driver.refresh()
                def cached_ready():
                    return self.driver.execute_script('''
                      const s=window.qojVpUi?.getState();
                      return !!s?.connected&&s.contest?.problemCount===12&&s.submissions?.some(x=>x.id==='900001')&&
                        document.querySelectorAll('#problems-list .card').length===12&&
                        document.querySelectorAll('#submissions-body tr').length===1;
                    ''')
                self.wait(cached_ready, 'cached cards and submissions before delayed HTTP completes', timeout=12)
                require(not fixture.release.is_set(), 'The provider gate was released before cache rendering')
                self.driver.find_element(By.ID, 'nav-problems').click()
                self.wait(lambda: self.driver.find_element(By.ID, 'problems-view').is_displayed(), 'Problemset navigation during slow HTTP')
                self.driver.find_element(By.ID, 'nav-home').click()
                self.wait(lambda: self.driver.find_element(By.ID, 'home-view').is_displayed(), 'Home navigation during slow HTTP')
                reloads.append({'index': index, 'cachedRenderSeconds': round(time.monotonic() - started, 3),
                                'visibleCards': 12, 'visibleSubmissions': 1, 'providerStillBlocked': True})
            self.wait(lambda: len(fixture.blocked) >= before + 2, 'one contest read and one history read reaching the HTTP gate')
            require(len(fixture.blocked) - before == 2, 'Reload duplicated provider reads instead of sharing the background requests')
            require(not self.driver.find_element(By.ID, 'refresh-submissions').is_enabled(),
                    'The refresh button allows duplicate activation while an existing refresh is pending')
            self.driver.save_screenshot(str(self.results / 'cached-home-during-delayed-http.png'))
            fixture.fail_delayed = True
            fixture.release.set()
            self.wait(lambda: self.driver.find_element(By.ID, 'refresh-submissions').is_enabled(), 'failed history refresh leaves cached rows available')
            self.wait(lambda: self.driver.find_element(By.ID, 'refresh-contest').get_attribute('hidden') is None, 'failed contest read exposes retry')
            require(len(self.driver.find_elements(By.CSS_SELECTOR, '#submissions-body tr')) == 1 and
                    len(self.driver.find_elements(By.CSS_SELECTOR, '#problems-list .card')) == 12,
                    'A failed background refresh cleared cached content')
            fixture.delay_contest = False
            self.driver.find_element(By.ID, 'nav-problems').click()
            self.wait(lambda: self.driver.find_element(By.ID, 'problems-view').is_displayed(), 'Problemset retry route')
            self.driver.find_element(By.ID, 'refresh-contest').click()
            self.wait(lambda: not self.driver.find_element(By.ID, 'problemset-status').is_displayed(), 'ordinary retry restores live contest data')
            self.driver.find_element(By.ID, 'nav-home').click()
            self.driver.find_element(By.ID, 'refresh-submissions').click()
            self.wait(lambda: self.driver.find_element(By.ID, 'refresh-submissions').is_enabled() and
                      self.driver.find_element(By.ID, 'refresh-status').text.startswith('更新于'), 'ordinary history retry completes')
            return {'reloads': reloads, 'blockedProviderReadCount': 2, 'cacheRenderedBeforeNetwork': True,
                    'navigationUnblocked': True, 'failedRefreshPreservedBothViews': True, 'normalRetryRecovered': True}
        finally:
            fixture.delay_contest = False
            fixture.release.set()

    def delayed_helper_keeps_display(self):
        from selenium.webdriver.common.by import By
        self.focus_ui()
        launcher = self.native_state / 'launcher.sh'
        original = launcher.read_text()
        gate = self.native_state / 'hold-startup'
        target = 'exec /usr/bin/python3 -B -m qojvp.native_host\n'
        require(original.count(target) == 1, 'Unexpected isolated launcher structure')
        delay = ('attempt=0\nwhile [ -e ' + shlex.quote(str(gate)) + ' ] && [ "$attempt" -lt 100 ]; do\n'
                 '  sleep 0.1\n  attempt=$((attempt + 1))\ndone\n')
        attempts = []
        try:
            gate.touch()
            launcher.write_text(original.replace(target, delay + target))
            for index in range(2):
                started = time.monotonic()
                self.driver.refresh()
                def cached_ready():
                    return self.driver.execute_script('''
                      const s=window.qojVpUi?.getState();
                      return s?.connected===false&&s.contest?.problemCount===12&&
                        document.querySelectorAll('#problems-list .card').length===12&&
                        document.querySelectorAll('#submissions-body tr').length===1;
                    ''')
                self.wait(cached_ready, 'browser display before any native bootstrap reply', timeout=5)
                require(not self.driver.find_element(By.ID, 'connection').is_displayed(), 'A loading banner hides normal startup')
                require(self.driver.find_element(By.ID, 'open-submit').get_attribute('aria-disabled') == 'true',
                        'Display cache enabled submission before the native session was verified')
                self.driver.find_element(By.ID, 'nav-problems').click()
                require(self.driver.find_element(By.ID, 'problems-view').is_displayed(), 'Cached Problemset navigation blocked')
                self.driver.find_element(By.ID, 'nav-home').click()
                require(self.driver.find_element(By.ID, 'home-view').is_displayed(), 'Cached Home navigation blocked')
                require(self.driver.execute_script("return getComputedStyle(document.querySelector('#contest-progress')).transitionDuration") == '0s',
                        'The restored contest clock animates from zero like a loading bar')
                attempts.append({'index': index, 'seconds': round(time.monotonic()-started, 3), 'helperStillBlocked': True,
                                 'cards': 12, 'historyRows': 1, 'loadingBannerVisible': False})
            self.driver.save_screenshot(str(self.results / 'cached-view-before-native-startup.png'))
        finally:
            gate.unlink(missing_ok=True)
            launcher.write_text(original)
        self.wait(lambda: self.driver.execute_script('return window.qojVpUi?.getState().connected===true'), 'native snapshot verification after gate release')
        return {'reloads': attempts, 'nativeVerificationRecovered': True, 'launcherRestored': launcher.read_text() == original}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--reference-snapshot', type=Path, required=True)
    args = parser.parse_args()
    h = HomeHarness(args.project)
    fixture = reference = None
    try:
        reference = visual.SnapshotReference(args.reference_snapshot).start()
        h.summary.update(referenceManifest=reference.manifest, verifiedSnapshots=reference.verified)
        configuration = json.loads((args.reference_snapshot / 'configuration.json').read_text())
        fixture = DelayedHomeFixture(configuration).start()
        require(h.step('isolated_namespace_alias_and_native_setup', lambda: h.setup_visual(fixture)) is not None, 'Alias setup failed')
        require(h.step('one_actual_firefox_boot', h.start_browser) is not None, 'Firefox failed to start')
        require(h.step('temporary_alias_extension_install', h.install_extension) is not None, 'Addon failed to install')
        require(h.call('hello').get('fixture') is True, 'The Home fixture routing is not active')
        account = h.call('qoj_contest', {'contestId': '3387'})
        require(account['account'] == fixture.account and len(account['problems']) == 12, 'The aligned twelve-problem fixture is unavailable')
        session = h.call('create_session', {'contestId': '3387', 'account': account['account'],
            'title': configuration['contest']['name'], 'startAt': int(time.time() * 1000) - 7200000, 'durationMs': 18000000})
        h.running_session_id = h.prepared_session_id = session['sessionId']
        h.driver.refresh()
        require(h.step('normal_home_ui_bootstrap', h.wait_boot_ready) is not None, 'The normal UI did not finish loading')
        h.select_visual_session(session['sessionId'])
        from selenium.webdriver.common.by import By
        h.driver.find_element(By.ID, 'nav-home').click()
        h.wait(lambda: h.driver.find_element(By.ID, 'home-view').is_displayed() and
               len(h.driver.find_elements(By.CSS_SELECTOR, '#teamscoresummary table.desktop-scoreboard thead th')) == 15,
               'the current Home and twelve problem summary columns')
        product = h.step('current_home_screenshot_and_readonly_structure', lambda: h.capture_home('extension'))
        require(product is not None, 'The current Home capture failed')
        h.driver.switch_to.new_window('tab')
        h.driver.get(reference.origin + '/team')
        h.wait(lambda: len(h.driver.find_elements(By.CSS_SELECTOR, '#teamscoresummary table.desktop-scoreboard thead th')) == 15,
               'the original DOMjudge Home and twelve problem summary columns')
        original = h.step('original_901_home_screenshot_and_readonly_structure', lambda: h.capture_home('reference'))
        require(original is not None and product['viewport'] == original['viewport'], 'Home viewport mismatch')
        require(h.step('home_columns_and_headings_match_official_901', lambda: h.compare_home_columns(product, original)) is not None,
                'Home column/style comparison failed')
        comparison = {'sameActualViewport': product['viewport'], 'homeParityCertified': False, 'pixelEquality': 'not-assessed',
            'referenceHeadings': [item['text'] for item in original['headings']],
            'extensionHeadings': [item['text'] for item in product['headings']],
            'businessAdaptations': ['Original Clarifications/Clarification Requests columns and heading styles are retained; backend unavailability is disclosed with a QOJ contest link.',
                'The extension adds a source-QOJ column and refresh/status controls.',
                'Rank and penalty stay unknown where the provider has not supplied them; account/team and clock data differ.'],
            'claim': 'Official two-column structure, widths/positions and heading computed styles are verified; whole-page pixel identity is not certified.'}
        atomic_json(h.results / 'comparison.json', comparison)
        h.summary['comparison'] = comparison
        require(h.step('three_reloads_during_slow_http_keep_cards_and_history', lambda: h.delayed_reload_keeps_views(fixture)) is not None,
                'Slow-network cache/navigation regression failed')
        require(h.step('two_reloads_before_native_startup_keep_display_without_animation', h.delayed_helper_keeps_display) is not None,
                'Cold-helper display regression failed')
    except Exception as error:
        h.summary['fatalError'] = {'type': type(error).__name__, 'message': str(error)[:1400]}
        if h.driver:
            try: h.driver.save_screenshot(str(h.results / 'home-capture-failed.png'))
            except Exception: pass
    finally:
        for name, action in [('firefox', h.quit_browser), ('qojFixture', lambda: fixture.shutdown() if fixture else None),
                             ('referenceSnapshot', lambda: reference.shutdown() if reference else None),
                             ('ownedAliasAndPermanentHost', h.cleanup_manifest)]:
            try: h.summary['cleanup'][name] = {'status': 'passed', 'evidence': action()}
            except Exception as error: h.summary['cleanup'][name] = {'status': 'failed', 'errorType': type(error).__name__}
            h.flush()
        def safety():
            require(fixture is not None and fixture.post_count == 0 and reference is not None and reference.post_count == 0,
                    'A POST reached a read-only Home fixture')
            pids = sorted(set(int(line) for line in h.helper_pids.read_text().splitlines())) if h.helper_pids.exists() else []
            return {'qojPostCount': fixture.post_count, 'referencePostCount': reference.post_count,
                    'sourceFilesSelected': 0, 'nativeHelperExits': [process_exit(pid, timeout=12) for pid in pids]}
        h.step('zero_posts_and_owned_native_helpers_exit', safety)
        try:
            require(h.summary['cleanup']['firefox']['status'] == 'passed', 'Browser exit is unconfirmed; keep the profile')
            require(h.profile.parent == h.state and h.profile.resolve().is_relative_to(h.project / 'state/home-parity'), 'Unowned profile cleanup denied')
            if h.profile.exists(): shutil.rmtree(h.profile)
            h.summary['cleanup']['ownedProfile'] = {'status': 'passed', 'userProfileAccessed': False}
        except Exception as error:
            h.summary['cleanup']['ownedProfile'] = {'status': 'failed', 'errorType': type(error).__name__}
        if fixture: atomic_json(h.results / 'qoj-fixture-requests.json', fixture.requests)
        if reference: atomic_json(h.results / 'snapshot-reference-requests.json', reference.requests)
        failed = [check['name'] for check in h.summary['checks'] if check['status'] != 'passed']
        failure = bool(failed or h.summary.get('fatalError') or any(c['status'] != 'passed' for c in h.summary['cleanup'].values()))
        h.summary.update(finishedAt=utc_now(), requiredFailures=failed, status='failed' if failure else 'captured-not-parity-certified')
        h.phase = 'finished'; h.flush()
        print(json.dumps({'status': h.summary['status'], 'summary': str(h.results / 'summary.json')}))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
