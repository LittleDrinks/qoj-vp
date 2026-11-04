#!/usr/bin/env python3
"""Real Hydro Firefox + unmodified RankLand bundle; all judge traffic is GET fixtures."""
from __future__ import annotations
from datetime import datetime, timezone
import html
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlsplit, parse_qs

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py')]
import guest_visual_parity as visual
from guest_preflight import atomic_json, require, utc_now

visual.HOST = 'org.littledrinks.qoj_vp_sync_qa'
visual.EXTENSION_ID = 'qoj-vp-sync-qa@littledrinks.local'
visual.OWNER = 'QOJ VP isolated delayed RankLand sync QA v1'


class Judge(visual.ReadOnlyServer):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.account = 'SyntheticSyncTeam'

    def response_request(self, path, xhr):
        parsed = urlsplit(path)
        if parsed.path == '/contest/3387/submissions' and parse_qs(parsed.query).get('page', ['1']) != ['1']:
            return 200, b'<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Submit time</th></tr></thead><tbody></tbody></table>', 'text/html'
        return self.response(parsed.path, xhr)

    def response(self, path, xhr):
        kind = 'text/html; charset=utf-8'
        if path == '/':
            return 200, ('<ul class="nav nav-pills float-right"><li class="nav-item dropdown">'
                '<a class="nav-link dropdown-toggle" href="//qoj.ac/user/profile/' + self.account + '">' + self.account + '</a>'
                '<ul class="dropdown-menu"><li><a href="//qoj.ac/user/profile/' + self.account + '">个人信息</a></li></ul></li>'
                '<li class="nav-item"><a href="//qoj.ac/logout">退出登录</a></li></ul>').encode(), kind
        if path == '/contest/3387':
            return 200, b'<title>Synthetic synchronization</title><table><tr><td>A</td><td><a href="/contest/3387/problem/15419">A</a></td></tr><tr><td>B</td><td><a href="/contest/3387/problem/15420">B</a></td></tr></table>', kind
        if path == '/contest/3387/submissions':
            rows = []
            for row in sorted(self.rows, key=lambda item: int(item['id']), reverse=True):
                stamp = datetime.fromtimestamp(row['at'] / 1000, timezone.utc).isoformat(timespec='milliseconds')
                rows.append('<tr><td><a href="/submission/{id}">{id}</a></td><td><a href="/user/profile/{account}">{account}</a></td>'
                    '<td><a href="/contest/3387/problem/{pid}">{label}</a></td><td>{verdict}</td><td>C++20</td>'
                    '<td><time datetime="{stamp}">{stamp}</time></td></tr>'.format(account=self.account, stamp=stamp, **row))
            return 200, ('<table><thead><tr><th>ID</th><th>Submitter</th><th>Problem</th><th>Result</th><th>Language</th><th>Submit time</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>').encode(), kind
        if path.startswith('/submission/'):
            row = next((r for r in self.rows if r['id'] == path.rsplit('/', 1)[-1]), None)
            if row:
                detail = {'WA': 'Wrong Answer', 'TL': 'Time Limit Exceeded', 'AC': 'Accepted', 'Judging': 'Judging'}[row['verdict']]
                body = '<div class="card"><div class="card-header">Details</div><div class="card-header">Test #1: score: ' + ('100' if detail == 'Accepted' else '0') + '</div><div class="col-sm-2">' + html.escape(detail) + '</div></div>'
                return 200, body.encode(), kind
        return 404, b'Synthetic fixture route missing', kind


class Board(visual.ReadOnlyServer):
    def response(self, path, xhr):
        root = PROJECT / 'tests/browser/rankland-fixtures'
        if path == '/api/v2/public/contests/qoj-preflight-fixture':
            return 200, (root / 'contest.json').read_bytes(), 'application/json'
        if path == '/':
            path = '/index.html'
        target = (root / path.lstrip('/')).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return 404, b'Not found', 'text/plain'
        kind = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.json':'application/json', '.woff2':'font/woff2'}.get(target.suffix, 'application/octet-stream')
        return 200, target.read_bytes(), kind


