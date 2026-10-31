#!/usr/bin/env python3
"""Exercise Firefox's real saveAsPDF engine with an isolated mock file picker.

No native registration, QOJ session, or user browser profile is changed. Only
the picker is controlled; Firefox's extension API and PDF renderer stay real.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'preflight/vendor_py'), str(PROJECT / 'preflight')]
from guest_preflight import atomic_json, process_exit, require, utc_now


MOCK_PICKER = r'''
const original = Components.manager.QueryInterface(Ci.nsIComponentRegistrar);
const audit = window.__qojPdfAudit = {path: arguments[0], result: 0, opens: []};
const factory = {
  QueryInterface: ChromeUtils.generateQI(["nsIFactory"]),
  createInstance(iid) {
    const picker = {
      QueryInterface: ChromeUtils.generateQI(["nsIFilePicker"]),
      defaultString: "", defaultExtension: "", filters: [],
      init(context, title, mode) {this.title=title; this.mode=mode;},
      appendFilter(label, pattern) {this.filters.push({label, pattern});},
      get file() {
        const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
        file.initWithPath(audit.path);
        return file;
      },
      open(callback) {
        audit.opens.push({mode:this.mode, defaultString:this.defaultString,
          defaultExtension:this.defaultExtension, filters:this.filters});
        Services.tm.dispatchToMainThread(() => callback.done(audit.result));
      },
    };
    return picker.QueryInterface(iid);
  },
};
// A throwaway headless browser owns this registration and exits after the test.
original.registerFactory(Components.ID("{94a97040-e756-4e89-9bc6-5d17de1f68ab}"),
  "QOJ VP isolated PDF picker", "@mozilla.org/filepicker;1", factory);
audit.factory = factory;
return true;
'''


FIXTURE_HTML = '''<!doctype html><meta charset="utf-8"><title>SYNTHETIC QOJ problem page</title>
<style>body{font:16px sans-serif;margin:40px}nav,aside{padding:18px;background:#eee}
.container{max-width:900px;margin:auto;padding:20px}.tab-pane{padding:15px}
a:link{color:rgb(10,50,150);text-decoration:underline}pre{background:#eee;padding:12px}
@media print{#site-navigation{display:block!important}}
.inactive{display:none}</style>
<nav id="site-navigation">SITE_NAV_NEVER_PRINT <a href="/logout?_token=FAKE_NAV_TOKEN">logout</a></nav>
<div class="container"><h1>OUTSIDE_PROBLEM_TITLE_NEVER_PRINT</h1><div class="row">
<aside>SIDEBAR_NEVER_PRINT <a href="/?session=FAKE_SIDEBAR_SESSION">account</a></aside>
<section><ul><li>TAB_CONTROLS_NEVER_PRINT</li></ul><div class="tab-content">
<div class="tab-pane active"><article class="uoj-article top-buffer-md">
<h2>题目描述</h2><p>题面 PDF：中文样例与数学公式。</p>
<p>Evaluate <math><mfrac><mrow><mi>n</mi><mo>(</mo><mi>n</mi><mo>+</mo><mn>1</mn><mo>)</mo></mrow><mn>2</mn></mfrac></math>.</p>
<p><a id="sensitive" href="/reference?CsRf_Token=FAKE_ARTICLE_TOKEN">敏感参数链接文字保留</a></p>
<p><a id="encoded" href="/reference?%61uth=FAKE_ENCODED_AUTH">Encoded query link label</a></p>
<p><a id="fragment" href="/reference#access_token=FAKE_FRAGMENT_TOKEN">Fragment link label</a></p>
<p><a id="userinfo" href="https://fake-user:FAKE_PASSWORD@example.org/reference">Userinfo link label</a></p>
<svg width="280" height="30" xmlns:xlink="http://www.w3.org/1999/xlink"><a id="svg-sensitive" xlink:href="/reference?session=FAKE_SVG_SESSION"><text x="0" y="20">SVG link label</text></a></svg>
<p><a id="safe" href="https://example.org/reference?chapter=2">PUBLIC_REFERENCE_RETAINED</a></p>
<h2>Sample Input</h2><pre>3</pre><h2>Sample Output</h2><pre>6</pre>
</article><div>SUBMIT_FORM_NEVER_PRINT</div></div>
<div class="tab-pane inactive"><article class="uoj-article top-buffer-md">INACTIVE_TAB_NEVER_PRINT</article></div>
</div></section></div></div><footer>FOOTER_NEVER_PRINT</footer>'''


class PdfFixture:
    def __init__(self):
        self.server = self.thread = None
        self.get_count = self.post_count = 0

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                owner.get_count += 1
                content = FIXTURE_HTML
                if self.path == '/contest/3387/problem/15420':
                    content += '<div class="tab-pane active"><article class="uoj-article top-buffer-md">Second active statement</article></div>'
                data = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                owner.post_count += 1
                self.send_error(405)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)


SNAPSHOT = r'''
const done=arguments[arguments.length-1],tabId=arguments[0];
browser.scripting.executeScript({target:{tabId},func:()=>{
  const article=document.querySelector('div.tab-pane.active > article.uoj-article.top-buffer-md');
  const rect=article.getBoundingClientRect(),link=document.getElementById('sensitive');
  const style=getComputedStyle(link);
  return {bodyText:document.body.innerText,documentTitle:document.title,
    articleRect:[rect.x,rect.y,rect.width,rect.height],linkColor:style.color,linkDecoration:style.textDecorationLine,
    sensitiveHrefCount:['sensitive','encoded','fragment','userinfo','svg-sensitive'].filter(id=>{const e=document.getElementById(id);return e.hasAttribute('href')||e.hasAttributeNS('http://www.w3.org/1999/xlink','href');}).length,
    safeHrefPresent:document.getElementById('safe').hasAttribute('href'),
    markers:document.querySelectorAll('[data-qoj-vp-pdf-path],[data-qoj-vp-pdf-article],[data-qoj-vp-pdf-hidden],[data-qoj-vp-pdf-title]').length,
    stylesheetCount:document.querySelectorAll('style').length,mathCount:article.querySelectorAll('math,mjx-container,.MathJax').length};
}}).then(values=>done(values[0].result),()=>done({error:true}));
'''


def main():
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    output_root = PROJECT / 'results/pdf-smoke'
    output = output_root / ('isolation-' + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=True)
    result = {'startedAt': utc_now(), 'picker': 'controlled in disposable browser',
              'renderer': 'real Firefox tabs.saveAsPDF', 'sourcePostEnabled': False,
              'nativeRegistrationChanged': False, 'checks': [], 'cleanup': {},
              'fixtureCredentials': 'public FAKE_* placeholders only', 'outputDir': str(output)}
    atomic_json(output / 'summary.json', {**result, 'status': 'running'})
    driver = None
    fixture = None
    try:
        addon = output / 'pdf-audit.xpi'
        addon_id, extension_uuid = 'qoj-vp-pdf-audit@littledrinks.local', str(uuid.uuid4())
        manifest = {'manifest_version': 3, 'name': 'QOJ VP isolated PDF audit',
                    'version': '0.0.2', 'permissions': ['tabs', 'scripting'],
                    'host_permissions': ['http://127.0.0.1/*'],
                    'browser_specific_settings': {'gecko': {'id': addon_id}}}
        product_script = PROJECT / 'extension/pdf-content.js'
        require(product_script.is_file(), 'Production PDF content script missing')
        result['productPdfContentSha256'] = hashlib.sha256(product_script.read_bytes()).hexdigest()
        with zipfile.ZipFile(addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('audit.html', '<!doctype html><meta charset="utf-8"><title>Isolated PDF controller</title>')
            archive.write(product_script, 'pdf-content.js')
            archive.write(PROJECT / 'extension/pdf-print.css', 'pdf-print.css')
        profile = PROJECT / 'state' / ('pdf-smoke-' + uuid.uuid4().hex)
        profile.mkdir(parents=True)
        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        for arg in ('-headless', '-profile', str(profile)):
            options.add_argument(arg)
        options.set_preference('browser.shell.checkDefaultBrowser', False)
        options.set_preference('extensions.webextensions.uuids', json.dumps({addon_id: extension_uuid}))
        service = Service(str(PROJECT / 'preflight/tools/geckodriver'),
                          service_args=['--allow-system-access'],
                          log_output=str(output / 'geckodriver.log'))
        driver = webdriver.Firefox(options=options, service=service)
        driver.command_executor.client_config.timeout = 70
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(45)
        require(driver.capabilities.get('moz:headless') is True, 'Browser must stay headless')
        require(Path(driver.capabilities['moz:profile']).resolve() == profile, 'Wrong isolated profile')
        driver.execute('INSTALL_ADDON', {'path': str(addon), 'temporary': True})
        driver.get(f'moz-extension://{extension_uuid}/audit.html')
        require(driver.execute_script('return typeof browser.tabs.saveAsPDF') == 'function', 'PDF API unavailable')
        driver.set_context('chrome')
        require(driver.execute_script(MOCK_PICKER, str(output / 'statement.pdf')), 'Picker not registered')
        driver.set_context('content')

        fixture = PdfFixture().start()
        fixture_url = fixture.origin + '/contest/3387/problem/15419'
        tab = driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          (async()=>{
            const tab=await browser.tabs.create({url:arguments[0],active:true});
            for(let n=0;n<100&&(await browser.tabs.get(tab.id)).status!=='complete';n++) await new Promise(r=>setTimeout(r,50));
            const values=await browser.scripting.executeScript({target:{tabId:tab.id},files:['pdf-content.js']});
            if(values.some(v=>v.error))throw new Error('content load failed');
            return {id:tab.id};
          })().then(done,e=>done({error:e.name}));
        ''', fixture_url)
        require('id' in tab, 'Production PDF script did not inject into the loopback tab')
        tab_id = tab['id']

        def snapshot():
            value = driver.execute_async_script(SNAPSHOT, tab_id)
            require(value and not value.get('error'), 'Could not observe fixture DOM')
            return value

        baseline = snapshot()
        require(baseline['sensitiveHrefCount'] == 5, 'Sensitive-link fixture was not initialized')

        def send(message):
            return driver.execute_async_script('''
              const done=arguments[arguments.length-1];
              browser.tabs.sendMessage(arguments[0],arguments[1]).then(done,e=>done({ok:false,code:e.name}));
            ''', tab_id, message)

        def save(path, picker_result):
            result['runningStep'] = {'destination': path.name, 'pickerResult': picker_result}
            atomic_json(output / 'summary.json', {**result, 'status': 'running'})
            driver.set_context('chrome')
            driver.execute_script('window.__qojPdfAudit.path=arguments[0];window.__qojPdfAudit.result=arguments[1]',
                                  str(path), picker_result)
            driver.set_context('content')
            return driver.execute_async_script('''
              const done=arguments[arguments.length-1];
              browser.tabs.update(arguments[0],{active:true}).then(()=>browser.tabs.saveAsPDF({headerLeft:"",headerCenter:"",headerRight:"",
                footerLeft:"",footerCenter:"",footerRight:""})).then(done,error=>done({error:error.name}));
            ''', tab_id)

        # Public synthetic baseline makes the original defect red-capable:
        # the same real renderer prints site-navigation FAKE-token URLs when
        # no statement isolation has been prepared.
        raw_pdf = output / 'synthetic-full-page-baseline.pdf'
        require(save(raw_pdf, 0) == 'saved', 'Synthetic whole-page baseline did not save')
        result['artifacts'] = {'unsafeSyntheticBaseline': str(raw_pdf)}

        def save_isolated(path, picker_result):
            request_id = str(uuid.uuid4())
            css_ready = driver.execute_async_script('''
              const done=arguments[arguments.length-1];
              browser.scripting.insertCSS({target:{tabId:arguments[0]},files:['pdf-print.css'],origin:'USER'}).then(()=>done(true),()=>done(false));
            ''', tab_id)
            require(css_ready is True, 'Production print stylesheet did not inject')
            try:
                prepared = send({'type': 'vp.pdf.prepare', 'requestId': request_id, 'expectedUrl': fixture_url,
                                 'problemLabel': 'A', 'problemName': 'PDF regression — 中文题面', 'stylesheetReady': True})
                require(prepared.get('ok') and prepared['sanitizedLinkCount'] == 5, 'Production PDF prepare did not sanitize all alternate credential forms')
                during = snapshot()
                require(during['bodyText'] == baseline['bodyText'], 'Print preparation changed visible screen text')
                require(all(abs(a - b) < 0.1 for a, b in zip(during['articleRect'], baseline['articleRect'])), 'Print preparation changed screen layout')
                require(during['linkColor'] == baseline['linkColor'] and during['linkDecoration'] == baseline['linkDecoration'], 'Removing href changed screen link appearance')
                require(during['sensitiveHrefCount'] == 0 and during['safeHrefPresent'], 'Credential links remain or safe reference was removed')
                require(during['mathCount'] == baseline['mathCount'], 'Math content was modified')
                return save(path, picker_result), prepared
            finally:
                restored = send({'type': 'vp.pdf.restore', 'requestId': request_id})
                removed = driver.execute_async_script('''
                  const done=arguments[arguments.length-1];
                  browser.scripting.removeCSS({target:{tabId:arguments[0]},files:['pdf-print.css'],origin:'USER'}).then(()=>done(true),()=>done(false));
                ''', tab_id)
                require(removed is True, 'Print stylesheet did not clean up')
                require(restored.get('ok') and restored.get('restored'), 'Production PDF cleanup failed')
                after = snapshot()
                require(after == baseline, 'PDF success/cancel/error did not restore the complete observed screen state')

        pdf = output / 'statement.pdf'
        status, isolation = save_isolated(pdf, 0)
        require(status == 'saved', 'Real saveAsPDF did not report saved: ' + str(status))
        data = pdf.read_bytes()
        require(data.startswith(b'%PDF-') and len(data) > 1000, 'Saved output is not a PDF')
        result['checks'].append({'name': 'real_extension_pdf_saved', 'status': 'passed',
                                  'apiStatus': status, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                  'isolation': isolation, 'screenAndHrefRestored': True})
        result['artifacts']['statement'] = str(pdf)
        canceled = output / 'canceled.pdf'
        status, _ = save_isolated(canceled, 1)
        require(status == 'canceled' and not canceled.exists(), 'Cancel wrote a file or returned wrong status')
        result['checks'].append({'name': 'cancel_does_not_write', 'status': 'passed', 'apiStatus': status, 'screenAndHrefRestored': True})
        # Gecko can create missing parent directories; an existing directory is
        # a deterministic invalid file destination, without changing permissions.
        status, _ = save_isolated(output, 0)
        require(status == 'not_saved', 'Write failure was not reported truthfully: ' + str(status))
        result['checks'].append({'name': 'write_failure_not_saved', 'status': 'passed', 'apiStatus': status, 'screenAndHrefRestored': True})

        # Strict region recognition must fail closed without invoking printing.
        ambiguous_url = fixture.origin + '/contest/3387/problem/15420'
        ambiguous = driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          (async()=>{
            const tab=await browser.tabs.create({url:arguments[0],active:true});
            for(let n=0;n<100&&(await browser.tabs.get(tab.id)).status!=='complete';n++)await new Promise(r=>setTimeout(r,50));
            await browser.scripting.executeScript({target:{tabId:tab.id},files:['pdf-content.js']});
            return browser.tabs.sendMessage(tab.id,{type:'vp.pdf.prepare',requestId:'ambiguous-synthetic',expectedUrl:arguments[0],problemLabel:'B',problemName:'Ambiguous fixture',stylesheetReady:true});
          })().then(done,e=>done({error:e.name}));
        ''', ambiguous_url)
        require(ambiguous.get('ok') is False and ambiguous.get('code') == 'PDF_STATEMENT_NOT_UNIQUE', 'Ambiguous statement did not fail closed')
        result['checks'].append({'name': 'ambiguous_statement_rejected_before_print', 'status': 'passed', 'evidence': ambiguous})
        driver.set_context('chrome')
        result['pickerCalls'] = driver.execute_script('return window.__qojPdfAudit.opens')
        require(len(result['pickerCalls']) == 4, 'Unexpected picker invocation count')
        driver.set_context('content')
        if shutil.which('pdfinfo') and shutil.which('pdftotext'):
            raw_urls = subprocess.run(['pdfinfo', '-url', str(raw_pdf)], check=True, capture_output=True).stdout.decode(errors='replace')
            urls = subprocess.run(['pdfinfo', '-url', str(pdf)], check=True, capture_output=True).stdout.decode(errors='replace')
            text = subprocess.run(['pdftotext', str(pdf), '-'], check=True, capture_output=True).stdout.decode(errors='replace')
            require('FAKE_NAV_TOKEN' in raw_urls, 'Baseline did not reproduce the URL disclosure')
            require(not any(value in urls.lower() for value in ('fake_', '_token', 'csrf', 'access_token', 'session=')), 'Isolated PDF still contains sensitive link annotations')
            require('https://example.org/reference?chapter=2' in urls, 'Legitimate reference link was lost')
            require('Sample Input' in text and 'Sample Output' in text and 'PDF regression' in text, 'Statement title/samples were lost')
            require(not any(value in text for value in ('SITE_NAV_NEVER_PRINT', 'SIDEBAR_NEVER_PRINT', 'TAB_CONTROLS_NEVER_PRINT', 'OUTSIDE_PROBLEM_TITLE_NEVER_PRINT', 'SUBMIT_FORM_NEVER_PRINT', 'FOOTER_NEVER_PRINT')), 'Non-statement content was printed')
            result['checks'].append({'name': 'decompressed_pdf_urls_and_text_audited', 'status': 'passed', 'originalLeakReproduced': True, 'sensitiveLinkCount': 0, 'safeReferenceRetained': True})
            result['pdfAudit'] = 'passed'
        else:
            result['pdfAudit'] = 'pending_host_pdfinfo_and_pdftotext'
        result['status'] = 'passed' if result['pdfAudit'] == 'passed' else 'browser_passed_host_audit_pending'
    except Exception as exc:
        result.update(status='failed', errorType=type(exc).__name__, message=str(exc)[:1500])
    finally:
        if driver:
            pid = driver.capabilities.get('moz:processID')
            try:
                driver.quit()
                result['cleanup']['firefox'] = process_exit(pid, timeout=20)
            except Exception as exc:
                result['cleanup']['errorType'] = type(exc).__name__
                result['status'] = 'failed'
        if fixture:
            fixture.stop()
            result['cleanup']['fixtureServerStopped'] = not fixture.thread.is_alive()
            result['fixturePostCount'] = fixture.post_count
            if fixture.post_count or fixture.thread.is_alive():
                result['status'] = 'failed'
        result['finishedAt'] = utc_now()
        atomic_json(output / 'summary.json', result)
        atomic_json(output_root / 'summary.json', result)
    return 0 if result.get('status') in {'passed', 'browser_passed_host_audit_pending'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
