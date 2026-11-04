#!/usr/bin/env python3
"""Narrow real-Firefox RankLand no-team regression; run inside the guest.

Uses VisualHarness's isolated alias/native fixture transport. QOJ is GET-only;
one synthetic already-judged fact is discovered through real history parsing.
RankLand itself is the live original application in a unique local run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py')]

import guest_visual_parity as visual
from guest_preflight import atomic_json, process_exit, require, utc_now
from rankland_readiness_probe import inspect_rankland_readiness

# Process-local namespace substitutions preserve the real product code apart
# from the same two aliases verified by VisualHarness. No permanent host edit.
visual.HOST = 'org.littledrinks.qoj_vp_rankland_qa'
visual.EXTENSION_ID = 'qoj-vp-rankland-qa@littledrinks.local'
visual.OWNER = 'QOJ VP isolated RankLand readiness native host v1'


class RanklandFixture(visual.VisualQojFixture):
    def __init__(self, configuration):
        super().__init__(configuration)
        self.account = 'csj-rankland-test'
        self.include_verdict = False
        self.submitted_at = int(time.time() * 1000) - 60000

    def response(self, path, xhr):
        if path == '/contest/3387/submissions' and self.include_verdict:
            first = self.problems[0]
            stamp = datetime.fromtimestamp(self.submitted_at / 1000, timezone.utc).isoformat(timespec='milliseconds')
            body = ('<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th>'
                '<th>Result</th><th>Language</th><th>Time</th></tr></thead><tbody>'
                '<tr><td><a href="/submission/1000001">1000001</a></td>'
                '<td><a href="/user/profile/' + self.account + '">' + self.account + '</a></td>'
                '<td><a href="/contest/3387/problem/' + str(first['probid']) + '">'
                + html.escape(first['label']) + '</a></td><td>100</td><td>C++20</td>'
                '<td><time datetime="' + stamp + '">' + stamp + '</time></td></tr></tbody></table>')
            return 200, body.encode(), 'text/html; charset=utf-8'
        return super().response(path, xhr)


class RanklandHarness(visual.VisualHarness):
    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/rankland-readiness-summary.json', self.summary)
        atomic_json(self.project / 'results/rankland-readiness-status.json', {
            'runId': self.run_id, 'phase': self.phase, 'status': self.summary.get('status', 'running'),
            'summary': str(self.results / 'summary.json'),
            'checks': [{'name': c['name'], 'status': c['status']} for c in self.summary['checks']]})

    def bridge_ready(self, session):
        self.focus_ui()
        return self.driver.execute_async_script('''
          const done=arguments[arguments.length-1], expected=arguments[0], sessionId=arguments[1];
          browser.tabs.query({}).then(tabs=>{
            const tab=tabs.find(t=>{try{return new URL(t.url).searchParams.get('run')===sessionId
              && new URL(t.url).origin==='https://vp.xcpc.link';}catch(_){return false;}});
            if(!tab)return done({bridgeError:'TAB_MISSING'});
            browser.tabs.sendMessage(tab.id,{type:'vp.rankland.ready',sessionId,expectedUrl:expected})
              .then(done,()=>done({bridgeError:'NO_RECEIVER'}));
          },()=>done({bridgeError:'TABS_UNAVAILABLE'}));
        ''', session['ranklandUrl'], session['sessionId'])

    def snapshot(self, session, label):
        self.rankland_handle(session)
        value = inspect_rankland_readiness(self.driver)
        atomic_json(self.results / (label + '.json'), value)
        self.driver.save_screenshot(str(self.results / (label + '.png')))
        return value

    def original_state(self, session):
        self.rankland_handle(session)
        return self.driver.execute_script('''
          const run=arguments[0], keys=Object.keys(localStorage)
            .filter(k=>k.startsWith('RanklandVP2:') && k.includes(':'+run+':'));
          if(keys.length!==1)return null;
          return {key:keys[0],value:JSON.parse(localStorage.getItem(keys[0]))};
        ''', session['sessionId'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--mode', choices=['reproduce', 'verify'], required=True)
    args = parser.parse_args()
    h = RanklandHarness(args.project, 1440, 1000)
    h.summary.update(schema='qoj-rankland-no-team-regression-v1', mode=args.mode,
        qojGetOnly=True, realRankland=True, sourceFilesSelected=0)
    fixture = None
    reproduced = False
    try:
        configuration = json.loads((h.project / 'tests/browser/visual-reference/rendered/configuration.json').read_text())
        fixture = RanklandFixture(configuration).start()
        require(h.step('isolated_alias_product_bytes_and_native_setup', lambda: h.setup_visual(fixture)) is not None,
                'Isolated setup failed')
        require(h.step('independent_actual_headless_firefox', h.start_browser) is not None, 'Firefox did not start')
        require(h.step('temporary_alias_product_extension', h.install_extension) is not None, 'Alias addon did not connect')
        hello = h.call('hello')
        require(hello.get('fixture') is True, 'Refusing a native helper outside the loopback GET fixture')
        contest = h.call('qoj_contest', {'contestId': '3387'})
        require(contest['account'] == fixture.account, 'Synthetic fixture account was not authenticated')
        raw_url = 'https://vp.xcpc.link/?' + urlencode({'contest': 'icpc2025nanjing', 'rule': 'ICPC'})
        session = h.call('create_session', {'contestId': '3387', 'title': 'RankLand no-team readiness QA',
            'account': fixture.account, 'startAt': int(time.time() * 1000) - 7200000,
            'durationMs': 18000000, 'ranklandUrl': raw_url})
        require('team' not in parse_qs(urlsplit(session['ranklandUrl']).query), 'Input unexpectedly provided a team')
        h.call('rankland.open', {'sessionId': session['sessionId']})
        session = h.call('inspect_session', {'sessionId': session['sessionId']})
        h.rankland_handle(session)
        h.wait(lambda: h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]");'),
               'the original RankLand contest board', timeout=60)
        before = h.snapshot(session, 'initial-original-no-team-board')
        ready = h.bridge_ready(session)
        atomic_json(h.results / 'initial-bridge-ready.json', ready)

        if args.mode == 'reproduce':
            # This checks the real old product's exact public failure, rather
            # than changing page storage or constructing a fake native form.
            result = h.call('rankland.sync', {'sessionId': session['sessionId']})
            current = h.snapshot(session, 'legacy-no-team-not-ready')
            require(result.get('state') == 'page_not_ready' and ready.get('ready') is False,
                    'The old production readiness failure was not reproduced')
            require(current['boardPresent'] and current['problemSelects'] == 0
                    and current['controls']['加入我的队伍'] == 1
                    and len(current['slots']) == 1 and current['slots'][0]['ownNameNonempty'] is False,
                    'The failure is not the missing-own-team path')
            h.summary['redEvidence'] = {'result': result, 'readiness': ready,
                'reasonFromOriginalDom': 'TEAM_REQUIRED', 'originalState': current}
            reproduced = True
        else:
            def prepared():
                result = h.call('rankland.sync', {'sessionId': session['sessionId']})
                require(result.get('state') == 'ready', 'Production did not prepare the original team form: ' + str(result))
                state = h.original_state(session)
                require(state and state['value']['ownName'] == fixture.account and state['value']['manual'] == [],
                        'The original UI did not persist the authenticated synthetic team without adding a verdict')
                value = h.snapshot(session, 'prepared-original-team')
                require(value['problemSelectsVisible'] == 1 and value['resultSelectsVisible'] == 1,
                        'Original record controls were not rendered')
                return {'result': result, 'readiness': h.bridge_ready(session), 'originalState': value}
            require(h.step('no_team_url_bootstraps_using_original_join_form', prepared) is not None,
                    'No-team original form bootstrap failed')

            fixture.include_verdict = True
            history = h.call('qoj_submissions', {'sessionId': session['sessionId'], 'refresh': True})
            require(len(history['submissions']) == 1 and history['submissions'][0]['verdict'] == 'CORRECT',
                    'Real QOJ history parsing did not produce the one synthetic final fact')

            def deliver():
                result = h.call('rankland.sync', {'sessionId': session['sessionId']})
                require(result.get('state') == 'ready', 'Original-site verdict sync did not complete: ' + str(result))
                state = h.original_state(session)
                require(state and len(state['value']['manual']) == 1
                        and state['value']['manual'][0]['result'] == 'AC', 'Exactly one original manual verdict was not saved')
                h.snapshot(session, 'one-original-manual-verdict')
                return {'result': result, 'manualCount': 1, 'ownNamePreserved': state['value']['ownName'] == fixture.account}
            require(h.step('get_only_fixture_final_verdict_uses_original_record_form_once', deliver) is not None,
                    'Single verdict delivery failed')

            def verify_score_snapshot():
                old = h.original_state(session)
                attempts = []

                def original_metrics():
                    h.rankland_handle(session)
                    original = inspect_rankland_readiness(h.driver)
                    rows = [row for row in original['ownRows'] if row.get('valid') and row.get('visible')]
                    require(len(rows) == 1 and rows[0]['ranks'], 'Original own-team score row is missing or ambiguous')
                    row = rows[0]
                    require(row['score'] == '1' and row['penaltyMinutes'].isdigit()
                            and row['ranks'][0]['text'].isdigit(), 'Original score fields are not numeric')
                    return {'rank': int(row['ranks'][0]['text']), 'score': int(row['score']),
                            'penaltyMinutes': int(row['penaltyMinutes'])}

                for attempt in range(6):
                    before = original_metrics()
                    result = h.call('rankland.snapshot', {'sessionId': session['sessionId']})
                    after = original_metrics()
                    snapshot = result.get('snapshot') or {}
                    attempts.append({'attempt': attempt + 1, 'before': before, 'after': after,
                                     'product': result, 'stable': before == after})
                    atomic_json(h.results / 'score-comparison-attempts.json', attempts)
                    require(result.get('state') == 'live', 'Product did not return a live original-site snapshot: ' + str(result))
                    if before == after:
                        require(all(snapshot.get(key) == value for key, value in after.items()),
                                'Product snapshot differs from stable original rank/score/penalty: ' + str(result))
                        break
                else:
                    raise AssertionError('Original rankings changed during all six snapshot comparisons')
                current = h.original_state(session)
                require(current['key'] == old['key'] and current['value']['manual'] == old['value']['manual'],
                        'Reading the score snapshot changed the original manual submissions')
                atomic_json(h.results / 'production-score-snapshot.json', result)
                h.snapshot(session, 'original-score-row')
                return {'primaryRank': snapshot['rank'], 'score': snapshot['score'],
                        'penaltyMinutes': snapshot['penaltyMinutes'], 'sameManualSubmissions': True,
                        'stableComparisonAttempts': len(attempts)}

            require(h.step('score_snapshot_matches_original_dom_without_writing_verdicts', verify_score_snapshot) is not None,
                    'Original score snapshot regression failed')

            def preserve_existing_team_and_reopen():
                from selenium.webdriver.common.by import By
                from rankland_probe import _click_text
                custom = 'qoj-existing-team-' + h.run_id[:12]
                h.rankland_handle(session)
                _click_text(h.driver, '修改队伍信息')
                field = h.wait(lambda: next((e for e in h.driver.find_elements(By.CSS_SELECTOR,
                    'input[aria-label="队伍名称"]') if e.is_displayed()), None), 'original team name dialog')
                field.clear()
                field.send_keys(custom)
                _click_text(h.driver, '保存')
                h.wait(lambda: (lambda state: state and state['value']['ownName'] == custom)(h.original_state(session)),
                       'original custom team name saved')
                old = h.original_state(session)
                old_handle = h.driver.current_window_handle
                h.driver.close()
                h.driver.switch_to.window(h.ui_handle)
                h.call('rankland.open', {'sessionId': session['sessionId']})
                result = h.call('rankland.sync', {'sessionId': session['sessionId']})
                require(result.get('state') == 'ready', 'Reopening the original replay did not become ready')
                current = h.original_state(session)
                require(current and current['key'] == old['key'] and current['value']['ownName'] == custom
                        and current['value']['manual'] == old['value']['manual'] and len(current['value']['manual']) == 1,
                        'Reopen changed the original team, storage identity or duplicated manual verdicts')
                require(h.driver.current_window_handle != old_handle, 'The original tab was not replaced')
                h.snapshot(session, 'reopened-custom-team-and-single-verdict')
                return {'result': result, 'sameStorageIdentity': True, 'customExistingTeamPreserved': True,
                        'manualCount': 1, 'newOriginalTab': True}
            require(h.step('reopen_preserves_existing_team_and_deduplicates_fact', preserve_existing_team_and_reopen) is not None,
                    'Existing-team reopen/deduplication failed')
    except Exception as exc:
        h.summary['fatalError'] = {'type': type(exc).__name__, 'message': str(exc)[:1400]}
        if h.driver:
            try:
                h.driver.save_screenshot(str(h.results / 'failure.png'))
            except Exception:
                pass
    finally:
        for name, fn in [('firefox', h.quit_browser), ('fixtureServer', lambda: fixture.shutdown() if fixture else None),
                         ('ownedAliasAndPermanentHost', h.cleanup_manifest)]:
            try:
                h.summary['cleanup'][name] = {'status': 'passed', 'evidence': fn()}
            except Exception as exc:
                h.summary['cleanup'][name] = {'status': 'failed', 'errorType': type(exc).__name__}
        try:
            require(fixture is not None and fixture.post_count == 0, 'A POST reached the GET-only QOJ fixture')
            pids = sorted(set(map(int, h.helper_pids.read_text().splitlines()))) if h.helper_pids.exists() else []
            exits = [process_exit(pid, timeout=12) for pid in pids]
            h.summary['safety'] = {'qojPostCount': 0, 'sourceFilesSelected': 0, 'nativeHelperExits': exits}
            require(h.summary['cleanup']['firefox']['status'] == 'passed', 'Browser exit was not confirmed')
            require(h.profile.resolve().is_relative_to(h.project / 'state/visual-parity')
                    and h.profile.parent == h.state and h.profile.name == 'firefox-profile', 'Unowned profile cleanup refused')
            if h.profile.exists():
                shutil.rmtree(h.profile)
            h.summary['cleanup']['ownedProfile'] = {'status': 'passed', 'isolatedProfileRemoved': True}
        except Exception as exc:
            h.summary['cleanup']['safety'] = {'status': 'failed', 'errorType': type(exc).__name__}
        failed = any(c['status'] != 'passed' for c in h.summary['checks'])
        cleanup_failed = any(c['status'] != 'passed' for c in h.summary['cleanup'].values())
        status = 'failed' if failed or cleanup_failed or h.summary.get('fatalError') else ('reproduced' if reproduced else 'passed')
        h.summary.update(status=status, finishedAt=utc_now())
        h.phase = 'finished'
        h.flush()
        print(json.dumps({'status': status, 'summary': str(h.results / 'summary.json')}))
    return 0 if h.summary['status'] in {'passed', 'reproduced'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