class Harness(visual.VisualHarness):
    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results / 'summary.json', self.summary)
        atomic_json(self.project / 'results/rankland-sync-summary.json', self.summary)

    def rankland_handle(self, session, *, navigate=True):
        target = urlsplit(session['ranklandUrl'])
        expected = parse_qs(target.query)
        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            url = urlsplit(self.driver.current_url)
            actual = parse_qs(url.query)
            if url.netloc == target.netloc and actual.get('contest') == expected.get('contest') and actual.get('at') and expected.get('at'):
                if datetime.fromisoformat(actual['at'][0].replace('Z','+00:00')) == datetime.fromisoformat(expected['at'][0].replace('Z','+00:00')):
                    return handle
        if not navigate:
            return None
        self.driver.switch_to.new_window('tab')
        self.driver.get(session['ranklandUrl'])
        return self.driver.current_window_handle

    def archive(self, session):
        self.rankland_handle(session)
        return self.driver.execute_script('''
          const q=new URL(location.href).searchParams,at=new Date(q.get('at')).toISOString();
          const key=`RanklandVP:submissions:${q.get('contest')}:${at}:${q.get('rule')||'auto'}:${Number(q.get('count')??50)}:${Number(q.get('ratio')??20)}`;
          const from=Number(q.get('from')||0)*60000,speed=Number(q.get('speed')||1);
          const play=q.get('play')!=='0',anchor=Date.parse(q.get('anchor')||q.get('at'));
          const elapsed=Math.min(arguments[0],from+(play?Math.max(0,Date.now()-anchor)*speed:0));
          return {key,value:{manual:JSON.parse(localStorage.getItem(key)||'[]'),elapsed,running:play&&elapsed<arguments[0],ownName:q.get('team')},url:location.href};
        ''',session['durationMs'])

    def score(self, session):
        self.rankland_handle(session)
        return self.driver.execute_script('''
          const n=[...document.querySelectorAll('.srk-user-name-text')].find(n=>n.textContent.trim()===arguments[0]);
          if(!n)return null;
          const cells=[...n.closest('tr').cells], i=cells.indexOf(n.closest('td'));
          return {score:Number(cells[i+1].textContent.trim()),penalty:Number(cells[i+2].textContent.trim())};
        ''', 'SyntheticSyncTeam')


