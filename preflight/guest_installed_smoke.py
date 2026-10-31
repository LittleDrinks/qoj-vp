#!/usr/bin/env python3
"""Smoke-test the installed real-mode helper; never sends source code."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'preflight/vendor_py'), str(PROJECT / 'preflight')]
from guest_preflight import atomic_json, process_exit, require, utc_now


def main():
    output = PROJECT / 'results/installed-smoke'
    output.mkdir(parents=True, exist_ok=True)
    result = {'startedAt': utc_now(), 'sourceCodePostEnabled': False, 'cleanup': {}}
    atomic_json(output / 'summary.json', result)
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        manifest = Path.home() / '.mozilla/native-messaging-hosts/org.littledrinks.qoj_vp.json'
        registration = json.loads(manifest.read_text())
        require(registration['description'] == 'QOJ VP Workbench owned one-shot native helper', 'Real-mode installation is missing')
        addon = output / 'workbench.xpi'
        with zipfile.ZipFile(addon, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((PROJECT / 'extension').rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(PROJECT / 'extension')))
        profile = PROJECT / 'state/installed-smoke-profile'
        profile.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        options.add_argument('-headless')
        options.add_argument('-profile')
        options.add_argument(str(profile))
        options.set_preference('browser.shell.checkDefaultBrowser', False)
        service = Service(str(PROJECT / 'preflight/tools/geckodriver'), log_output=str(output / 'geckodriver.log'))
        driver = webdriver.Firefox(options=options, service=service)
        driver.set_page_load_timeout(40)
        driver.set_script_timeout(100)
        require(Path(driver.capabilities['moz:profile']).resolve() == profile, 'Wrong smoke profile')
        require(driver.capabilities.get('moz:headless') is True, 'Browser must stay headless')
        driver.execute('INSTALL_ADDON', {'path': str(addon), 'temporary': True})
        deadline = time.monotonic() + 30
        ui = None
        while time.monotonic() < deadline:
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                if driver.current_url.startswith('moz-extension://') and driver.current_url.endswith('/ui.html'):
                    if driver.execute_script('return !!window.qojVpUi?.getState().connected'):
                        ui = handle
                        break
            if ui:
                break
            time.sleep(0.1)
        require(ui is not None, 'Installed helper did not connect to workbench')

        def call(method, args=None):
            driver.switch_to.window(ui)
            return driver.execute_async_script('''
              const done=arguments[arguments.length-1];
              browser.runtime.sendMessage({type:'vp.task',method:arguments[0],args:arguments[1]}).then(done,
                e=>done({ok:false,error:{message:e.name}}));
            ''', method, args or {})

        hello = call('hello')
        require(hello.get('ok') and hello['result'].get('fixture') is False, 'Helper must use real QOJ mode')
        require(hello['result']['stateDir'] == str(Path.home() / '.local/share/qoj-vp'), 'Wrong real user state directory')
        result['hello'] = hello['result']
        result['helperExit'] = process_exit(hello['result']['helperPid'])
        result['capabilities'] = driver.execute_script('return {saveAsPDF:typeof browser.tabs.saveAsPDF==="function"}')
        driver.save_screenshot(str(output / 'workbench-ready.png'))
        # No credentials are imported. This is an access observation, never a
        # claim that the authenticated submission acceptance is complete.
        observed = call('qoj_contest', {'contestId': '3387'})
        if observed.get('ok'):
            result['realQojRead'] = {'outcome': 'read-passed', 'source': observed['result'].get('source'),
                                     'problemCount': len(observed['result'].get('problems', []))}
        else:
            error = observed.get('error', {})
            result['realQojRead'] = {'outcome': 'access-or-login-required', 'error': error,
                                     'authenticatedSubmission': 'not-tested'}
        result['status'] = 'passed'
    except Exception as exc:
        result.update(status='failed', errorType=type(exc).__name__, message=str(exc)[:1200])
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
