'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
function harness(cache = {}) {
  const calls = [], events = {}, session = {sessionId:'practice', account:'me', startAt:1,
    durationMs:1000, state:'running', ranklandUrl:'https://vp.xcpc.link/?contest=test&run=practice&from=0'};
  const listen = {addListener() {}};
  const env = {calls, cache, session, events, failRefresh:false, tabOpen:true, inspectWait:null,
    refreshResult:{submissions:[],coverage:{complete:true,pages:1}},plan:{items:[],pendingCount:1,waiting:[{}]}};
  const context = {URL, Map, Set, Promise, Date, setTimeout, clearTimeout, crypto:require('node:crypto').webcrypto,
    VpTransport:{pause:async()=>{}}, VpRanklandTransfer:{sync:async args=>{calls.push(['transfer',args]);if(env.transferError)throw env.transferError;return {synced:0};}},
    __native:async (method,args)=>{ calls.push([method,args]); switch(method) {
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
      tabs:{query:async()=>env.tabOpen?[{id:7,url:session.ranklandUrl}]:[],get:async()=>({id:7,url:session.ranklandUrl}),
        sendMessage:async()=>({ready:true}), update:async()=>{},create:async args=>{
          calls.push(['tab.create',args]);env.tabOpen=true;return {id:7,url:session.ranklandUrl};}},
      scripting:{executeScript:async()=>[{result:null}]},
      storage:{local:{get:async k=>k===null?{...cache}:({[k]:cache[k]}),set:async v=>Object.assign(cache,v)}}}};
  vm.createContext(context);
 for (const file of ['board/generated/engine.js','board/cache.js','board/service.js'])
  vm.runInContext(fs.readFileSync('src/firefox/'+file,'utf8'),context);
 if (!context.VpScoreboardSources) context.VpScoreboardSources={};
  vm.runInContext(fs.readFileSync('src/firefox/rankland-protocol.js','utf8'),context);
  vm.runInContext(fs.readFileSync('src/firefox/qoj-lifecycle.js','utf8'),context);
  vm.runInContext(fs.readFileSync('src/firefox/background.js','utf8').replace(/\}\)\(\);\s*$/,
    'native=globalThis.__native;globalThis.dispatch=dispatch;})();'),context);
  env.sync=()=>context.dispatch('rankland.sync',{sessionId:session.sessionId});
  env.stop=()=>context.dispatch('rankland.stop',{sessionId:session.sessionId});
  env.dispatch=context.dispatch;
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

test('opting in once delivers a delayed verdict on the next alarm without another click',async()=>{
  const h=harness();
  h.plan={items:[],allItems:[],pendingCount:1,waiting:[{}],planToken:'a'.repeat(64)};
  await h.sync();h.calls.length=0;
  h.plan={items:[],allItems:[],pendingCount:0,waiting:[],planToken:'b'.repeat(64)};
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1,'a late verdict must reach the opted-in external board');
});

test('unchanged projections do not touch tabs, and restart retains delivery identity',async()=>{
  const h=harness();h.plan={items:[],allItems:[],pendingCount:0,waiting:[],planToken:'c'.repeat(64)};
  await h.sync();h.calls.length=0;h.tabOpen=false;
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer'||c[0]==='tab.create').length,0);
  const restarted=harness(h.cache);restarted.session.ranklandSyncedPlanToken=h.session.ranklandSyncedPlanToken;restarted.plan=h.plan;restarted.tabOpen=false;restarted.settled=true;
  await restarted.events.alarm({name:'vp-refresh'});
  assert.equal(restarted.calls.filter(c=>c[0]==='transfer'||c[0]==='tab.create').length,0);
  restarted.plan={...h.plan,planToken:'d'.repeat(64)};
  await restarted.events.alarm({name:'vp-refresh'});
  assert.equal(restarted.calls.filter(c=>c[0]==='transfer').length,1,'finished ledger still delivers an outstanding revision');
});
test('automatic failures back off and stopping disables persisted background delivery',async()=>{
  const h=harness();await h.sync();h.calls.length=0;
  h.transferError=Object.assign(new Error('offline'),{code:'RANKLAND_LOAD_TIMEOUT'});
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1);
  const retry=h.cache['rankland-sync-retry:'+h.session.sessionId];assert.ok(retry.nextAt>Date.now());
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1,'no rapid retries');
  retry.nextAt=0;h.transferError=null;
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,2);
  assert.equal((await h.stop()).enabled,false);
  const restarted=harness(h.cache);await restarted.events.alarm({name:'vp-refresh'});
  assert.equal(restarted.calls.filter(c=>c[0]==='transfer').length,0);
});
test('ownership conflicts require an explicit retry rather than overwriting manual records',async()=>{
  const h=harness();await h.sync();h.calls.length=0;
  h.transferError=Object.assign(new Error('conflict'),{code:'RANKLAND_OWNERSHIP_CONFLICT'});
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.cache['rankland-sync-retry:'+h.session.sessionId].suspended,true);
  h.transferError=null;h.cache['rankland-sync-retry:'+h.session.sessionId].nextAt=0;
  await h.events.alarm({name:'vp-refresh'});
  assert.equal(h.calls.filter(c=>c[0]==='transfer').length,1);
  await h.sync();assert.equal(h.calls.filter(c=>c[0]==='transfer').length,2);
});