def main():
    h = Harness(PROJECT, 1440, 1000)
    h.summary.update(schema='qoj-vp-delayed-sync-v1', realFirefox=True, upstreamRankland=True,
                     network='live RankLand; fixture QOJ' if '--online' in sys.argv else 'loopback fixtures', realQojSubmissions=0)
    h.summary['codeSha256'] = {str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('extension','qojvp') for p in (PROJECT/folder).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts}
    judge, board = Judge().start(), Board().start()
    try:
        h.setup_visual(judge)
        h.start_browser()
        h.install_extension()
        require(h.call('hello')['fixture'], 'Only fixture helpers are allowed')
        require(h.call('qoj_contest', {'contestId':'3387'})['account']==judge.account, 'Fixture account menu did not authenticate')

        def create(start):
            return h.call('create_session', {'contestId':'3387', 'account':judge.account,
                'title':'Delayed verdict integration', 'startAt':start, 'durationMs':18000000,
                'ranklandUrl':('https://vp.xcpc.link/?contest=ccpc2026ladies' if '--online' in sys.argv else board.origin + '/?contest=qoj-preflight-fixture&rule=ICPC')})

        def row(sid, label, elapsed, verdict, start):
            return {'id':str(sid), 'label':label, 'pid':'15419' if label=='A' else '15420', 'at':start+elapsed, 'verdict':verdict}

        def sync(session):
            result = h.call('rankland.sync', {'sessionId':session['sessionId']})
            require(result['state'] in {'ready','waiting'}, 'Sync failed: ' + str(result))
            session.update(h.call('inspect_session', {'sessionId':session['sessionId']}))
            return result

        start = int(time.time()*1000) - 7200000
        session = create(start)
        judge.rows = [row(1000001,'A',1215000,'Judging',start),row(1000002,'A',1325000,'AC',start),row(1000003,'B',1500000,'WA',start)]

        def pending_barrier():
            result=sync(session)
            value=h.archive(session)['value']
            require(result['pending']==1 and len(value['manual'])==1 and value['manual'][0]['problemIndex']==1,
                    'Later AC must wait for earlier same-problem pending; other problem must proceed')
            return {'result':result,'manual':value['manual']}
        h.step('pending_same_problem_barrier',pending_barrier)

        def delayed_wa():
            judge.rows[0]['verdict']='WA'
            result=sync(session)
            manual=h.archive(session)['value']['manual']
            require(len(manual)==3 and any(r['timeMs']==1215000 and r['result']=='WA' for r in manual), 'Original ms missing')
            require(h.score(session)=={'score':1,'penalty':42}, 'Late WA must add original penalty before AC')
            h.driver.save_screenshot(str(h.results/'delayed-wa-recomputed.png'))
            return {'result':result,'score':h.score(session),'manual':manual}
        h.step('late_wa_recomputes_original_rankland',delayed_wa)

        def duplicates_and_retry():
            judge.rows.extend([row(1000004,'B',1500000,'WA',start),row(1000005,'B',1800000,'AC',start)])
            sync(session)
            before=h.archive(session)['value']
            require(len(before['manual'])==5 and h.score(session)=={'score':2,'penalty':112}, 'Both same-second WA must count')
            again=sync(session)
            require(again['synced']==0 and h.archive(session)['value']['manual']==before['manual'], 'Repeat added records')
            return {'score':h.score(session),'retry':again,'manual':before['manual']}
        h.step('same_second_distinct_submissions_and_retry',duplicates_and_retry)

        def rejudge():
            judge.rows[1]['verdict']='TL'
            sync(session)
            manual=h.archive(session)['value']['manual']
            require(len(manual)==5 and h.score(session)=={'score':1,'penalty':70}, 'Old AC was not replaced')
            judge.rows[4]['verdict']='Judging'
            result=sync(session)
            require(len(h.archive(session)['value']['manual'])==4 and h.score(session)['score']==0, 'Rejudging AC was not withdrawn')
            judge.rows[4]['verdict']='AC'
            sync(session)
            return {'pending':result,'score':h.score(session)}
        h.step('replace_and_withdraw_owned_rejudgements',rejudge)

        def manual_record():
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support.ui import Select
            from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
            h.rankland_handle(session)
            Select(h.driver.find_element(By.CSS_SELECTOR,'select[aria-label="题目"]')).select_by_value('0')
            Select(h.driver.find_element(By.CSS_SELECTOR,'select[aria-label="结果"]')).select_by_value('CE')
            for label,value in [('提交时间（时）','0'),('提交时间（分）','10')]:
                control=h.driver.find_element(By.CSS_SELECTOR,'input[aria-label="'+label+'"]')
                # React may restore the current replay hour after clear() emits
                # an empty value. Replace the selection in one keyboard edit;
                # otherwise entering 0 into restored 2 produces 20 hours.
                control.send_keys(Keys.CONTROL,'a',Keys.NULL,value)
                require(control.get_attribute('value')==value,'Manual submission input did not retain '+label)
            def click_record():
                button=h.driver.find_element(By.XPATH,'//button[normalize-space(.)="记录提交"]')
                h.driver.execute_script("arguments[0].scrollIntoView({block:'center'});",button)
                try:
                    button.click()
                    return True
                except (ElementClickInterceptedException, StaleElementReferenceException):
                    # Native WebDriver click must reach the real control after
                    # the sticky toolbar/layout settles, never a JS bypass.
                    return False
            h.wait(click_record,'unobscured original manual-submit control')
            record={'problemIndex':0,'timeMs':600000,'result':'CE'}
            h.wait(lambda: record in h.archive(session)['value']['manual'],'original manual record')
            sync(session)
            after=h.archive(session)['value']['manual']
            require(after.count(record)==1 and len(after)==6,'Original manual submission was changed or lost')
            require(h.score(session)=={'score':1,'penalty':70},'Manual CE changed score')
            return {'manual':record,'total':len(after),'score':h.score(session)}
        h.step('preserves_original_manual_submission',manual_record)

        def reopen():
            before=h.archive(session)['value']['manual']
            h.driver.close()
            result=sync(session)
            require(h.archive(session)['value']['manual']==before and h.score(session)=={'score':1,'penalty':70},'Reopen lost or duplicated progress')
            return {'result':result,'score':h.score(session)}
        h.step('close_reopen_preserves_same_run',reopen)

        def late_after_end():
            h.call('finish_session',{'sessionId':session['sessionId']})
            h.call('archive_session',{'sessionId':session['sessionId']})
            ended_start=int(time.time()*1000)-18120000
            ended=create(ended_start)
            judge.rows=[row(1000010,'A',17980200,'Judging',ended_start)]
            first=sync(ended)
            h.wait(lambda: h.archive(ended)['value']['elapsed']==18000000,'original replay to finish',timeout=15)
            before=h.archive(ended)['value']
            require(not before['running'], 'Original replay is still running')
            h.driver.close()
            judge.rows[0]['verdict']='AC'
            h.focus_ui()
            # The alarm settles the ledger independently of the optional export.
            h.driver.execute_script('browser.alarms.create("vp-refresh",{when:Date.now()+100});')
            def settled():
                snapshot=h.call('session_snapshot',{'sessionId':ended['sessionId']})
                rows=snapshot['history']['submissions']
                return snapshot if any(str(row.get('id'))=='1000010' and row.get('verdict')=='CORRECT' for row in rows) else None
            h.wait(settled,'automatic post-end ledger settlement',timeout=40)
            result=sync(ended)
            after=h.archive(ended)['value']
            require(after['elapsed']==18000000 and not after['running'],'Late result changed ended clock')
            require(after['manual']==[{'problemIndex':0,'timeMs':17980200,'result':'AC'}], 'Late result lost original submission time')
            require(h.score(ended)=={'score':1,'penalty':299},'Ended original scoreboard did not recompute')
            h.driver.save_screenshot(str(h.results/'post-end-settlement.png'))
            return {'first':first,'automaticLedger':True,'explicitExport':True,'result':result,'archive':after,'score':h.score(ended)}
        h.step('post_end_settlement_then_explicit_export',late_after_end)
    except Exception as error:
        h.summary['fatalError']={'type':type(error).__name__,'message':str(error)}
        if h.driver:
            try: h.driver.save_screenshot(str(h.results/'failure.png'))
            except Exception: pass
    finally:
        for name,fn in [('firefox',h.quit_browser),('nativeManifest',h.cleanup_manifest),('judge',judge.shutdown),('board',board.shutdown)]:
            try: h.summary['cleanup'][name]={'status':'passed','evidence':fn()}
            except Exception as error: h.summary['cleanup'][name]={'status':'failed','error':str(error)}
        atomic_json(h.results/'judge-requests.json',judge.requests)
        h.summary['judgePostCount'] = judge.post_count
        if judge.post_count: h.summary['fatalError'] = {'message':'Unexpected source POST in read-only fixture'}
        if h.profile.exists() and h.summary['cleanup']['firefox']['status']=='passed': shutil.rmtree(h.profile)
        h.summary['status']='failed' if h.summary.get('fatalError') or any(c['status']!='passed' for c in h.summary['checks']) or any(c['status']!='passed' for c in h.summary['cleanup'].values()) else 'passed'
        h.phase='finished';h.flush()
    print(json.dumps({'status':h.summary['status'],'summary':str(h.results/'summary.json')}))
    return h.summary['status']!='passed'

if __name__=='__main__':
    raise SystemExit(main())
