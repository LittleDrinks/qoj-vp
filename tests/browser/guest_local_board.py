#!/usr/bin/env python3
"""Hydro Firefox: real native helper + local SRK renderer, read-only judge fixture."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT), str(PROJECT/'tests/browser'), str(PROJECT/'tests/browser/vendor_py')]
from guest_rankland_sync import Judge
import guest_visual_parity as visual
from guest_preflight import atomic_json, require, utc_now

visual.HOST='org.littledrinks.qoj_vp_board_qa'
visual.EXTENSION_ID='qoj-vp-board-qa@littledrinks.local'
visual.OWNER='QOJ VP isolated local board QA v1'

class Harness(visual.VisualHarness):
    def flush(self):
        self.summary.update(phase=self.phase, updatedAt=utc_now())
        atomic_json(self.results/'summary.json',self.summary)
        atomic_json(self.project/'results/local-board-summary.json',self.summary)


def main():
    h=Harness(PROJECT,1440,1000)
    h.summary.update(schema='qoj-vp-local-board-v1',realFirefox=True,network='GET-only QOJ fixture; cached synthetic SRK',realQojSubmissions=0)
    judge=Judge().start()
    try:
        h.step('isolated_product_install',lambda:h.setup_visual(judge))
        h.step('headless_firefox',h.start_browser)
        h.step('extension_native_connection',h.install_extension)
        require(h.call('hello')['fixture'],'Fixture helper required')
        if h.driver.execute_script('return typeof VpBoardView;')=='undefined':
            failure=h.driver.execute_async_script("""
              const done=arguments[arguments.length-1];
              window.addEventListener('error',event=>done({error:event.message,stack:event.error?.stack}),{once:true});
              const script=document.createElement('script');script.src='board/generated/view.js';
              script.onload=()=>done({loaded:true,type:typeof VpBoardView});document.head.append(script);
            """)
            raise AssertionError('Renderer initialization: '+str(failure))
        h.call('judger.contest',{'contestId':'3387'})
        start=int(time.time()*1000)-7200000
        session=h.call('create_session',{'contestId':'3387','account':judge.account,'title':'Local Board QA',
            'startAt':start,'durationMs':18000000,'ranklandUrl':'https://vp.xcpc.link/?contest=board-fixture',
            'board':{'rule':'ICPC'}})
        sid=session['sessionId']
        archive={'version':'0.3.14','type':'general','contest':{'title':'Historical fixture','startAt':'2020-01-01T00:00:00Z','duration':[5,'h']},
            'problems':[{'alias':'A'},{'alias':'B'}],'series':[{'title':'Rank','rule':{'preset':'Normal'}}],
            'sorter':{'algorithm':'ICPC','config':{'penalty':[20,'min'],'timePrecision':'min'}},
            'rows':[{'user':{'id':'other','name':'Historical opponent'},'score':{'value':1,'time':[30,'min']},
                     'statuses':[{'result':'AC','tries':1,'time':[30,'min'],'solutions':[{'result':'AC','time':[30,'min']}]},{'solutions':[]}]}]}
        # Populate the real extension-origin IndexedDB before its first board read.
        result=h.driver.execute_async_script('''
          const done=arguments[arguments.length-1],record=arguments[0];
          const r=indexedDB.open('qoj-vp-board',1);
          r.onupgradeneeded=()=>r.result.createObjectStore('archives');
          r.onerror=()=>done({error:String(r.error)});
          r.onsuccess=()=>{const db=r.result,tx=db.transaction('archives','readwrite');
            tx.objectStore('archives').put(record,'https://vp.xcpc.link:board-fixture');
            tx.oncomplete=()=>{db.close();done({ok:true});};tx.onerror=()=>done({error:String(tx.error)});};
        ''',{'archive':archive,'hash':'synthetic-qa','contestKey':'board-fixture','fetchedAt':int(time.time()*1000)})
        require(result.get('ok'),'Cache setup failed: '+str(result))
        judge.rows=[{'id':'1000001','label':'A','pid':'15419','at':start+600000,'verdict':'Judging'},
                    {'id':'1000002','label':'A','pid':'15419','at':start+1200000,'verdict':'AC'}]

        def read():
            h.call('judger.submissions',{'sessionId':sid,'refresh':True})
            return h.call('board.snapshot',{'sessionId':sid})
        def pending():
            b=read()
            require(b['own']['score']==1 and b['own']['penaltyMinutes']==20 and b['provisional'],'Pending inflated penalty')
            require(b['own']['rank']==1 and b['scope']=='historical','Historical source not consumed')
            return {'own':b['own'],'scope':b['scope'],'provisional':b['provisional']}
        h.step('pending_before_ac',pending)
        def late():
            judge.rows[0]['verdict']='WA'
            b=read()
            require(b['own']['penaltyMinutes']==40 and b['own']['rank']==2,'Late verdict did not recompute original time')
            h.driver.get(h.ui_url.split('?')[0].split('#')[0]+'?session='+sid+'#scoreboard')
            def rendered():
                return h.driver.execute_script('''return document.querySelector('#board-table')?.textContent.includes('Historical opponent') && document.querySelector('#board-table')?.textContent.includes('SyntheticSyncTeam');''')
            h.wait(rendered,'bundled SRK renderer to show both teams')
            urls=[]
            for handle in h.driver.window_handles:
                h.driver.switch_to.window(handle);urls.append(h.driver.current_url)
            h.focus_ui()
            require(not any(url.startswith('https://vp.xcpc.link') for url in urls),'Board opened an external tab')
            h.driver.save_screenshot(str(h.results/'local-board.png'))
            return {'own':b['own'],'renderer':h.driver.execute_script("return document.querySelector('#board-table').innerText;"),'tabs':len(h.driver.window_handles)}
        h.step('late_wa_and_real_renderer',late)
        def reload():
            h.driver.refresh()
            h.wait(lambda:h.driver.execute_script("return document.querySelector('#board-table')?.textContent.includes('Historical opponent');"),'board after page reload')
            b=h.call('board.snapshot',{'sessionId':sid})
            require(b['own']['rank']==2 and b['own']['penaltyMinutes']==40,'Reload changed rank or penalty')
            return {'rank':b['own']['rank'],'penalty':b['own']['penaltyMinutes']}
        h.step('reload_preserves_board',reload)
        def rule_controls():
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import Select
            h.driver.execute_script("location.hash='#jury';")
            h.wait(lambda:h.driver.find_element(By.ID,'rankland-settings').is_displayed(),'Jury settings')
            h.driver.find_element(By.ID,'rankland-settings').click()
            h.wait(lambda:h.driver.find_element(By.ID,'board-rule').is_displayed(),'board settings modal')
            for rule in ('ICPC','auto','CCPC26','ICPC'):
                Select(h.driver.find_element(By.ID,'board-rule')).select_by_value(rule)
                visible=h.driver.find_element(By.ID,'board-count').is_displayed()
                enabled=h.driver.find_element(By.ID,'board-count').is_enabled()
                require(visible==(rule=='CCPC26') and enabled==(rule=='CCPC26'),'Reveal settings leaked into '+rule)
            h.driver.find_element(By.CSS_SELECTOR,'#rankland-modal [data-bs-dismiss="modal"]').click()
            h.wait(lambda:not h.driver.find_element(By.ID,'rankland-modal').is_displayed(),'settings close')
            return {'rules':['ICPC','auto','CCPC26'],'conditionalRevealControls':True}
        h.step('rule_specific_settings_in_real_firefox',rule_controls)

        def rejudge():
            judge.rows[1]['verdict']='WA'
            b=read()
            require(b['own']['score']==0 and b['own']['penaltyMinutes']==0,'Rejudge retained an AC')
            require(b['own']['progress'][0]['judged']==2,'Rejudge duplicated attempts')
            return b['own']
        h.step('rejudge_replaces_verdict',rejudge)
        def board_does_not_fetch_judge():
            # Isolate this RPC from the workbench's independent five-second
            # judger poll. A static extension document retains runtime access
            # without running UI timers; leave the production scripts intact.
            h.focus_ui()
            h.driver.get(h.ui_url.split('ui.html')[0]+'manifest.json')
            h.driver.execute_async_script("const done=arguments[arguments.length-1];browser.alarms.clear('vp-refresh').then(done);")
            # Join any provider read already started before navigation.
            h.call('judger.submissions',{'sessionId':sid,'refresh':True})
            before=len(judge.requests)
            for _ in range(3): h.call('board.snapshot',{'sessionId':sid})
            require(len(judge.requests)==before,'Board read fetched the judge: '+str(judge.requests[before:]))
            return {'judgeRequests':0,'tabs':len(h.driver.window_handles)}
        h.step('board_judger_decoupling',board_does_not_fetch_judge)
    except Exception as error:
        h.summary['fatalError']={'type':type(error).__name__,'message':str(error)}
        if h.driver:
            try:h.driver.save_screenshot(str(h.results/'failure.png'))
            except Exception:pass
    finally:
        for name,fn in [('firefox',h.quit_browser),('nativeManifest',h.cleanup_manifest),('judge',judge.shutdown)]:
            try:h.summary['cleanup'][name]={'status':'passed','evidence':fn()}
            except Exception as error:h.summary['cleanup'][name]={'status':'failed','error':str(error)}
        h.summary['judgePostCount']=judge.post_count
        if judge.post_count:h.summary['fatalError']={'message':'Unexpected source POST'}
        if h.profile.exists() and h.summary['cleanup']['firefox']['status']=='passed':shutil.rmtree(h.profile)
        h.summary['status']='failed' if h.summary.get('fatalError') or any(c['status']!='passed' for c in h.summary['checks']) or any(c['status']!='passed' for c in h.summary['cleanup'].values()) else 'passed'
        h.phase='finished';h.flush()
    print(json.dumps({'status':h.summary['status'],'summary':str(h.results/'summary.json')}))
    return h.summary['status']!='passed'

if __name__=='__main__':raise SystemExit(main())
