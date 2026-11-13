#!/usr/bin/env python3
"""Hydro Firefox regression for Board visibility, early finish and external playback."""
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import parse_qs, urlsplit

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT/'src'), str(PROJECT/'tests/browser'), str(PROJECT/'tests/browser/vendor_py')]
from guest_board_parity import Harness, Judge, Reference, visual, seek
from guest_preflight import atomic_json, require


def main():
    visual.HOST = 'org.littledrinks.qoj_vp_board_lifecycle_qa'
    visual.EXTENSION_ID = 'qoj-vp-board-lifecycle-qa@littledrinks.local'
    visual.OWNER = 'QOJ VP isolated Board lifecycle QA'
    h = Harness(PROJECT, 1440, 1000)
    judge, reference = Judge().start(), Reference().start()
    report = {'checks': [], 'realQojSubmission': False}
    output = PROJECT/'results/board-lifecycle'
    output.mkdir(parents=True, exist_ok=True)
    try:
        h.setup_visual(judge)
        (h.profile/'user.js').write_text('user_pref("xpinstall.signatures.required", false);\n')
        h.start_browser(); h.install_extension()
        h.call('judger.contest', {'contestId': '3387'})
        start = int(time.time()*1000) - 20*60000
        session = h.call('create_session', {'contestId': '3387', 'account': judge.account,
            'title': 'Board lifecycle', 'startAt': start, 'durationMs': 18000000,
            'ranklandUrl': reference.origin+'/?contest=qoj-preflight-fixture', 'board': {'rule': 'ICPC'}})
        sid = session['sessionId']
        archive = json.loads((PROJECT/'tests/browser/rankland-fixtures/feed.srk.json').read_text())
        archive['rows'] = [{'user': {'id': 'other', 'name': 'Historical opponent'}, 'score': {'value': 2},
            'statuses': [{'solutions': [{'result': 'AC', 'time': [60, 'min']}]},
                         {'solutions': [{'result': 'AC', 'time': [250, 'min']}]}]}]
        reference.archive = archive
        record = {'archive': archive, 'hash': 'lifecycle', 'contestKey': 'qoj-preflight-fixture', 'fetchedAt': int(time.time()*1000)}
        require(h.driver.execute_async_script('''const done=arguments[arguments.length-1],record=arguments[0],key=arguments[1];
          const r=indexedDB.open('qoj-vp-board',1);r.onupgradeneeded=()=>r.result.createObjectStore('archives');
          r.onsuccess=()=>{const tx=r.result.transaction('archives','readwrite');tx.objectStore('archives').put(record,key);
            tx.oncomplete=()=>done(true);tx.onerror=()=>done(false);};''', record, reference.origin+':qoj-preflight-fixture'), 'cache setup')
        url = h.ui_url.split('?')[0].split('#')[0]+'?session='+sid+'#scoreboard'
        # Simulate a replay state left by the previous buggy version.
        h.driver.execute_script('localStorage.setItem(arguments[0],JSON.stringify(arguments[1]));',
            'qojVpBoardPlaybackV1:'+sid, {'version': 1, 'startAt': start, 'elapsedMs': 18000000,
                'custom': True, 'speed': 60, 'playing': True, 'savedAt': int(time.time()*1000)})
        h.driver.get(url)
        h.wait(lambda: 'Historical opponent' in h.driver.find_element('tag name', 'body').text, 'live board')
        for selector in ['input[aria-label="Time Travel"]', '[data-id="board-play-toggle"]', '[aria-label="虚拟参赛倍速"]']:
            require(not h.driver.find_element('css selector', '.qoj-board '+selector).is_enabled(), 'Live replay control enabled: '+selector)
        result = h.call('board.snapshot', {'sessionId': sid, 'elapsedMs': 18000000, 'includeHistory': True})
        require(20*60000 <= result['elapsedMs'] < 22*60000, 'API exposed future time')
        opponent = next(row for row in result['ranklist']['rows'] if row['user']['name'] == 'Historical opponent')
        require(opponent['score']['value'] == 0, 'API exposed future results')
        require('05:00:00' not in h.driver.find_element('css selector', '.srk-progress-secondary-area-left').text, 'Restored future replay')
        h.driver.save_screenshot(str(output/'live.png'))
        report['checks'].append({'name': 'live_controls_restore_and_api_boundary', 'elapsedMs': result['elapsedMs'], 'score': 0})
        link = h.driver.find_element('css selector', '[data-id="board-open-rankland"]').get_attribute('href')
        require(parse_qs(urlsplit(link).query)['play'] == ['1'], 'Live link is paused')
        h.driver.switch_to.new_window('tab'); h.driver.get(link)
        h.wait(lambda: h.driver.execute_script('return !!document.querySelector(".srk-progress-secondary-area-left")'), 'external live', 60)
        external = h.driver.find_element('css selector', '.srk-progress-secondary-area-left').text
        require('0:20:' in external or '0:21:' in external, 'Original player opened at wrong time: '+external)
        h.driver.save_screenshot(str(output/'external-live.png'))
        h.driver.close(); h.focus_ui()
        report['checks'].append({'name': 'original_player_follows_confirmed_start', 'elapsed': external})
        finished = h.call('finish_session', {'sessionId': sid})
        require(finished.get('finishedAt') is not None, 'Finish response missing time')
        h.driver.refresh()
        h.wait(lambda: h.driver.execute_script('return window.qojVpUi?.getState().session?.finishedAt != null'), 'finish visible')
        h.wait(lambda: h.driver.find_element('css selector', 'input[aria-label="Time Travel"]').is_enabled(), 'replay enabled')
        seek(h.driver, 300)
        require(not h.driver.find_elements('css selector', '.qoj-board [role="alert"]'), 'Early finish replay error')
        final = h.call('board.snapshot', {'sessionId': sid, 'elapsedMs': 18000000, 'includeHistory': True})
        require(final['elapsedMs'] == 18000000, 'History replay truncated')
        require(next(row for row in final['ranklist']['rows'] if row['user']['name'] == 'Historical opponent')['score']['value'] == 2, 'Full history missing')
        after = h.call('inspect_session', {'sessionId': sid})
        require(after['finishedAt'] == finished['finishedAt'] and after['startAt'] == start, 'Replay changed lifecycle')
        h.driver.save_screenshot(str(output/'early-finish-replay.png'))
        final_url = reference.origin+'/ranklist/qoj-preflight-fixture'
        for selector in ['#nav-rankland', '#scoreboard-source-link', '[data-id="board-open-rankland"]']:
            require(h.driver.find_element('css selector', selector).get_attribute('href') == final_url,
                    'Final standings link differs: '+selector)
        report['checks'].append({'name': 'final_standings_from_navigation_jury_and_full_replay', 'url': final_url})
        seek(h.driver, 125)
        link = h.driver.find_element('css selector', '[data-id="board-open-rankland"]').get_attribute('href')
        require(parse_qs(urlsplit(link).query)['from'] == ['125'], 'Replay link lost display time')
        require(h.driver.find_element('id', 'nav-rankland').get_attribute('href') == final_url,
                'Explicit replay changed the navigation final standings')
        h.driver.switch_to.new_window('tab'); h.driver.get(link)
        h.wait(lambda: h.driver.execute_script('return document.querySelector(".srk-progress-secondary-area-left")?.textContent.includes("2:05:00")'), 'external replay', 60)
        h.driver.save_screenshot(str(output/'external-replay.png'))
        h.driver.close(); h.focus_ui()
        report['checks'].append({'name': 'early_finish_full_replay_and_external_position', 'finishedAt': finished['finishedAt'], 'elapsedMs': final['elapsedMs']})
        h.call('update_session', {'sessionId': sid, 'board': {'rule': 'CCPC26', 'revealCount': 1000, 'revealRatio': 100}})
        h.driver.refresh()
        h.wait(lambda: bool(h.driver.find_elements('css selector', '.qoj-ccpc26-note')), 'CCPC26 view')
        def aliases():
            return [e.text.split('\n')[0] if e.text else '' for e in h.driver.find_elements('css selector', '.qoj-board .srk-main thead .srk-problem-header')]
        seek(h.driver, 239)
        h.wait(lambda: aliases() == ['', ''], 'anonymous columns before freeze')
        seek(h.driver, 240)
        h.wait(lambda: aliases() == ['A', 'B'], 'all problem aliases at freeze')
        h.driver.save_screenshot(str(output/'ccpc26-freeze-reveals-all.png'))
        seek(h.driver, 239)
        h.wait(lambda: aliases() == ['', ''], 'reverse playback restores anonymous columns')
        report['checks'].append({'name': 'ccpc26_freeze_boundary_and_reverse_playback', 'freezeMinutes': 240, 'revealed': ['A', 'B']})
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
        if h.driver: h.driver.save_screenshot(str(output/'failure.png'))
    finally:
        report['cleanup'] = {}
        for name, fn in [('firefox', h.quit_browser), ('nativeManifest', h.cleanup_manifest), ('judge', judge.shutdown), ('reference', reference.shutdown)]:
            try: report['cleanup'][name] = {'status': 'passed', 'evidence': fn()}
            except Exception as error:
                report['cleanup'][name] = {'status': 'failed', 'error': str(error)}; report['status'] = 'failed'
        report['judgePostCount'], report['referencePostCount'] = judge.post_count, reference.post_count
        if judge.post_count or reference.post_count: report['status'] = 'failed'
        if h.profile.exists() and report['cleanup']['firefox']['status'] == 'passed': shutil.rmtree(h.profile)
        atomic_json(output/'summary.json', report)
    print(json.dumps(report))
    return report['status'] != 'passed'


if __name__ == '__main__': raise SystemExit(main())
