#!/usr/bin/env python3
"""Hydro Firefox: original VP bundle vs local Board using one isolated SRK."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlencode, urlsplit

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT), str(PROJECT/'tests/browser'), str(PROJECT/'tests/browser/vendor_py')]
import guest_visual_parity as visual
from guest_rankland_sync import Board, Judge
from guest_preflight import atomic_json, require, utc_now
from rankland_probe import _click_text, _dismiss_settings_intro

visual.HOST='org.littledrinks.qoj_vp_board_parity_qa'
visual.EXTENSION_ID='qoj-vp-board-parity-qa@littledrinks.local'
visual.OWNER='QOJ VP isolated Board parity QA v1'


class Reference(Board):
    def __init__(self):
        super().__init__()
        self.archive=None
        self.source_offline=False

    def response(self, path, xhr):
        if path=='/feed.srk.json' and self.archive is not None:
            return 200,json.dumps(self.archive,ensure_ascii=False).encode(),'application/json'
        if self.source_offline and (path.startswith('/api/') or path=='/feed.srk.json'):
            return 503,b'Synthetic source outage','text/plain'
        return super().response(path,xhr)


class Harness(visual.VisualHarness):
    def start_browser(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        options=Options()
        options.binary_location='/usr/bin/firefox-esr'
        for argument in ['-headless','-profile',str(self.profile)]:options.add_argument(argument)
        options.set_capability('unhandledPromptBehavior','ignore')
        for key,value in {'browser.shell.checkDefaultBrowser':False,'browser.startup.page':0,
            'browser.startup.homepage':'about:blank','browser.sessionstore.resume_from_crash':False}.items():
            options.set_preference(key,value)
        service=Service(str(self.project/'tests/browser/tools/geckodriver'),service_args=['--allow-system-access'],
            log_output=str(self.results/'geckodriver.log'))
        self.driver=webdriver.Firefox(options=options,service=service)
        self.driver.set_page_load_timeout(45)
        self.driver.set_script_timeout(160)
        self.driver.set_window_size(self.width,self.height)
        capabilities=self.driver.capabilities
        require(Path(capabilities['moz:profile']).resolve()==self.profile,'Firefox profile was copied or not isolated')
        require(capabilities.get('moz:headless') is True,'Browser is not headless')
        return {'pid':capabilities['moz:processID'],'version':capabilities['browserVersion'],
            'profile':capabilities['moz:profile'],'headless':True,'profileCopied':False,
            'viewport':self.driver.execute_script('return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio};')}

    def install_extension(self):
        installed=self.driver.execute('INSTALL_ADDON',{'path':str(self.addon),'temporary':False})['value']
        require(installed==visual.EXTENSION_ID,'Unexpected persistent alias extension identifier')
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                url=self.driver.current_url
                if url.startswith('moz-extension://') and urlsplit(url).path=='/ui.html':
                    if self.driver.execute_script('return !!window.qojVpUi?.getState().connected;'):
                        self.ui_handle,self.ui_url=handle,url
                        return {'extensionId':installed,'temporary':False,'installation':'isolated-profile-persistent'}
            time.sleep(.1)
        raise AssertionError('Persistent isolated workbench did not connect')

    def flush(self):
        self.summary.update(phase=self.phase,updatedAt=utc_now())
        atomic_json(self.results/'summary.json',self.summary)
        atomic_json(self.project/'results/board-parity-summary.json',self.summary)


def selected_rows(driver):
    return driver.execute_script("return [...document.querySelectorAll('.srk-main tbody tr[data-rich-row=\"true\"]')].map(row=>row.innerText);")


def wait_local(h, description='local board'):
    return h.wait(lambda:h.driver.execute_script('''const root=document.querySelector('.qoj-board');
      return window.qojVpUi?.getState().connected && !!root?.querySelector('.srk-main') && root.querySelectorAll('.srk-main tbody tr').length>1 &&
        root.querySelector('.srk-ranklist-title')?.textContent.includes('QOJ 前置测试');'''),description)


def metrics(driver):
    return driver.execute_script('''
      const rect=e=>{if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};};
      const style=e=>{if(!e)return null;const s=getComputedStyle(e);return {color:s.color,backgroundColor:s.backgroundColor,fontSize:s.fontSize,
        fontFamily:s.fontFamily,fontWeight:s.fontWeight,lineHeight:s.lineHeight,padding:s.padding,borderRadius:s.borderRadius};};
      const root=document.querySelector('[data-id="vp-ranklist-content"]'),table=root?.querySelector('.srk-main > table');
      const header=table?.tHead?.rows[0],first=table?.tBodies[0]?.rows[0];
      return {url:location.href,viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},root:rect(root),rootStyle:style(root),title:rect(root?.querySelector('.srk-ranklist-title')),
        titleStyle:style(root?.querySelector('.srk-ranklist-title')),header:rect(header),firstRow:rect(first),headerCells:header?[...header.cells].map(rect):[],
        firstCells:first?[...first.cells].map(rect):[],tableStyle:style(table),rows:table?.tBodies[0]?.rows.length||0,
        problemHeaderAlign:[...root.querySelectorAll('thead .srk-problem-header')].map(e=>getComputedStyle(e).textAlign),
        speedWidth:document.querySelector('.qoj-speed-select')?.getBoundingClientRect().width||null,
        richRows:root?.querySelectorAll('tbody tr[data-rich-row="true"]').length||0,
        retainedNames:root?.querySelectorAll('.srk-main tbody .srk-user-name-text').length||0,
        windowed:root?.querySelector('.ranklist-window')?.dataset.windowed||null,scrollY,
        modalWidth:document.querySelector('[data-srk-modal-panel="true"]')?.getBoundingClientRect().width||null,
        elapsed:root?.querySelector('.srk-progress-secondary-area-left')?.textContent||'',theme:root?.dataset.theme||document.documentElement.className};
    ''')


def capture(driver, results, label):
    driver.execute_script('window.scrollTo(0,0);if(document.activeElement?.blur)document.activeElement.blur();')
    time.sleep(.35)
    driver.save_screenshot(str(results/(label+'.png')))
    value=metrics(driver)
    atomic_json(results/(label+'.json'),value)
    return value


def seek(driver, minutes):
    from selenium.webdriver.common.keys import Keys
    slider=driver.find_element('css selector','.qoj-board input[aria-label="Time Travel"]')
    if slider.get_attribute('value')!=str(minutes):
        slider.send_keys(Keys.HOME)
        while int(slider.get_attribute('value'))<minutes:
            remaining=minutes-int(slider.get_attribute('value'))
            slider.send_keys(Keys.PAGE_UP if remaining>=30 else Keys.ARROW_RIGHT)
            time.sleep(.08)
    def complete():
        return driver.execute_script('''const input=document.querySelector('.qoj-board input[aria-label="Time Travel"]');
          const region=document.querySelector('.qoj-board .srk-ranklist-table-scroll');
          return input?.value===String(arguments[0]) && region?.getAttribute('aria-busy')==='false' &&
            window.qojVpUi?.getState().connected && region.querySelectorAll('tbody tr').length>1 &&
            document.querySelector('.qoj-board .srk-ranklist-title')?.textContent.includes('QOJ 前置测试') &&
            document.querySelector('.qoj-board .srk-progress-secondary-area-left')?.textContent.includes(arguments[1]);''',minutes,f'{minutes//60:02d}:{minutes%60:02d}:00')
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if complete():return
        time.sleep(.1)
    raise AssertionError(f'Local Board did not seek to {minutes}: '+str(driver.execute_script("return document.querySelector('.qoj-board .srk-progress-secondary-area-left')?.textContent")))


def close_modal(driver):
    from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
    deadline=time.monotonic()+5
    clicked=False
    while time.monotonic()<deadline:
        try:
            roots=[e for e in driver.find_elements('css selector','.srk-modal-root') if e.is_displayed()]
            if not roots:return
            if not clicked:
                buttons=[e for e in driver.find_elements('css selector','.srk-modal-root .srk-modal-close') if e.is_displayed()]
                if buttons:
                    buttons[-1].click();clicked=True
        except (StaleElementReferenceException,ElementClickInterceptedException):
            pass
        time.sleep(.1)
    raise AssertionError('Ranklist modal did not close')


def pro_switch(driver):
    buttons=driver.find_elements('xpath', '//*[normalize-space()="Pro 模式"]/ancestor::div[contains(@class,"srk-ranklist-setting-item")][1]//button')
    require(buttons,'Pro mode switch is missing')
    return buttons[-1]


def org_filter(driver):
    from selenium.webdriver.common.keys import Keys
    driver.find_element('css selector','[data-id="ranklist-org-multi-select"]').click()
    field=driver.find_element('css selector','[data-id="ranklist-org-search"]')
    field.send_keys('Synthetic fixtures')
    before=driver.execute_script("return document.querySelectorAll('.srk-main tbody tr').length;")
    option=driver.find_element('css selector','[data-id="ranklist-org-option-Synthetic fixtures"]')
    option.click()
    deadline=time.monotonic()+5
    def applied():
        return driver.execute_script('''return !!document.querySelector('[data-id="ranklist-org-selected-count"]') &&
          document.querySelectorAll('.srk-main tbody tr').length<arguments[0];''',before)
    while time.monotonic()<deadline and not applied():time.sleep(.1)
    require(applied(),'Organization selection did not filter real rows')
    option.send_keys(Keys.ESCAPE)
    while time.monotonic()<deadline:
        if not driver.find_elements('css selector','[data-id="ranklist-org-search"]'):return
        time.sleep(.1)
    raise AssertionError('Organization dropdown did not close')


def main():
    h=Harness(PROJECT,1440,1000)
    h.summary.update(schema='qoj-vp-board-parity-v1',realFirefox=True,realExternalVpCreated=False,
        reference='unmodified upstream VP bundle on loopback',sourceFilesSelected=0)
    judge=Judge().start()
    reference=Reference().start()
    session=None
    try:
        require(h.step('isolated_product_install',lambda:h.setup_visual(judge)) is not None,'Setup failed')
        (h.profile/'user.js').write_text('user_pref("intl.accept_languages", "zh-CN, zh, en");\nuser_pref("xpinstall.signatures.required", false);\n')
        require(h.step('headless_firefox',h.start_browser) is not None,'Firefox failed')
        require(h.step('extension_native_connection',h.install_extension) is not None,'Extension failed')
        archive=json.loads((PROJECT/'tests/browser/rankland-fixtures/feed.srk.json').read_text())
        archive['rows'].append({'user':{'id':'fixture-unofficial','name':'Fixture unofficial','organization':'Guest College','official':False},
            'score':{'value':0,'time':[0,'s']},'statuses':[{'result':None,'solutions':[]},{'result':None,'solutions':[]}]})
        for index in range(342):
            archive['rows'].append({'user':{'id':f'fixture-large-{index}','name':f'Large board team {index:03d}',
                'organization':'Synthetic fixtures' if index%2==0 else 'Another school','official':True},
                'score':{'value':0,'time':[0,'s']},'statuses':[{'result':None,'solutions':[]},{'result':None,'solutions':[]}]})
        reference.archive=archive
        start=1767225600000
        raw=reference.origin+'/?'+urlencode({'contest':'qoj-preflight-fixture','rule':'ICPC','feed':'0'})
        def create():
            nonlocal session
            session=h.call('create_session',{'contestId':'3387','account':judge.account,'title':'Board parity fixture',
                'startAt':start,'durationMs':18000000,'ranklandUrl':raw,'board':{'rule':'ICPC'}})
            record={'archive':archive,'hash':'parity-v1','contestKey':'qoj-preflight-fixture','fetchedAt':int(time.time()*1000)}
            result=h.driver.execute_async_script('''const done=arguments[arguments.length-1],record=arguments[0],key=arguments[1];
              const r=indexedDB.open('qoj-vp-board',1);r.onupgradeneeded=()=>r.result.createObjectStore('archives');
              r.onsuccess=()=>{const tx=r.result.transaction('archives','readwrite');tx.objectStore('archives').put(record,key);
              tx.oncomplete=()=>done({ok:true});tx.onerror=()=>done({error:String(tx.error)});};r.onerror=()=>done({error:String(r.error)});''',
              record,reference.origin+':qoj-preflight-fixture')
            require(result.get('ok'),'Cache setup failed')
            return {'sessionId':session['sessionId'],'rows':len(archive['rows'])}
        require(h.step('same_srk_local_session',create) is not None,'Session failed')
        reference_url=reference.origin+'/?'+urlencode({'contest':'qoj-preflight-fixture','rule':'ICPC','from':'120','play':'0','feed':'0'})
        def prepare_reference():
            nonlocal reference_url
            h.driver.switch_to.new_window('tab');h.driver.get(reference_url)
            h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference board',60)
            _dismiss_settings_intro(h.driver)
            _click_text(h.driver,'加入我的队伍')
            field=h.driver.find_element('css selector','input[aria-label="队伍名称"]');field.send_keys(judge.account)
            _click_text(h.driver,'加入')
            h.wait(lambda:h.driver.execute_script('return [...document.querySelectorAll(".srk-user-name-text")].some(e=>e.textContent===arguments[0]);',judge.account),'reference own team')
            reference_url=h.driver.current_url
            return {'url':reference_url,'metrics':metrics(h.driver)}
        require(h.step('reference_real_controls_and_team',prepare_reference) is not None,'Reference failed')
        local_url=h.ui_url.split('?')[0].split('#')[0]+'?session='+session['sessionId']+'#scoreboard'
        def prepare_local():
            h.focus_ui();h.driver.get(local_url)
            wait_local(h,'local board')
            feed=h.driver.find_element('css selector','.qoj-board [aria-label="实时滚动提交状态"]')
            if feed.get_attribute('aria-checked')=='true':feed.click()
            seek(h.driver,120)
            require(h.driver.execute_script('return document.querySelectorAll(".qoj-board .srk-main tbody tr").length')==len(archive['rows'])+1,'Own row missing')
            return metrics(h.driver)
        require(h.step('local_real_controls_and_time',prepare_local) is not None,'Local failed')
        def main_pair():
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference main')
            _dismiss_settings_intro(h.driver);ref=capture(h.driver,h.results,'reference-main-light')
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local main')
            seek(h.driver,120);local=capture(h.driver,h.results,'local-main-light')
            require(ref['viewport']==local['viewport'],'Viewport differs')
            require(ref['rows']==local['rows']==len(archive['rows'])+1,'SRK row count differs')
            require(local['problemHeaderAlign']==ref['problemHeaderAlign']==['center']*len(archive['problems']), 'Host CSS changed problem header alignment')
            require(0<local['speedWidth']<100, 'Playback speed inherited the organization filter width')
            require(local['firstRow']['y']+1>=max(cell['bottom'] for cell in local['headerCells']),'Header cells overlap first row')
            atomic_json(h.results/'main-comparison.json',{'reference':ref,'local':local,'pixelEquality':'assessed separately; not assumed'})
            return {'reference':ref['titleStyle'],'local':local['titleStyle'],'rows':local['rows'],'richRows':local['richRows']}
        require(h.step('desktop_main_light_same_data_time_viewport',main_pair) is not None,'Main comparison failed')
        def filter_pair():
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference filter')
            _dismiss_settings_intro(h.driver);org_filter(h.driver);ref=capture(h.driver,h.results,'reference-filter')
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local filter')
            seek(h.driver,120);org_filter(h.driver);local=capture(h.driver,h.results,'local-filter')
            require('本队被当前筛选隐藏' in h.driver.find_element('css selector','.qoj-board').text,'Own filter path missing')
            h.driver.find_element('css selector','[data-id="board-locate-own"]').click()
            h.wait(lambda:h.driver.execute_script('return !!document.querySelector(".qoj-board tr[data-own-team]")'),'own locate after clearing filter')
            h.wait(lambda:h.driver.execute_script('''const row=document.querySelector('.qoj-board tr[data-own-team]');
              if(!row)return false;const r=row.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;'''),'own row enters viewport')
            h.driver.execute_script("window.scrollTo({top:0,behavior:'instant'});")
            h.driver.find_element('css selector','.qoj-board [aria-label="仅正式参赛"]').click()
            require(not any('Fixture unofficial' in row for row in selected_rows(h.driver)),'Official filter failed')
            h.driver.find_element('css selector','.qoj-board [aria-label="仅正式参赛"]').click()
            return {'referenceRows':ref['rows'],'filteredLocalRows':local['rows'],'ownLocate':True,'officialOnly':True}
        require(h.step('real_filter_official_and_own_location',filter_pair) is not None,'Filter interaction failed')
        def settings_pair():
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference settings')
            _dismiss_settings_intro(h.driver);h.driver.find_element('css selector','[data-id="ranklist-settings-action"]').click();time.sleep(.35)
            pro_switch(h.driver).click()
            h.wait(lambda:pro_switch(h.driver).get_attribute('data-state')=='checked' or pro_switch(h.driver).get_attribute('aria-checked')=='true','reference Pro enabled')
            capture(h.driver,h.results,'reference-settings')
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local settings')
            h.driver.find_element('css selector','[data-id="ranklist-settings-action"]').click();time.sleep(.35)
            pro=pro_switch(h.driver)
            if pro.get_attribute('aria-checked')!='true':pro.click()
            h.wait(lambda:pro_switch(h.driver).get_attribute('data-state')=='checked' or pro_switch(h.driver).get_attribute('aria-checked')=='true','local Pro enabled')
            capture(h.driver,h.results,'local-settings')
            before=h.driver.execute_script('window.__parityRow=document.querySelector(".qoj-board tbody tr[data-rich-row=true]");return scrollY;')
            h.driver.execute_async_script('const done=arguments[arguments.length-1];window.qojVpUi.refresh().then(()=>done(true),()=>done(false));')
            require(pro_switch(h.driver).is_displayed(),'Refresh closed settings')
            require(h.driver.execute_script('return window.__parityRow===document.querySelector(".qoj-board tbody tr[data-rich-row=true]");'),'Refresh replaced visible rows')
            close_modal(h.driver)
            require(h.driver.find_element('css selector','.qoj-board tfoot').is_displayed(),'Pro footer did not render')
            return {'proFooter':True,'refreshRetainedModal':True,'refreshRetainedRow':True,'scrollYBefore':before}
        require(h.step('real_settings_and_non_destructive_refresh',settings_pair) is not None,'Settings interaction failed')
        def details_pair():
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference user')
            _dismiss_settings_intro(h.driver);h.driver.find_element('css selector','.srk-main tbody .srk-user-cell').click();ref_user=capture(h.driver,h.results,'reference-user-detail');close_modal(h.driver)
            h.driver.find_element('css selector','.srk-main thead .srk-problem-header').click();ref_problem=capture(h.driver,h.results,'reference-problem-detail');close_modal(h.driver)
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local details')
            h.driver.find_element('css selector','.qoj-board .srk-main tbody .srk-user-cell').click()
            require('Fixture ghost' in h.driver.find_element('css selector','.srk-react-modal-root').text,'User detail content missing')
            local_user=capture(h.driver,h.results,'local-user-detail')
            require(ref_user['modalWidth']==local_user['modalWidth']==960,'Desktop user modal width differs')
            close_modal(h.driver)
            h.driver.find_element('css selector','.qoj-board .srk-main thead .srk-problem-header').click()
            require('Accepted' in h.driver.find_element('css selector','.srk-react-modal-root').text,'Problem statistics missing')
            local_problem=capture(h.driver,h.results,'local-problem-detail')
            require(ref_problem['modalWidth']==local_problem['modalWidth']==680,'Desktop problem modal width differs')
            close_modal(h.driver)
            h.driver.find_element('css selector','.qoj-board .srk-main .srk-prest-status-block-accepted').click()
            require('Solutions of' in h.driver.find_element('css selector','.srk-react-modal-root').text,'Solution detail missing')
            capture(h.driver,h.results,'local-solution-detail');close_modal(h.driver)
            return {'user':True,'problem':True,'solution':True,'userModalWidth':local_user['modalWidth'],'problemModalWidth':local_problem['modalWidth']}
        require(h.step('real_team_problem_and_solution_details',details_pair) is not None,'Details failed')
        def scroll_pair():
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference scroll')
            _dismiss_settings_intro(h.driver)
            h.driver.execute_script('window.scrollTo(0,document.querySelector(".srk-main tbody").getBoundingClientRect().top+scrollY+7200);')
            time.sleep(.4);ref=metrics(h.driver);h.driver.save_screenshot(str(h.results/'reference-large-scroll.png'))
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local scroll')
            h.driver.execute_script('window.scrollTo(0,document.querySelector(".qoj-board .srk-main tbody").getBoundingClientRect().top+scrollY+7200);')
            time.sleep(.4);local=metrics(h.driver);h.driver.save_screenshot(str(h.results/'local-large-scroll.png'))
            require(0<local['richRows']<=60,'Local virtual list is not bounded')
            require(local['retainedNames']==local['rows'],'Offscreen identities are not retained')
            require(ref['rows']==local['rows'],'Reference/local row totals differ')
            return {'referenceRich':ref['richRows'],'localRich':local['richRows'],'localRows':local['rows'],'localRetained':local['retainedNames']}
        require(h.step('large_board_real_scroll_window',scroll_pair) is not None,'Large board failed')
        def feed_reference():
            h.driver.get(reference.origin+'/?'+urlencode({'contest':'qoj-preflight-fixture','rule':'ICPC','from':'29','play':'1','speed':'10','feed':'1'}))
            h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference feed')
            _dismiss_settings_intro(h.driver);before=h.driver.execute_script('return scrollY;')
            h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=scroll-solution-container] .plugin_scroll-solution-toast")'),'reference feed cards',20)
            after=h.driver.execute_script('return scrollY;');require(before==after,'Submission feed scrolled the main page')
            h.driver.save_screenshot(str(h.results/'reference-feed.png'))
            return {'cards':True,'scrollYBefore':before,'scrollYAfter':after}
        require(h.step('reference_feed_is_toast_queue_not_page_scroll',feed_reference) is not None,'Reference feed failed')
        def feed_local():
            h.focus_ui();h.driver.get(local_url);wait_local(h,'local feed')
            toggle=h.driver.find_element('css selector','.qoj-board [aria-label="实时滚动提交状态"]')
            if toggle.get_attribute('aria-checked')!='true':toggle.click()
            seek(h.driver,0);before=h.driver.execute_script('return scrollY;');seek(h.driver,120)
            h.wait(lambda:'Fixture ghost' in h.driver.find_element('css selector','.qoj-board [data-id="scroll-solution-container"]').text,'local submission feed cards')
            require(before==h.driver.execute_script('return scrollY;'),'Local feed scrolled the main page')
            h.driver.save_screenshot(str(h.results/'local-feed.png'))
            h.driver.find_element('css selector','.qoj-board [aria-label="实时滚动提交状态"]').click()
            h.wait(lambda:not h.driver.find_elements('css selector','.qoj-board .plugin_scroll-solution-toast'),'local feed switch clears cards')
            return {'cards':True,'scrollYBefore':before,'scrollYAfter':h.driver.execute_script('return scrollY;'),'disableClearsCards':True}
        require(h.step('local_feed_matches_toast_behavior',feed_local) is not None,'Local feed failed')
        def restart_dark():
            def mark(stage):
                atomic_json(h.results/'restart-progress.json',{'stage':stage,'at':utc_now()})
            h.focus_ui();h.driver.get(local_url);wait_local(h,'before restart');mark('local-ready-before-quit')
            h.quit_browser();mark('firefox-exited')
            with (h.profile/'user.js').open('a') as file:
                file.write('\nuser_pref("ui.systemUsesDarkTheme", 1);\nuser_pref("layout.css.prefers-color-scheme.content-override", 0);\n')
            require(h.start_browser() is not None,'Restart failed');mark('firefox-started')
            h.driver.set_context('chrome')
            installed=h.driver.execute_async_script('''const done=arguments[arguments.length-1];
              const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              AddonManager.getAddonByID(arguments[0]).then(addon=>done(addon?{active:addon.isActive,temporary:addon.temporarilyInstalled}:null));''',visual.EXTENSION_ID)
            h.ui_url=h.driver.execute_script("return WebExtensionPolicy.getByID(arguments[0]).getURL('ui.html');",visual.EXTENSION_ID)
            h.driver.set_context('content')
            require(installed and installed['active'] and not installed['temporary'],'Persistent isolated extension did not survive restart')
            h.driver.get(h.ui_url)
            h.ui_handle=h.driver.current_window_handle
            h.wait(lambda:h.driver.execute_script('return !!window.qojVpUi?.getState().connected;'),'persistent native connection')
            recovered=['persistent-isolated-profile']
            mark('extension-installed')
            h.focus_ui();h.driver.get(local_url);h.wait(lambda:h.driver.execute_script('return document.querySelector(".qoj-board")?.dataset.theme==="dark"'),'local dark theme');wait_local(h,'local dark history');mark('local-dark')
            seek(h.driver,120)
            require(h.driver.find_element('css selector','.qoj-board tfoot').is_displayed(),'Settings did not survive Firefox restart')
            local=capture(h.driver,h.results,'local-main-dark');mark('local-captured')
            h.driver.get(reference_url);h.wait(lambda:h.driver.execute_script('return !!document.querySelector("[data-id=vp-ranklist-content]")'),'reference dark');mark('reference-ready')
            _dismiss_settings_intro(h.driver);ref=capture(h.driver,h.results,'reference-main-dark')
            atomic_json(h.results/'dark-comparison.json',{'reference':ref,'local':local})
            return {'localTheme':local['theme'],'referenceTheme':ref['theme'],'settingsPersisted':True,'installRecovery':recovered}
        require(h.step('firefox_restart_dark_and_persistence',restart_dark) is not None,'Dark restart failed')
        def replay_and_rules():
            h.focus_ui();h.driver.get(local_url);wait_local(h,'replay')
            seek(h.driver,120)
            before=h.call('inspect_session',{'sessionId':session['sessionId']})
            from selenium.webdriver.support.ui import Select
            Select(h.driver.find_element('css selector','.qoj-board [aria-label="虚拟参赛倍速"]')).select_by_value('5')
            h.driver.find_element('css selector','[data-id="board-play-toggle"]').click();time.sleep(1.2)
            h.driver.find_element('css selector','[data-id="board-play-toggle"]').click()
            paused=h.driver.find_element('css selector','.qoj-board .srk-progress-secondary-area-left').text
            time.sleep(.5);require(paused==h.driver.find_element('css selector','.qoj-board .srk-progress-secondary-area-left').text,'Pause did not hold view clock')
            after=h.call('inspect_session',{'sessionId':session['sessionId']})
            require(before['startAt']==after['startAt'] and before['durationMs']==after['durationMs'],'Replay changed lifecycle')
            seek(h.driver,0)
            require(not h.driver.find_elements('css selector','.qoj-board .srk-prest-status-block-accepted'),'Seek zero retained future AC')
            h.call('update_session',{'sessionId':session['sessionId'],'board':{'rule':'CCPC26','revealCount':1,'revealRatio':20}})
            h.driver.refresh();wait_local(h,'CCPC26')
            seek(h.driver,0)
            require(all(not e.text for e in h.driver.find_elements('css selector','.qoj-board .srk-main thead .srk-problem-header')),'CCPC26 exposed aliases at zero')
            seek(h.driver,120)
            require([e.text.split('\n')[0] for e in h.driver.find_elements('css selector','.qoj-board .srk-main thead .srk-problem-header')]==['A','B'],'CCPC26 did not reveal thresholds')
            h.call('update_session',{'sessionId':session['sessionId'],'board':{'rule':'ICPC'}})
            h.driver.refresh();wait_local(h,'ICPC again')
            seek(h.driver,0)
            require([e.text.split('\n')[0] for e in h.driver.find_elements('css selector','.qoj-board .srk-main thead .srk-problem-header')]==['A','B'],'ICPC inherited CCPC26 behavior')
            return {'pauseStable':True,'lifecycleUnchanged':True,'ccpc26HideReveal':True,'icpcRestored':True}
        require(h.step('real_replay_clock_and_ccpc26_icpc',replay_and_rules) is not None,'Replay/rules failed')
        def offline_cache():
            reference.source_offline=True
            result=h.call('board.snapshot',{'sessionId':session['sessionId'],'refresh':True,'includeHistory':True})
            require(result['scope']=='historical' and result['cached'],'Cached source did not survive source outage')
            require(h.driver.find_element('css selector','.qoj-board .srk-main').is_displayed(),'Board blank after source outage')
            return {'cached':True,'scope':result['scope'],'warning':result.get('warning')}
        require(h.step('source_outage_keeps_cached_history',offline_cache) is not None,'Offline cache failed')
        def prepared():
            h.call('finish_session',{'sessionId':session['sessionId']});h.call('archive_session',{'sessionId':session['sessionId']})
            created=h.call('create_session',{'contestId':'3387','account':judge.account,'title':'Prepared board fixture',
                'durationMs':18000000,'ranklandUrl':raw,'board':{'rule':'ICPC'}})
            require(created['startAt'] is None,'Prepared session already has a start')
            h.driver.get(h.ui_url.split('?')[0].split('#')[0]+'?session='+created['sessionId']+'#scoreboard')
            h.wait(lambda:h.driver.execute_script('''const state=window.qojVpUi?.getState();
              return state?.connected && state.session?.sessionId===arguments[0];''',created['sessionId']),'prepared native selection')
            h.wait(lambda:'准备中' in h.driver.find_element('css selector','.qoj-board').text,'Prepared board')
            first=h.driver.find_element('css selector','.qoj-board .srk-progress-secondary-area-left').text;time.sleep(1.2)
            require(first==h.driver.find_element('css selector','.qoj-board .srk-progress-secondary-area-left').text,'Opening board started the clock')
            require(h.driver.find_element('css selector','[data-id="board-play-toggle"]').get_attribute('disabled')=='true','Prepared playback enabled')
            link=h.driver.find_element('css selector','[data-id="board-open-rankland"]').get_attribute('href')
            require('play=0' in link and 'at=' not in link,'Prepared external link invented a start')
            capture(h.driver,h.results,'local-prepared')
            return {'startAt':None,'clockStable':True,'externalPausedWithoutAt':True}
        require(h.step('prepared_board_never_starts_contest',prepared) is not None,'Prepared board failed')
    except Exception as error:
        h.summary['fatalError']={'type':type(error).__name__,'message':str(error)}
        if h.driver:
            try:h.driver.save_screenshot(str(h.results/'failure.png'))
            except Exception:pass
    finally:
        for name,fn in [('firefox',h.quit_browser),('nativeManifest',h.cleanup_manifest),('judge',judge.shutdown),('reference',reference.shutdown)]:
            try:h.summary['cleanup'][name]={'status':'passed','evidence':fn()}
            except Exception as error:h.summary['cleanup'][name]={'status':'failed','error':str(error)}
        h.summary['judgePostCount']=judge.post_count
        h.summary['referencePostCount']=reference.post_count
        if judge.post_count or reference.post_count:h.summary['fatalError']={'message':'Unexpected source POST'}
        if h.profile.exists() and h.summary['cleanup']['firefox']['status']=='passed':shutil.rmtree(h.profile)
        h.summary['status']='failed' if h.summary.get('fatalError') or any(c['status']!='passed' for c in h.summary['checks']) or any(c['status']!='passed' for c in h.summary['cleanup'].values()) else 'passed'
        h.phase='finished';h.flush()
    print(json.dumps({'status':h.summary['status'],'summary':str(h.results/'summary.json')}))
    return h.summary['status']!='passed'


if __name__=='__main__':raise SystemExit(main())
