#!/usr/bin/env python3
"""Real file picker -> native QOJ adapter -> loopback judge -> local Board."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT), str(PROJECT/'tests/browser'), str(PROJECT/'tests/browser/vendor_py')]
import guest_visual_parity as visual
from guest_preflight import atomic_json, require, utc_now
from mvp_fixture_server import MvpFixtureServer

visual.HOST = 'org.littledrinks.qoj_vp_submit_qa'
visual.EXTENSION_ID = 'qoj-vp-submit-qa@littledrinks.local'
visual.OWNER = 'QOJ VP isolated submission QA v1'


class Harness(visual.VisualHarness):
    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results/'summary.json', self.summary)
        atomic_json(self.project/'results/submission-flow-summary.json', self.summary)


def main():
    h = Harness(PROJECT, 1440, 1000)
    judge = MvpFixtureServer(judge_after_reads=1).start()
    h.summary.update(realQojSubmissions=0, network='loopback judge only', fixtureCodeSubmissionOnly=True)
    try:
        h.step('isolated_product_install', lambda: h.setup_visual(judge))
        h.step('headless_firefox', h.start_browser)
        h.step('extension_native_connection', h.install_extension)
        require(h.call('hello')['fixture'], 'Fixture helper required before source selection')
        h.call('judger.contest', {'contestId':'3387'})
        session = h.call('create_session', {'contestId':'3387', 'account':judge.account,
            'title':'Synthetic source upload', 'startAt':int(time.time()*1000)-600000})
        sid = session['sessionId']
        h.driver.get(h.ui_url.split('?')[0].split('#')[0]+'?session='+sid+'#home')

        def submit():
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import Select, WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            h.wait(lambda: h.driver.execute_script("return !document.querySelector('#open-submit').disabled && window.qojVpUi.getState().connected"), 'ready submission UI')
            h.driver.find_element(By.ID, 'open-submit').click()
            h.modal_fields('extension', 'generic')
            source = h.state/'synthetic.cpp'
            source.write_text('int main() { return 0; }\n')
            h.driver.find_element(By.ID, 'submit_problem_code').send_keys(str(source))
            Select(h.driver.find_element(By.ID, 'submit_problem_problem')).select_by_value('15419')
            Select(h.driver.find_element(By.ID, 'submit_problem_language')).select_by_visible_text('C++20')
            h.driver.find_element(By.ID, 'submit-send').click()
            alert = WebDriverWait(h.driver, 15).until(EC.alert_is_present())
            require('synthetic.cpp' in alert.text and 'Make submission?' in alert.text, 'Missing source confirmation')
            alert.accept()
            h.wait(lambda: judge.accepted_post_count==1, 'one accepted multipart source upload')
            require(judge.submissions[0]['sourceSha256']==hashlib.sha256(source.read_bytes()).hexdigest(), 'Uploaded bytes changed')
            h.wait(lambda: h.driver.execute_script("return !document.querySelector('#submit-form').hasAttribute('aria-busy')"), 'submit completion')
            return {'acceptedFixturePosts':judge.accepted_post_count, 'sourceBytes':source.stat().st_size}
        h.step('file_selection_confirmation_and_native_post', submit)

        def settle():
            def judged():
                history = h.call('judger.submissions', {'sessionId':sid, 'refresh':True})
                h.summary['lastHistory']=history
                return len(history['submissions'])==1 and history['submissions'][0]['verdict']=='CORRECT'
            h.wait(judged, 'final accepted verdict')
            board = h.call('board.snapshot', {'sessionId':sid})
            require(board['own']['score']==1 and board['own']['penaltyMinutes']==(judge.submissions[0]['submittedAt']-session['startAt'])//60000, 'Board did not use original submit time')
            h.driver.refresh()
            h.wait(lambda: h.driver.execute_script("return document.querySelector('#submissions')?.textContent.includes('CORRECT') || document.body.textContent.includes('CORRECT')"), 'accepted submission after reload')
            require(judge.post_count==1, 'Reload resent the source')
            return {'own':board['own'], 'sourcePostCount':judge.post_count}
        h.step('judgement_board_and_reload_without_resubmit', settle)
    except Exception as error:
        h.summary['fatalError'] = {'type':type(error).__name__, 'message':str(error)}
    finally:
        for name, fn in [('firefox',h.quit_browser), ('nativeManifest',h.cleanup_manifest), ('judge',judge.shutdown)]:
            try: h.summary['cleanup'][name] = {'status':'passed', 'evidence':fn()}
            except Exception as error: h.summary['cleanup'][name] = {'status':'failed', 'error':str(error)}
        if h.profile.exists() and h.summary['cleanup']['firefox']['status']=='passed': shutil.rmtree(h.profile)
        h.summary['status'] = 'failed' if h.summary.get('fatalError') or any(c['status']!='passed' for c in h.summary['checks']) or any(c['status']!='passed' for c in h.summary['cleanup'].values()) else 'passed'
        h.phase = 'finished'; h.flush()
    print(json.dumps({'status':h.summary['status'], 'summary':str(h.results/'summary.json')}))
    return h.summary['status']!='passed'


if __name__=='__main__': raise SystemExit(main())
