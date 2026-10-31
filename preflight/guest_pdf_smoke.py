#!/usr/bin/env python3
"""Exercise Firefox's real saveAsPDF engine with an isolated mock file picker.

No native registration, QOJ session, or user browser profile is changed. Only
the picker is controlled; Firefox's extension API and PDF renderer stay real.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
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


def main():
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    output = PROJECT / 'results/pdf-smoke'
    output.mkdir(parents=True, exist_ok=True)
    result = {'startedAt': utc_now(), 'picker': 'controlled in disposable browser',
              'renderer': 'real Firefox tabs.saveAsPDF', 'sourcePostEnabled': False,
              'nativeRegistrationChanged': False, 'checks': [], 'cleanup': {}}
    atomic_json(output / 'summary.json', {**result, 'status': 'running'})
    driver = None
    try:
        addon = output / 'pdf-audit.xpi'
        addon_id, extension_uuid = 'qoj-vp-pdf-audit@littledrinks.local', str(uuid.uuid4())
        manifest = {'manifest_version': 3, 'name': 'QOJ VP isolated PDF audit',
                    'version': '0.0.1', 'permissions': ['tabs'],
                    'browser_specific_settings': {'gecko': {'id': addon_id}}}
        html = '''<!doctype html><meta charset="utf-8"><title>QOJ VP PDF audit</title>
          <style>body{font:16px sans-serif;margin:40px}pre{background:#eee;padding:12px}
          @media print{.screen-only{display:none}}</style>
          <h1>Problem A — PDF regression</h1><p>题面 PDF：中文样例与数学公式。</p>
          <p>Evaluate <math><mfrac><mrow><mi>n</mi><mo>(</mo><mi>n</mi><mo>+</mo><mn>1</mn><mo>)</mo></mrow><mn>2</mn></mfrac></math>.</p>
          <h2>Sample Input</h2><pre>3\n</pre><h2>Sample Output</h2><pre>6\n</pre>
          <p class="screen-only">SCREEN_ONLY_NOT_PRINTED</p>'''
        with zipfile.ZipFile(addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('statement.html', html)
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
        driver.get(f'moz-extension://{extension_uuid}/statement.html')
        require(driver.execute_script('return typeof browser.tabs.saveAsPDF') == 'function', 'PDF API unavailable')
        driver.set_context('chrome')
        require(driver.execute_script(MOCK_PICKER, str(output / 'statement.pdf')), 'Picker not registered')
        driver.set_context('content')

        def save(path, picker_result):
            result['runningStep'] = {'destination': path.name, 'pickerResult': picker_result}
            atomic_json(output / 'summary.json', {**result, 'status': 'running'})
            driver.set_context('chrome')
            driver.execute_script('window.__qojPdfAudit.path=arguments[0];window.__qojPdfAudit.result=arguments[1]',
                                  str(path), picker_result)
            driver.set_context('content')
            return driver.execute_async_script('''
              const done=arguments[arguments.length-1];
              browser.tabs.saveAsPDF({headerLeft:"",headerCenter:"",headerRight:"",
                footerLeft:"",footerCenter:"",footerRight:""}).then(done,
                error=>done({error:error.name,message:error.message}));
            ''')

        pdf = output / 'statement.pdf'
        status = save(pdf, 0)
        require(status == 'saved', 'Real saveAsPDF did not report saved: ' + str(status))
        data = pdf.read_bytes()
        require(data.startswith(b'%PDF-') and len(data) > 1000, 'Saved output is not a PDF')
        result['checks'].append({'name': 'real_extension_pdf_saved', 'status': 'passed',
                                  'apiStatus': status, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        canceled = output / 'canceled.pdf'
        status = save(canceled, 1)
        require(status == 'canceled' and not canceled.exists(), 'Cancel wrote a file or returned wrong status')
        result['checks'].append({'name': 'cancel_does_not_write', 'status': 'passed', 'apiStatus': status})
        # Gecko can create missing parent directories; an existing directory is
        # a deterministic invalid file destination, without changing permissions.
        status = save(output, 0)
        require(status == 'not_saved', 'Write failure was not reported truthfully: ' + str(status))
        result['checks'].append({'name': 'write_failure_not_saved', 'status': 'passed', 'apiStatus': status})
        driver.set_context('chrome')
        result['pickerCalls'] = driver.execute_script('return window.__qojPdfAudit.opens')
        require(len(result['pickerCalls']) == 3, 'Unexpected picker invocation count')
        result['status'] = 'passed'
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
        result['finishedAt'] = utc_now()
        atomic_json(output / 'summary.json', result)
    return 0 if result.get('status') == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
