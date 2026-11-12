'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
function harness(cache = {}) {
  const calls = [], events = {}, session = {sessionId:'practice', contestId:'7', account:'me', startAt:1,
    durationMs:1000, state:'running', ranklandUrl:'https://vp.xcpc.link/?contest=test&run=practice&from=0'};
  const listen = {addListener() {}};
  const env = {calls, cache, session, events, failRefresh:false, tabOpen:true, inspectWait:null,
    refreshResult:{submissions:[],coverage:{complete:true,pages:1}},plan:{items:[],pendingCount:1,waiting:[{}]}};
  const context = {URL, Map, Set, Promise, Date, setTimeout, clearTimeout, crypto:require('node:crypto').webcrypto,
    VpTransport:{pause:async()=>{}}, VpRanklandTransfer:{sync:async args=>{calls.push(['transfer',args]);if(env.transferError)throw env.transferError;return {synced:0};}},
    __native:async (method,args)=>{ calls.push([method,args]); switch(method) {
      case 'qoj_bind_virtual':session.qojVirtual={mode:'qoj-native',origin:'https://qoj.ac',contestId:'7',account:'me',startAt:session.startAt};return {session:{...session}};
      case 'qoj_confirm_virtual_start':return {session:{...session,qojVirtual:{mode:'qoj-native',origin:'https://qoj.ac',contestId:'7',account:'me',startAt:session.startAt}},virtual:{state:env.startUnconfirmed?'unknown':'running'}};
      case 'hello':return {fixture:!env.resolveResult};
      case 'session_snapshot':return {session:{...session},contest:{id:'7',name:'Fixture contest',scoreboardUrl:'https://qoj.ac/contest/7/standings',problems:[]}};
      case 'update_session':session.ranklandUrl=args.ranklandUrl;return {...session};
      case 'list_sessions':return {sessions:[{...session}]};
      case 'inspect_session':if(env.inspectWait)return env.inspectWait;return {...session};
      case 'prepare_rankland':return {...session};
      case 'qoj_submissions': if(env.failRefresh) throw Error('offline');return env.refreshResult;
      case 'rankland_plan':return {...env.plan,sessionId:session.sessionId};
      case 'rankland_queue':return {items:[]};
      case 'rankland_ack':case 'rankland_ack_batch':session.ranklandSyncedPlanToken=args.planToken;return {accepted:true};
      case 'settlement_sessions':return {sessions:env.settled?[]:[{...session,refreshRequired:true,syncRequired:true}]};
      default:throw Error('unexpected native '+method);
    }},
    browser:{runtime:{id:'test',getURL:p=>'moz-extension://test/'+p,onMessage:listen,onInstalled:listen},
      action:{onClicked:listen}, alarms:{create(){},onAlarm:{addListener:f=>{events.alarm=f;}}},
      tabs:{query:async()=>env.tabOpen?[{id:7,url:env.tabUrl||session.ranklandUrl}]:[],get:async id=>id===17?{id,url:'https://qoj.ac/contest/7/virtual/register'}:({id:7,url:session.ranklandUrl}),
        sendMessage:async()=>({ready:true}), update:async(id,args)=>({id,url:session.ranklandUrl,...args}),create:async args=>{
          calls.push(['tab.create',args]);if(args.url.startsWith('https://vp.xcpc.link'))env.tabOpen=true;return {id:7,...args};}},
      scripting:{executeScript:async()=>[{result:null}]},
      storage:{local:{get:async k=>k===null?{...cache}:({[k]:cache[k]}),set:async v=>Object.assign(cache,v),remove:async k=>{delete cache[k];}}}}};
  vm.createContext(context);
 for (const file of ['readiness-bridge.js','board/generated/engine.js','board/cache.js','board/service.js'])
  vm.runInContext(fs.readFileSync('src/firefox/'+file,'utf8'),context);
 if (!context.VpScoreboardSources) context.VpScoreboardSources={resolve:async()=>env.resolveResult};
  vm.runInContext(fs.readFileSync('src/firefox/rankland-protocol.js','utf8'),context);
  vm.runInContext(fs.readFileSync('src/firefox/qoj-lifecycle.js','utf8'),context);
  vm.runInContext(fs.readFileSync('src/firefox/background.js','utf8').replace(/\}\)\(\);\s*$/,
    'native=globalThis.__native;globalThis.dispatch=dispatch;globalThis.lifecycle=qojLifecycle;})();'),context);
  env.sync=()=>context.dispatch('rankland.sync',{sessionId:session.sessionId});
  env.stop=()=>context.dispatch('rankland.stop',{sessionId:session.sessionId});
  env.dispatch=context.dispatch;
  env.start=()=>context.lifecycle.startIntent({cid:'7'},{id:'test',frameId:0,url:'https://qoj.ac/contest/7/virtual/register',tab:{id:17}});
  env.readCached=()=>context.dispatch('qoj_submissions',{sessionId:session.sessionId,refresh:false});
  return env;
}
test('one click refreshes QOJ before preparing the complete RankLand projection',async()=>{
  const h=harness(), result=await h.sync();
  assert.ok(h.calls.findIndex(c=>c[0]==='qoj_submissions')>=0,'one click must fetch QOJ');
  assert.ok(h.calls.findIndex(c=>c[0]==='qoj_submissions')<h.calls.findIndex(c=>c[0]==='rankland_plan'));
  assert.equal(result.pending,1);assert.equal(result.state,'waiting');
});
test('post-end alarms poll unsettled sessions from the ledger, not only running browser cache',async()=>{
  const h=harness(); await h.events.alarm({name:'vp-refresh'});
  assert.ok(h.calls.some(c=>c[0]==='settlement_sessions'));
  assert.ok(h.calls.some(c=>c[0]==='qoj_submissions'));
  assert.ok(!h.calls.some(c=>c[0]==='transfer'),'automatic Judger polling never exports to external pages');
});
test('QOJ outage never publishes a freshly successful synchronization result',async()=>{
  const h=harness();h.failRefresh=true;
  await assert.rejects(h.sync(),/offline/);
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,0);
});
for(const pages of [0,1]) {
  test(`resolved incomplete QOJ history (${pages} verified pages) retains cached delivery but reports that refresh remains due`,async()=>{
    const h=harness();h.plan={items:[],allItems:[],pendingCount:0,waiting:[],planToken:'a'.repeat(64)};
    h.refreshResult={submissions:[],coverage:{complete:false,pages,warning:pages?'Repeated history page; earlier records remain unverified':'A history page could not be verified: HTTPError'}};
    const result=await h.sync();
    assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1,'confirmed cached facts may still be delivered');
    assert.equal(result.state,'waiting','an incomplete provider refresh cannot claim the synchronization is settled');
    assert.equal(result.needsRefresh,true);
    assert.match(result.message,/QOJ|判定.*读取|读取.*判定|更新.*未完成|刷新.*未完成/);
    assert.doesNotMatch(result.message,/已确认的判定均已同步/);
    assert.equal(h.cache['rankland-sync-status:'+h.session.sessionId].needsRefresh,true);
  });
}
test('cached history is independent; explicit exports coalesce and reopen a closed tab once',async()=>{
  const h=harness();h.tabOpen=false;
  h.plan={items:[],allItems:[],pendingCount:0,waiting:[],planToken:'a'.repeat(64)};
  let release;h.inspectWait=new Promise(resolve=>{release=resolve;});
  await h.readCached();
  assert.equal(h.calls.filter(c=>c[0]==='inspect_session').length,0,'cached history never starts an external synchronization');
  const clicks=[h.sync(),h.sync(),h.sync()];
  release({...h.session});
  const results=await Promise.all(clicks);
  assert.ok(results.every(result=>result.state==='ready'),'the explicit click must not inherit waiting_for_scoreboard from the automatic pass');
  assert.equal(h.calls.filter(c=>c[0]==='qoj_submissions'&&c[1].refresh===true).length,1,'joined explicit clicks require exactly one fresh QOJ read');
  assert.equal(h.calls.filter(c=>c[0]==='prepare_rankland').length,1);
  assert.equal(h.calls.filter(c=>c[0]==='tab.create').length,1);
  assert.equal(h.calls.find(c=>c[0]==='tab.create')[1].active,false);
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1);
  assert.equal(h.cache['rankland-auto-sync:'+h.session.sessionId],true,'the click must enable later automatic reopening');
});


