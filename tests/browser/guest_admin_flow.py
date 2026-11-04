#!/usr/bin/env python3
"""Isolated Firefox acceptance of Jury administration and manual samples.

Uses a fresh alias/native ledger, a GET-only loopback judge and a private browser
profile. All contest creation, edits, imports, finish and delete are performed
through real UI controls. The initial sibling fixture is only setup data.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py'), str(PROJECT / 'vendor/qoj-submitter')]
from guest_resource_cache import ResourceHarness, ResourceFixture, zipped
from guest_preflight import atomic_json, process_exit, require, utc_now


class AdminHarness(ResourceHarness):
    def __init__(self, project):
        super().__init__(project)
        self.results = self.project / 'results/admin-flow' / self.run_id
        self.results.mkdir(parents=True, exist_ok=True)
        self.summary.update(schema='qoj-vp-admin-browser-v1', offlineScope='Manual sample import and cached download; loopback judge remains online.')
        self.flush()

    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/admin-flow-summary.json', self.summary)
        atomic_json(self.project / 'results/admin-flow-status.json', {'runId': self.run_id, 'phase': self.phase,
                    'status': self.summary.get('status', 'running'), 'summary': str(self.results / 'summary.json'),
                    'checks': [{'name': check['name'], 'status': check['status']} for check in self.summary['checks']]})

    def modal_ready(self, name):
        self.wait(lambda: self.driver.execute_script('''
          const m=document.getElementById(arguments[0]+'-modal'),i=window.bootstrap.Modal.getInstance(m);
          return !!i?._isShown && i._isTransitioning===false;
        ''', name), name + ' modal shown transition')

    def team_boundary(self):
        self.enter_team()
        value = self.driver.execute_script('''
          const home=document.getElementById('home-view');
          return {submissions:!!home.querySelector('#submissions-table'),
            administration:home.querySelectorAll('#rankland-settings,#open-resources,#new-session,#start-session,#finish-session,#delete-session').length,
            jury:document.getElementById('jury-view').hidden,
            trophyCreation:!!document.querySelector('#session-select #new-session')};
        ''')
        require(value['submissions'] and value['administration'] == 0 and value['jury'] and not value['trophyCreation'],
                'Team Home still exposes contest administration')
        return value

    def create_contest(self):
        from selenium.webdriver.common.by import By
        self.driver.find_element(By.ID, 'nav-jury').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-list-view').is_displayed(), 'Jury list')
        self.driver.find_element(By.ID, 'new-session').click()
        self.modal_ready('session')
        self.driver.find_element(By.ID, 'contest-input').send_keys('3387')
        self.driver.find_element(By.ID, 'load-contest').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'prepare-session').is_enabled(), 'authenticated contest preview')
        title = self.driver.find_element(By.ID, 'session-title')
        title.clear(); title.send_keys('Administrator flow fixture')
        minutes = self.driver.find_element(By.ID, 'duration-input')
        minutes.clear(); minutes.send_keys('90')
        self.driver.find_element(By.ID, 'prepare-session').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-detail-view').is_displayed() and
                  self.ui_state()['session']['title'] == 'Administrator flow fixture', 'created contest in Jury details')
        self.wait(lambda: not self.driver.find_element(By.ID, 'session-modal').is_displayed(), 'setup modal hidden')
        session = self.ui_state()['session']
        require(session['state'] == 'prepared' and session['startAt'] is None, 'Creating a contest started its clock')
        return {'sessionId': session['sessionId'], 'state': session['state'], 'normalUiCreation': True}

    def configure_contest(self):
        from selenium.webdriver.common.by import By
        for element_id, value in [('jury-title-input', 'Administrator edited fixture'), ('jury-duration-input', '91')]:
            field = self.driver.find_element(By.ID, element_id)
            field.clear(); field.send_keys(value)
        self.driver.find_element(By.ID, 'jury-config-save').click()
        self.wait(lambda: self.ui_state()['session']['title'] == 'Administrator edited fixture' and
                  self.ui_state()['session']['durationMs'] == 5460000 and
                  self.driver.find_element(By.ID, 'jury-config-save').is_enabled(), 'saved configuration and editable prepared fields')
        require(self.driver.find_element(By.ID, 'jury-title-input').is_enabled(), 'Saving left the prepared form locked')
        self.driver.save_screenshot(str(self.results / 'jury-contest.png'))
        return {'title': self.ui_state()['session']['title'], 'durationMs': 5460000}

    def open_manual(self, pid):
        from selenium.webdriver.common.by import By
        self.wait_resource_modal()
        selector = f'[data-manual-samples="{pid}"]'
        # A shown Bootstrap instance can precede the compositor's final table
        # layout after switching between two modals. Observe the actual pointer
        # target and stable geometry, then make exactly one normal WebDriver
        # click. Persistent overlap remains a failure, never a JS click/retry.
        observations = []
        stable_since = None
        previous = None

        def pointer_ready():
            nonlocal stable_since, previous
            value = self.driver.execute_script('''
              const e=document.querySelector(arguments[0]),r=e?.getBoundingClientRect();
              if(!r)return null;
              const x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
              return {rect:{x:r.x,y:r.y,width:r.width,height:r.height},
                hit:hit?.tagName||null,ready:!e.disabled&&r.width>0&&r.height>0&&
                x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&(hit===e||e.contains(hit))};
            ''', selector)
            if not observations or observations[-1] != value:
                observations.append(value)
            self.summary['manualButtonPointerObservations'] = observations[-20:]
            if value and value['ready'] and value == previous:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= .2:
                    return True
            else:
                stable_since = None
            previous = value
            return False
        self.wait(pointer_ready, 'stable, unobscured real manual-samples button')
        self.driver.find_element(By.CSS_SELECTOR, selector).click()
        self.modal_ready('manual-samples')

    def paste_samples(self, pid):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import Select
        self.open_manual(pid)
        Select(self.driver.find_element(By.ID, 'manual-samples-mode')).select_by_value('text')
        self.driver.find_element(By.ID, 'manual-sample-input').send_keys('2 3\n')
        self.driver.find_element(By.ID, 'manual-sample-output').send_keys('5\n')
        self.driver.find_element(By.ID, 'manual-samples-save').click()
        self.wait(lambda: self.prepared_entry(pid) and self.prepared_entry(pid).get('manualSamples') is True,
                  'saved pasted sample resource')
        self.wait_resource_modal()
        return {'problemId': pid, 'manualSamples': True, 'entry': self.prepared_entry(pid)}

    def upload_files_preserving_attachment(self, fixture):
        from selenium.webdriver.common.by import By
        self.prepare_one(1, fixture.b, 'ready', 'attachment', interactive=True)
        before = self.prepared_entry(fixture.b)
        attachment = next(item for item in before['downloads'] if item['kind'] == 'attachment')
        self.open_manual(fixture.b)
        folder = self.state / 'manual-input'; folder.mkdir(exist_ok=True)
        files = [folder / 'case.in', folder / 'case.out']
        files[0].write_bytes(b'9 1\r\n'); files[1].write_bytes(b'10\n')
        self.driver.find_element(By.ID, 'manual-samples-files').send_keys('\n'.join(map(str, files)))
        self.driver.find_element(By.ID, 'manual-samples-save').click()
        self.wait(lambda: self.prepared_entry(fixture.b).get('manualSamples') is True, 'uploaded paired samples')
        self.wait_resource_modal()
        after = self.prepared_entry(fixture.b)
        require(next(item for item in after['downloads'] if item['kind'] == 'attachment') == attachment,
                'Manual sample import changed the existing interactor attachment')
        return {'problemId': fixture.b, 'attachmentPreserved': True, 'manualSamples': True}

    def replace_zip_with_confirmation(self, pid):
        from selenium.webdriver.common.by import By
        before = self.prepared_entry(pid)
        self.open_manual(pid)
        sample_zip = self.state / 'replacement.zip'
        sample_zip.write_bytes(zipped({'another.in': b'7 8\n', 'another.out': b'15\n'}))
        self.driver.find_element(By.ID, 'manual-samples-files').send_keys(str(sample_zip))
        require(self.driver.find_element(By.ID, 'manual-samples-replace-group').is_displayed(), 'Existing samples do not require replacement confirmation')
        self.driver.find_element(By.ID, 'manual-samples-save').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'manual-samples-error').is_displayed(), 'explicit overwrite confirmation error')
        require(self.prepared_entry(pid)['resourceId'] == before['resourceId'], 'Unconfirmed replacement modified samples')
        self.driver.find_element(By.ID, 'manual-samples-replace').click()
        self.driver.find_element(By.ID, 'manual-samples-save').click()
        self.wait(lambda: self.prepared_entry(pid)['resourceId'] != before['resourceId'], 'confirmed ZIP replacement')
        self.wait_resource_modal()
        return {'problemId': pid, 'unconfirmedReplacementRejected': True, 'confirmedZipImported': True}

    def lifecycle_and_delete(self, session_id, sibling_id):
        from selenium.webdriver.common.by import By
        self.driver.find_element(By.ID, 'start-session').click()
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        WebDriverWait(self.driver, 10).until(EC.alert_is_present()).accept()
        self.wait(lambda: self.ui_state()['session']['state'] == 'running', 'running contest')
        require(not self.driver.find_element(By.ID, 'delete-session').is_enabled(), 'Running contest allows deletion')
        self.driver.find_element(By.ID, 'finish-session').click()
        WebDriverWait(self.driver, 10).until(EC.alert_is_present()).accept()
        self.wait(lambda: self.ui_state()['session']['state'] == 'finished', 'finished contest')
        session = self.ui_state()['session']
        require(session.get('finishedAt') and session['durationMs'] == 5460000, 'Finish lost the anchor or changed the configured duration')
        require(self.driver.find_element(By.ID, 'timeleft').text == 'contest ended', 'Finished contest is still counting down')
        progress = self.driver.find_element(By.ID, 'contest-progress').get_attribute('style')
        time.sleep(1.1)
        require(progress == self.driver.find_element(By.ID, 'contest-progress').get_attribute('style'), 'The ended progress bar did not freeze')
        self.driver.find_element(By.ID, 'delete-session').click()
        self.modal_ready('delete-contest')
        self.driver.find_element(By.ID, 'delete-contest-confirm').click()
        self.driver.find_element(By.ID, 'delete-contest-send').click()
        self.wait(lambda: self.driver.find_element(By.ID, 'jury-list-view').is_displayed() and
                  not self.driver.find_elements(By.CSS_SELECTOR, f'[data-jury-session="{session_id}"]'), 'deleted contest absent from Jury list')
        self.wait(lambda: not self.driver.find_element(By.ID, 'delete-contest-modal').is_displayed(), 'delete modal hidden')
        saved = self.driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          browser.storage.local.get(['sessions','vpUiActiveSession','vpUiSubmissionIntents']).then(done);
        ''')
        require(all(item['sessionId'] != session_id for item in saved.get('sessions', [])), 'Background session cache resurrected the deleted contest')
        require(saved.get('vpUiActiveSession') != session_id and
                all(item.get('sessionId') != session_id for item in saved.get('vpUiSubmissionIntents', [])), 'Deleted active-session or intent remained')
        remaining = self.call('list_sessions')['sessions']
        require([item['sessionId'] for item in remaining] == [sibling_id], 'Deletion removed the sibling fixture or kept the target')
        self.driver.refresh()
        self.running_session_id = self.prepared_session_id = sibling_id
        self.wait_boot_ready()
        require(self.ui_state()['session']['sessionId'] == sibling_id, 'Reload restored the deleted contest')
        return {'runningDeleteDisabled': True, 'finishedAt': session['finishedAt'], 'clockFrozen': True,
                'deletedOnlyRequestedSession': True, 'browserCacheCleared': True, 'reloadPreservedSibling': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--configuration', type=Path)
    args = parser.parse_args()
    harness = AdminHarness(args.project)
    fixture = None
    try:
        configuration = json.loads((args.configuration or harness.project / 'tests/browser/visual-reference/rendered/configuration.json').read_text())
        fixture = ResourceFixture(configuration).start()
        for name, action in [('isolated_alias_product_bytes_and_native_host', lambda: harness.setup_visual(fixture)),
                             ('headless_private_firefox', harness.start_browser), ('temporary_admin_alias_install', harness.install_extension)]:
            require(harness.step(name, action) is not None, name + ' failed')
        require(harness.call('hello').get('fixture') is True, 'Native requests are not isolated')
        account = harness.call('qoj_contest', {'contestId': '3387'})
        sibling = harness.call('create_session', {'contestId': '3387', 'title': 'Retained sibling fixture',
                               'account': account['account'], 'durationMs': 18000000})
        harness.running_session_id = harness.prepared_session_id = sibling['sessionId']
        harness.driver.refresh()
        require(harness.step('initial_fixture_boot', harness.wait_boot_ready) is not None, 'UI did not boot')
        require(harness.step('team_administration_boundary', harness.team_boundary) is not None, 'Team view leaked administration')
        created = harness.step('jury_real_ui_create_contest', harness.create_contest)
        require(created is not None, 'Normal UI contest creation failed')
        session_id = created['sessionId']
        require(harness.step('jury_real_ui_save_configuration', harness.configure_contest) is not None, 'Normal configuration save failed')
        from selenium.webdriver.common.by import By
        harness.driver.find_element(By.ID, 'open-resources').click()
        require(harness.step('jury_paste_samples', lambda: harness.paste_samples(fixture.c)) is not None, 'Paste import failed')
        require(harness.step('jury_paired_upload_preserves_interactor', lambda: harness.upload_files_preserving_attachment(fixture)) is not None,
                'Paired import changed attachments')
        require(harness.step('jury_zip_replace_requires_confirmation', lambda: harness.replace_zip_with_confirmation(fixture.c)) is not None,
                'ZIP replace confirmation failed')
        harness.close_modal('extension', 'admin-resources')
        harness.enter_team()
        harness.driver.find_element(By.ID, 'nav-problems').click()
        harness.wait(lambda: harness.driver.find_element(By.ID, 'problems-view').is_displayed(), 'Team Problemset')
        harness.step('team_download_manual_zip', lambda: harness.download_one(fixture.c,
                     {'samples-C/1.in': b'7 8\n', 'samples-C/1.ans': b'15\n'}, 'samples'))
        harness.step('team_download_manual_pairs', lambda: harness.download_one(fixture.b,
                     {'samples-B/1.in': b'9 1\r\n', 'samples-B/1.ans': b'10\n'}, 'samples'))
        harness.step('team_download_preserved_interactor', lambda: harness.download_one(fixture.b, fixture.expected[fixture.b], 'attachment'))
        harness.driver.save_screenshot(str(harness.results / 'team-manual-samples.png'))
        harness.enter_jury(session_id)
        harness.step('jury_local_start_finish_delete_and_reload', lambda: harness.lifecycle_and_delete(session_id, sibling['sessionId']))
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
            require(fixture is not None and fixture.post_count == 0, 'A POST reached the GET-only judge fixture')
            pids = sorted(set(int(line) for line in harness.helper_pids.read_text().splitlines())) if harness.helper_pids.exists() else []
            return {'qojPostCount': fixture.post_count, 'nativeHelperExits': [process_exit(pid, timeout=12) for pid in pids],
                    'permanentHostUnchanged': (harness.permanent_path.read_bytes() if harness.permanent_path.exists() else None) == harness.permanent_before}
        harness.step('zero_qoj_posts_and_owned_helpers_exit', safety)
        try:
            require(harness.summary['cleanup']['firefox']['status'] == 'passed', 'Keep profile until browser exit confirmed')
            require(harness.profile.parent == harness.state and harness.profile.resolve().is_relative_to(harness.project / 'state/resource-cache'), 'Refusing to clean an unowned profile')
            if harness.profile.exists(): shutil.rmtree(harness.profile)
            harness.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'passed', 'userProfileAccessed': False}
        except Exception as error:
            harness.summary['cleanup']['ownedFirefoxProfile'] = {'status': 'failed', 'errorType': type(error).__name__}
        if fixture: atomic_json(harness.results / 'qoj-fixture-requests.json', fixture.requests)
        failed = [check['name'] for check in harness.summary['checks'] if check['status'] != 'passed']
        harness.summary.update(finishedAt=utc_now(), requiredFailures=failed,
            status='failed' if failed or harness.summary.get('fatalError') or any(value['status'] != 'passed' for value in harness.summary['cleanup'].values()) else 'passed')
        harness.phase = 'finished'; harness.flush()
        print(json.dumps({'status': harness.summary['status'], 'summary': str(harness.results / 'summary.json')}))
    return 0 if harness.summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
