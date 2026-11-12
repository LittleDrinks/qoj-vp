#!/usr/bin/env python3
"""Firefox readiness flow with isolated QOJ, CLI and RankLand HTTP fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor_py'), str(ROOT / 'tests/browser/vendor_py')]
from tests.unit.support import account_menu
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

HOST = 'org.littledrinks.qoj_ready_qa'
ADDON = 'qoj-ready-qa@littledrinks.local'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'results/vp-readiness'
    output.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / 'tests/browser/fixtures'
    archive = {'version': '0.3.14', 'type': 'general',
        'contest': {'title': 'Readiness fixture', 'startAt': '2020-01-01T00:00:00Z', 'duration': [5, 'h']},
        'problems': [{'alias': 'A'}, {'alias': 'B'}], 'series': [{'title': 'Rank', 'rule': {'preset': 'Normal'}}],
        'sorter': {'algorithm': 'ICPC', 'config': {'penalty': [20, 'min'], 'timePrecision': 'min'}},
        'rows': [{'user': {'id': 'other', 'name': 'Historical opponent'}, 'score': {'value': 1, 'time': [30, 'min']},
                  'statuses': [{'result': 'AC', 'tries': 1, 'time': [30, 'min'], 'solutions': [{'result': 'AC', 'time': [30, 'min']}]}, {'solutions': []}]}]}
    data = json.dumps(archive).encode()
    detail = {'_id': '1', 'uk': 'ready-fixture', 'name': 'Readiness fixture', 'duration': [5, 'h'], 'srkFileID': '2',
              'problems': archive['problems'], 'sorter': archive['sorter']}
    file = {'id': '2', 'contestId': '1', 'category': 'RankMain', 'name': 'ready.srk.json', 'path': '2/ready.srk.json',
            'hashType': 'sha256', 'hashValue': hashlib.sha256(data).hexdigest(), 'size': len(data),
            'url': 'https://cdn.algoux.cn/rankland/file/2/ready.srk.json'}
    traffic, starts = [], []
    form = '<form id="form-register_vp" method="post" action="/contest/3387/virtual/register"><input type="hidden" name="_token" value="fixture"><p>Click the button below to start your virtual participation immediately.</p><button class="btn btn-primary w-100" id="button-submit-register_vp" name="submit-register_vp" type="submit">Start</button></form>'
    register = account_menu('FixtureUser', body='<div class="container my-4"><h1>VP Ready · 隔离比赛</h1><p class="text-muted">VMware Firefox · QOJ、历史榜单与 CLI 使用隔离测试数据</p><div class="row mt-4"><section class="col-8"><div class="card"><h4 class="card-header">Virtual Contest Rules</h4><div class="card-body"><p>Prepare your contest before starting virtual participation.</p><ul><li>The contest is 300 minutes long.</li><li>Each wrong submission adds 20 minutes of penalty.</li></ul></div></div></section><aside class="col-4"><div class="card border-primary"><h4 class="card-header bg-primary text-white">Start virtual participation</h4><div class="card-body"><p>Ruleset &nbsp; ICPC &emsp; Duration &nbsp; 5:00</p>' + form + '</div></div></aside></div></div>')
    register = register.replace('//qoj.ac/', '/')
    register = '<!doctype html><meta charset="utf-8"><title>VP Ready · 隔离比赛</title><link rel="stylesheet" href="/bootstrap.css">' + register + '<script>document.getElementById("button-submit-register_vp").addEventListener("click",e=>{e.preventDefault();document.getElementById("form-register_vp").submit();});</script>'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def emit(self, body, kind='text/html; charset=utf-8', code=200):
            if isinstance(body, str): body = body.encode()
            self.send_response(code); self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path = urlsplit(self.path).path; traffic.append(('GET', path))
            if path == '/': return self.emit(account_menu('FixtureUser'))
            if path == '/download.php' and parse_qs(urlsplit(self.path).query).get('id') == ['15419']:
                return self.emit((fixtures / 'attachment-15419.zip').read_bytes(), 'application/zip')
            if path == '/bootstrap.css': return self.emit((ROOT / 'src/firefox/assets/bootstrap/bootstrap.min.css').read_bytes(), 'text/css')
            if path == '/contest/3387/virtual/register': return self.emit(register)
            if path == '/contest/3387':
                body = (fixtures / 'contest-3387.html').read_text().replace('QOJ PRE-FLIGHT FIXTURE', 'VP Ready · 隔离比赛')
                if starts:
                    body += '<div class="card border-info"><h4 class="card-header bg-info">Contest ends in</h4><div class="card-body text-center countdown" data-rest="17999"></div></div><div class="uoj-footer"><p>Server Time: ' + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + ' (UTC+0)</p></div>'
                return self.emit(account_menu('FixtureUser', body=body))
            if path.startswith('/contest/3387/problem/'):
                return self.emit((fixtures / ('problem-' + path.split('/')[4] + '.html')).read_text())
            if path == '/contest/3387/submissions': return self.emit((fixtures / 'submissions-empty.html').read_bytes())
            if path.startswith('/api/v2/public/contests'):
                result = {'contests': []} if path.endswith('contests') else detail
                return self.emit(json.dumps({'success': True, 'code': 0, 'data': result}), 'application/json')
            if path.startswith('/api/v2/public/files/'):
                return self.emit(json.dumps({'success': True, 'code': 0, 'data': file}), 'application/json')
            if path == '/rankland/file/2/ready.srk.json': return self.emit(data, 'application/json')
            return self.emit('missing fixture', code=404)
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            traffic.append(('POST', urlsplit(self.path).path))
            if urlsplit(self.path).path == '/contest/3387/virtual/register':
                starts.append(time.time()); self.send_response(302);self.send_header('Location', '/contest/3387');self.end_headers()
            else: self.emit('unexpected upload', code=405)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = 'http://127.0.0.1:' + str(server.server_port)
    driver = None
    manifest_path = Path.home() / '.mozilla/native-messaging-hosts' / (HOST + '.json')
    before = manifest_path.read_bytes() if manifest_path.exists() else None
    report = {'status': 'running', 'screenshots': []}
    (output/'summary.json').write_text(json.dumps(report))
    try:
        with tempfile.TemporaryDirectory(prefix='qoj-ready-qa-') as directory:
            work = Path(directory); extension = work / 'extension'
            shutil.copytree(ROOT / 'src/firefox', extension)
            # Only this isolated copy accepts the fixture origin and host identity.
            manifest = json.loads((extension / 'manifest.json').read_text())
            manifest['browser_specific_settings']['gecko']['id'] = ADDON
            manifest['content_scripts'][1]['matches'] = ['http://127.0.0.1/contest/*']
            manifest['web_accessible_resources'][0]['matches'] = ['http://127.0.0.1/*']
            manifest['background']['scripts'].insert(0, 'fixture-fetch.js')
            (extension / 'manifest.json').write_text(json.dumps(manifest))
            (extension / 'fixture-fetch.js').write_text('const originalFetch=globalThis.fetch;globalThis.fetch=(url,args)=>{const u=new URL(url);return originalFetch(["rl.algoux.cn","cdn.algoux.cn"].includes(u.hostname)?' + json.dumps(origin) + '+u.pathname+u.search:url,args);};')
            for name in ['qoj-prepare-content.js', 'readiness-bridge.js', 'ready-ui.js']:
                p = extension / name; text = p.read_text().replace('https://qoj.ac', origin)
                if name == 'qoj-prepare-content.js': text = text.replace('url:location.origin + location.pathname', 'url:"https://qoj.ac" + location.pathname')
                p.write_text(text)
            p = extension / 'qoj-lifecycle.js';p.write_text(p.read_text().replace('url.origin === "https://qoj.ac"', '(url.origin === "https://qoj.ac" || url.origin === ' + json.dumps(origin) + ')'))
            p = extension / 'background.js';p.write_text(p.read_text().replace('org.littledrinks.qoj_vp', HOST).replace('urls:["https://qoj.ac/contest/*/virtual/register*"]', 'urls:[' + json.dumps('http://127.0.0.1/contest/*/virtual/register*') + ']'))
            launcher = work / 'native-host'
            launcher.write_text('#!/usr/bin/python3 -I\nimport sys,os\nsys.path[:0]=' + repr([str(ROOT / 'src'), str(ROOT / 'vendor/qoj-submitter')]) + '\nos.environ.update(' + repr({'QOJ_VP_QOJ_PATH': str(ROOT / 'vendor/qoj-submitter'), 'QOJ_VP_STATE_DIR': str(work / 'state'), 'XDG_DATA_HOME': str(work / 'cli'), 'QOJ_VP_FIXTURE_ORIGIN': origin}) + ')\nimport requests\noriginal=requests.Session.send\ndef send(self,request,**kwargs):\n url=request.url\n if url.startswith("https://qoj.ac/"):request.url=' + repr(origin) + '+url[len("https://qoj.ac"):]\n response=original(self,request,**kwargs)\n response.url=url\n return response\nrequests.Session.send=send\nfrom qojvp.native_host import serve_once\nraise SystemExit(serve_once(sys.stdin.buffer,sys.stdout.buffer))\n')
            launcher.chmod(0o700);manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({'name': HOST, 'description': 'QOJ readiness isolated test', 'path': str(launcher), 'type': 'stdio', 'allowed_extensions': [ADDON]}))
            options=Options();options.binary_location='/usr/bin/firefox-esr'
            if not args.headed: options.add_argument('-headless')
            options.set_preference('devtools.console.stdout.content',True)
            tools = ROOT / 'geckodriver'
            if not tools.exists(): tools = ROOT / 'tests/browser/tools/geckodriver'
            driver=webdriver.Firefox(options=options,service=Service(str(tools),log_output=str(output/'geckodriver.log')))
            driver.set_window_rect(x=0,y=0,width=1440,height=900)
            if args.headed: driver.fullscreen_window()
            registration_handle=driver.current_window_handle
            driver.execute('INSTALL_ADDON', {'path':str(extension),'temporary':True})
            driver.switch_to.window(registration_handle)
            driver.get(origin + '/contest/3387/virtual/register')
            wait=WebDriverWait(driver,40,poll_frequency=.3)
            def overview():
                driver.switch_to.window(registration_handle)
                driver.switch_to.default_content()
                return driver.execute_script('return [...(document.getElementById("qoj-vp-resource-preparation")?.shadowRoot?.querySelectorAll(".row")||[])].map(e=>({state:e.className,text:e.innerText}));')
            def settled():
                rows=overview();(output/'progress.json').write_text(json.dumps({'url':driver.current_url,'rows':rows},ensure_ascii=False));return rows if len(rows)==3 and all('checking' not in row['state'] for row in rows) else False
            def capture(name):
                driver.save_screenshot(str(output/name));report['screenshots'].append(name)
            def modal_ready(name=None):
                wait.until(lambda _:driver.execute_script('const m=arguments[0]?document.getElementById(arguments[0]):document.querySelector(".modal.show");return m?.classList.contains("show") && bootstrap.Modal.getInstance(m)?._isTransitioning===false;', name))
            def enter(section):
                driver.switch_to.window(registration_handle)
                driver.switch_to.default_content()
                driver.execute_script('document.getElementById("qoj-vp-resource-preparation").shadowRoot.querySelectorAll(".row")[arguments[0]].click();',section)
                driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]'))
                modal_ready()
            def close():
                driver.find_element(By.CSS_SELECTOR,'.modal.show .btn-close').click();driver.switch_to.default_content()
                wait.until(lambda _:not driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]').is_displayed())
            initial=wait.until(lambda _:settled());report['initial']=initial
            assert all('attention' in row['state'] for row in initial), initial
            assert '待处理：B' in initial[0]['text'], initial
            def saved_session():
                with sqlite3.connect(work/'state/vp.sqlite3') as database:
                    records=database.execute('SELECT record_json FROM sessions').fetchall()
                    assert len(records)==1, 'Preparation must reuse the same session'
                    return json.loads(records[0][0])
            assert saved_session()['startAt'] is None
            capture('01-needs-attention.png')
            # Resource dialog and manual samples are the workbench's shared components.
            enter(0);capture('02-resources.png')
            wait.until(lambda _:driver.find_element(By.CSS_SELECTOR,'[data-manual-samples="15420"]').is_enabled())
            driver.find_element(By.CSS_SELECTOR,'[data-manual-samples="15420"]').click()
            modal_ready('manual-samples-modal')
            mode=driver.find_element(By.ID,'manual-samples-mode')
            from selenium.webdriver.support.ui import Select
            Select(mode).select_by_value('text')
            driver.find_element(By.ID,'manual-sample-input').send_keys('1 2\n')
            driver.find_element(By.ID,'manual-sample-output').send_keys('3\n')
            driver.find_element(By.CSS_SELECTOR,'#manual-samples-form button[type=submit]').click()
            modal_ready('resources-modal')
            close();wait.until(lambda _:'ready' in settled()[0]['state'] if settled() else False)
            enter(1);field=driver.find_element(By.ID,'rankland-url');field.clear();field.send_keys('https://rl.algoux.cn/ranklist/ready-fixture')
            capture('03-board-settings.png');driver.find_element(By.CSS_SELECTOR,'#rankland-form button[type=submit]').click()
            driver.switch_to.default_content();wait.until(lambda _:'ready' in settled()[1]['state'] if settled() else False)
            enter(2);driver.find_element(By.ID,'ready-judger-bind').click()
            wait.until(lambda _:'dry-run 通过' in driver.find_element(By.ID,'ready-judger-status').text)
            capture('04-judger-dry-run.png');close()
            assert all(row['state'].endswith(' ready') for row in settled()), overview()
            capture('05-all-ready.png')
            # Changing a setting invalidates Ready; Start remains advisory.
            enter(2);Select(driver.find_element(By.ID,'ready-language')).select_by_value('py');close()
            driver.find_element(By.ID,'button-submit-register_vp').click()
            driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]'))
            modal_ready('ready-warning-modal');capture('06-start-warning.png')
            assert not starts
            driver.find_element(By.CSS_SELECTOR,'#ready-warning-modal .btn-secondary').click();driver.switch_to.default_content()
            wait.until(lambda _:not driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]').is_displayed());assert not starts
            driver.find_element(By.ID,'button-submit-register_vp').click();driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]'))
            modal_ready('ready-warning-modal');driver.find_element(By.ID,'ready-continue').click()
            driver.switch_to.default_content();wait.until(lambda _:len(starts)==1)
            session=wait.until(lambda _:saved_session() if saved_session()['startAt'] is not None else False)
            assert session['startAt']==session['qojVirtual']['startAt']
            assert abs(session['startAt']/1000-starts[0])<5
            assert [path for method,path in traffic if method=='POST']==['/contest/3387/virtual/register']
            report.update(status='passed',nativeStartPosts=len(starts),submissionPosts=0,clock='QOJ server time')
    except Exception as error:
        report.update(status='failed',error=repr(error))
        report['traffic']=traffic
        import traceback
        (output/'failure.txt').write_text(traceback.format_exc())
        if driver:
            try:
                driver.switch_to.window(registration_handle);driver.switch_to.default_content()
                driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR,'iframe[title="QOJ VP 准备设置"]'))
            except Exception:pass
            try:report['page']={'url':driver.current_url,'body':driver.execute_script('return document.body.innerText').strip()[:2000]}
            except Exception:pass
        if driver: driver.save_screenshot(str(output/'failure.png'))
        raise
    finally:
        (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        if driver: driver.quit()
        server.shutdown();server.server_close()
        if before is not None:manifest_path.write_bytes(before)
        else:manifest_path.unlink(missing_ok=True)


if __name__=='__main__': main()
