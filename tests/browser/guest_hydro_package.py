#!/usr/bin/env python3
"""Installed Hydro package regression; isolated HOME/profile, no judge traffic."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signed-xpi', required=True, type=Path)
    parser.add_argument('--geckodriver', required=True, type=Path)
    parser.add_argument('--dependencies', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--deb', type=Path, help='Reinstall this package between browser launches')
    args = parser.parse_args()
    sys.path[:0] = ['/usr/lib/qoj-vp', str(args.dependencies)]
    from qojvp.native_host import read_frame, write_frame
    from qojvp import __version__
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    root = Path(tempfile.mkdtemp(prefix='hydro-package-', dir=args.output.parent))
    home = root / 'home'; home.mkdir()
    env = {**os.environ, 'HOME':str(home), 'XDG_CONFIG_HOME':str(home/'.config')}
    env.pop('QOJ_VP_STATE_DIR', None)
    state = home / 'custom-state'; state.mkdir()
    manifest = home / '.mozilla/native-messaging-hosts/org.littledrinks.qoj_vp.json'
    manifest.parent.mkdir(parents=True)
    old = {'name':'org.littledrinks.qoj_vp','description':'QOJ VP Workbench owned one-shot native helper',
           'path':str(state/'native-launcher.sh')}
    manifest.write_text(json.dumps(old))
    report = {'status':'failed','realQojSubmissions':0,'network':'blocked proxy', 'checks':[]}
    driver = None
    expected_hash = hashlib.sha256(args.signed_xpi.read_bytes()).hexdigest()
    def check(name, condition):
        if not condition: raise AssertionError(name)
        report['checks'].append(name)
    def native(method, arguments):
        request=io.BytesIO();write_frame(request,{'type':'task','id':'package-test','method':method,'args':arguments})
        p=subprocess.run(['/usr/lib/qoj-vp/native-host'],input=request.getvalue(),capture_output=True,env=env,timeout=20)
        reply=read_frame(io.BytesIO(p.stdout))
        check('native '+method, p.returncode==0 and reply['ok'])
        return reply
    def browser():
        options=Options();options.binary_location='/usr/bin/firefox-esr'
        for arg in ['-headless','-profile',str(root/'profile')]:options.add_argument(arg)
        for k,v in {'browser.shell.checkDefaultBrowser':False,'browser.startup.page':0,
          'browser.startup.homepage':'about:blank','network.proxy.type':1,
          'network.proxy.http':'127.0.0.1','network.proxy.http_port':9,
          'network.proxy.ssl':'127.0.0.1','network.proxy.ssl_port':9,
          'xpinstall.signatures.required':True}.items():options.set_preference(k,v)
        d=webdriver.Firefox(options=options,service=Service(str(args.geckodriver),env=env,
          service_args=['--allow-system-access'],log_output=str(root/'geckodriver.log')))
        d.set_script_timeout(25)
        return d
    def browser_native(method):
        driver.set_context('chrome')
        url=driver.execute_script("return WebExtensionPolicy.getByID('qoj-vp@littledrinks.local').getURL('ui.html');")
        driver.set_context('content');driver.get(url)
        return driver.execute_async_script('''
          const done=arguments[arguments.length-1];
          browser.runtime.sendNativeMessage('org.littledrinks.qoj_vp',
            {type:'task',id:'package-browser',method:arguments[0],args:{}}).then(done,e=>done({error:String(e)}));
        ''',method)
    try:
        prepared=subprocess.run(['/usr/bin/qoj-vp','--check'],env=env,capture_output=True,text=True,timeout=30)
        report['setup']=json.loads(prepared.stdout)
        check('desktop migration and connection',prepared.returncode==0 and report['setup']['stateDir']==str(state))
        check('legacy registration backed up',not manifest.exists() and len(list(manifest.parent.glob('*.before-deb-*')))==1)
        session=native('create_session',{'contestId':'1','title':'Package QA (no VP started)'})['result']
        sid=session['sessionId']
        repeat=subprocess.run(['/usr/bin/qoj-vp','--check'],env=env,capture_output=True,text=True,timeout=30)
        check('repeat setup retains state',repeat.returncode==0 and json.loads(repeat.stdout)['stateDir']==str(state))
        (root/'profile').mkdir()
        driver=browser()
        driver.install_addon(str(args.signed_xpi),temporary=False)
        for phase in ['first launch','restart']:
            if phase=='restart':
                driver.quit();driver=None
                if args.deb:
                    subprocess.run(['sudo','-n','dpkg','-i',str(args.deb.resolve())],check=True,timeout=60)
                driver=browser()
            driver.set_context('chrome')
            install=driver.execute_async_script('''const done=arguments[arguments.length-1];
              const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              AddonManager.getAddonByID('qoj-vp@littledrinks.local').then(a=>done({version:a.version,
                signed:a.signedState===AddonManager.SIGNEDSTATE_SIGNED,active:a.isActive,temporary:a.temporarilyInstalled}));''')
            report[phase]=install
            check(phase+' signed installation',install['signed'] and install['active'] and not install['temporary'])
            check(phase+' expected extension version', install['version']==__version__)
            installed=root/'profile/extensions/qoj-vp@littledrinks.local.xpi'
            check(phase+' exact signed payload', hashlib.sha256(installed.read_bytes()).hexdigest()==expected_hash)
            hello=browser_native('hello')
            check(phase+' global native connection',hello.get('ok') and hello['result']['stateDir']==str(state))
            check(phase+' matching helper version',hello['result']['version']==__version__)
            sessions=browser_native('list_sessions')
            check(phase+' persisted competition',sessions.get('ok') and any(s['sessionId']==sid for s in sessions['result']['sessions']))
            pid=hello['pid']
            for _ in range(30):
                if not Path('/proc',str(pid)).exists():break
                time.sleep(.1)
            check(phase+' helper exits',not Path('/proc',str(pid)).exists())
        report['status']='passed'
    except Exception as error:
        import traceback
        report['error']=traceback.format_exc()
    finally:
        if driver:driver.quit()
        report['evidenceRoot']=str(root)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    return int(report['status']!='passed')

if __name__=='__main__':raise SystemExit(main())