const settleBackground=async()=>{for(let i=0;i<12;i++)await new Promise(setImmediate);};
test('verified Start binds and opens a view-only board without preparing or exporting a team',async()=>{
 const h=harness();h.tabOpen=false;
 assert.equal((await h.start()).state,'started');await settleBackground();
 const boards=h.calls.filter(c=>c[0]==='tab.create' && c[1].url.startsWith('https://vp.xcpc.link'));
 assert.equal(boards.length,1);assert.equal(boards[0][1].active,false);
 assert.equal(h.calls.some(c=>['prepare_rankland','rankland_plan','transfer'].includes(c[0])),false);
 assert.notEqual(h.cache['rankland-auto-sync:'+h.session.sessionId],true);
 await h.start();await settleBackground();
 assert.equal(h.calls.filter(c=>c[0]==='tab.create' && c[1].url.startsWith('https://vp.xcpc.link')).length,1);
});
test('a start with no configured board saves a verified match, while an unmatched contest stays local',async()=>{
 const h=harness(),target=h.session.ranklandUrl;h.session.ranklandUrl=null;h.tabOpen=false;
 h.resolveResult={source:'rankland',state:'matched',ranklandUrl:target};
 await h.start();await settleBackground();assert.equal(h.session.ranklandUrl,target);
 assert.equal(h.calls.some(c=>c[0]==='transfer'),false);
 assert.equal(h.calls.filter(c=>c[0]==='tab.create' && c[1].url===target).length,1);
 const other=harness();other.session.ranklandUrl=null;await other.start();await settleBackground();
 assert.equal(other.session.ranklandUrl,null);
 assert.equal(other.calls.some(c=>c[0]==='tab.create' && c[1].url.startsWith('https://vp.xcpc.link')),false);
});
test('unconfirmed Start never opens a historical board',async()=>{
 const h=harness();h.startUnconfirmed=true;
 assert.equal((await h.start()).state,'waiting');await settleBackground();
 assert.equal(h.calls.some(c=>c[0]==='tab.create'),false);
});
test('old auto-sync settings cannot export on alarms or a new QOJ verdict',async()=>{
 const h=harness({'rankland-auto-sync:practice':true});
 await h.events.alarm({name:'vp-refresh'});
 await h.dispatch('qoj_submissions',{sessionId:h.session.sessionId,refresh:true});await settleBackground();
 assert.ok(h.calls.some(c=>c[0]==='qoj_submissions'));
 assert.equal(h.calls.some(c=>['prepare_rankland','rankland_plan','transfer','tab.create'].includes(c[0])),false);
});
test('opening a configured board reuses its tab and never sends submission records',async()=>{
 const h=harness();await h.dispatch('rankland.open',{sessionId:h.session.sessionId});
 assert.equal(h.calls.some(c=>['prepare_rankland','rankland_plan','transfer'].includes(c[0])),false);
 assert.notEqual(h.cache['rankland-auto-sync:'+h.session.sessionId],true);
});

test('RankLand canonical timezone and default parameters do not create a second tab',async()=>{
 const h=harness();h.session.ranklandUrl='https://vp.xcpc.link/?contest=test&at=2026-11-01T00%3A00%3A00Z&from=0&play=1&speed=1';
 const canonical=new URL(h.session.ranklandUrl);canonical.searchParams.set('at','2026-11-01T08:00:00+08:00');canonical.searchParams.set('rule','auto');canonical.searchParams.set('feed','1');h.tabUrl=canonical.href;
 await h.dispatch('scoreboard.view',{sessionId:h.session.sessionId});
 assert.equal(h.calls.some(c=>c[0]==='tab.create'),false);
 assert.equal(h.calls.some(c=>c[0]==='transfer'),false);
});
