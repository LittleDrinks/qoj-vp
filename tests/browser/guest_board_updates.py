#!/usr/bin/env python3
"""Firefox regression for live/replay rank updates and segmented rank columns."""
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'vendor_py'),str(ROOT/'tests/browser/vendor_py')]
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--headed',action='store_true');parser.add_argument('--ui-source',type=Path,default=ROOT/'src/firefox/ui.js');args=parser.parse_args()
    output=ROOT/'results/board-updates';output.mkdir(parents=True,exist_ok=True)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'src/firefox'),**kwargs)
        def log_message(self,*_):pass
        def do_GET(self):
            if self.path=='/':
                page='''<!doctype html><meta charset="utf-8"><title>QOJ VP · 排名更新验证</title><link rel="stylesheet" href="/assets/bootstrap/bootstrap.min.css"><link rel="stylesheet" href="/assets/domjudge/style_domjudge.css"><link rel="stylesheet" href="/ui.css"><link rel="stylesheet" href="/board/generated/view.css"><script src="/board/generated/view.js"></script><script src="/board/generated/engine.js"></script><script src="/scoreboard-sources.js"></script><body class="board-route"><nav class="navbar navbar-dark bg-dark fixed-top"><span class="navbar-brand px-3">DOMjudge · Scoreboard</span></nav><p id="board-status" hidden></p><main id="board-table"></main>'''.encode()
                self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page)
            else:super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    options=Options();options.binary_location='/usr/bin/firefox-esr'
    if not args.headed:options.add_argument('-headless')
    driver_path=ROOT/'geckodriver'
    if not driver_path.exists():driver_path=ROOT/'tests/browser/tools/geckodriver'
    driver=webdriver.Firefox(options=options,service=Service(str(driver_path),log_output=str(output/'geckodriver.log')))
    report={'status':'failed'}
    try:
        driver.set_window_rect(width=1440,height=1000)
        if args.headed:driver.fullscreen_window()
        driver.get('http://127.0.0.1:'+str(server.server_port))
        driver.execute_script('''
          const start=Date.now()-18000000;
          window.fixture={session:{sessionId:'rank-updates',state:'finished',startAt:start,durationMs:18000000},snapshot:{sessionId:'rank-updates',inputKey:'fixture',observedAt:1,elapsedMs:18000000,own:{id:'own'},ranklist:{version:'0.3.14',type:'general',contest:{title:'排名更新 · 阅读位置保持',startAt:new Date(start).toISOString(),duration:[5,'h']},time:new Date(start+18000000).toISOString(),problems:[{alias:'A'},{alias:'B'}],series:[{title:'Rank',rule:{preset:'Normal'},segments:[{count:400,style:'bronze'}]}],sorter:{algorithm:'ICPC',config:{penalty:[20,'min']}},rows:Array.from({length:400},(_,i)=>({user:{id:i===150?'own':'team-'+i,name:i===150?'本队':'参赛队 '+(i+1)},rankValues:[{rank:i+1,segmentIndex:0}],score:{value:1,time:[i+1,'min']},statuses:[{result:'AC',tries:1,time:[i+1,'min']},{}]}))}}};
          fixture.paint=()=>VpBoardView.render(document.getElementById('board-table'),structuredClone(fixture.snapshot),{session:fixture.session});fixture.paint();
        ''')
        wait=WebDriverWait(driver,15,poll_frequency=.1)
        wait.until(lambda _:driver.find_elements('css selector','tr[data-own-team]'))
        driver.find_element('css selector','[data-id=board-locate-own]').click()
        wait.until(lambda _:driver.execute_script("const r=document.querySelector('[data-own-team]').getBoundingClientRect();return r.top>100&&r.bottom<innerHeight"))
        # Wait for the user-requested smooth positioning to finish before measuring updates.
        driver.execute_async_script('''const done=arguments[arguments.length-1];let previous=scrollY,stable=0;const timer=setInterval(()=>{stable=previous===scrollY?stable+1:0;previous=scrollY;if(stable>=3){clearInterval(timer);done(true)}},50);''')
        before=driver.execute_script('return scrollY');driver.save_screenshot(str(output/'rank-before.png'))
        result=driver.execute_async_script('''
          const done=arguments[arguments.length-1],samples=[scrollY];let frames=0;
          const watch=()=>{samples.push(scrollY);if(++frames<90)requestAnimationFrame(watch);else done({before:samples[0],min:Math.min(...samples),max:Math.max(...samples),after:scrollY,rank:document.querySelector('[data-own-team] td')?.textContent})};requestAnimationFrame(watch);
          const rows=fixture.snapshot.ranklist.rows,own=rows.splice(150,1)[0];rows.splice(140,0,own);rows.forEach((r,i)=>r.rankValues[0].rank=i+1);
          fixture.snapshot.observedAt++;fixture.paint();
        ''')
        report['rankUpdate']=result
        assert result['rank']=='141',result
        assert result['max']-result['min']<=1,result
        # Read a visible segmented rank cell after the rank change.
        measure=driver.execute_script('''
          const e=[...document.querySelectorAll('tbody tr[data-rich-row=true] td.srk-series-segmented-column')].find(e=>{const r=e.getBoundingClientRect();return r.top>80&&r.bottom<innerHeight});
          const range=document.createRange();range.selectNodeContents(e);const cell=e.getBoundingClientRect(),text=range.getBoundingClientRect(),stripe=parseFloat(getComputedStyle(e,'::after').width);
          return {text:e.textContent,textRight:text.right,stripeLeft:cell.right-stripe,paddingRight:getComputedStyle(e).paddingRight};
        ''')
        report['rankColumn']=measure;driver.save_screenshot(str(output/'rank-after.png'))
        assert measure['textRight']<=measure['stripeLeft']-4,measure
        # Exercise the workbench's actual two-stage refresh: judgement first,
        # historical rank next. A slow second read must retain the full table.
        source=args.ui_source.read_text()
        functions=source[source.index('  function boardInput('):source.index('  function renderSummary(')]
        driver.execute_script("""
          window.state={session:fixture.session,contest:{problems:[{id:'1',label:'A'},{id:'2',label:'B'}]},submissions:[{id:'1',problemId:'1',state:'confirmed',elapsedMs:60000,inSession:true,pending:false,verdict:'CORRECT',timeSource:'provider-absolute'}]};
          window.$=id=>document.getElementById(id);location.hash='scoreboard';
        """+functions+"""
          window.refreshFixture=()=>renderBoard();
          fixture.snapshot.scope='historical';fixture.snapshot.inputKey=VpBoardEngine.inputKey(boardInput());
          state.board=fixture.snapshot;
          if(typeof boardContext==='function')state.boardContext=boardContext();
          refreshFixture();
        """)
        result=driver.execute_async_script("""
          const done=arguments[arguments.length-1],initial=scrollY;let min=initial,max=initial,minRows=400,frames=0;
          const watch=()=>{min=Math.min(min,scrollY);max=Math.max(max,scrollY);minRows=Math.min(minRows,document.querySelectorAll('.srk-main tbody>tr').length);if(++frames<100)requestAnimationFrame(watch);else done({initial,min,max,after:scrollY,minRows})};requestAnimationFrame(watch);
          state.submissions[0].verdict='WRONG-ANSWER';refreshFixture();
          setTimeout(()=>{fixture.snapshot={...fixture.snapshot,inputKey:VpBoardEngine.inputKey({session:state.session,contest:state.contest,history:{submissions:state.submissions}}),observedAt:3};state.board=fixture.snapshot;refreshFixture()},500);
        """)
        report['judgementRefresh']=result
        driver.save_screenshot(str(output/'judgement-refresh.png'))
        assert result['minRows']==400,result
        assert result['max']-result['min']<=1,result
        # Render projections through the real engine and table at the freeze edges.
        driver.execute_script('''
          window.freezeInput={session:{sessionId:'freeze-rank',account:'本队',state:'finished',startAt:Date.now()-18000000,durationMs:18000000,elapsedMs:18000000},contest:{problems:[{id:'1',label:'A'},{id:'2',label:'B'}]},history:{submissions:[{id:'1',problemId:'1',state:'confirmed',inSession:true,elapsedMs:245*60000,verdict:'CORRECT',timeSource:'provider-absolute'}]}};
          window.freezeArchive={version:'0.3.14',type:'general',contest:{title:'封榜期间本队排名待揭晓',startAt:new Date(0).toISOString(),duration:[5,'h'],frozenDuration:[1,'h']},problems:[{alias:'A'},{alias:'B'}],series:[{title:'Rank',rule:{preset:'Normal'},segments:[{count:10,style:'bronze'}]},{title:'All',rule:{preset:'Normal'}}],sorter:{algorithm:'ICPC',config:{penalty:[20,'min']}},rows:[{user:{id:'opponent',name:'历史对手'},score:{value:0},statuses:[{solutions:[{result:'AC',time:[30,'min']}]},{solutions:[{result:'AC',time:[250,'min']}]}]}]};
          window.paintFrozen=minute=>{
            const elapsedMs=minute*60000;freezeInput.session.startAt=Date.now()-elapsedMs;
            const snapshot=VpBoardEngine.project(freezeInput,freezeArchive,elapsedMs);
            VpBoardView.render(document.getElementById('board-table'),snapshot,{session:{...freezeInput.session}});
          };scrollTo(0,0);
        ''')
        report['freezeRanks']=[]
        for minute in [239,240,245,299,300,260,239]:
            expected='?' if 240<=minute<300 else '2'
            driver.execute_script('paintFrozen(arguments[0])',minute)
            wait.until(lambda _:driver.execute_script("const cells=document.querySelector('[data-own-team]')?.cells;return cells?.[0].textContent===arguments[0]&&cells?.[3].textContent===arguments[1]",expected,'1' if minute>=245 else '0'))
            values=driver.execute_script('''
              const row=document.querySelector('[data-own-team]'),cells=[...row.cells];
              return {ranks:cells.slice(0,2).map(c=>c.textContent),score:cells[3].textContent,penalty:cells[4].textContent,
                medal:cells[0].className.includes('srk-preset-series-segment-bronze'),opponentRank:[...row.parentElement.rows].find(r=>r!==row).cells[0].textContent};
            ''')
            report['freezeRanks'].append({'minute':minute,**values})
            assert values['ranks']==[expected,expected],values
            assert values['opponentRank']=='1',values
            assert values['score']==('1' if minute>=245 else '0'),values
            assert values['penalty']==('245' if minute>=245 else '0'),values
            if expected=='?':assert values['medal'] is False,values
            if minute in [299,300]:driver.save_screenshot(str(output/f'freeze-{minute}.png'))
        # Selecting CCPC26 for an unfrozen archive must also supply its freeze.
        driver.execute_script('''
          freezeInput.session={...freezeInput.session,sessionId:'ccpc26-replay',startAt:Date.now()-18000000,board:{rule:'CCPC26',revealCount:50,revealRatio:100}};
          freezeArchive.contest.frozenDuration=[0,'h'];freezeArchive.contest.title='CCPC26 · 四小时揭示全部题号';
          const project=elapsed=>({...VpBoardEngine.project(freezeInput,freezeArchive,elapsed),inputKey:'ccpc26'});
          VpBoardView.render(document.getElementById('board-table'),project(18000000),{session:freezeInput.session,onProject:project});
          scrollTo(0,0);
        ''')
        wait.until(lambda _:driver.find_element('css selector','input[type=range]').is_enabled())
        report['ccpc26Replay']=[]
        for minute in [239,240,280,300,239]:
            driver.execute_script("document.querySelector('input[type=range]').value=arguments[0]",minute-1)
            driver.find_element('css selector','input[type=range]').send_keys(Keys.ARROW_RIGHT)
            expected='?' if 240<=minute<300 else '2'
            wait.until(lambda _:driver.execute_script("return document.querySelector('[data-own-team] td')?.textContent===arguments[0]&&document.querySelector('input[type=range]')?.value===arguments[1]&&!document.querySelector('[aria-busy=true]')",expected,str(minute)))
            labels=driver.execute_script("return [...document.querySelectorAll('.srk-main thead .srk-problem-header .srk--display-block:first-child')].map(e=>e.textContent.trim()).filter(t=>/^[AB]$/.test(t))")
            assert len(labels)==(0 if minute<240 else 2),labels
            report['ccpc26Replay'].append({'minute':minute,'visibleProblemLabels':len(labels),'ownRank':expected})
            if minute in [239,240,280,300]:driver.save_screenshot(str(output/f'ccpc26-{minute}.png'))
        report['status']='passed'
    finally:
        (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        driver.quit();server.shutdown()
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
