#!/usr/bin/env python3
"""Guest-only real Firefox receipt diagnostics; no native host or judge access.

The QA manifest grants only a new loopback origin. Three synthetic, sourceless
multipart POSTs exercise actual product transport.js and qoj-content.js. No
real QOJ account, source code, cookies, existing profile or native host is used.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'tests/browser'), str(PROJECT / 'tests/browser/vendor_py')]
from guest_preflight import atomic_json, process_exit, require, utc_now


class Fixture:
    def __init__(self):
        self.post_count = 0
        self.records = []
        self.server = self.thread = None

    @property
    def origin(self):
        return 'http://127.0.0.1:' + str(self.server.server_port)

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def emit(self, status, body=b'', location=None):
                owner.records.append({'method': self.command, 'path': urlsplit(self.path).path, 'status': status})
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                if location:
                    self.send_header('Location', location)
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def do_GET(self):
                self.emit(200, b'<!doctype html><title>Receipt fixture only</title><p>Loopback QA</p>')

            def do_POST(self):
                owner.post_count += 1
                size = int(self.headers.get('Content-Length', '0'))
                if size > 65536:
                    return self.emit(413)
                # Drain only synthetic test bytes; never parse/log/store body.
                self.rfile.read(size)
                pid = urlsplit(self.path).path.rsplit('/', 1)[-1]
                if pid == '15419':
                    return self.emit(302, location='/submission/1000001?auth=FAKE_LOCATION_SECRET')
                if pid == '15420':
                    return self.emit(503, b'Synthetic unavailable response')
                if pid == '15421':
                    return self.emit(302, b'Synthetic missing Location')
                self.emit(404)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(5)
        require(not self.thread or not self.thread.is_alive(), 'Receipt fixture did not stop')


PAGE_SCRIPT = r'''
window.receiptQa = {
  ready: true,
  safeCode(error) {
    const known=new Set(['UNCONFIRMED_REDIRECT','HTTP_TAB_ORIGIN_MISMATCH','HTTP_ORIGIN_DENIED',
      'POST_REQUIRES_EXPLICIT_SUBMIT','CONTENT_SCRIPT_UNAVAILABLE','CONTENT_FETCH_FAILED',
      'FIXTURE_ORIGIN_DENIED','FIXTURE_TAB_NOT_READY','FIXTURE_STATUS_MISMATCH',
      'OBSERVED_RECEIPT_MISSING','FALSE_SUCCESS_RECEIPT','MISSING_LOCATION_NOT_OBSERVED',
      'DIAGNOSTICS_NOT_PERSISTED','PERSISTED_ATTEMPT_COUNT','DIAGNOSTIC_STORAGE_FAILED',
      'SENSITIVE_DIAGNOSTICS','REAL_REQUEST_BINDING_MISSING','REAL_HEADERS_MISSING',
      'DIRECT_HTTP_DIAGNOSTICS_MISMATCH']);
    return known.has(error?.message)?error.message:'QA_FAILED';
  },
  async settle() {
    for(let n=0;n<100;n++) {
      const p=VpTransport.diagnostics().persistence;
      if(p.loaded && !p.pendingWrites)return;
      await new Promise(r=>setTimeout(r,50));
    }
    throw new Error('DIAGNOSTICS_NOT_PERSISTED');
  },
  async capture() {
    let settleErrorCode=null;
    try { await this.settle(); } catch(error) { settleErrorCode=this.safeCode(error); }
    const diagnostics=VpTransport.diagnostics();
    let storedAttemptCount=null,storageReadFailed=false,context=null;
    try { storedAttemptCount=(await browser.storage.local.get('http-post-diagnostics-v1'))['http-post-diagnostics-v1']?.attempts?.length??null; }
    catch(_) { storageReadFailed=true; }
    if(this.fixtureTabId!==undefined) {
      try {
        const tab=await browser.tabs.get(this.fixtureTabId);
        context={tabId:tab.id,status:tab.status,urlMatchesFixture:tab.url===this.fixtureUrl,
          originMatches:new URL(tab.url).origin===new URL(this.fixtureUrl).origin};
      } catch(_) { context={tabId:this.fixtureTabId,unavailable:true}; }
    }
    const serialized=JSON.stringify(diagnostics);
    const unsafe=serialized.includes('FAKE_') || serialized.includes('contentsBase64') || serialized.includes('bodyBase64') ||
      /"(?:nonce|requestHeaders|responseHeaders|body|headers)"\s*:/.test(serialized);
    return {outcomes:this.outcomes||[],currentCase:this.currentCase||null,fixtureReady:this.navigation||null,
      fixtureContext:context,storedAttemptCount,storageReadFailed,settleErrorCode,
      ...(unsafe?{diagnostics:null,diagnosticsOmitted:true,captureErrorCode:'SENSITIVE_DIAGNOSTICS'}:{diagnostics}),
      diagnosticIds:diagnostics.postAttempts.map(attempt=>attempt.diagnosticId)};
  },
  async run(origin) {
    this.outcomes=[];this.currentCase=null;this.navigation=null;
    let result=null,errorCode=null;
    try { result=await this.perform(origin); } catch(error) {
      errorCode=this.safeCode(error);
      if(this.currentCase) {
        this.currentCase.phase='failed';
        const last=this.outcomes.at(-1);
        if(last?.pid===this.currentCase.pid)last.errorCode=errorCode;
      }
    }
    let captured;
    try { captured=await this.capture(); } catch(_) { captured={captureErrorCode:'QA_CAPTURE_FAILED'}; }
    return {...(result||{}),...captured,...(errorCode?{errorCode}:{})};
  },
  async perform(origin) {
    const u=new URL(origin);
    if(u.protocol!=='http:' || u.hostname!=='127.0.0.1' || u.pathname!=='/')throw new Error('FIXTURE_ORIGIN_DENIED');
    const fixtureUrl=origin+'/contest/3387/problem/15419';
    const tab=await browser.tabs.create({url:fixtureUrl,active:false});
    this.fixtureUrl=fixtureUrl;this.fixtureTabId=tab.id;
    // tabs.create can resolve while Tab.url is still about:blank. Wait for
    // the intended complete document and its real content-script handshake;
    // production's strict httpTabId/origin validation remains unchanged.
    let fixtureReady=false;
    for(let n=0;n<100;n++) {
      const current=await browser.tabs.get(tab.id);
      this.navigation={status:current.status,urlMatches:current.url===fixtureUrl,contentReady:false};
      if(current.status==='complete' && current.url===fixtureUrl) {
        try {
          const ready=await browser.tabs.sendMessage(tab.id,{type:'vp.http.ready'});
          if(ready?.ready && ready.pageOrigin===u.origin) {
            this.navigation.contentReady=true;
            fixtureReady=true;
            break;
          }
        } catch(_) { /* The declared content script may still be attaching. */ }
      }
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if(!fixtureReady)throw new Error('FIXTURE_TAB_NOT_READY');
    const outcomes=this.outcomes;
    for(const [pid,status] of [['15419',302],['15420',503],['15421',302]]) {
      this.currentCase={pid,expectedStatus:status,phase:'callingTransport'};
      let result;
      try {
        result=await VpTransport.http({method:'POST',url:origin+'/contest/3387/problem/'+pid+'?csrf=FAKE_QUERY_SECRET',
          allowRedirects:false,timeoutMs:5000,headers:{'X-QA-Secret':'FAKE_HEADER_SECRET'},
          data:{_token:'FAKE_BODY_TOKEN',qa:'synthetic-sourceless-multipart'}},
          {id:crypto.randomUUID(),method:'qoj_submit',httpTabId:tab.id,finished:false});
      } catch(error) {
        const code=this.safeCode(error);
        const attempt=VpTransport.diagnostics().postAttempts.filter(a=>a.requestPath.endsWith('/'+pid)).at(-1);
        const observed=attempt?.events.filter(e=>e.phase==='headersObserved').at(-1);
        if(pid==='15421' && code==='UNCONFIRMED_REDIRECT' && observed?.status===302 && observed.locationPresent===false) {
          outcomes.push({pid,status:302,observedStatus:302,locationAbsent:true,receiptObserved:false,
            unknownExpected:true,errorCode:code,responseShape:'opaque-missing-location'});
          this.currentCase.phase='validated-expected-unknown';
          continue;
        }
        outcomes.push({pid,expectedStatus:status,errorCode:code,receiptObserved:false,
          observedStatus:observed?.status??null,locationAbsent:observed?observed.locationPresent===false:null});
        this.currentCase.phase='failed';
        throw error;
      }
      this.currentCase.phase='transportReturned';
      this.currentCase.status=result.status;
      this.currentCase.receiptObserved=!!result.receiptTransport;
      const outcome={pid,status:result.status,receiptObserved:!!result.receiptTransport};
      outcomes.push(outcome);
      if(result.status!==status)throw new Error('FIXTURE_STATUS_MISMATCH');
      if(pid==='15419' && result.receiptTransport!=='webRequest-observed-headers')throw new Error('OBSERVED_RECEIPT_MISSING');
      if(pid!=='15419' && result.receiptTransport)throw new Error('FALSE_SUCCESS_RECEIPT');
      if(pid==='15421') {
        const attempt=VpTransport.diagnostics().postAttempts.filter(a=>a.requestPath.endsWith('/'+pid)).at(-1);
        const observed=attempt?.events.filter(e=>e.phase==='headersObserved').at(-1);
        if(observed?.status!==302 || observed.locationPresent!==false)throw new Error('MISSING_LOCATION_NOT_OBSERVED');
        Object.assign(outcome,{observedStatus:302,locationAbsent:true,unknownExpected:true,
          errorCode:null,responseShape:'direct-http-missing-location'});
      }
      this.currentCase.phase='validated';
    }
    // A later audit failure must not overwrite the last request's actual
    // outcome (in particular its expected UNCONFIRMED_REDIRECT result).
    this.currentCase=null;
    await this.settle();
    const diagnostics=VpTransport.diagnostics();
    const saved=(await browser.storage.local.get('http-post-diagnostics-v1'))['http-post-diagnostics-v1'];
    if(diagnostics.postAttempts.length!==3 || saved?.attempts.length!==3)throw new Error('PERSISTED_ATTEMPT_COUNT');
    if(diagnostics.persistence.error)throw new Error('DIAGNOSTIC_STORAGE_FAILED');
    const serialized=JSON.stringify({diagnostics,saved});
    if(serialized.includes('FAKE_') || serialized.includes('contentsBase64') || serialized.includes('bodyBase64'))throw new Error('SENSITIVE_DIAGNOSTICS');
    for(const attempt of diagnostics.postAttempts) {
      if(attempt.requestPath==='/contest/3387/problem/15420') {
        // A normal Fetch response already supplies its HTTP status. Firefox
        // may deliver the observational webRequest events after that response,
        // when transport has correctly cleared the request's nonce binding.
        const returned=attempt.events.filter(e=>e.phase==='httpReturned').at(-1);
        if(attempt.finalCode!=='HTTP_RESPONSE' || returned?.status!==503 || returned.urlMatches!==true ||
            attempt.events.some(e=>e.phase==='receiptReturned'))throw new Error('DIRECT_HTTP_DIAGNOSTICS_MISMATCH');
        continue;
      }
      if(!attempt.events.some(e=>e.phase==='beforeBound' && e.tabMatches && e.urlMatches && e.methodMatches))throw new Error('REAL_REQUEST_BINDING_MISSING');
      if(!attempt.events.some(e=>e.phase==='headersObserved'))throw new Error('REAL_HEADERS_MISSING');
    }
    return {outcomes,diagnostics,storedAttemptCount:saved.attempts.length,fixtureReady:this.navigation,
      diagnosticIds:diagnostics.postAttempts.map(a=>a.diagnosticId),fixtureTabId:tab.id};
  },
  async restored() {
    await this.settle();
    return VpTransport.diagnostics();
  }
};
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    args = parser.parse_args()
    project = args.project.resolve()
    trial = uuid.uuid4().hex
    state = project / 'state/receipt-diagnostics' / trial
    profile = state / 'firefox-profile'
    output = project / 'results/receipt-diagnostics' / trial
    output.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    summary = {'schema': 'qoj-receipt-diagnostics-firefox-v1', 'runId': trial, 'startedAt': utc_now(),
               'checks': [], 'cleanup': {}, 'realQojRequests': 0, 'sourceFilesSelected': 0, 'nativeHostUsed': False}
    fixture = driver = None
    def check(name, passed, evidence=None):
        summary['checks'].append({'name': name, 'passed': bool(passed), 'evidence': evidence})
        require(passed, name)
    try:
        fixture = Fixture().start()
        addon = state / 'receipt-qa.xpi'
        extension_id = 'qoj-receipt-' + trial + '@littledrinks.local'
        manifest = {'manifest_version': 3, 'name': 'Isolated receipt diagnostics QA', 'version': '0.0.1',
            'browser_specific_settings': {'gecko': {'id': extension_id}},
            'permissions': ['tabs', 'scripting', 'storage', 'webRequest'],
            'host_permissions': ['http://127.0.0.1/*'],
            'content_scripts': [{'matches': ['http://127.0.0.1/*'], 'js': ['qoj-content.js'], 'run_at': 'document_start'}],
            'background': {'scripts': ['launcher.js'], 'persistent': False},
            'content_security_policy': {'extension_pages': "script-src 'self'; object-src 'none'"}}
        summary['sourceHashes'] = {}
        with zipfile.ZipFile(addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ['transport.js', 'qoj-content.js']:
                data = (project / 'src/firefox' / name).read_bytes()
                archive.writestr(name, data)
                summary['sourceHashes'][name] = hashlib.sha256(data).hexdigest()
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('launcher.js', "browser.runtime.onInstalled.addListener(()=>browser.tabs.create({url:browser.runtime.getURL('qa.html')}));")
            archive.writestr('qa.html', '<!doctype html><title>Receipt diagnostics QA</title><script src="transport.js"></script><script src="qa.js"></script>')
            archive.writestr('qa.js', PAGE_SCRIPT)
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        options.add_argument('-headless')
        options.add_argument('-profile')
        options.add_argument(str(profile))
        options.set_preference('browser.shell.checkDefaultBrowser', False)
        options.set_preference('browser.sessionstore.resume_from_crash', False)
        service = Service(str(project / 'tests/browser/tools/geckodriver'), log_output=str(output / 'geckodriver.log'))
        driver = webdriver.Firefox(options=options, service=service)
        driver.set_script_timeout(45)
        check('isolated_actual_headless_firefox', driver.capabilities.get('moz:headless') is True
              and Path(driver.capabilities['moz:profile']).resolve() == profile,
              {'pid': driver.capabilities['moz:processID'], 'version': driver.capabilities['browserVersion']})
        check('temporary_loopback_only_qa_addon', driver.execute('INSTALL_ADDON', {'path': str(addon), 'temporary': True})['value'] == extension_id)
        deadline = time.monotonic() + 20
        qa_handle = None
        while time.monotonic() < deadline and not qa_handle:
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                if driver.current_url.startswith('moz-extension://') and urlsplit(driver.current_url).path == '/qa.html':
                    if driver.execute_script('return !!window.receiptQa?.ready;'):
                        qa_handle = handle
                        break
            if not qa_handle:
                time.sleep(.1)
        require(qa_handle is not None, 'QA extension page did not bootstrap')
        result = driver.execute_async_script('const done=arguments[arguments.length-1];receiptQa.run(arguments[0]).then(done,()=>done({errorCode:"QA_CAPTURE_FAILED"}));', fixture.origin)
        summary['browserEvidence'] = result
        summary['fixturePostCount'] = fixture.post_count
        atomic_json(output / 'actual-post-diagnostics.json', result)
        summary['fixtureNavigation'] = result.get('fixtureReady')
        check('fixture_tab_navigation_and_content_script_ready', result.get('fixtureReady') == {
            'status': 'complete', 'urlMatches': True, 'contentReady': True}, result.get('fixtureReady'))
        require(not result.get('errorCode'), 'Browser receipt QA: ' + str(result.get('errorCode')))
        require(not result.get('captureErrorCode'), 'Safe browser evidence was not captured')
        check('real_observed_302_and_nonreceipt_503_missing_location',
              [item['receiptObserved'] for item in result['outcomes']] == [True, False, False], result['outcomes'])
        third = result['outcomes'][2]
        check('missing_location_302_is_unconfirmed_without_success_receipt_or_retry',
              third.get('unknownExpected') is True and third.get('observedStatus') == 302
              and third.get('locationAbsent') is True and third.get('receiptObserved') is False
              and third.get('errorCode') in {None, 'UNCONFIRMED_REDIRECT'} and fixture.post_count == 3, third)
        check('exactly_three_synthetic_sourceless_posts', fixture.post_count == 3, {'postCount': fixture.post_count})
        check('safe_diagnostics_persisted_in_real_browser_storage', result['storedAttemptCount'] == 3)
        driver.refresh()
        restored = driver.execute_async_script('const done=arguments[arguments.length-1];receiptQa.restored().then(done,()=>done({errorCode:"RESTORE_FAILED"}));')
        require(not restored.get('errorCode'), 'Browser diagnostic restore failed')
        atomic_json(output / 'restored-post-diagnostics.json', restored)
        check('fresh_extension_context_restores_history_without_replay', fixture.post_count == 3
              and [a['diagnosticId'] for a in restored['postAttempts']] == result['diagnosticIds']
              and restored['postObservations'] == [], {'postCount': fixture.post_count, 'restoredAttemptCount': len(restored['postAttempts'])})
    except Exception as exc:
        summary['error'] = {'type': type(exc).__name__, 'message': 'Receipt QA failed; inspect safe browserEvidence and checks'}
        if driver and 'browserEvidence' not in summary:
            try:
                evidence = driver.execute_async_script('const done=arguments[arguments.length-1];receiptQa.capture().then(done,()=>done({captureErrorCode:"QA_CAPTURE_FAILED"}));')
                summary['browserEvidence'] = evidence
                atomic_json(output / 'actual-post-diagnostics.json', evidence)
            except Exception:
                summary['browserEvidence'] = {'captureErrorCode': 'QA_CAPTURE_FAILED'}
        if driver:
            try:
                driver.save_screenshot(str(output / 'failure.png'))
            except Exception:
                pass
    finally:
        try:
            if driver:
                pid = driver.capabilities['moz:processID']
                driver.quit()
                summary['cleanup']['firefox'] = process_exit(pid, timeout=20)
            else:
                summary['cleanup']['firefox'] = {'alreadyStopped': True}
            if profile.exists():
                require(profile.parent == state and profile.resolve().is_relative_to(project / 'state/receipt-diagnostics'), 'Unowned profile')
                shutil.rmtree(profile)
            summary['cleanup']['ownedProfileRemoved'] = True
        except Exception as exc:
            summary['cleanup']['errorType'] = type(exc).__name__
        try:
            if fixture:
                fixture.stop()
                summary['fixtureRequests'] = fixture.records
                summary['fixturePostCount'] = fixture.post_count
            summary['cleanup']['fixtureStopped'] = True
        except Exception as exc:
            summary['cleanup']['fixtureErrorType'] = type(exc).__name__
        summary.update(finishedAt=utc_now(), status='failed' if summary.get('error') or any(
            key.endswith('ErrorType') or key == 'errorType' for key in summary['cleanup']) else 'passed')
        atomic_json(output / 'summary.json', summary)
        atomic_json(project / 'results/receipt-diagnostics-summary.json', summary)
        print(json.dumps({'status': summary['status'], 'summary': str(output / 'summary.json')}))
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
