#!/usr/bin/env python3
"""Capture original DOMjudge 9.0.1 and current Home once; do not certify 1:1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'preflight'), str(PROJECT / 'preflight/vendor_py')]
import guest_visual_parity as visual
from guest_preflight import atomic_json, process_exit, require, utc_now


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
                        'scope': 'One browser boot, two Home screenshots and read-only structure; no source submit or RankLand.'}
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
        fixture = visual.VisualQojFixture(configuration).start()
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
        comparison = {'sameActualViewport': product['viewport'], 'homeParityCertified': False, 'pixelEquality': 'not-assessed',
            'referenceHeadings': [item['text'] for item in original['headings']],
            'extensionHeadings': [item['text'] for item in product['headings']],
            'businessAdaptations': ['Original Clarifications/Clarification Requests are replaced by local Contest metadata/actions.',
                'The extension adds a source-QOJ column and refresh/status controls.',
                'Rank and penalty stay unknown where the provider has not supplied them; account/team and clock data differ.'],
            'claim': 'Screenshots and structural readings captured; Home is an adaptation, not certified 1:1.'}
        atomic_json(h.results / 'comparison.json', comparison)
        h.summary['comparison'] = comparison
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
